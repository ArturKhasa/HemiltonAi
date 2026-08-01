"""LLM agent that selects the appropriate ping script for a dialog."""
import logging
import re
import time
from typing import Literal

from agents import Agent, ModelSettings, Runner, function_tool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cost import (
    CACHE_READ_MULT_BY_MODEL,
    DEFAULT_CACHE_READ_MULT,
    calculate_cost,
    get_model_pricing,
)
from app.ai.providers import get_model_name, get_model_string, parse_agent_output
from app.ai.run_log import log_failed_run, usage_from_result
from app.config import settings
from app.db.models import AIRun, Client, Dialog, DialogPingState, Message, MessageRole, PingRule
from app.ai.feedback import load_active_feedback_rules
from app.ping.prompts import get_ping_prompt

logger = logging.getLogger(__name__)


def _ping_model_override() -> str | None:
    """Model to use for pings. On anthropic, pings run on the cheaper haiku model
    instead of the main dialog's sonnet. None for other providers (use their default)."""
    if settings.PING_AI_PROVIDER.lower() == "anthropic":
        return settings.PING_ANTHROPIC_MODEL_NAME
    return None


def _ping_model_string() -> str:
    return get_model_string(settings.PING_AI_PROVIDER, _ping_model_override())


def _ping_model_name() -> str:
    return get_model_name(settings.PING_AI_PROVIDER, _ping_model_override())


def _ping_is_qwen() -> bool:
    return settings.PING_AI_PROVIDER.lower() == "qwen"


# qwen3-max can't combine tools with response_format (output_type) — it suppresses tool_calls.
# So for qwen we drop output_type, keep tool_choice="required" (works without response_format),
# request the JSON via prompt, and parse final_output by hand. See providers.parse_agent_output.
PING_JSON_INSTRUCTION = """

# ФОРМАТ ОТВЕТА
Сначала ОБЯЗАТЕЛЬНО вызови инструменты (get_dialog_history, get_ping_scripts),
чтобы прочитать историю и доступные скрипты. Затем верни ТОЛЬКО один JSON-объект (без markdown-обёрток,
без текста до/после) со схемой:
{
  "action": "<send|skip|complete>",
  "selected_step": <номер step для отправки, обязателен при action=send, иначе null>,
  "custom_text": "<адаптированный текст сообщения при action=send, иначе null>",
  "reason": "<краткая причина решения>"
}
action="skip" — если ВСЕ показанные шаги уже покрыты диалогом по смыслу, но в воронке есть ещё
шаги дальше: воронка сдвинется, и на следующем тике ты увидишь следующие шаги.
action="complete" — ТОЛЬКО по СТОП-условиям или когда шагов в воронке больше не осталось."""


async def _save_ping_run(
    db: AsyncSession,
    dialog_id: int,
    result,
    elapsed_ms: int,
    label: str,
    instructions: str | None = None,
) -> AIRun:
    _provider = settings.PING_AI_PROVIDER
    _model = _ping_model_name()
    input_tokens = sum(getattr(r.usage, "input_tokens", 0) for r in result.raw_responses)
    output_tokens = sum(getattr(r.usage, "output_tokens", 0) for r in result.raw_responses)
    # OpenAI-style usage: input_tokens INCLUDES cached tokens, which are billed at a
    # discounted per-family rate — bill them separately instead of at full input price
    # (same logic as app/ai/runner.py). Providers that don't report
    # input_tokens_details (or return 0) are unaffected.
    cache_read_tokens = sum(
        getattr(getattr(r.usage, "input_tokens_details", None), "cached_tokens", 0) or 0
        for r in result.raw_responses
    )
    in_price, out_price = get_model_pricing(_model)
    cost = calculate_cost(
        input_tokens - cache_read_tokens,
        output_tokens,
        in_price,
        out_price,
        cache_read_tokens=cache_read_tokens,
        cache_read_mult=CACHE_READ_MULT_BY_MODEL.get(_model, DEFAULT_CACHE_READ_MULT),
    )
    full_context = None
    if instructions is not None:
        try:
            full_context = {"system": instructions, "messages": result.to_input_list()}
        except Exception:
            logger.warning("ping: failed to build full_context | dialog=%s", dialog_id, exc_info=True)
    run = AIRun(
        dialog_id=dialog_id,
        provider=_provider,
        model=_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=0,
        cost_amount=cost,
        cost_currency="USD",
        cost_estimated=(input_tokens == 0),
        latency_ms=elapsed_ms,
        selected_script=label,
        full_context=full_context,
    )
    db.add(run)
    await db.flush()
    return run


class FunnelOutput(BaseModel):
    funnel: str = Field(description="Detected funnel type from the available list")
    reason: str = Field(description="Brief reason for this classification")


# Product prices are always 4-5 digits, optionally space-grouped («12 900₽», «12900 руб»).
# 3-digit amounts (delivery «от 890₽», first payment «800 руб») are NOT a price quote.
_PRICE_RE = re.compile(r"\d{1,3}[  ]?\d{3}\s*(?:₽|руб)", re.IGNORECASE)


def _manager_sent_price(history_text: str) -> bool:
    """True if any manager/AI line in the transcript contains a product price.

    The funnel prompt's own gate («hot/thinking/expensive only after prices were
    sent») is routinely ignored by the model — client 8546030 got the hot funnel
    («клиент прислал фото, уточнил город») before any price was quoted. This is
    the deterministic version of that gate. Continuation lines of a multi-line
    message belong to the last seen role prefix.
    """
    is_manager = False
    for line in history_text.splitlines():
        if line.startswith("[Клиент]"):
            is_manager = False
        elif line.startswith("["):
            is_manager = True
        if is_manager and _PRICE_RE.search(line):
            return True
    return False


async def detect_funnel_with_ai(
    db: AsyncSession,
    dialog: Dialog,
) -> tuple[str | None, str | None]:
    """Returns (funnel_type, reason). reason is a one-sentence justification for the
    chosen funnel, persisted on the ping state and surfaced in the chat UI.
    Returns (None, None) on detection failure (caller skips state creation)."""
    type_id = getattr(dialog, "type_id", None)

    funnels_result = await db.execute(
        select(PingRule.funnel_type).where(
            PingRule.type_id == type_id,
            PingRule.is_active == True,
        ).distinct()
    )
    funnels = [row[0] for row in funnels_result.fetchall()]
    if not funnels:
        logger.warning("detect_funnel_ai: no funnels in DB | dialog=%s type_id=%s", dialog.id, type_id)
        return "regular", "нет активных воронок в БД — fallback regular"

    msgs_result = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog.id)
        .order_by(Message.created_at.desc())
        .limit(30)
    )
    msgs = list(reversed(msgs_result.scalars().all()))
    lines = [
        f"[{'Клиент' if m.role == MessageRole.client else 'Менеджер'}]: {m.text}"
        for m in msgs
    ]
    history_text = "\n".join(lines)

    # Deterministic gate: without a quoted price every paid-track funnel is off the
    # table, so skip the LLM entirely (also saves the detection call).
    if not _manager_sent_price(history_text):
        if "regular" in funnels:
            reason = "цены ещё не отправлялись — платные воронки недоступны (код-гейт)"
            logger.info(
                "detect_funnel_ai: price gate -> regular | dialog=%s type_id=%s", dialog.id, type_id,
            )
            return "regular", reason
        # Единственная настроенная воронка — «Знает цену», и до отправки цены она
        # бессмысленна: клиент, который цены не видел, получил бы «Я Вам стоимость
        # отправила, а вы мне что-то не отвечаете))». Пингов пока нет вообще.
        logger.info(
            "detect_funnel_ai: цены нет, воронки без цены не настроены — пингов не будет "
            "| dialog=%s type_id=%s | funnels=%s", dialog.id, type_id, funnels,
        )
        return None, None

    # Выбирать не из чего — вызов модели вернул бы единственный вариант, но стоил бы
    # запроса на каждый молчащий диалог.
    if len(funnels) == 1:
        logger.info(
            "detect_funnel_ai: одна воронка в БД -> %s без вызова модели | dialog=%s",
            funnels[0], dialog.id,
        )
        return funnels[0], "единственная настроенная воронка"

    funnels_list = ", ".join(f'"{f}"' for f in funnels)
    instructions = f"""\
Ты классифицируешь диалог клиента по типу воронки для выбора стратегии follow-up пингов.
Доступные воронки: {funnels_list}

Пункты hot,thinking,expensive,after_payment работают только если клиенту уже отправили цены

hot:
1) Есть фото от КЛИЕНТА
2) Написал дату и город
3) Сам задаёт вопросы после расчёта
4) Быстро (до часа) отвечает после расчёта
5) Просит позвонить после того, как активно отвечал в диалоге
6) Ответил после цены  (удобно / всё подходит / поищу фото)
7) Прислал ФИО и номер телефона
8) Спросил, куда отправлять предоплату
9) Попросил скидку

thinking (только при явном тексте):
1) Прямо пишет «думаю»
2) После расчёта задаёт сопутствующие вопросы (сроки / какие фото нужны)
3) Сравнивает с другими подарками/студиями

expensive (только при явном тексте):
1) Прямо говорит «дорого»
2) После расчёта пишет: спасибо / спасибо за информацию / мне не надо / напишу потом / мне на будущее / напишу позже

after_payment:
1) Ссылку на оплату отправили, но клиент не оплатил

regular - Для всех остальных случаев

ВАЖНО: Отвечай ТОЛЬКО валидным JSON без каких-либо объяснений, рассуждений или markdown.
Формат ответа: {{"funnel": "<тип>", "reason": "<одно предложение обоснования>"}}
Никакого текста вне JSON. Никаких заголовков. Только JSON.
"""

    agent = Agent(
        name="FunnelDetector",
        instructions=instructions,
        model=_ping_model_string(),
        tools=[],
        output_type=FunnelOutput,
    )

    result = None
    run_saved = False
    _t0 = int(time.time() * 1000)
    try:
        result = await Runner.run(
            agent,
            [{"role": "user", "content": f"История диалога:\n{history_text or '(пусто)'}"}],
        )
        await _save_ping_run(db, dialog.id, result, int(time.time() * 1000) - _t0, "ping:detect_funnel", instructions)
        run_saved = True
        output: FunnelOutput = result.final_output
        detected = output.funnel if output.funnel in funnels else funnels[0]
        reason = output.reason
        logger.info(
            "detect_funnel_ai: funnel=%s reason=%r | dialog=%s type_id=%s",
            detected, reason, dialog.id, type_id,
        )
    except Exception as e:
        raw = str(e)
        logger.error(
            "detect_funnel_ai: detection FAILED, skipping funnel | dialog=%s type_id=%s: %s",
            dialog.id, type_id, raw[:200],
        )
        if not run_saved:  # otherwise the usage is already in ai_runs — don't double-count
            p_in, p_out, p_cached = usage_from_result(result)
            await log_failed_run(
                dialog_id=dialog.id, provider=settings.PING_AI_PROVIDER,
                model=_ping_model_name(), error=e, label="ping:detect_funnel",
                input_tokens=p_in, output_tokens=p_out, cache_read_tokens=p_cached,
                elapsed_ms=int(time.time() * 1000) - _t0,
            )
        return None, None
    return detected, reason


class PingAgentOutput(BaseModel):
    action: Literal["send", "skip", "complete"] = Field(
        description=(
            "'send' to send a script to the client, 'skip' when every shown step is already "
            "covered by the dialog but the funnel has more steps ahead (advances the window "
            "without sending), 'complete' to end the ping sequence"
        )
    )
    selected_step: int | None = Field(
        default=None,
        description="Ping rule step number to send. Required when action='send'.",
    )
    custom_text: str | None = Field(
        default=None,
        description=(
            "Adapted message text to send instead of the raw quick phrase. "
            "When action='send', always provide this — rewrite the phrase to fit the dialog context naturally. "
            "Keep the same intent but adjust wording, tone, or details as needed."
        ),
    )
    reason: str = Field(default="", description="Brief reason for the decision")


async def _fetch_dialog_history(db: AsyncSession, dialog: Dialog) -> str:
    """Recent local dialog history, formatted for the prompt."""
    result = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog.id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    msgs = list(reversed(result.scalars().all()))
    lines = []
    for m in msgs:
        role = "Клиент" if m.role == MessageRole.client else "Менеджер"
        lines.append(f"[{role}]: {m.text}")
    return "\n".join(lines) or "(история пуста)"


def _build_ping_agent(
    instructions: str, dialog: Dialog, state: DialogPingState, db: AsyncSession, counter: dict
) -> Agent:
    @function_tool
    async def get_dialog_history() -> str:
        """Return the recent dialog history to understand the conversation context."""
        counter["context_calls"] += 1
        counter["history_calls"] += 1
        return await _fetch_dialog_history(db, dialog)

    @function_tool
    async def get_ping_scripts() -> str:
        """Return the next 3 ping scripts (current_step .. current_step + 2).

        Each line: step number, the step's full phrase text, and manual_text if applicable.
        The 3-step window lets the agent skip a step whose topic the manager/AI has
        already covered in the dialog and jump to the first step with a fresh topic.
        A trailing summary line reports how many steps remain BEYOND the window, so a
        fully-duplicated window leads to action='skip' (advance the window), not a
        premature 'complete' (see dialog 15365: steps 0-2 were all photo-themed, the
        client had already sent a photo, and the agent killed the whole sequence).
        """
        counter["context_calls"] += 1

        async def _fetch(tag) -> list[PingRule]:
            result = await db.execute(
                select(PingRule).where(
                    PingRule.type_id == getattr(dialog, "type_id", None),
                    PingRule.funnel_type == state.funnel_type,
                    PingRule.step >= state.current_step,
                    PingRule.is_active == True,
                    PingRule.marketing_tag == tag,
                ).order_by(PingRule.step)
            )
            return list(result.scalars().all())

        # Strictly by tag first. Only if nothing found for the tag, fall back to untagged (NULL).
        all_rules = await _fetch(state.marketing_tag) if state.marketing_tag else []
        if not all_rules:
            all_rules = await _fetch(None)
        if not all_rules:
            return "Нет доступных скриптов."
        rules = [r for r in all_rules if r.step <= state.current_step + 2]
        later_steps = sorted({r.step for r in all_rules if r.step > state.current_step + 2})
        lines = []
        for r in rules:
            text = " ".join((r.phrase_text or "").split())
            manual = f" | manual_text: {r.manual_text}" if r.manual_text else ""
            phrase = f" | текст: {text}" if text else ""
            lines.append(f"step={r.step}{phrase}{manual}")
        if later_steps:
            lines.append(
                f"Дальше в воронке есть ещё {len(later_steps)} шаг(ов): "
                f"{', '.join(str(s) for s in later_steps)}. Если ВСЕ показанные шаги уже "
                "покрыты диалогом по смыслу — верни action=\"skip\" (НЕ complete), и я "
                "покажу следующие шаги."
            )
        else:
            lines.append("Это последние шаги воронки — дальше шагов нет.")
        return "\n".join(lines)

    tools = [get_dialog_history, get_ping_scripts]
    # Force a tool call before the agent may emit its final decision — otherwise the
    # model sometimes returns action=complete without ever reading the dialog. Agent
    # resets tool_choice to "auto" after the first call (reset_tool_choice defaults
    # True), so this guarantees at least one context fetch without looping forever.
    model_settings = ModelSettings(tool_choice="required")

    if _ping_is_qwen():
        # No output_type — response_format would suppress tool_calls. tool_choice="required"
        # still works without response_format. JSON requested via prompt, parsed manually.
        return Agent(
            name="PingAgent",
            instructions=instructions + PING_JSON_INSTRUCTION,
            model=_ping_model_string(),
            tools=tools,
            model_settings=model_settings,
        )

    return Agent(
        name="PingAgent",
        instructions=instructions,
        model=_ping_model_string(),
        tools=tools,
        output_type=PingAgentOutput,
        model_settings=model_settings,
    )


async def run_ping_agent(
    db: AsyncSession,
    state: DialogPingState,
    dialog: Dialog,
) -> tuple[PingAgentOutput, int, int, AIRun]:
    """Run the ping agent. Returns (output, context_calls, history_calls, ai_run).

    context_calls = how many times the agent fetched dialog context (get_dialog_history
    / get_ping_scripts). Lets the caller distinguish a genuine 'complete' (agent read the
    context and decided to stop) from a misfire ('complete' emitted without ever reading
    context — the model bailing instead of fetching it).

    history_calls = how many times the agent called get_dialog_history specifically.
    A 'send' with history_calls==0 is a blind send — the agent adapted the raw phrase
    template without ever reading the conversation (wrong message, stray greeting).
    get_ping_scripts satisfies tool_choice="required" without counting here as a history
    read, so the agent can emit a decision having read only the scripts, never the dialog."""
    type_id: int | None = getattr(dialog, "type_id", None)
    instructions = await get_ping_prompt(db, type_id=type_id)

    # Per-turn dynamic context goes into separate user messages (NOT the system prompt)
    # so the system prompt stays byte-stable and cacheable.
    dynamic_context: list[str] = []

    feedback_rules = await load_active_feedback_rules(db, type_id, is_ping=True)
    if feedback_rules:
        items = []
        for r in feedback_rules:
            items.append(f"Сообщение ИИ: «{r['message_text']}»\nОшибка: {r['rule_text']}")
        rules_block = "\n\n".join(items)
        dynamic_context.append("[Разбор ошибок пинг-сообщений — учти и не повторяй]\n" + rules_block)
        logger.info("ping_agent: feedback rules injected | count=%d | dialog=%s", len(feedback_rules), dialog.id)

    # Sales-script stage (funnel_stage) injection removed: it was derived from the manager's
    # LAST message and instructed "work this step", which forced the ping to repeat the topic
    # the manager had just covered (e.g. format already pitched → ping re-pitches format).
    # Step selection now relies on get_ping_scripts + history dedup in the prompt.

    counter = {"context_calls": 0, "history_calls": 0}
    agent = _build_ping_agent(instructions, dialog, state, db, counter)

    client = await db.get(Client, dialog.client_id)
    client_name = (client.name or "").strip() if client else ""

    # History is injected unconditionally — never left to the model to decide whether to
    # fetch it. Without it the agent adapts the raw phrase template blind and produces
    # off-context messages (the get_dialog_history tool stays available for a re-read).
    history = await _fetch_dialog_history(db, dialog)
    user_prompt = (
        "Выбери подходящий ping-скрипт для отправки клиенту.\n\n"
        f"[История диалога]\n{history}"
    )
    if client_name:
        user_prompt += f"\n\n[Контекст сессии]\nИмя клиента: {client_name}"

    run_messages = [{"role": "user", "content": user_prompt}]
    for block in dynamic_context:
        run_messages.append({"role": "user", "content": block})

    _t0 = int(time.time() * 1000)
    result = None
    try:
        result = await Runner.run(agent, run_messages)
        elapsed_ms = int(time.time() * 1000) - _t0
        # qwen drops output_type (response_format kills tool_calls), so final_output is a raw
        # JSON string — parse it by hand. Other providers return a validated PingAgentOutput.
        if _ping_is_qwen():
            output: PingAgentOutput = parse_agent_output(result.final_output, PingAgentOutput)
        else:
            output: PingAgentOutput = result.final_output
    except Exception as e:
        # The API call was billed even though the run failed (parse error keeps its
        # usage on `result`; transport error leaves it None) — record it for cost.
        p_in, p_out, p_cached = usage_from_result(result)
        await log_failed_run(
            dialog_id=dialog.id, provider=settings.PING_AI_PROVIDER,
            model=_ping_model_name(), error=e, label="ping:agent",
            input_tokens=p_in, output_tokens=p_out, cache_read_tokens=p_cached,
            elapsed_ms=int(time.time() * 1000) - _t0,
        )
        raise

    context_calls = counter["context_calls"]
    history_calls = counter["history_calls"]

    label = f"ping:{output.action}" if output.selected_step is None else f"ping:step={output.selected_step}"
    ping_run = await _save_ping_run(db, dialog.id, result, elapsed_ms, label, instructions)

    logger.info(
        "ping_agent: action=%s step=%s context_calls=%d history_calls=%d reason=%r | dialog=%s funnel=%s",
        output.action, output.selected_step, context_calls, history_calls, output.reason, dialog.id, state.funnel_type,
    )
    return output, context_calls, history_calls, ping_run
