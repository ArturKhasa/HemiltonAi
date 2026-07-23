"""FunnelAgent — detects the current sales-script stage of a dialog.

Runs on every client message BEFORE the SalesAgent, and the result is persisted on
``dialogs.funnel_stage`` so the async PingAgent can reuse the last-detected stage
(pings fire when the client is silent, so no fresh message is available there).

The stage is the sales-script step the manager is currently working on — orthogonal
to ``funnel_type`` (lead temperature, drives ping cadence) and to dialog status. It tells
both agents WHERE in the script the conversation stands, not how the client behaves.
"""
import logging
import re
import time

from agents import Agent, Runner
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cost import (
    CACHE_READ_MULT_BY_MODEL,
    DEFAULT_CACHE_READ_MULT,
    calculate_cost,
    get_model_pricing,
)
from app.ai.providers import get_model_name, get_model_string
from app.config import settings
from app.db.models import AIRun, Dialog, Message, MessageRole

logger = logging.getLogger(__name__)


# Ordered for readability only — detection allows ANY order (a client may send a photo
# before timing is discussed). The stage is the furthest point actually reached, not a
# position in a rigid chain.
STAGES: list[str] = [
    "greeting",
    "format",
    "calculation",
    "timing",
    "photo",
    "contacts",
    "prepayment",
    "paid",
]
_DEFAULT_STAGE = "greeting"

# Short human labels for prompt injection. The agents already carry the full sales
# script in their system prompt — this only pins WHICH step they're on right now.
STAGE_LABELS: dict[str, str] = {
    "greeting": "Приветствие + квалификация",
    "format": "Выбор/представление формата книги",
    "calculation": "Расчёт стоимости и отработка возражений по цене",
    "timing": "Сроки / дата получения",
    "photo": "Запрос фото ребёнка",
    "contacts": "Сбор имени и телефона",
    "prepayment": "Предоплата 1000₽ по ссылке",
    "paid": "Оплата получена — воронка закрыта, дальше ведение (другой скрипт)",
}


# Per-stage hard rules appended to the stage block. The generic line only forbids
# going BACKWARD; these forbid the common FORWARD skips (e.g. jumping to эскиз/предоплата
# before the price is actually on the table). Keyed by stage; missing key → no extra rule.
STAGE_RULES: dict[str, str] = {
    "format": (
        "Отправлять расчет и писать про цены, только если клиенту были отправлены размеры"
    ),
    "calculation": (
        "Если расчёта (цены за выбранный формат) ещё НЕТ в истории диалога — ОБЯЗАТЕЛЬНО "
        "сначала пришли клиенту РАСЧЁТ. Если расчёт УЖЕ отправлен — НЕ отправляй его "
        "повторно: работай с возражением или вопросом клиента по скриптам этой стадии"
    ),
}


def format_stage_block(stage: str | None) -> str:
    """Prompt-injection block telling an agent the current sales-script stage.
    Returns '' for an unknown/missing stage so callers can append unconditionally."""
    if not stage or stage not in STAGE_LABELS:
        return ""
    block = (
        f"[Текущая стадия воронки: {stage} — {STAGE_LABELS[stage]}]\n"
        "Работай по этому шагу скрипта. Не возвращайся к уже пройденным шагам."
    )
    rule = STAGE_RULES.get(stage)
    if rule:
        block += "\n" + rule
    return block


def _funnel_model_override() -> str | None:
    """Stage detection is a lightweight classifier — run it on the cheap ping model
    (haiku on anthropic) rather than the main sonnet dialog model."""
    if settings.PING_AI_PROVIDER.lower() == "anthropic":
        return settings.PING_ANTHROPIC_MODEL_NAME
    return None


def _funnel_model_string() -> str:
    return get_model_string(settings.PING_AI_PROVIDER, _funnel_model_override())


def _funnel_model_name() -> str:
    return get_model_name(settings.PING_AI_PROVIDER, _funnel_model_override())


class FunnelStageOutput(BaseModel):
    stage: str = Field(description="Detected sales-script stage from the available list")
    reason: str = Field(description="Brief reason for this classification")


_INSTRUCTIONS = """\
Ты классифицируешь диалог по СТАДИИ скрипта продаж — на каком шаге сейчас находится \
разговор. Это нужно, чтобы менеджер (SalesAgent) и follow-up пинги (PingAgent) знали, \
что делать дальше.

Доступные стадии: greeting, format, calculation, timing, photo, contacts, prepayment, paid.

КАК ОПРЕДЕЛЯТЬ:
- Стадия = последний шаг скрипта, который УЖЕ начат менеджером, но ещё НЕ закрыт клиентом.
- Сканируй ВСЮ историю, бери самую позднюю достигнутую точку. Шаг закрыт → стадия = следующий.
Ориентируйся на реально достигнутые точки, а не на позицию в списке.
- ЖЁСТКИЙ ПОРОГ ЦЕНЫ: стадии timing, photo, contacts, prepayment возможны ТОЛЬКО если в \
истории уже есть сообщение менеджера с ценой/расчётом. Цены ещё нет → стадия НЕ ВЫШЕ \
calculation, даже если клиент сам прислал фото, назвал дату или оставил контакты. \
Раннее фото/дата — вклад на будущее, а не закрытие шага.
- ПОРОГ ПРИВЕТСТВИЯ: если от менеджера ещё нет НИ ОДНОГО сообщения — стадия ВСЕГДА \
greeting, что бы ни писал клиент (спросил цену, прислал фото и т.д.). Шаг не может быть \
закрыт, пока менеджер его даже не начал.
- Вопрос или возражение ВНУТРИ шага — это НЕ откат. Остаёшься на шаге, пока он не закрыт.

СТАДИИ:

greeting — Приветствие + квалификация.
- Менеджер еще не поздоровался ИЛИ поздоровался и спросил квалификацию \
- Закрыт когда: менеджер поздоровался И клиент написал для кого подарок или спросил \
про цену → format.

format — Выбор/представление формата товара.
- Квалификация пройдена. Менеджер представляет формат или размер, \
показывает видео-обзор, ориентирует.
- Признаки: известен получатель/повод; формат ещё не подтверждён; цена ещё НЕ названа.
- Вопрос клиента о цене НЕ закрывает format сам по себе: если менеджер ещё НЕ показал \
размеры/форматы — остаёмся на format (сначала размеры, «цены зависят от размера»).
- Закрыт когда: клиент выбрал размер/формат (согласился на предложенный ИЛИ назвал свой), \
ЛИБО спросил цену ПОСЛЕ того, как менеджер уже показал размеры → calculation.
- Согласие клиента («да», «ок», «давайте», «показывайте») в ответ на предложение \
менеджера показать пример / рассказать стоимость КОНКРЕТНОГО формата = формат выбран → \
format закрыт → calculation. Отдельного подтверждения формата НЕ требуется.
- «Скажите цену» / «сколько стоит» после того, как менеджер уже предложил конкретный \
формат (например «чаще всего берут 20×20 на 10 разворотов») — тоже calculation.

calculation — Расчёт стоимости (контрольная точка).
- Формат ясен. Менеджер прислал расчёт (цена + доставка + шаги оплаты), спросил «подходит?».
- Признаки: в истории есть сообщение с ценой/расчётом.
- СЮДА ЖЕ входит отработка возражений ПОСЛЕ озвученной цены: «дорого», «подумаю», \
сравнение с конкурентами, сомнения. Пока цена не принята — остаёшься в calculation.
- Закрыт когда: клиент принял цену/формат («да, подходит», «беру») → timing.

timing — Сроки.
- Цена принята. Обсуждаются дата получения / сроки.
- Признаки: клиент ок с ценой; менеджер спросил дату или клиент назвал дату.
- Закрыт когда: дата ясна → photo.

photo — Фото.
- Менеджер попросил пару фото.
- Признаки: запрос фото отправлен; клиент ещё не прислал фото.
- Закрыт когда: клиент прислал фото → contacts.

contacts — Имя и телефон.
- Фото получено. Менеджер просит имя + номер телефона для оформления.
- Закрыт когда: клиент дал имя И телефон → prepayment.

prepayment — Предоплата 1000₽ (финал воронки).
- Контакты есть. Отправлена ссылка на оплату 1000₽ (photo-book-payment.online), ждём оплату.
- Признаки: в истории ссылка на оплату; оплата ещё не подтверждена.
- Закрыт когда: оплата прошла → paid.

paid — Оплачено (терминал).
- Оплата 1000₽ ПОДТВЕРЖДЕНА: чек/скриншот от клиента ИЛИ менеджер явно зафиксировал \
поступление оплаты.
- НЕ ДОСТАТОЧНО для paid: клиент только НАПИСАЛ «оплатил/перевёл» без чека, или менеджер \
поблагодарил в ответ на такие слова. Ссылка на оплату не отправлялась / оплата не видна → \
остаёшься на prepayment (или раньше).

ВАЖНО: Отвечай ТОЛЬКО валидным JSON без объяснений, рассуждений или markdown.
Формат: {"stage": "<стадия>", "reason": "<одно предложение обоснования>"}
Никакого текста вне JSON.
"""


async def _fetch_history(db: AsyncSession, dialog: Dialog) -> str:
    result = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog.id)
        .order_by(Message.created_at.desc())
        .limit(30)
    )
    msgs = list(reversed(result.scalars().all()))
    lines = [
        f"[{'Клиент' if m.role == MessageRole.client else 'Менеджер'}]: {m.text}"
        for m in msgs
    ]
    return "\n".join(lines)


async def _save_run(db: AsyncSession, dialog_id: int, result, elapsed_ms: int, instructions: str) -> None:
    _provider = settings.PING_AI_PROVIDER
    _model = _funnel_model_name()
    input_tokens = sum(getattr(r.usage, "input_tokens", 0) for r in result.raw_responses)
    output_tokens = sum(getattr(r.usage, "output_tokens", 0) for r in result.raw_responses)
    in_price, out_price = get_model_pricing(_model)
    # OpenAI input_tokens includes cached tokens — bill the cached portion at the
    # cache-read discount (same as runner.py). input_tokens stays full for storage.
    # Anthropic/MiniMax don't surface cached here, so this is a no-op for them.
    cache_read_tokens = 0
    billable_input = input_tokens
    if _provider.lower() not in ("anthropic", "minimax"):
        cache_read_tokens = sum(
            getattr(getattr(r.usage, "input_tokens_details", None), "cached_tokens", 0) or 0
            for r in result.raw_responses
        )
        billable_input = input_tokens - cache_read_tokens
    cost = calculate_cost(
        billable_input, output_tokens, in_price, out_price,
        cache_read_tokens=cache_read_tokens,
        cache_read_mult=CACHE_READ_MULT_BY_MODEL.get(_model, DEFAULT_CACHE_READ_MULT),
    )
    try:
        full_context = {"system": instructions, "messages": result.to_input_list()}
    except Exception:
        full_context = None
    db.add(AIRun(
        dialog_id=dialog_id,
        provider=_provider,
        model=_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cost_amount=cost,
        cost_currency="USD",
        cost_estimated=(input_tokens == 0),
        latency_ms=elapsed_ms,
        selected_script="funnel:detect_stage",
        full_context=full_context,
    ))
    await db.flush()


# Stages that require a price already sent by the manager. The prompt-level «ЖЁСТКИЙ
# ПОРОГ ЦЕНЫ» rule proved unreliable on the light classifier model (client 8479729:
# contacts/prepayment detected with no price in history → the client was sent a 1000₽
# payment link without ever seeing the cost), so the gate is enforced in code too.
_PRICE_GATED_STAGES = {"timing", "photo", "contacts", "prepayment"}

# «р\b» covers the bare-ruble spelling used in book quotes («9400 р», «1000 р.»)
# without matching words like «разворотов» (letter follows «р», so no word boundary).
_PRICE_RE = re.compile(r"\d[\d\s ]{2,}\s*(?:₽|руб|р\b)", re.IGNORECASE)


def _has_manager_message(history_text: str) -> bool:
    return any(line.startswith("[Менеджер]") for line in (history_text or "").splitlines())


def _manager_sent_price(history_text: str) -> bool:
    """True if any manager-authored line of the transcript mentions a price."""
    is_manager = False
    for line in (history_text or "").splitlines():
        if line.startswith("[Менеджер]"):
            is_manager = True
        elif line.startswith("[Клиент]"):
            is_manager = False
        if is_manager and _PRICE_RE.search(line):
            return True
    return False


async def detect_stage(
    db: AsyncSession,
    dialog: Dialog,
) -> str | None:
    """Classify the dialog's current sales-script stage. Returns a value from STAGES,
    or None on failure (caller should keep the previous stage). Persists an AIRun for
    cost tracking, mirroring detect_funnel_with_ai."""
    history_text = await _fetch_history(db, dialog)

    # История пуста — не классифицируем вслепую, оставляем прежнюю стадию
    # (клиент 8495644: пустая история → greeting → агент поздоровался посреди
    # диалога после возражения по цене).
    if not (history_text or "").strip():
        logger.warning(
            "detect_stage: empty history, keeping previous stage | dialog=%s", dialog.id,
        )
        return None

    # Приветствие: нет ни одного сообщения менеджера → всегда greeting. Промпт-правило
    # «ПОРОГ ПРИВЕТСТВИЯ» модель нарушает (клиент 8497342: «Привет» клиента засчитан за
    # пройденное приветствие → format), поэтому гейт в коде, без вызова LLM.
    if not _has_manager_message(history_text):
        logger.info(
            "detect_stage: no manager message in history -> greeting | dialog=%s", dialog.id,
        )
        return "greeting"

    agent = Agent(
        name="FunnelAgent",
        instructions=_INSTRUCTIONS,
        model=_funnel_model_string(),
        tools=[],
        output_type=FunnelStageOutput,
    )
    try:
        _t0 = int(time.time() * 1000)
        result = await Runner.run(
            agent,
            [{"role": "user", "content": f"История диалога:\n{history_text or '(пусто)'}"}],
        )
        await _save_run(db, dialog.id, result, int(time.time() * 1000) - _t0, _INSTRUCTIONS)
        output: FunnelStageOutput = result.final_output
        stage = output.stage if output.stage in STAGES else _DEFAULT_STAGE
        if stage in _PRICE_GATED_STAGES and not _manager_sent_price(history_text):
            logger.info(
                "detect_stage: clamped %s -> calculation (no price in history) | dialog=%s",
                stage, dialog.id,
            )
            stage = "calculation"
        logger.info(
            "detect_stage: stage=%s reason=%r | dialog=%s",
            stage, output.reason, dialog.id,
        )
        return stage
    except Exception as e:
        logger.error(
            "detect_stage: detection FAILED, keeping previous stage | dialog=%s: %s",
            dialog.id, str(e)[:200],
        )
        return None
