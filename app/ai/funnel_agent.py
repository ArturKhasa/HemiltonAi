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


# Ordered for readability only — detection allows ANY order (a client may send a размер
# before цвет is discussed). The stage is the furthest point actually reached, not a
# position in a rigid chain. Mirrors the canonical sales funnel "НОВАЯ ВОРОНКА ОП1"
# (quick-phrases sheet) for the Hemilton hoodie/sweatshirt line.
STAGES: list[str] = [
    "greeting",
    "pricing",
    "options",
    "sizing",
    "design",
    "checkout",
    "payment_link",
    "post_payment",
    "paid",
]
_DEFAULT_STAGE = "greeting"

# Short human labels for prompt injection. The agents already carry the full sales
# script in their system prompt — this only pins WHICH step they're on right now.
STAGE_LABELS: dict[str, str] = {
    "greeting": "Приветствие + вопрос про дизайн/повод, присоединение (до цены)",
    "pricing": "Базовая цена изделия + куда доставка (город)",
    "options": "Цвет изделия (+ доп. цвета)",
    "sizing": "Размер (рост/вес)",
    "design": "Согласование дизайна на словах + фиксация деталей",
    "checkout": "Способы оплаты + сбор ФИО и телефона для оформления",
    "payment_link": "Отправлена ссылка на оплату, ждём чек",
    "post_payment": "Чек получен — уточняем СДЭК/почту, возможен апсейл (вышивка/принт/второе изделие)",
    "paid": "Макет согласован, заказ передан на ведение (терминал)",
}


# Per-stage hard rules appended to the stage block. The generic line only forbids
# going BACKWARD; these forbid the common FORWARD skips (e.g. jumping to оформление
# before the price is actually on the table). Keyed by stage; missing key → no extra rule.
STAGE_RULES: dict[str, str] = {
    "pricing": (
        "Если базовой цены изделия ещё НЕТ в истории диалога — ОБЯЗАТЕЛЬНО сначала "
        "пришли клиенту СТОИМОСТЬ. Если цена УЖЕ отправлена — НЕ отправляй её повторно: "
        "работай с возражением или вопросом клиента по скриптам этой стадии"
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
что делать дальше. Бизнес — кастомные худи/свитшоты с принтом или вышивкой (Hemilton).

Доступные стадии: greeting, pricing, options, sizing, design, checkout, payment_link, \
post_payment, paid.

КАК ОПРЕДЕЛЯТЬ:
- Стадия = последний шаг скрипта, который УЖЕ начат менеджером, но ещё НЕ закрыт клиентом.
- Сканируй ВСЮ историю, бери самую позднюю достигнутую точку. Шаг закрыт → стадия = следующий.
Ориентируйся на реально достигнутые точки, а не на позицию в списке.
- ЖЁСТКИЙ ПОРОГ ЦЕНЫ: стадии options, sizing, design, checkout, payment_link, post_payment, \
paid возможны ТОЛЬКО если в истории уже есть сообщение менеджера с базовой ценой изделия. \
Цены ещё нет → стадия НЕ ВЫШЕ greeting, даже если клиент сам назвал размер, цвет или оставил \
контакты. Раннее упоминание — вклад на будущее, а не закрытие шага.
- ПОРОГ ПРИВЕТСТВИЯ: если от менеджера ещё нет НИ ОДНОГО сообщения — стадия ВСЕГДА \
greeting, что бы ни писал клиент (спросил цену, прислал фото и т.д.). Шаг не может быть \
закрыт, пока менеджер его даже не начал.
- Вопрос или возражение ВНУТРИ шага — это НЕ откат. Остаёшься на шаге, пока он не закрыт.

СТАДИИ:

greeting — Приветствие + вопрос про дизайн/повод (до цены).
- Менеджер представился, спросил про дизайн (текст/эмблема/город) или повод, возможно \
похвалил/присоединился к ответу клиента. Цена ещё НЕ названа.
- Закрыт когда: менеджер назвал БАЗОВУЮ цену изделия → pricing.

pricing — Базовая цена + доставка (контрольная точка).
- Менеджер прислал цену изделия (обычно со скидкой «сегодня»), уточняет город доставки.
- Признаки: в истории есть сообщение с ценой изделия.
- СЮДА ЖЕ входит отработка возражений ПОСЛЕ озвученной цены: «дорого», «подумаю», \
сомнения, бронь депозитом. Пока цена не принята — остаёшься в pricing.
- Закрыт когда: клиент принял цену/готов продолжать («да, подходит», «беру», назвал город) \
→ options.

options — Цвет изделия.
- Город известен. Менеджер уточняет/предлагает цвет, доп. цвета при необходимости.
- Закрыт когда: цвет выбран → sizing.

sizing — Размер.
- Цвет известен. Менеджер уточняет размер (рост/вес) для индивидуального пошива.
- Закрыт когда: размер известен → design.

design — Согласование дизайна.
- Размер известен. Менеджер словами согласовывает дизайн (что именно писать/изображать) \
и фиксирует детали для дизайнера.
- Закрыт когда: дизайн зафиксирован → checkout.

checkout — Оформление (способы оплаты + данные).
- Дизайн зафиксирован. Менеджер рассказывает про способы оплаты, запрашивает ФИО и \
телефон получателя.
- Закрыт когда: клиент дал ФИО И телефон → payment_link.

payment_link — Ссылка на оплату.
- Контакты есть. Отправлена ссылка/QR на оплату (СБП), ждём чек.
- Признаки: в истории ссылка на оплату; чек ещё не пришёл.
- Закрыт когда: клиент прислал чек/скриншот оплаты → post_payment.

post_payment — После оплаты (уточнение доставки + возможен апсейл).
- Чек получен. Менеджер уточняет способ доставки (СДЭК/почта), адрес ПВЗ; может предложить \
доп. вышивку/принт/второе изделие, пока дизайнер готовит макет.
- Закрыт когда: макет согласован клиентом → paid.

paid — Заказ передан на ведение (терминал).
- Макет СОГЛАСОВАН клиентом, заказ оформлен и передан в производство/логистику.
- НЕ ДОСТАТОЧНО для paid: клиент только прислал чек без согласования макета — это ещё \
post_payment.

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
# contacts/prepayment detected with no price in history → the client was sent a
# payment link without ever seeing the cost), so the gate is enforced in code too.
_PRICE_GATED_STAGES = {"options", "sizing", "design", "checkout", "payment_link", "post_payment", "paid"}

# «р\\b» covers the bare-ruble spelling used in quotes («5990 р», «300 р.»)
# without matching words like «размер» (letter follows «р», so no word boundary).
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
                "detect_stage: clamped %s -> greeting (no price in history) | dialog=%s",
                stage, dialog.id,
            )
            stage = "greeting"
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
