"""Ping worker — finds ignored dialogs and sends scheduled follow-up pings."""
import asyncio
import logging
import re
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Client, Dialog, DialogPingState, DialogStatusConfig, DialogType, Message, MessageRole,
    PingRule, VkGroup,
)
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.logging_context import current_dialog_type
from app.ping.eligibility import is_non_broadcast_curator_message, is_pingable_outbound
from app.sales.color_palette import with_palette
from app.sales.order_slots import collect_slots
from app.utils.media import carry_over_attachments
from app.utils.time import msk_now
from app.ai.triggers import CURATOR_STATUS_NAME
from app.utils.text import normalize_dashes, strip_foreign_name
from app.vk.outgoing import delivered_only, mark_delivered, was_delivered
from app.messaging import MessagesForbiddenError, dialogs_on_inactive_channels, send_to_dialog
from app.vk.spintax import resolve_spintax

logger = logging.getLogger(__name__)

_MIN_SILENCE_SECONDS = 15 * 60

# Воронки, которые назначает КОД по факту, а не классификатор по переписке:
# «показаны способы оплаты» и «выставлен счёт». Их две особенности — они не
# участвуют в автоопределении (app.ping.agent.detect_funnel_with_ai) и не гасятся
# заслоном горячей стадии: заслон написан против ОБЩЕЙ воронки, которая после
# способов оплаты спрашивала «что для Вас важнее — качество или цена?», а эти
# воронки для горячей стадии и заведены (просьба Лены от 01.09).
FORCED_FUNNELS = frozenset({"checkout", "after_payment"})

# Какая из них подходит диалогу, застрявшему на горячей стадии. Стадию ставит
# классификатор на каждое сообщение клиента, и по ней видно, что человеку уже
# показали: способы оплаты (checkout) или счёт (payment_link, post_payment).
FUNNEL_BY_STAGE = {
    "checkout": "checkout",
    "payment_link": "after_payment",
    "post_payment": "after_payment",
}

# Ping agent sometimes returns action=complete without calling its context tools (a
# model misfire). We retry such states instead of killing them; _MAX_PING_MISFIRES
# bounds the retries so a persistently-broken agent eventually stops.
_PING_MISFIRE_RETRY_SECONDS = 30 * 60
_MAX_PING_MISFIRES = 3


async def _find_rule(
    db: AsyncSession,
    type_id: int | None,
    funnel_type: str,
    step: int,
    marketing_tag: str | None,
) -> PingRule | None:
    """Look up a ping rule, preferring marketing_tag-specific match, falling back to NULL."""
    if marketing_tag:
        rule = await db.scalar(
            select(PingRule).where(
                PingRule.type_id == type_id,
                PingRule.funnel_type == funnel_type,
                PingRule.step == step,
                PingRule.marketing_tag == marketing_tag,
                PingRule.is_active == True,
            )
        )
        if rule:
            return rule
    return await db.scalar(
        select(PingRule).where(
            PingRule.type_id == type_id,
            PingRule.funnel_type == funnel_type,
            PingRule.step == step,
            PingRule.marketing_tag == None,
            PingRule.is_active == True,
        )
    )


async def _find_next_rule_after(
    db: AsyncSession,
    type_id: int | None,
    funnel_type: str,
    after_step: int,
    marketing_tag: str | None,
) -> PingRule | None:
    """First active rule with step > after_step. Same tag preference as _find_rule:
    tag-specific rules first, untagged (NULL) only when the tag has none at all."""
    async def _first(tag) -> PingRule | None:
        return await db.scalar(
            select(PingRule).where(
                PingRule.type_id == type_id,
                PingRule.funnel_type == funnel_type,
                PingRule.step > after_step,
                PingRule.marketing_tag == tag,
                PingRule.is_active == True,
            ).order_by(PingRule.step).limit(1)
        )

    if marketing_tag:
        rule = await _first(marketing_tag)
        if rule:
            return rule
    return await _first(None)


async def _find_first_rule(
    db: AsyncSession,
    type_id: int | None,
    funnel_type: str,
    marketing_tag: str | None,
) -> PingRule | None:
    """First active rule of the funnel by MIN step — funnels may start at 0 or 1."""
    return await _find_next_rule_after(db, type_id, funnel_type, -1, marketing_tag)


# Leading name vocative: "Татьяна, ..." → group(1)="Татьяна". Requires a comma + space.
_LEADING_NAME = re.compile(r"^\s*([А-ЯЁ][а-яё]+)\s*,\s+")

# Pings forbid greetings, but the qwen model keeps prepending "Добрый день" no matter
# how the prompt phrases the ban — so strip it deterministically. Optional leading name
# vocative is captured and kept ("Натали, добрый день! …" → "Натали, …").
_GREETING_WORDS = (
    r"добр(?:ый|ого|ое|ого)\s+(?:день|дня|вечер|вечера|утро|утра)"
    r"|доброго\s+времени(?:\s+суток)?"
    r"|здравствуйте|здравствуй|приветствую|привет(?:ик)?"
)
_LEADING_GREETING = re.compile(
    rf"^\s*(?:([А-ЯЁ][а-яё]+)\s*,\s*)?(?:{_GREETING_WORDS})[\s!,.…)\-–—]*",
    re.IGNORECASE,
)


def _strip_greeting(text: str) -> str:
    """Drop a leading greeting ("Добрый день" / "Здравствуйте" / "Привет"), keeping any
    name vocative: "Натали, добрый день! Текст" → "Натали, Текст"."""
    m = _LEADING_GREETING.match(text)
    if not m:
        return text
    rest = text[m.end():]
    if not rest:
        return text
    rest = rest[0].upper() + rest[1:]
    name = m.group(1)
    return f"{name}, {rest}" if name else rest


def _deliverable(dialog: Dialog | None) -> bool:
    """Есть ли куда отправлять. Тестовый диалог живёт только в панели: клиента в
    канала за ним нет, и send_to_dialog на нём падает с «no VK client binding».
    Сообщение всё равно сохраняем — ради него тестовый диалог и заводят."""
    return bool(dialog) and not dialog.is_test


async def _last_outbound_text(db: AsyncSession, dialog: Dialog) -> str | None:
    """Text of the most recent manager/AI message in this dialog."""
    rows = await db.execute(
        select(Message)
        .where(
            Message.dialog_id == dialog.id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
        .order_by(Message.created_at.desc())
        .limit(5)
    )
    for msg in rows.scalars().all():
        if was_delivered(msg):
            return (msg.text or "").strip() or None
    return None


# Столько последних сообщений хватает, чтобы найти надпись: её называют в самом
# начале воронки, но и полную историю ради одного слова тянуть незачем.
_INSCRIPTION_HISTORY_LIMIT = 100


async def _order_inscription(db: AsyncSession, dialog: Dialog | None) -> str | None:
    """Надпись, которую клиент заказал на изделие. Ею модель зовёт клиента."""
    if dialog is None:
        return None
    rows = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog.id)
        .order_by(Message.created_at.desc())
        .limit(_INSCRIPTION_HISTORY_LIMIT)
    )
    msgs = list(reversed(rows.scalars().all()))
    slots = collect_slots(
        [("client" if m.role == MessageRole.client else "manager", m.text) for m in msgs]
    )
    return slots.get("inscription")


def _strip_repeated_name(text: str, prev_text: str | None) -> str:
    """Rule "имя максимум через раз": if the previous outbound message already
    opened with the SAME name vocative, drop the leading name from this one.
    Same-word match keeps non-name openers ("Да,", "Здравствуйте,") untouched."""
    m = _LEADING_NAME.match(text)
    if not m:
        return text
    pm = _LEADING_NAME.match(prev_text or "")
    if not pm or m.group(1).lower() != pm.group(1).lower():
        return text
    rest = text[m.end():]
    if not rest:
        return text
    return rest[0].upper() + rest[1:]


async def _send_ping(
    db: AsyncSession,
    state: DialogPingState,
    rule: PingRule,
    now,
    custom_text: str | None = None,
    ai_run=None,
):
    """Отправка пинга через ВК. Возвращает True | 'duplicate' | 'blocked' | False."""
    dialog = await db.get(Dialog, state.dialog_id)

    if custom_text:
        custom_text = normalize_dashes(custom_text)
        degreeted = _strip_greeting(custom_text)
        if degreeted != custom_text:
            logger.info("ping: stripped greeting | dialog=%s", state.dialog_id)
            custom_text = degreeted
        # Обращение чужим именем: пинг звал клиента «Пётр» по надписи на кофте,
        # хотя в профиле имени нет вовсе (клиент 289653120).
        client = await db.get(Client, dialog.client_id) if dialog else None
        dename = strip_foreign_name(
            custom_text,
            client.name if client else None,
            await _order_inscription(db, dialog),
        )
        if dename != custom_text:
            logger.info("ping: убрано чужое обращение по имени | dialog=%s", state.dialog_id)
            custom_text = dename
        prev_text = await _last_outbound_text(db, dialog)
        stripped = _strip_repeated_name(custom_text, prev_text)
        if stripped != custom_text:
            logger.info("ping: stripped repeated name | dialog=%s", state.dialog_id)
            custom_text = stripped

    phrase_template = (rule.phrase_text or "").strip()

    # Шаг без текста: manual_text уходит как есть, совсем пустой шаг — маркер для куратора.
    if not phrase_template and not custom_text:
        if rule.manual_text:
            result = None
            if _deliverable(dialog):
                try:
                    result = await send_to_dialog(db, dialog, rule.manual_text)
                except MessagesForbiddenError:
                    return "blocked"
                except Exception as exc:
                    logger.error("ping: send failed | dialog=%s: %s", state.dialog_id, exc)
                    return False
            msg = Message(
                dialog_id=state.dialog_id,
                role=MessageRole.ai,
                text=rule.manual_text,
                msg_metadata={
                    "ping": True,
                    "funnel": state.funnel_type,
                    "step": state.current_step,
                },
            )
            db.add(msg)
            if result is not None:
                mark_delivered(msg, result)
            dialog.last_message_at = now
            logger.info("ping: manual_text sent | dialog=%s step=%s", state.dialog_id, state.current_step)
        else:
            msg = Message(
                dialog_id=state.dialog_id,
                role=MessageRole.ai,
                text="[ручной пинг]",
                msg_metadata={
                    "ping": True,
                    "need_curator": True,
                    "funnel": state.funnel_type,
                    "step": state.current_step,
                },
            )
            db.add(msg)
            logger.info("ping: manual step (no text) | dialog=%s step=%s", state.dialog_id, state.current_step)
        if ai_run is not None:
            await db.flush()
            ai_run.output_message_id = msg.id
        return True

    sent_text = custom_text or normalize_dashes(resolve_spintax(phrase_template))
    # Агент переписывает фразу своими словами и теряет вложения: 33 пинга из 70
    # ушли без картинки, хотя в правиле она была. Возвращаем их на место.
    sent_text = carry_over_attachments(sent_text, phrase_template)
    # Пинг тоже переспрашивает про цвет («Стоимость я уже отправила… подскажите,
    # какой цвет?»), а палитра к такому вопросу обязательна — требование ОП.
    sent_text = await with_palette(
        db, sent_text, getattr(dialog, "type_id", None), None, f"ping:{state.dialog_id}",
    )

    # Content-level duplicate guard: the model can rewrite an already-sent message
    # almost verbatim (same pattern as sales client 8474931). Same normalization/
    # threshold as the runner's guard.
    from app.ai.runner import _find_duplicate_reply

    prior_rows = await db.execute(
        select(Message).where(
            Message.dialog_id == state.dialog_id,
            Message.role.in_((MessageRole.ai, MessageRole.curator)),
        )
    )
    prior_texts = [m.text for m in delivered_only(list(prior_rows.scalars().all())) if m.text]
    if _find_duplicate_reply(sent_text, prior_texts):
        logger.info(
            "ping: text near-duplicates an already sent message, skip | dialog=%s step=%s",
            state.dialog_id, state.current_step,
        )
        return "duplicate"

    result = None
    if not _deliverable(dialog):
        logger.info("ping: тестовый диалог %s — пишем в панель, ВК не трогаем", state.dialog_id)
    else:
        try:
            result = await send_to_dialog(db, dialog, sent_text)
        except MessagesForbiddenError:
            return "blocked"
        except Exception as exc:
            logger.error("ping: send failed | dialog=%s: %s", state.dialog_id, exc)
            return False

    msg = Message(
        dialog_id=state.dialog_id,
        role=MessageRole.ai,
        text=sent_text,
        msg_metadata={
            "ping": True,
            "ping_rule_id": rule.id,
            "funnel": state.funnel_type,
            "step": state.current_step,
            "custom_text": bool(custom_text),
        },
    )
    db.add(msg)
    # Без VK id и random_id ВК вернёт нам этот же пинг как message_reply, и мы
    # примем его за сообщение живого оператора — диалог встанет на паузу сам от
    # себя. Раньше возвращаемое значение send_to_dialog здесь выбрасывалось.
    if result is not None:
        mark_delivered(msg, result)
    dialog.last_message_at = now
    if ai_run is not None:
        await db.flush()
        ai_run.output_message_id = msg.id
    logger.info(
        "ping: sent | dialog=%s funnel=%s step=%s rule=%s custom=%s",
        state.dialog_id, state.funnel_type, state.current_step, rule.id, bool(custom_text),
    )
    return True


# Стадии, на которых лид уже горячий: назвал контакты, выбрал оплату, ждёт счёт
# или макет. Автопинг здесь только мешает — дальше ведёт человек.
HOT_STAGES = frozenset({"checkout", "payment_link", "post_payment"})


async def _escalate(db: AsyncSession, dialog: Dialog, reason: str) -> None:
    """Поставить диалогу «Нужен куратор» и позвать менеджера."""
    status = await db.scalar(
        select(DialogStatusConfig).where(DialogStatusConfig.name == CURATOR_STATUS_NAME)
    )
    if status:
        dialog.current_status_id = status.id
    logger.info("ping: диалог %s передан менеджеру — %s", dialog.id, reason)
    from app.notify import notify_curator
    await notify_curator(dialog.id, reason)


async def _process_state(db: AsyncSession, state: DialogPingState, now) -> None:
    dialog = await db.get(Dialog, state.dialog_id)

    # Живой оператор ведёт диалог или клиент запретил сообщения — пинги стоп.
    if dialog and (dialog.ai_paused or dialog.vk_blocked):
        state.is_completed = True
        logger.info(
            "ping: %s, stopping | dialog=%s",
            "ai paused" if dialog.ai_paused else "vk blocked", state.dialog_id,
        )
        await db.commit()
        return

    # MAX не сообщает о том, что менеджер ответил клиенту мимо панели, — об
    # этом можно узнать только из истории диалога. Спрашиваем до прогона: пинг
    # поверх живого разговора хуже, чем лишний запрос к MAX.
    if dialog:
        from app.max.manager_watch import pause_if_manager_replied

        if await pause_if_manager_replied(dialog.id):
            state.is_completed = True
            logger.info(
                "ping: диалог ведёт менеджер в MAX, stopping | dialog=%s", state.dialog_id,
            )
            await db.commit()
            return

    # Клиент уже выбрал способ оплаты или дал контакты — ОБЩИЙ пинг тут вредит.
    # Диалог 150: в 09:59 у клиента запросили ФИО, в 10:15 пинг спросил «что для
    # Вас важнее - качество или цена?» и отбросил его назад. ОП, 14:12: «должен
    # подключаться менеджер и пинговать клиента индивидуально. Не общими, как бот».
    #
    # Два исключения, оба появились 02.09 из правок ОП. Именная воронка горячей
    # стадии — это и есть тот самый индивидуальный дожим, ради которого заслон
    # ставили. А диалог, который менеджер вручную вернул ИИ, человек уже видел:
    # забирать его обратно автоматике незачем («вне зависимости от статуса»).
    if (
        dialog
        and dialog.funnel_stage in HOT_STAGES
        and state.funnel_type not in FORCED_FUNNELS
        and not state.resumed_by_manager
    ):
        state.is_completed = True
        dialog.ai_paused = True
        await _escalate(db, dialog, f"горячая стадия «{dialog.funnel_stage}», клиент молчит")
        await db.commit()
        return

    if dialog and dialog.current_status_id:
        status_obj = await db.get(DialogStatusConfig, dialog.current_status_id)
        if status_obj and status_obj.name == "ЧС":
            state.is_completed = True
            logger.info("ping: ЧС status, stopping | dialog=%s", state.dialog_id)
            await db.commit()
            return

    last_msg_result = await db.execute(
        select(Message)
        .where(Message.dialog_id == state.dialog_id)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last_msg = last_msg_result.scalar_one_or_none()
    if last_msg and last_msg.role == MessageRole.client:
        state.is_completed = True
        logger.info("ping: client responded, stop | dialog=%s", state.dialog_id)
        await db.commit()
        return

    from app.ping.agent import run_ping_agent
    agent_output, context_calls, _history_calls, ping_run = await run_ping_agent(db, state, dialog)

    if agent_output.action == "complete":
        # A 'complete' without reading any context is a model misfire — the agent bailed
        # instead of reading the dialog. Don't kill the sequence; retry on a later tick.
        if context_calls == 0:
            state.misfire_count = (state.misfire_count or 0) + 1
            if state.misfire_count >= _MAX_PING_MISFIRES:
                state.is_completed = True
                logger.warning(
                    "ping: %d consecutive complete-without-tools misfires, giving up | dialog=%s",
                    state.misfire_count, state.dialog_id,
                )
            else:
                state.next_ping_due_at = now + timedelta(seconds=_PING_MISFIRE_RETRY_SECONDS)
                logger.warning(
                    "ping: complete without tool calls (misfire %d/%d), retry at %s | dialog=%s",
                    state.misfire_count, _MAX_PING_MISFIRES, state.next_ping_due_at, state.dialog_id,
                )
            await db.commit()
            return
        state.is_completed = True
        await db.commit()
        return

    # Genuine agent decision — reset the misfire counter.
    if state.misfire_count:
        state.misfire_count = 0

    dialog_type_id = getattr(dialog, "type_id", None)

    if agent_output.action == "skip":
        # Every step in the agent's 3-step window is already covered by the dialog, but
        # the funnel has more steps ahead — advance the window instead of completing.
        next_rule = await _find_next_rule_after(
            db, dialog_type_id, state.funnel_type, state.current_step + 2, state.marketing_tag
        )
        if not next_rule:
            state.is_completed = True
            logger.info(
                "ping: skip requested but no steps beyond window, stop | dialog=%s step=%s",
                state.dialog_id, state.current_step,
            )
            await db.commit()
            return
        state.current_step = next_rule.step
        state.next_ping_due_at = now + timedelta(seconds=next_rule.delay_seconds)
        logger.info(
            "ping: window skipped to step %s, next at %s | dialog=%s reason=%s",
            next_rule.step, state.next_ping_due_at, state.dialog_id, (agent_output.reason or "")[:200],
        )
        await db.commit()
        return

    rule = await _find_rule(db, dialog_type_id, state.funnel_type, agent_output.selected_step, state.marketing_tag)
    if not rule:
        state.is_completed = True
        await db.commit()
        return

    state.current_step = agent_output.selected_step
    ok = await _send_ping(
        db, state, rule, now,
        custom_text=agent_output.custom_text, ai_run=ping_run,
    )

    if ok == "duplicate":
        # The picked step's content is already covered (near-verbatim text) — advance
        # the window to the next step instead of killing the funnel.
        next_rule = await _find_next_rule_after(
            db, dialog_type_id, state.funnel_type, agent_output.selected_step, state.marketing_tag
        )
        if not next_rule:
            state.is_completed = True
            logger.info(
                "ping: duplicate content and no steps left, stop | dialog=%s step=%s",
                state.dialog_id, agent_output.selected_step,
            )
        else:
            state.current_step = next_rule.step
            state.next_ping_due_at = now + timedelta(seconds=next_rule.delay_seconds)
            logger.info(
                "ping: duplicate content at step %s, window advanced to step %s | dialog=%s",
                agent_output.selected_step, next_rule.step, state.dialog_id,
            )
        await db.commit()
        return

    if ok and ok != "blocked" and rule.after_status:
        status_result = await db.execute(
            select(DialogStatusConfig).where(DialogStatusConfig.name == rule.after_status)
        )
        status_obj = status_result.scalar_one_or_none()
        if status_obj:
            dialog.current_status_id = status_obj.id
            logger.info(
                "ping: after_status applied | dialog=%s status=%s",
                state.dialog_id, rule.after_status,
            )
        else:
            logger.warning(
                "ping: after_status not found in dialog_statuses | dialog=%s status=%s",
                state.dialog_id, rule.after_status,
            )

    if ok == "blocked":
        blacklist_result = await db.execute(
            select(DialogStatusConfig).where(DialogStatusConfig.name == "ЧС")
        )
        blacklist_status = blacklist_result.scalar_one_or_none()
        if blacklist_status:
            dialog.current_status_id = blacklist_status.id
            logger.info("ping: client blocked community messages, set ЧС | client_id=%s dialog=%s", dialog.client_id, state.dialog_id)
        else:
            logger.warning("ping: ЧС status not found in dialog_statuses | dialog=%s", state.dialog_id)
        state.is_completed = True
        await db.commit()
        return
    if not ok:
        return

    state.last_ping_sent_at = now

    next_rule = await _find_next_rule_after(
        db, dialog_type_id, state.funnel_type, state.current_step, state.marketing_tag
    )
    if next_rule:
        state.current_step = next_rule.step
        state.next_ping_due_at = now + timedelta(seconds=next_rule.delay_seconds)
    else:
        # Автопинги кончились, а клиент так и не ответил. Раньше диалог на этом
        # просто затихал. Лена, 10.08: «Тут надо бросать диалог, должен
        # подключаться менеджер и пинговать клиента индивидуально. Не общими, как
        # бот». Дальше шаблоном давить нечем — зовём человека.
        state.is_completed = True
        if dialog is not None:
            await _escalate(db, dialog, "автопинги кончились, клиент не ответил")

    await db.commit()


async def _resolve_marketing_tag(db: AsyncSession, client: Client | None, type_id: int | None) -> str | None:
    """Первый локальный тег клиента, для которого есть тегированные пинг-правила."""
    if not client or not client.marketing_tags:
        return None
    client_tags = [t.upper().lstrip("#") for t in client.marketing_tags]
    known_result = await db.execute(
        select(PingRule.marketing_tag)
        .where(PingRule.type_id == type_id, PingRule.marketing_tag.isnot(None), PingRule.is_active == True)
        .distinct()
    )
    for row in known_result.fetchall():
        if row[0] and row[0].upper().lstrip("#") in client_tags:
            return row[0]
    return None


async def _init_ping_state(
    db: AsyncSession,
    dialog: Dialog,
    last_outbound_at,
    now,
    *,
    restart_completed: bool = False,
    resumed_by_manager: bool = False,
) -> None:
    existing_result = await db.execute(
        select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        if not restart_completed or not existing.is_completed:
            return
        # Менеджер остановил воронку, затем диалог передали обратно ИИ. Старое
        # завершённое состояние уникально по dialog_id и иначе навсегда мешает
        # завести новую последовательность пингов.
        await db.delete(existing)
        await db.flush()

    from app.ping.agent import detect_funnel_with_ai
    funnel, funnel_reason = await detect_funnel_with_ai(db, dialog)
    if funnel is None:
        logger.error("ping: state NOT created, funnel detection failed | dialog=%s", dialog.id)
        return

    type_id = getattr(dialog, "type_id", None)
    client = await db.get(Client, dialog.client_id)
    marketing_tag = await _resolve_marketing_tag(db, client, type_id)

    first_rule = await _find_first_rule(db, type_id, funnel, marketing_tag)
    if not first_rule:
        return

    next_due = last_outbound_at + timedelta(seconds=first_rule.delay_seconds)
    state = DialogPingState(
        dialog_id=dialog.id,
        funnel_type=funnel,
        funnel_reason=funnel_reason,
        current_step=first_rule.step,
        next_ping_due_at=next_due,
        marketing_tag=marketing_tag,
        resumed_by_manager=resumed_by_manager,
    )
    db.add(state)
    await db.flush()
    logger.info(
        "ping: state created | dialog=%s funnel=%s next_due=%s",
        dialog.id, funnel, next_due,
    )


async def stop_pings(db: AsyncSession, dialog_id: int, reason: str) -> None:
    """Закрыть пинг-воронку диалога прямо сейчас.

    `_process_state` гасит пинги по `ai_paused`, но только когда до диалога
    дойдёт очередь воркера — а очередной пинг может уйти раньше. Диалог, который
    забрал человек, должен замолкать в тот же момент: «пинги должны отключаться,
    когда диалог переведён на менеджера».
    """
    state = await db.scalar(
        select(DialogPingState).where(
            DialogPingState.dialog_id == dialog_id,
            DialogPingState.is_completed == False,
        )
    )
    if state is None:
        return
    state.is_completed = True
    logger.info("ping: остановлены | dialog=%s | %s", dialog_id, reason)


async def _last_outbound(db: AsyncSession, dialog_id: int) -> Message | None:
    """Последнее наше сообщение в диалоге: ответ ИИ или живая реплика менеджера.

    Рассылка сюда не годится — она приходит в диалог сама по себе и продолжением
    разговора не является (см. app.ping.eligibility).
    """
    rows = (await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog_id)
        .order_by(Message.created_at.desc())
        .limit(50)
    )).scalars().all()
    for msg in rows:
        if is_pingable_outbound(msg):
            return msg
    return None


async def _last_sent_ping_step(db: AsyncSession, dialog_id: int) -> int | None:
    """Номер шага последнего УШЕДШЕГО пинга, если он был.

    По самому состоянию это не восстановить: `current_step` означает то шаг,
    который ещё предстоит отправить (воронку погасил менеджер), то последний
    отправленный (воронка кончилась сама). Отличить одно от другого можно только
    по фактически ушедшим сообщениям.
    """
    rows = (await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog_id, Message.role == MessageRole.ai)
        .order_by(Message.created_at.desc())
        .limit(50)
    )).scalars().all()
    for msg in rows:
        meta = msg.msg_metadata or {}
        if meta.get("ping") and isinstance(meta.get("step"), int):
            return meta["step"]
    return None


async def resume_after_handoff(db: AsyncSession, dialog: Dialog, now=None) -> str:
    """Менеджер снял паузу — воронка пингов продолжается с того шага, где встала.

    Лена, 01.09: «Если менеджер снимает ИИ с паузы - ИИ нужно продолжить
    пинговать лида вне зависимости от статуса/прошлого диалога», и следом: «на
    чем закончили, то нужно и продолжить».

    Полагаться на `discover()` тут нельзя по двум причинам: он смотрит только
    сутки назад (`PING_DISCOVERY_MAX_AGE_HOURS`), а диалог менеджеру отдают и на
    неделю, и заводит он воронку с ПЕРВОГО шага — клиент, до которого дошли
    двенадцать, получил бы «Я Вам стоимость отправила, а вы мне что-то не
    отвечаете))» заново.

    Возвращает строку для лога — что именно сделали.
    """
    now = now or msk_now()
    last_out = await _last_outbound(db, dialog.id)
    state = await db.scalar(
        select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
    )

    # Диалог стоит на горячей ступени — догонять его надо своей воронкой, а не
    # общей: «Я Вам стоимость отправила, а вы мне что-то не отвечаете))» человеку,
    # которому уже показали способы оплаты, — это шаг назад. Пока ОП не заполнил
    # такую воронку, диалог молчит: это лучше, чем не тот пинг.
    named = FUNNEL_BY_STAGE.get(dialog.funnel_stage or "")
    if named and (state is None or state.funnel_type != named):
        first_rule = await _find_first_rule(db, dialog.type_id, named, None)
        if first_rule is None:
            return f"воронка «{named}» ещё не заполнена — пингов не будет"
        if state is not None:
            await db.delete(state)
            await db.flush()
        base = last_out.created_at if last_out is not None else now
        db.add(DialogPingState(
            dialog_id=dialog.id,
            funnel_type=named,
            funnel_reason="диалог вернул менеджер на горячей ступени",
            current_step=first_rule.step,
            next_ping_due_at=max(
                base + timedelta(seconds=first_rule.delay_seconds),
                now + timedelta(seconds=_MIN_SILENCE_SECONDS),
            ),
            resumed_by_manager=True,
        ))
        return f"заведена воронка «{named}» с шага {first_rule.step}"

    if state is None:
        if last_out is None:
            return "воронка не заведена — в диалоге нет наших сообщений"
        await _init_ping_state(
            db, dialog, last_out.created_at, now, resumed_by_manager=True,
        )
        # Завестись могло и не получиться: без отправленной цены платные воронки
        # недоступны, а другой в базе нет. Отчёт об этом обязан быть честным —
        # по нему решают, уйдёт клиенту сообщение или нет.
        created = await db.scalar(
            select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
        )
        if created is None:
            return "воронка не заведена — цену клиенту не отправляли"
        # Диалог молчит давно, и срок первого шага давно прошёл. Отправлять
        # немедленно нельзя: менеджер только что нажал «вернуть ИИ» и, скорее
        # всего, ещё в диалоге. Даём те же 15 минут тишины, что и всем.
        created.next_ping_due_at = max(
            created.next_ping_due_at, now + timedelta(seconds=_MIN_SILENCE_SECONDS),
        )
        return f"воронка «{created.funnel_type}» заведена с шага {created.current_step}"

    sent_step = await _last_sent_ping_step(db, dialog.id)
    if sent_step is None:
        # Ни одного пинга ещё не ушло — продолжаем с того шага, который был
        # назначен следующим.
        rule = await _find_rule(
            db, dialog.type_id, state.funnel_type, state.current_step, state.marketing_tag,
        ) or await _find_first_rule(db, dialog.type_id, state.funnel_type, state.marketing_tag)
    else:
        rule = await _find_next_rule_after(
            db, dialog.type_id, state.funnel_type, sent_step, state.marketing_tag,
        )
    if rule is None:
        state.is_completed = True
        where = f"после шага {sent_step} " if sent_step is not None else ""
        return f"шагов {where}в воронке {state.funnel_type} не осталось"

    base = last_out.created_at if last_out is not None else now
    due = base + timedelta(seconds=rule.delay_seconds)
    # Пауза могла держаться дольше всей воронки. Тогда пинг уходит ближайшим
    # тиком, но не мгновенно: менеджер только что писал клиенту сам.
    state.next_ping_due_at = max(due, now + timedelta(seconds=_MIN_SILENCE_SECONDS))
    state.current_step = rule.step
    state.is_completed = False
    state.resumed_by_manager = True
    state.misfire_count = 0
    return f"воронка {state.funnel_type} продолжена с шага {rule.step}"


async def force_ping_funnel(db: AsyncSession, dialog: Dialog, funnel: str, now) -> None:
    """Delete existing ping state and restart with the given funnel from its first step."""
    existing = await db.execute(
        select(DialogPingState).where(DialogPingState.dialog_id == dialog.id)
    )
    state = existing.scalar_one_or_none()
    if state:
        await db.delete(state)
        await db.flush()

    first_rule = await _find_first_rule(db, dialog.type_id, funnel, None)
    if not first_rule:
        logger.warning("force_ping_funnel: no rules | dialog=%s funnel=%s", dialog.id, funnel)
        return

    db.add(DialogPingState(
        dialog_id=dialog.id,
        funnel_type=funnel,
        current_step=first_rule.step,
        next_ping_due_at=now + timedelta(seconds=first_rule.delay_seconds),
    ))
    logger.info("ping: force funnel=%s | dialog=%s", funnel, dialog.id)


async def _load_type_names(db: AsyncSession) -> dict[int, str]:
    type_rows = await db.execute(select(DialogType))
    return {dt.id: dt.name for dt in type_rows.scalars().all()}


async def _process_due_one(state_id: int, now, type_id_to_name: dict[int, str]) -> None:
    """Process one due state in its own session/transaction.

    Re-locks the row by id with SKIP LOCKED and re-checks due-ness: between the id scan
    in process_due() and this task starting, a concurrent force_ping_funnel (which
    deletes/recreates the state), a client reply, or a second replica may have completed,
    rescheduled, or deleted the state — that race is what produced the StaleDataError
    stalls. A vanished or no-longer-due row is simply skipped.
    """
    async with AsyncSessionLocal() as db:
        state = await db.scalar(
            select(DialogPingState)
            .where(
                DialogPingState.id == state_id,
                DialogPingState.is_completed == False,
                DialogPingState.next_ping_due_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
        if not state:
            return
        # Capture the id up front: after a failed commit the session is in a
        # rolled-back state and every ORM attribute is expired, so reading
        # state.dialog_id later would itself raise PendingRollbackError.
        dialog_id = state.dialog_id
        _dialog = await db.get(Dialog, dialog_id)
        _type_name = type_id_to_name.get(getattr(_dialog, "type_id", None), "default") if _dialog else "default"
        _token = current_dialog_type.set(_type_name)
        try:
            await _process_state(db, state, now)
            # Commit per row so one bad state can't roll back others.
            await db.commit()
        except Exception as exc:
            # Roll back FIRST — otherwise the error log's attribute access dies on
            # the poisoned session and kills the task.
            await db.rollback()
            logger.error("ping: _process_state error | dialog=%s: %s", dialog_id, exc, exc_info=True)
        finally:
            current_dialog_type.reset(_token)


async def process_due() -> None:
    """Send pings whose next_ping_due_at has arrived. Runs in its own loop.

    States are processed concurrently (bounded by PING_DUE_CONCURRENCY): each state is
    an LLM + VK round-trip taking up to minutes, so sequential processing capped
    throughput at ~1 state/min and let the due backlog grow faster than it drained.
    Each state gets its own session — AsyncSession is not safe for concurrent use.
    """
    if not settings.PING_ENABLED:
        return

    now = msk_now()
    if not (8 <= now.hour < 22):
        return

    async with AsyncSessionLocal() as db:
        type_id_to_name = await _load_type_names(db)

        # Воронку выключенного канала не гасим (is_completed), а пропускаем: канал
        # включат обратно — и она продолжится с того же шага.
        due_filter = (
            DialogPingState.is_completed == False,
            DialogPingState.next_ping_due_at <= now,
            DialogPingState.dialog_id.not_in(dialogs_on_inactive_channels()),
        )
        due_total = await db.scalar(
            select(func.count()).select_from(DialogPingState).where(*due_filter)
        )
        if not due_total:
            return
        # LIMIT bounds the pass: an unbounded backlog otherwise made a single pass
        # run for minutes and never drain.
        ids_result = await db.execute(
            select(DialogPingState.id)
            .where(*due_filter)
            .order_by(DialogPingState.next_ping_due_at)
            .limit(settings.PING_DUE_BATCH_SIZE)
        )
        state_ids = list(ids_result.scalars().all())

    logger.info(
        "ping: due pass | due_total=%s processing=%s concurrency=%s",
        due_total, len(state_ids), settings.PING_DUE_CONCURRENCY,
    )

    sem = asyncio.Semaphore(settings.PING_DUE_CONCURRENCY)

    async def _guarded(state_id: int) -> None:
        async with sem:
            await _process_due_one(state_id, now, type_id_to_name)

    await asyncio.gather(*(_guarded(sid) for sid in state_ids))


async def discover() -> None:
    """Find stateless dialogs needing a ping, most-recently-silent first, capped per pass.

    Runs in a loop separate from process_due() so heavy due-send passes can't starve
    discovery. Ordered by last_message_at DESC and bounded to a [now-MAX_AGE,
    now-MIN_SILENCE] window.

    DESC (not ASC) is deliberate: eligible dialogs get a ping-state and leave the pool,
    so the frontier self-drains backwards in time. ASC instead piled the LIMIT onto the
    OLDEST dialogs — abandoned single-message leads that fail the eligibility gate, never
    get a state, never leave the pool, and so block every pass forever while fresh leads
    at the new end are never reached.
    """
    if not settings.PING_ENABLED:
        return

    async with AsyncSessionLocal() as db:
        now = msk_now()

        if not (8 <= now.hour < 22):
            return

        type_id_to_name = await _load_type_names(db)

        # Активная воронка всегда исключает диалог. Завершённую обычно тоже
        # сохраняем, чтобы исчерпанная цепочка не начиналась заново. Единственное
        # исключение ниже — последнее слово менеджера в уже снятой паузе: это
        # ручная передача диалога обратно автоматике.
        latest_role_subq = (
            select(Message.role)
            .where(Message.dialog_id == Dialog.id)
            .order_by(Message.created_at.desc())
            .limit(1)
            .correlate(Dialog)
            .scalar_subquery()
        )
        existing_ids_subq = select(DialogPingState.dialog_id).where(
            or_(
                DialogPingState.is_completed == False,
                latest_role_subq != MessageRole.curator,
            )
        )
        blacklist_ids_subq = select(DialogStatusConfig.id).where(DialogStatusConfig.name == "ЧС")
        silence_cutoff = now - timedelta(seconds=_MIN_SILENCE_SECONDS)
        max_age_cutoff = now - timedelta(hours=settings.PING_DISCOVERY_MAX_AGE_HOURS)
        dialogs_result = await db.execute(
            select(Dialog, VkGroup.platform)
            # Платформа нужна прямо в выборке: у MAX другое условие «клиент
            # вообще с нами общался» (см. ниже). outerjoin — тестовый диалог из
            # панели канала не имеет вовсе, а пинги в нём смотрят.
            .join(Client, Dialog.client_id == Client.id)
            .outerjoin(VkGroup, Client.vk_group_id == VkGroup.id)
            .where(
                # Тестовые диалоги тоже пингуем: воронку из 17 шагов иначе негде
                # посмотреть, а уйти клиенту такой пинг не может — отправка в ВК
                # для них пропускается (см. _deliverable).
                Dialog.ai_paused == False,
                # Канал выключен в админке — бот снят с работы целиком, догонять
                # его клиентов нельзя (см. dialogs_on_inactive_channels).
                Dialog.id.not_in(dialogs_on_inactive_channels()),
                Dialog.vk_blocked == False,
                Dialog.id.not_in(existing_ids_subq),
                Dialog.last_message_at.isnot(None),
                Dialog.last_message_at <= silence_cutoff,
                Dialog.last_message_at >= max_age_cutoff,
                or_(
                    Dialog.current_status_id.is_(None),
                    Dialog.current_status_id.not_in(blacklist_ids_subq),
                ),
            )
            .order_by(Dialog.last_message_at.desc())
            .limit(settings.PING_DISCOVERY_LIMIT)
        )
        for dialog, platform in dialogs_result.all():
            _type_name = type_id_to_name.get(dialog.type_id, "default")
            _token = current_dialog_type.set(_type_name)
            try:
                last_msg_result = await db.execute(
                    select(Message)
                    .where(Message.dialog_id == dialog.id)
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
                last_msg = last_msg_result.scalar_one_or_none()
                if not last_msg:
                    continue
                if not is_pingable_outbound(last_msg):
                    continue
                if last_msg.created_at > now - timedelta(seconds=_MIN_SILENCE_SECONDS):
                    continue
                client_msg_count = await db.scalar(
                    select(func.count()).where(
                        Message.dialog_id == dialog.id,
                        Message.role == MessageRole.client,
                    )
                )
                # Молчащего клиента, который нам ни разу не написал, в ВК не
                # догоняем: диалог там заводит либо его собственное сообщение,
                # либо рассылка, и пинговать второе — писать незнакомому
                # человеку. В MAX так нельзя рассуждать: боту там пишут только
                # после кнопки «Начать», её нажатие и есть согласие, а первым
                # словом клиента может быть молчание — приветствие и цену он
                # получает, не написав ни строчки. Такие диалоги оставались без
                # воронки навсегда: 24 диалога MAX, ни одного с пингами
                # (замечание ОП от 27.08: «в максе нет пингов по клиентам после
                # вопроса о доставке, их нужно подключить»). Цену он при этом
                # уже видел — без неё воронка всё равно не заводится
                # (app.ping.agent.detect_funnel_with_ai).
                if client_msg_count < 1 and platform != "max":
                    continue
                await _init_ping_state(
                    db,
                    dialog,
                    last_msg.created_at,
                    now,
                    restart_completed=is_non_broadcast_curator_message(last_msg),
                )
            except Exception as exc:
                logger.error("ping: _init_ping_state error | dialog=%s: %s", dialog.id, exc, exc_info=True)
            finally:
                current_dialog_type.reset(_token)

        await db.commit()
