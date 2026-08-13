"""AI runner — orchestrates agent execution and persists results to DB."""
import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime

from agents import Runner
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents import build_sales_agent
from app.ai.anthropic_runner import run_with_cache
from app.ai.audio import is_audio_url, transcribe_audio_url
from app.ai.cost import (
    CACHE_READ_MULT_BY_MODEL,
    DEFAULT_CACHE_READ_MULT,
    calculate_cost,
    get_model_pricing,
)
from app.ai.prompts import get_system_prompt, format_statuses_block
from app.ai.run_log import log_failed_run, usage_from_result
from app.ai.tools import fetch_client_tags
from app.ai.providers import get_model_name
from app.ai.schemas import AgentOutput
from app.ai.triggers import CURATOR_STATUS_NAME, curator_trigger
from app.config import settings
from app.utils.time import human_msk_now
from app.utils.media import (
    carry_over_attachments,
    is_document_url,
    is_image_url,
    is_sticker_url,
    is_video_url,
)
from app.vk.outgoing import delivered_only
from app.vk.spintax import resolve_spintax
from app.ai.feedback import load_active_feedback_rules
from app.ai.funnel_agent import detect_stage, format_stage_block
from app.ai.greeting import greeting_text, resolve_greeting
from app.sales.price_objection import concession_allowed
from app.sales.price_placeholder import payment_link_configured, render_price_placeholders
from app.sales.status_names import (
    AWAITING_PREPAY,
    HOT_ALLOWED_NEXT,
    ORDER_CREATED,
    can_await_prepay,
    is_hot,
)
from app.sales.funnel_steps import (
    CHECKOUT_PRESENTED_RE,
    PAYMENT_LINK_RE,
    answered_inscription_question,
    checkout_presented,
    client_refused,
    client_wants_design_edit,
    discount_script_ids,
    design_just_confirmed,
    dialog_has_payment_link,
    find_contacts_script,
    find_checkout_script,
    find_design_fixed_script,
    find_design_review_script,
    find_payment_link_script,
    find_praise_script,
    find_price_script,
    scripts_repeating_recent_question,
    funnel_advancing_script_ids,
    HONEST_CURATOR_OPTIONS,
    HONEST_OPTIONS,
    honest_answer,
    payment_option_chosen,
    render_design_review,
    reply_advances_funnel,
    size_just_given,
)
from app.sales.order_slots import (
    asked_slot,
    collect_slots,
    format_slots_block,
    render_order_placeholders,
    slot_is_filled,
)
from app.db.models import AIRun, Client, Dialog, DialogStatusConfig, Message, MessageRole, Script
from app.utils.text import (
    normalize_dashes,
    render_name_placeholder,
    strip_foreign_name,
    strip_repeated_greeting,
    vary_repeated_opening,
)

logger = logging.getLogger(__name__)


# (?<!\[photo-) / (?<!\[video-) — не трогать URL внутри "[photo-URL]"/"[video-URL]"
# токенов: их разбирает app.vk.sender.extract_and_resolve_attachments (перезалив
# на своё сообщество), а не эта голая-ссылка-текстом ветка.
_BARE_IMAGE_URL_RE = re.compile(
    r'(?<!\[photo-)(?<!\[video-)https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\S*)?',
    re.IGNORECASE,
)
_IMAGES_BLOCK_RE = re.compile(r"\n*<<<IMAGES>>>\n?(.*?)\n?<<<END_IMAGES>>>", re.DOTALL)

def _apply_status(dialog: Dialog, name: str, active_statuses) -> None:
    """Поставить диалогу статус по имени. Нужен для решений, принятых уже ПОСЛЕ
    основного блока смены статуса — он отрабатывает до сборки реплик."""
    matching = next((s for s in active_statuses if s.name == name), None)
    if matching is not None:
        dialog.current_status_id = matching.id


def _fit(value: str | None, limit: int) -> str | None:
    """Подрезать строку под ширину колонки. Значение пришло от модели, и слишком
    длинное роняло весь INSERT прогона — клиент вместо ответа получал 500."""
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit]


def _split_image_urls(text: str) -> tuple[str, list[str]]:
    """Вынести картинки из текста реплики: сначала блок <<<IMAGES>>> (его агент
    копирует из истории), иначе — голые ссылки на изображения."""
    images_match = _IMAGES_BLOCK_RE.search(text)
    if images_match:
        urls = [u.strip() for u in images_match.group(1).splitlines() if u.strip()]
        return text[: images_match.start()].rstrip(), urls
    urls = _BARE_IMAGE_URL_RE.findall(text)
    if urls:
        text = _BARE_IMAGE_URL_RE.sub("", text).strip()
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, urls


@dataclass
class ReplyPart:
    """Одно исходящее сообщение. За ход их может быть больше одного: регламент ОП
    описывает связки скриптов («приветствие», следом «вопрос про имя/фамилию»),
    которые менеджер отправляет подряд, не дожидаясь ответа клиента."""
    text: str
    image_urls: list[str]
    message: Message

# Cap history sent to the model — older turns rarely change the reply but cost input tokens.
_HISTORY_MAX_MESSAGES = 100


OBJECTION_KEYWORDS = [
    "дорого", "дорог", "expensive", "цена высок", "много стоит",
    "подумаю", "подумать", "думать", "need to think",
    "конкурент", "дешевле", "другая компания",
    "качество", "не уверен", "сомневаюсь",
    "долго", "сроки", "быстрее",
]


def _is_objection(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in OBJECTION_KEYWORDS)


_normalize_dashes = normalize_dashes

# Free-form replies (source_script_id=None) have no code-level anti-repeat guard, and
# prompt rules alone don't hold: see client 8474931 — the model re-sent its own previous
# message verbatim when the client merely confirmed the proposed size. Threshold is on
# normalized text; 0.85 catches near-verbatim copies but not a routine same-topic reply.
_DUP_SIMILARITY_THRESHOLD = 0.85
# Short acks («Хорошо, жду фото 😊») legitimately repeat — only long replies are checked.
_DUP_MIN_LENGTH = 80

_DUP_RETRY_INSTRUCTION = (
    "[Служебное] Твой ответ выше почти дословно повторяет сообщение, которое менеджер "
    "УЖЕ отправил клиенту (см. историю диалога). Клиент его уже читал. Напиши ДРУГОЙ "
    "ответ: не пересказывай уже отправленное, отреагируй на последнее сообщение клиента "
    "и продвинь диалог на следующий шаг текущей стадии воронки."
)




def _normalize_for_dup(text: str) -> str:
    return re.sub(r"[\W_]+", " ", (text or "").lower()).strip()


def _find_duplicate_reply(reply: str, manager_texts: list[str]) -> str | None:
    """Return the already-sent manager message the reply near-duplicates, else None."""
    from difflib import SequenceMatcher

    norm_reply = _normalize_for_dup(reply)
    if len(norm_reply) < _DUP_MIN_LENGTH:
        return None
    for prev in manager_texts:
        norm_prev = _normalize_for_dup(prev)
        if len(norm_prev) < _DUP_MIN_LENGTH:
            continue
        if SequenceMatcher(None, norm_reply, norm_prev).ratio() >= _DUP_SIMILARITY_THRESHOLD:
            return prev
    return None


# Один и тот же абзац живёт в нескольких скриптах ОП: «Ткани таааак подорожали,
# это просто ужас!» есть и в 477, и в 478 — клиент прочитал его дважды за девять
# минут (прогоны 1353 и 1381). Реплики целиком при этом разные, и проверка выше
# их не ловит: у неё порог на всё сообщение.
_DUP_CHUNK_THRESHOLD = 0.9
# Короткие строки повторяются законно: «Всё верно?», «Что скажете?», подпись.
_DUP_CHUNK_MIN_LENGTH = 60


def _chunks(text: str) -> list[str]:
    """Абзацы реплики, нормализованные для сравнения."""
    parts = re.split(r"\n\s*\n|\n", text or "")
    return [c for c in (_normalize_for_dup(p) for p in parts) if len(c) >= _DUP_CHUNK_MIN_LENGTH]


def _find_repeated_chunk(reply: str, manager_texts: list[str]) -> str | None:
    """Абзац ответа, который клиент уже читал в другом нашем сообщении."""
    from difflib import SequenceMatcher

    sent = [c for t in manager_texts for c in _chunks(t)]
    if not sent:
        return None
    for chunk in _chunks(reply):
        for prev in sent:
            if SequenceMatcher(None, chunk, prev).ratio() >= _DUP_CHUNK_THRESHOLD:
                return chunk
    return None



# Клиент отвечает одним словом на «что остановило — цена или сроки?». Это ОТВЕТ,
# а не новый вопрос о стоимости, но модель читает «цена» буквально и присылает
# прайс заново. Промптом не держится — проверяем в коде.
_OBJECTION_ANSWER_RE = re.compile(
    r"^\W*(цена|цены|ценник|стоимость|дорого|дороговато|сроки|срок|долго|"
    r"дизайн|финансы|деньги|не надо|не нужно|подумаю)\W*$",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(r"\d[\d\s\u00a0]{2,7}(?=\s*(?:₽|руб))", re.IGNORECASE)

# Ответ без вопроса обрывает диалог: следующего хода не будет, пока клиент не
# напишет сам, а писать ему больше не на что (диалог 51: «Фиксирую этот вариант и
# передаю его в работу.» — и тишина на середине воронки). Регламент ОП требует
# закрывать каждую реплику вопросом, кроме терминального шага.
_NO_QUESTION_RETRY_INSTRUCTION = (
    "[Служебное] Твой ответ не заканчивается вопросом — диалог на нём оборвётся, "
    "потому что клиенту нечего ответить. Перепиши: сохрани смысл, но закончи "
    "сообщение вопросом, который двигает заказ к следующему шагу текущей стадии "
    "воронки."
)
# На этой стадии заказ уже передан на ведение — вопрос не нужен.
_TERMINAL_STAGE = "paid"

# «Спасибо не надо», «Не надо мне» — клиент отказывается, а модель читает это как
# согласие: на третье подряд она написала «фиксирую под Вас этот вариант» и следом
# ушёл счёт на 4 990 ₽ (диалог 89). Шаг не закрыт, пока не понятно, от чего отказ.
_REFUSAL_RETRY_INSTRUCTION = (
    "[Служебное] Клиент отказывается, а не подтверждает. Воронку двигать нельзя: "
    "не фиксируй дизайн, не называй сумму заказа, не проси ФИО и телефон, не "
    "выставляй счёт. Присоединись к клиенту и одним коротким вопросом уточни, от "
    "чего именно отказ и что не подошло."
)

# Абзац из скрипта, который клиент уже читал в другом сообщении: «Ткани таааак
# подорожали…» стоит и в 477, и в 478, и ушёл дважды за девять минут.
# Клиент просит переделать дизайн, а модель читает это как согласие: на «Изменить
# дизайн» она выбрала скрипт «Зафиксировали дизайн» и тем же ходом отправила
# сумму заказа (диалог 163, 14:14).
_DESIGN_EDIT_RETRY_INSTRUCTION = (
    "[Служебное] Клиент просит ПОМЕНЯТЬ дизайн, а не подтверждает его. Шаг не "
    "закрыт: не фиксируй дизайн, не называй сумму заказа, не проси ФИО и телефон, "
    "не выставляй счёт. Уточни одним вопросом, что именно поменять, и дождись "
    "ответа."
)

_REPEATED_CHUNK_RETRY_INSTRUCTION = (
    "[Служебное] Один из абзацев твоего ответа клиент уже читал — этот текст есть "
    "в двух скриптах, и второй раз он звучит как заевшая пластинка. Скажи то же "
    "самое своими словами и короче или вовсе опусти этот абзац: остальную часть "
    "ответа сохрани."
)

_REQUOTE_RETRY_INSTRUCTION = (
    "[Служебное] Клиент отвечает на ТВОЙ вопрос о том, что его остановило, а не "
    "спрашивает цену заново — он её уже видел. Не повторяй стоимость и не описывай "
    "товар снова. Отработай возражение: присоединись, назови ценность, предложи "
    "оплату частями. Напиши другой ответ."
)


def _prices_in(text: str) -> set[str]:
    """Суммы в тексте, нормализованные: «4 990 ₽» и «4990руб» — одно и то же."""
    return {re.sub(r"\D", "", m) for m in _MONEY_RE.findall(text or "")}


# Вопрос-сверка: на него клиент ОБЯЗАН ответить, и до ответа воронку двигать
# нельзя. Замечание ОП от 10 августа, 13:51: «Два вопроса подряд нельзя задавать.
# Сначала очень важно увидеть ответ на первый вопрос, затем задавать второй».
#
# Так уходили: «Приняла: … герб на спине. Всё верно?» + сразу сумма заказа
# (диалог 156, 14:35); «Что именно изменяем в дизайне?» + сразу сумма заказа
# (диалог 163, 14:14); «…Всё верно?» + полный скрипт оформления (диалог 142,
# 10:01). Во всех трёх второе сообщение отвечало на согласие, которого не было.
_AWAITS_ANSWER_RE = re.compile(
    r"вс[её]\s+верно|что\s+именно|правильно\s+понима|подтвержда[еи]те|"
    r"всё\s+так\?|все\s+так\?",
    re.I,
)


def awaits_client_answer(text: str) -> bool:
    """Реплика заканчивается сверкой — связку за ней разворачивать нельзя."""
    return bool(text and "?" in text and _AWAITS_ANSWER_RE.search(text))


# Последний вопрос реплики: им заменяем дубль скрипта. ОП, 13:45: «Дубль полного
# скрипта. Вместо него можно было задублировать только вопрос про удобный способ
# оплаты».
_LAST_QUESTION_RE = re.compile(r"[^.!?\n]*\?")


def _last_question(text: str) -> str | None:
    found = _LAST_QUESTION_RE.findall(text or "")
    return found[-1].strip() if found else None


# Предложения, которые звучат один раз за диалог. ОП, 10 августа, 13:53:
# «Примерно четвёртое предложение о бесплатном макете в этом диалоге. Или не
# запомнила, или хз». Формулировки каждый раз разные, поэтому проверка дублей по
# тексту их не ловит — ловим по смыслу.
_ONE_TIME_OFFERS: dict[str, re.Pattern] = {
    "бесплатный макет": re.compile(r"бесплатн\w*\s+макет|макет\s+бесплатн", re.I),
    "подарок за полную оплату": re.compile(r"подарок\s+на\s+выбор", re.I),
    "дополнительная скидка": re.compile(r"доп\.?\s*скидочк|дополнительн\w*\s+скидк", re.I),
    "второе изделие": re.compile(r"второе\s+издели|второй\s+макет", re.I),
}
# Предложение целиком, вместе с завершающей пунктуацией.
_SENTENCE_RE = re.compile(r"[^.!?\n]*(?:[.!?]+|\n|$)")


def _drop_repeated_offers(parts, manager_texts: list[str], ctx: str):
    """Убрать предложение, которое клиент в этом диалоге уже слышал."""
    spent = {
        name for name, rx in _ONE_TIME_OFFERS.items()
        if any(rx.search(t or "") for t in manager_texts)
    }
    if not spent:
        return parts
    kept = []
    for part in parts:
        text = part.text or ""
        for name in spent:
            rx = _ONE_TIME_OFFERS[name]
            if not rx.search(text):
                continue
            trimmed = "".join(
                sent for sent in _SENTENCE_RE.findall(text) if not rx.search(sent)
            )
            trimmed = re.sub(r"\n{3,}", "\n\n", trimmed).strip()
            logger.info("[%s] повтор предложения «%s» снят", ctx, name)
            text = trimmed
        if not text and not part.image_urls:
            continue
        part.text = text
        kept.append(part)
    return kept


def _drop_duplicate_parts(parts, manager_texts: list[str], ctx: str):
    """Убрать из хода то, что клиент уже читал.

    Проверка дублей до сих пор смотрела только на реплику модели: части, которые
    породила связка скриптов, не сравнивались ни с историей, ни между собой — и в
    диалоге 142 в 10:01 ушли два побайтово одинаковых скрипта оформления подряд.

    От дубля оставляем один его вопрос: он и есть то, ради чего повтор был нужен.
    """
    seen = list(manager_texts)
    kept = []
    for part in parts:
        text = part.text or ""
        dup = _find_duplicate_reply(text, seen) or _find_repeated_chunk(text, seen)
        if dup:
            # Повтор нужен ради вопроса — его и оставляем. ОП, 13:45: «Вместо
            # него можно было задублировать только вопрос про удобный способ
            # оплаты». Повтор вопроса ВНУТРИ одного хода снимет следующий шаг
            # (_drop_repeated_questions).
            question = _last_question(text)
            if question:
                logger.info(
                    "[%s] дубль скрипта свёрнут до вопроса | %r", ctx, question[:60],
                )
                part.text = question
                seen.append(part.text)
                kept.append(part)
                continue
            logger.info("[%s] дубль без вопроса не отправлен | %r", ctx, text[:60])
            if part.image_urls:
                part.text = ""
                kept.append(part)
            continue
        seen.append(text)
        kept.append(part)
    return kept


# Ход без вопроса обрывает диалог: клиенту нечего ответить, и следующего хода не
# будет. Замечание ОП, 13:42: «Нет вопроса. Они обязательно должны быть после
# каждого сообщения, чтобы диалог продолжался»; 13:53: «нет вопроса в конце
# скрипта». Так вышло в диалоге 142 в 13:19 — прайс ушёл, а звено «2.3 Доставка»
# пропустилось, потому что город уже был известен, и вопрос ушёл вместе с ним.
#
# Спрашиваем то, чего ещё не знаем о заказе; порядок — как в воронке ОП.
_SLOT_QUESTIONS: list[tuple[str, str]] = [
    ("city", "В какой город нужна будет доставка?"),
    ("color", "Какой цвет выберем?"),
    ("size", "Подскажите рост и вес, чтобы точно подобрать размер?"),
]
# Про заказ известно всё — остаётся вернуть слово клиенту.
_FALLBACK_QUESTION = "Что скажете?"


def _ensure_question(parts, slots: dict[str, str], ctx: str):
    """Дописать вопрос к последней реплике хода, если его нет ни в одной."""
    if not parts or any("?" in (p.text or "") for p in parts):
        return parts
    question = next(
        (q for slot, q in _SLOT_QUESTIONS if not slots.get(slot)), _FALLBACK_QUESTION,
    )
    last = parts[-1]
    last.text = f"{(last.text or '').rstrip()}\n\n{question}".strip()
    logger.info("[%s] ход заканчивался без вопроса — дописан %r", ctx, question)
    return parts


# Один вопрос за ход. «В какой город нужна доставка?» задали трижды подряд:
# его несли два ценовых скрипта и скрипт доставки (диалог 111, 07:37-07:38).
# Ценовые дубли выключены, но связка может свести любые два звена с одинаковым
# хвостом, поэтому повтор снимается на выходе.
_QUESTION_RE = re.compile(r"[^.!?\n]*\?")


def _keep_one_question(parts, ctx: str):
    """Оставить в ходе ровно один вопрос — первый.

    ОП (документ от 11 августа, п. 2): «Добавить условие, что ии всегда
    дожидается ответ на вопрос, потом задает следующий/отправляет следующий
    скрипт. На скрине задала 2 вопроса подряд».

    Речь именно о двух ВОПРОСАХ, а не о двух сообщениях: регламент сам требует
    отправлять похвалу, стоимость и доставку подряд, не дожидаясь клиента, — но
    вопрос там ровно один, в последнем звене. Поэтому режем не сообщения, а
    лишние вопросы: первый остаётся, всё остальное вопросительное снимается.
    """
    seen_question = False
    kept = []
    for part in parts:
        text = part.text or ""
        questions = _QUESTION_RE.findall(text)
        if seen_question and questions:
            for q in questions:
                text = text.replace(q, "")
                logger.info("[%s] второй вопрос за ход снят | %r", ctx, q.strip()[:60])
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
        elif questions:
            seen_question = True
        if not text and not part.image_urls:
            continue
        part.text = text
        kept.append(part)
    return kept


def _drop_repeated_questions(parts, ctx: str):
    """Убрать из поздних реплик вопрос, который уже задан в этом же ходу."""
    asked: set[str] = set()
    kept = []
    for part in parts:
        text = part.text or ""
        for q in _QUESTION_RE.findall(text):
            key = _normalize_for_dup(q)
            if not key:
                continue
            if key in asked:
                logger.warning("[%s] повтор вопроса в том же ходу снят | %r", ctx, q.strip()[:60])
                text = text.replace(q, "")
            else:
                asked.add(key)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text and not part.image_urls:
            continue
        part.text = text
        kept.append(part)
    return kept


def _drop_conflicting_prices(parts, manager_texts: list[str], ctx: str):
    """Убрать реплики, называющие сумму, отличную от уже названной в диалоге.

    Порядок сохраняем: первая названная цена и есть цена заказа, спорит с ней
    всегда та, что пришла следом.
    """
    quoted: set[str] = set()
    for t in manager_texts:
        quoted |= _prices_in(t)
    kept = []
    for part in parts:
        prices = _prices_in(part.text)
        if prices and quoted and not (prices & quoted):
            logger.warning(
                "[%s] реплика с другой ценой не отправлена | было=%s | стало=%s",
                ctx, sorted(quoted), sorted(prices),
            )
            continue
        quoted |= prices
        kept.append(part)
    return kept


def _requotes_known_price(client_text: str, reply: str, manager_texts: list[str]) -> bool:
    """Ответ повторяет уже названную сумму в ответ на возражение одним словом."""
    if not _OBJECTION_ANSWER_RE.match((client_text or "").strip()):
        return False
    already = set()
    for t in manager_texts:
        already |= _prices_in(t)
    return bool(_prices_in(reply) & already)


# Подпись перед картинкой стикера. Без неё модель принимает её за фото клиента
# и начинает обсуждать «присланный дизайн».
_STICKER_IMAGE_LABEL = "[Стикер] — картинка стикера ниже, это не фото клиента и не макет:"


def _attachment_content(
    text: str, files: list[str], sticker_files: list[str] | None = None,
) -> list[dict]:
    """Собирает multimodal-контент сообщения клиента: текст + вложения.

    Не-изображения превращаются в текстовые плейсхолдеры ([Стикер] и т.п.).
    Плейсхолдер не дублируется, если он уже есть в тексте сообщения
    (adapter подставляет его же вместо пустого текста).

    Стикер отдаём картинкой — иначе «[Стикер]» для модели ничем не отличается
    от любого другого: палец вверх, сердечко и «ну не знаю» читаются одинаково.
    Перед картинкой идёт своя подпись: это стикер, а не фото дизайна.
    """
    content: list[dict] = [{"type": "input_text", "text": text}]
    seen_placeholders = {text}
    for url in sticker_files or []:
        content.append({"type": "input_text", "text": _STICKER_IMAGE_LABEL})
        content.append({"type": "input_image", "image_url": url, "detail": "low"})
        seen_placeholders.add("[Стикер]")
    for url in files:
        if is_sticker_url(url):
            placeholder = "[Стикер]"
        elif is_audio_url(url):
            placeholder = "[голосовое сообщение]"
        elif is_video_url(url):
            placeholder = "[видео]"
        elif is_document_url(url):
            placeholder = "[файл]"
        else:
            content.append({"type": "input_image", "image_url": url, "detail": "auto"})
            continue
        if placeholder not in seen_placeholders:
            seen_placeholders.add(placeholder)
            content.append({"type": "input_text", "text": placeholder})
    return content


async def run_ai(
    db: AsyncSession,
    dialog: Dialog,
    client_message: Message,
) -> tuple[AgentOutput, AIRun, list[ReplyPart]]:
    """Run the appropriate agent, persist the AIRun and every outgoing message.

    Реплик за ход может быть несколько — см. ReplyPart. Первая всегда ответ
    модели, за ней могут идти скрипты, привязанные через follow_up_script_id.
    """
    text = client_message.text

    type_id: int | None = getattr(dialog, "type_id", None)

    client = await db.get(Client, dialog.client_id)
    vk_user_id = client.vk_user_id if client else None
    ctx = f"vk_user={vk_user_id}" if vk_user_id else f"dialog={dialog.id}"

    logger.info(
        "[%s] run_ai start | type_id=%s | msg_id=%s | text=%r",
        ctx, type_id, client_message.id, text[:80],
    )

    greeting_script = await resolve_greeting(db, dialog, client, type_id)
    if greeting_script is not None:
        return await _run_scripted_greeting(db, dialog, client, greeting_script, ctx)

    logger.info("[%s] loading system prompt | type_id=%s", ctx, type_id)
    instructions = await get_system_prompt(db, type_id=type_id)
    logger.info("[%s] system prompt loaded | len=%d chars", ctx, len(instructions))

    # Load active statuses and inject them into the prompt
    active_statuses_result = await db.execute(
        select(DialogStatusConfig).where(DialogStatusConfig.is_active == True).order_by(DialogStatusConfig.id)
    )
    active_statuses = active_statuses_result.scalars().all()
    statuses_block = format_statuses_block(active_statuses)
    if statuses_block:
        instructions = instructions + "\n\n" + statuses_block

    # Per-turn dynamic context goes into user messages (NOT the system prompt) so the
    # system prompt stays byte-stable and the Anthropic prompt cache hits every turn.
    # These messages are appended right before the current client message and kept in the
    # uncached tail (see cache_uncached_tail below).
    dynamic_context: list[str] = []

    # Текущая дата. В контексте её не было вовсе: на «хочу к 9 августа» модель не
    # знала, три это дня или три месяца, и отвечала «подстроимся под Вас» вместо
    # честного «не успеем» (замечание ОП от 6 августа). Строка меняется каждую
    # минуту, поэтому идёт в динамический хвост, а не в кэшируемый системный
    # промпт.
    dynamic_context.append(
        f"[Сегодня]\n{human_msk_now()}\n"
        "Изготовление занимает 10-14 дней плюс доставка 2-3 дня. Считай сроки от "
        "этой даты и не обещай того, что в них не укладывается."
    )

    # Ответ цифрой на пинговый список «давайте начистоту, из-за чего молчите?».
    # Для модели «1» — просто символ; расшифровываем, иначе она продолжает
    # продавать поверх «заказ не актуален» (диалог 111, 10:40).
    honest = await honest_answer(db, dialog.id, text)
    if honest:
        dynamic_context.append(
            "[Клиент ответил на список «давайте начистоту»]\n"
            f"{honest} — {HONEST_OPTIONS[honest]}"
        )
        logger.info("[%s] ответ на «начистоту»: %s — %s", ctx, honest, HONEST_OPTIONS[honest])

    # FunnelAgent: detect the current sales-script stage BEFORE the SalesAgent runs, so
    # the reply is grounded in where the conversation actually stands. Persisted on the
    # dialog so the async PingAgent can reuse the last-detected stage. On failure we keep
    # the previous stage rather than blocking the reply.
    stage = await detect_stage(db, dialog)
    if stage:
        dialog.funnel_stage = stage
    stage_block = format_stage_block(dialog.funnel_stage)
    if stage_block:
        dynamic_context.append(stage_block)
        logger.info("[%s] funnel stage injected | stage=%s", ctx, dialog.funnel_stage)

    feedback_rules = await load_active_feedback_rules(db, type_id)
    if feedback_rules:
        items = []
        for r in feedback_rules:
            items.append(f"Сообщение ИИ: «{r['message_text']}»\nОшибка: {r['rule_text']}")
        rules_block = "\n\n".join(items)
        dynamic_context.append("[Разбор ошибок — учти и не повторяй]\n" + rules_block)
        logger.info("[%s] feedback rules injected | count=%d", ctx, len(feedback_rules))

    # The script used in the previous AI reply is excluded from list_scripts so the model
    # physically can't send the same phrase twice in a row (prompt-level «не
    # повторяйся» rules proved unreliable — see dialog 8457478, same phrase sent 3x).
    last_script_id = await db.scalar(
        select(AIRun.source_script_id)
        .where(AIRun.dialog_id == dialog.id, AIRun.source_script_id.isnot(None))
        .order_by(AIRun.id.desc())
        .limit(1)
    )
    used_script_ids = {last_script_id} if last_script_id else set()

    # Скрипты из связок (follow_up_script_id) уходят клиенту без собственного
    # AIRun, поэтому запросом выше не видны — иначе модель на следующем же ходу
    # снова выбрала бы «какое имя напишем на кофте?» и переспросила бы то, на что
    # клиент только что ответил. Читаем их из метаданных отправленных сообщений.
    recent_ai = await db.execute(
        select(Message.msg_metadata)
        .where(Message.dialog_id == dialog.id, Message.role == MessageRole.ai)
        .order_by(Message.id.desc())
        .limit(2)
    )
    for (meta,) in recent_ai.all():
        sent_script_id = (meta or {}).get("source_script_id")
        if sent_script_id:
            used_script_ids.add(sent_script_id)

    # Пока счёт выставляет человек, скрипт «5.2 Ссылка на оплату» модели не
    # показываем вовсе. Иначе она строит на нём ответ и обещает «вот счёт-ссылка
    # на 500 рублей», а ссылки в сообщении нет — вырезать её мало, обещание
    # остаётся.
    if not payment_link_configured():
        _link_script = await find_payment_link_script(db, type_id)
        if _link_script is not None:
            used_script_ids.add(_link_script.id)

    # Прайс во второй раз не отправляем: клиент цену уже видел, а на возражение
    # отвечают отдельные скрипты отработки. В диалоге 156 прайс ушёл трижды за
    # два часа (замечание ОП от 10 августа, 13:53: «Опять отправили цену»).
    # Признак «цену называли» — закреплённая за диалогом сумма (см. _pin_price).
    skip_script_ids: set[int] = set()
    if dialog.quoted_prices:
        _price_script = await find_price_script(db, type_id)
        if _price_script is not None:
            skip_script_ids.add(_price_script.id)
            used_script_ids.add(_price_script.id)
            logger.info("[%s] прайс уже отправлен — скрипт %s исключён", ctx, _price_script.id)

    # Скидка — только после ПОВТОРНОГО ценового возражения, уже отработанного
    # ценностью. Регламент ОП: 5990 → отработка → повторное «дорого» → 5490 →
    # повторное «дорого» → 4990. «Подумаю», «понятно» и вопросы о товаре скидку
    # не открывают, иначе ИИ раздаёт её на первое же сомнение.
    if not await concession_allowed(db, dialog.id, text):
        _discounts = await discount_script_ids(db, type_id)
        if _discounts:
            skip_script_ids |= _discounts
            used_script_ids |= _discounts
            logger.info(
                "[%s] скидка не открыта — скидочные скрипты %s скрыты",
                ctx, sorted(_discounts),
            )

    # Вопрос, заданный только что, повторять нельзя — ни тем же скриптом, ни
    # другим с тем же смыслом.
    repeating = await scripts_repeating_recent_question(db, dialog.id, type_id)
    if repeating:
        skip_script_ids |= repeating
        used_script_ids |= repeating
        logger.info("[%s] вопрос уже задан — скрипты %s исключены", ctx, sorted(repeating))

    exclude_script_ids: set[int] | None = used_script_ids or None
    if exclude_script_ids:
        logger.info("[%s] excluding recently used scripts | script_ids=%s", ctx, sorted(exclude_script_ids))

    dialog_provider = getattr(dialog, "ai_provider", None) or settings.AI_PROVIDER

    audio_urls: list[str] = (client_message.msg_metadata or {}).get("audio_urls", [])
    if audio_urls:
        logger.info("[%s] transcribing %d audio message(s)", ctx, len(audio_urls))
        transcripts: list[str] = []
        for url in audio_urls:
            t = await transcribe_audio_url(url)
            if t:
                transcripts.append(t)
        if transcripts:
            combined = " ".join(transcripts)
            logger.info("[%s] audio transcribed | total_chars=%d", ctx, len(combined))
            text = f"[Голосовое сообщение]\n{combined}"
        else:
            logger.warning("[%s] all audio transcriptions failed", ctx)

    input_messages: list[dict] = []

    ctx_lines: list[str] = []
    if vk_user_id:
        ctx_lines.append(f"VK ID клиента: {vk_user_id}")
    client_name = (client.name or "").strip() if client else ""
    if client_name:
        ctx_lines.append(f"Имя клиента: {client_name}")
    client_tags = await fetch_client_tags(client.id if client else None)
    if client_tags:
        ctx_lines.append("Маркетинговые теги клиента: " + ", ".join(sorted(client_tags)))
    if ctx_lines:
        input_messages.append({"role": "user", "content": "[Контекст сессии]\n" + "\n".join(ctx_lines)})
        input_messages.append({"role": "assistant", "content": "Принял."})

    # Recent manager/AI messages already sent to the client — the duplicate-reply guard
    # compares the fresh reply against these after the agent call.
    manager_history_texts: list[str] = []

    # Вся история диалога живёт локально (CRM больше нет) — подаём её моделью
    # как чередование user/assistant, свежие _HISTORY_MAX_MESSAGES сообщений.
    local_history_result = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog.id, Message.id != client_message.id)
        .order_by(Message.created_at.desc())
        .limit(_HISTORY_MAX_MESSAGES)
    )
    # Не дошедшее до клиента в историю не идёт: строка сообщения пишется до
    # отправки, и упавшая отправка оставляла модели ложное «я это уже сказала» —
    # шаг воронки после этого не повторялся никогда (85 таких из 314 исходящих).
    local_msgs = delivered_only(list(reversed(local_history_result.scalars().all())))
    logger.info("[%s] local history loaded | messages=%d", ctx, len(local_msgs))
    for msg in local_msgs:
        if msg.role == MessageRole.client:
            meta = msg.msg_metadata or {}
            files = meta.get("files", [])
            stickers = meta.get("sticker_files", [])
            if files or stickers:
                input_messages.append({
                    "role": "user",
                    "content": _attachment_content(msg.text, files, stickers),
                })
            else:
                input_messages.append({"role": "user", "content": msg.text})
        elif msg.role in (MessageRole.ai, MessageRole.curator):
            input_messages.append({"role": "assistant", "content": msg.text})
            if msg.text:
                manager_history_texts.append(msg.text)

    # Что клиент уже сообщил по заказу. Модель это переспрашивает, хотя история у
    # неё перед глазами (диалог 52: пять ходов подряд «какой дизайн нанесём?»),
    # поэтому факты собираются кодом и подаются готовым списком.
    slots = collect_slots(
        [("client" if m.role == MessageRole.client else "manager", m.text) for m in local_msgs]
        + [("client", text)]
    )
    slots_block = format_slots_block(slots)
    if slots_block:
        dynamic_context.append(slots_block)
        logger.info("[%s] order slots injected | %s", ctx, sorted(slots))

    # Оплату подтверждает человек. Пока подтверждения нет, шаги «после оплаты»
    # модели недоступны: она поблагодарила за заказ и попросила адрес ПВЗ у
    # клиента, не заплатившего ни рубля (диалог 142, 14:13; замечание ОП от
    # 10 августа, 14:15: «Оплаты от клиента не было»).
    payment_confirmed = dialog.payment_confirmed_at is not None

    # Агент собирается ПОСЛЕ разбора слотов: списку скриптов нужно знать, какую
    # вещь выбрал клиент, иначе на «покажите, как выглядит» модели предлагается
    # и скрипт про костюм (диалог 111, 07:54).
    agent = build_sales_agent(
        instructions,
        type_id=type_id,
        provider=dialog_provider,
        client_id=client.id if client else None,
        funnel_stage=dialog.funnel_stage,
        exclude_script_ids=exclude_script_ids,
        client_product=slots.get("product"),
        dialog_id=dialog.id,
        payment_confirmed=payment_confirmed,
    )
    logger.info(
        "[%s] agent built | model=%s | provider=%s | товар=%s",
        ctx, get_model_name(dialog_provider), dialog_provider, slots.get("product"),
    )

    # Dynamic per-turn context (funnel stage, feedback rules) as separate user messages,
    # placed right before the current client message so they sit in the uncached tail and
    # don't bust the cached system prompt / history prefix.
    for block in dynamic_context:
        input_messages.append({"role": "user", "content": block})

    _meta = client_message.msg_metadata or {}
    files = _meta.get("files", [])
    stickers = _meta.get("sticker_files", [])
    if files or stickers:
        image_files = [url for url in files if is_image_url(url)]
        sticker_files = stickers + [url for url in files if is_sticker_url(url)]
        logger.info("[%s] current message has files | images=%d stickers=%d", ctx, len(image_files), len(sticker_files))
        input_messages.append({"role": "user", "content": _attachment_content(text, files, stickers)})
    else:
        input_messages.append({"role": "user", "content": text})

    # Точка воронки «клиент ответил на вопрос про надпись»: по регламенту ОП следом
    # обязаны уйти похвала, стоимость и доставка. Считаем ДО ответа модели — после
    # него последним нашим сообщением будет уже её реплика.
    # Отказ клиента («Спасибо не надо») модель читает как согласие и идёт дальше
    # по воронке. Ни одна точка связки на отказе разворачиваться не должна.
    refused = client_refused(text)
    if refused:
        logger.info("[%s] клиент отказывается — воронку не двигаем | text=%r", ctx, text[:60])
    # Просьба переделать дизайн — шаг не закрыт: ни фиксировать дизайн, ни
    # называть сумму заказа нельзя, пока правка не внесена и не подтверждена.
    design_edit = client_wants_design_edit(text)
    if design_edit:
        logger.info("[%s] клиент просит правку дизайна — воронку не двигаем | text=%r", ctx, text[:60])
    held = refused or design_edit
    praise_point = not held and await answered_inscription_question(db, dialog.id)
    payment_choice_point = not held and await payment_option_chosen(db, dialog.id, text)
    # Клиент назвал рост и вес — следующим ходом идёт сверка дизайна, и она
    # уходит скриптом: свой пересказ модель пишет без раскладки нанесений.
    design_review_point = not held and await size_just_given(db, dialog.id, text)
    # Сверки «всё верно?» встречаются и после оплаты — при подведении итогов заказа
    # и при согласовании макета. Без этой проверки «да» на итоговую сверку тянуло
    # диалог обратно в оформление: клиент, уже приславший чек, получил условия
    # оплаты второй раз (диалог 68, сообщение 979).
    design_point = (
        not held
        and not await dialog_has_payment_link(db, dialog.id)
        and await design_just_confirmed(db, dialog.id, text)
    )

    logger.info(
        "[%s] calling agent | provider=%s | model=%s | context_turns=%d",
        ctx, dialog_provider, get_model_name(dialog_provider), len(input_messages),
    )
    full_context: dict | None = None
    # Anthropic prompt-cache tokens; the openai-agents path leaves these at 0.
    cache_read_tokens = 0
    cache_write_tokens = 0
    # Attempt 2 is the duplicate-reply retry: the first reply plus a service correction
    # are appended to input_messages, so the tail grows by 2 uncached messages.
    # The provider bills every attempt, so token/cost metrics accumulate across them.
    acc_input = acc_output = acc_cache_read = acc_cache_write = 0
    dup_match: str | None = None
    ignores_refusal = False
    for dup_attempt in (1, 2):
        uncached_tail = 1 + len(dynamic_context) + 2 * (dup_attempt - 1)
        result = None  # set on the openai-agents path; read by the failure logger
        attempt_t0 = time.time()
        try:
            if dialog_provider == "anthropic":
                output, input_tokens, output_tokens, elapsed_ms, full_context, cache_read_tokens, cache_write_tokens = await asyncio.wait_for(
                    run_with_cache(
                        instructions=instructions,
                        input_messages=input_messages,
                        type_id=type_id,
                        client_id=client.id if client else None,
                        cache_uncached_tail=uncached_tail,
                        funnel_stage=dialog.funnel_stage,
                        exclude_script_ids=exclude_script_ids,
                        client_product=slots.get("product"),
                        dialog_id=dialog.id,
                        payment_confirmed=payment_confirmed,
                    ),
                    timeout=settings.AI_RUNNER_TIMEOUT,
                )
            elif dialog_provider == "minimax":
                # MiniMax via its Anthropic-compatible endpoint — same runner as Anthropic,
                # just pointed at MiniMax's base_url/key/model. Avoids the OpenAI-endpoint
                # tool-call-as-text bug that made M3 loop until the turn budget ran out.
                async def _run_minimax(minimax_model, allow_salvage):
                    return await asyncio.wait_for(
                        run_with_cache(
                            instructions=instructions,
                            input_messages=input_messages,
                            type_id=type_id,
                            client_id=client.id if client else None,
                            api_key=settings.MINIMAX_API_KEY,
                            base_url=settings.MINIMAX_ANTHROPIC_BASE_URL,
                            model=minimax_model,
                            allow_salvage=allow_salvage,
                            cache_uncached_tail=uncached_tail,
                            funnel_stage=dialog.funnel_stage,
                            exclude_script_ids=exclude_script_ids,
                            dialog_id=dialog.id,
                            payment_confirmed=payment_confirmed,
                        ),
                        timeout=settings.AI_RUNNER_TIMEOUT,
                    )

                try:
                    # Primary model with salvage disabled: a broken/empty reply raises instead of
                    # returning low-quality salvaged text, so we get a clean shot at the fallback model.
                    output, input_tokens, output_tokens, elapsed_ms, full_context, cache_read_tokens, cache_write_tokens = await _run_minimax(
                        settings.MINIMAX_MODEL_NAME, allow_salvage=False,
                    )
                except RuntimeError as e:
                    logger.warning(
                        "[%s] primary minimax (%s) failed: %s — retrying via %s",
                        ctx, settings.MINIMAX_MODEL_NAME, e, settings.MINIMAX_MODEL_NAME_FALLBACK,
                    )
                    # Fallback model with salvage enabled: last resort, take any text it produces.
                    output, input_tokens, output_tokens, elapsed_ms, full_context, cache_read_tokens, cache_write_tokens = await _run_minimax(
                        settings.MINIMAX_MODEL_NAME_FALLBACK, allow_salvage=True,
                    )
            else:
                start_ms = int(time.time() * 1000)
                result = await asyncio.wait_for(
                    Runner.run(agent, input_messages),
                    timeout=settings.AI_RUNNER_TIMEOUT,
                )
                elapsed_ms = int(time.time() * 1000) - start_ms
                # qwen drops output_type (response_format kills tool_calls), so final_output is a
                # raw JSON string — parse it by hand. Other providers return a validated AgentOutput.
                if dialog_provider == "qwen":
                    from app.ai.providers import parse_agent_output
                    try:
                        output: AgentOutput = parse_agent_output(result.final_output)
                    except Exception as parse_err:
                        # qwen occasionally ignores the JSON instruction and answers the
                        # client in plain prose (client 8548093: perfectly good reply lost,
                        # клиент не получил ответа). If the output is prose — no JSON braces
                        # at all — send it flagged for curator review instead of failing.
                        raw_text = re.sub(
                            r"<think>.*?</think>", "", result.final_output or "", flags=re.DOTALL
                        ).strip()
                        if raw_text and "{" not in raw_text:
                            logger.warning(
                                "[%s] qwen returned plain prose instead of JSON — salvaging | err=%s",
                                ctx, parse_err,
                            )
                            output: AgentOutput = AgentOutput(
                                reply_text=raw_text,
                                confidence_score=0.5,
                                need_curator=True,
                                curator_reason="qwen вернул текст вместо JSON — ответ отправлен как есть, нужна проверка",
                            )
                        else:
                            raise
                else:
                    output: AgentOutput = result.final_output
                input_tokens = sum(r.usage.input_tokens for r in result.raw_responses)
                output_tokens = sum(r.usage.output_tokens for r in result.raw_responses)
                # OpenAI's input_tokens INCLUDES cached tokens. Capture the cached count so
                # the cost calc can bill that portion at the discounted cache-read rate
                # instead of full price (cached can be >60% of the prompt). input_tokens
                # itself stays full for storage/reporting. cache_write stays 0 — OpenAI
                # cache writes are free.
                cache_read_tokens = sum(
                    r.usage.input_tokens_details.cached_tokens for r in result.raw_responses
                )
                # openai-agents SDK path: capture the full accumulated turn list incl. tool calls.
                try:
                    full_context = {"system": instructions, "messages": result.to_input_list()}
                except Exception:
                    full_context = {"system": instructions, "messages": input_messages}
        except asyncio.TimeoutError:
            logger.error("[%s] agent timed out after %ds", ctx, settings.AI_RUNNER_TIMEOUT)
            # The request keeps burning provider tokens server-side; usage is
            # unrecoverable client-side, but the run must exist for reconciliation.
            await log_failed_run(
                dialog_id=dialog.id, provider=dialog_provider,
                model=get_model_name(dialog_provider),
                error=f"timeout after {settings.AI_RUNNER_TIMEOUT}s", status="timeout",
                input_tokens=acc_input, output_tokens=acc_output,
                cache_read_tokens=acc_cache_read, cache_write_tokens=acc_cache_write,
                elapsed_ms=int((time.time() - attempt_t0) * 1000),
                input_message_id=client_message.id,
            )
            raise
        except Exception as e:
            logger.exception("[%s] agent failed", ctx)
            # A parse error happens AFTER the API returned — its usage sits on
            # `result` and was billed; a transport error leaves result=None.
            p_in, p_out, p_cached = usage_from_result(result)
            await log_failed_run(
                dialog_id=dialog.id, provider=dialog_provider,
                model=get_model_name(dialog_provider), error=e,
                input_tokens=acc_input + p_in, output_tokens=acc_output + p_out,
                cache_read_tokens=acc_cache_read + p_cached,
                cache_write_tokens=acc_cache_write,
                elapsed_ms=int((time.time() - attempt_t0) * 1000),
                input_message_id=client_message.id,
            )
            raise

        acc_input += input_tokens
        acc_output += output_tokens
        acc_cache_read += cache_read_tokens
        acc_cache_write += cache_write_tokens

        dup_match = _find_duplicate_reply(output.reply_text, manager_history_texts)
        repeated_chunk = _find_repeated_chunk(output.reply_text, manager_history_texts)
        requote = _requotes_known_price(text, output.reply_text, manager_history_texts)
        # Клиент отказался, а ответ всё равно фиксирует дизайн, называет сумму
        # или просит контакты. Скрипты воронки ищем только на отказе — лишний
        # проход по таблице скриптов на каждом ходу тут ни к чему.
        ignores_refusal = held and reply_advances_funnel(
            output.reply_text, output.source_script_id,
            await funnel_advancing_script_ids(db, type_id),
        )
        # Вопрос спрашиваем только с самой модели: когда следом уходит связка
        # скриптов (своя у похвалы, своя у выбранного моделью скрипта), вопрос
        # задаёт последнее звено связки, а не эта реплика.
        no_question = (
            "?" not in (output.reply_text or "")
            and not praise_point
            and output.source_script_id is None
            and dialog.funnel_stage != _TERMINAL_STAGE
        )
        if (
            not dup_match and not requote and not no_question and not ignores_refusal
            and not repeated_chunk
        ) or dup_attempt == 2:
            break
        if ignores_refusal and design_edit and not refused:
            logger.warning(
                "[%s] клиент просит правку, а ответ двигает воронку — retrying", ctx,
            )
            correction = _DESIGN_EDIT_RETRY_INSTRUCTION
        elif repeated_chunk:
            logger.warning(
                "[%s] абзац уже был отправлен — retrying | chunk=%r", ctx, repeated_chunk[:80],
            )
            correction = _REPEATED_CHUNK_RETRY_INSTRUCTION
        elif ignores_refusal:
            logger.warning(
                "[%s] клиент отказался, а ответ двигает воронку — retrying | reply_head=%r",
                ctx, (output.reply_text or "")[:80],
            )
            correction = _REFUSAL_RETRY_INSTRUCTION
        elif requote:
            logger.warning(
                "[%s] reply re-quotes a known price in answer to an objection — retrying", ctx,
            )
            correction = _REQUOTE_RETRY_INSTRUCTION
        elif no_question:
            logger.warning("[%s] reply ends without a question — retrying", ctx)
            correction = _NO_QUESTION_RETRY_INSTRUCTION
        else:
            logger.warning(
                "[%s] reply duplicates an already-sent manager message — retrying | dup_head=%r",
                ctx, dup_match[:100],
            )
            correction = _DUP_RETRY_INSTRUCTION
        input_messages.append({"role": "assistant", "content": output.reply_text})
        input_messages.append({"role": "user", "content": correction})

    if dup_match:
        logger.warning("[%s] duplicate reply survived the retry — escalating to curator", ctx)
        output = output.model_copy(update={
            "need_curator": True,
            "curator_reason": "Дубль: ответ почти дословно повторяет сообщение, уже отправленное клиенту",
        })

    # Отказ пережил повтор — дальше начинается счёт, а клиент говорит «не надо».
    # Ответ придерживаем (см. вебхук) и отдаём диалог куратору: source_script_id
    # снимаем, иначе следом развернётся связка с суммой заказа.
    if ignores_refusal:
        logger.warning("[%s] отказ проигнорирован и после повтора — куратору", ctx)
        output = output.model_copy(update={
            "source_script_id": None,
            "need_curator": True,
            "curator_reason": (
                "Клиент просит правку дизайна, а ответ двигает заказ к оплате"
                if design_edit and not refused
                else "Клиент отказывается, а ответ двигает заказ к оплате"
            ),
        })
    # Billed totals across all attempts, not just the last one.
    input_tokens, output_tokens = acc_input, acc_output
    cache_read_tokens, cache_write_tokens = acc_cache_read, acc_cache_write
    total_tokens = input_tokens + output_tokens

    model_name = get_model_name(dialog_provider)
    in_price, out_price = get_model_pricing(model_name)
    # Anthropic/MiniMax: input_tokens is already uncached (cache tokens reported
    # separately) and the read rate is the 0.1x default. OpenAI: input_tokens still
    # includes cache_read_tokens, so subtract them before pricing and use the
    # per-family cached multiplier.
    if dialog_provider in ("anthropic", "minimax"):
        billable_input = input_tokens
        cache_read_mult = DEFAULT_CACHE_READ_MULT
    else:
        billable_input = input_tokens - cache_read_tokens
        cache_read_mult = CACHE_READ_MULT_BY_MODEL.get(model_name, DEFAULT_CACHE_READ_MULT)
    cost = calculate_cost(
        billable_input, output_tokens, in_price, out_price,
        cache_read_tokens=cache_read_tokens, cache_write_tokens=cache_write_tokens,
        cache_read_mult=cache_read_mult,
    )

    logger.info(
        "[%s] Runner.run complete | latency_ms=%d | input_tokens=%d | output_tokens=%d | cache_read=%d | cache_write=%d | total_tokens=%d | cost_usd=%.6f | confidence=%.3f | need_curator=%s | action=%s",
        ctx, elapsed_ms, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, total_tokens, cost,
        output.confidence_score, output.need_curator, output.action_hint,
    )

    confidence = output.confidence_score
    need_curator = output.need_curator or (confidence < settings.CONFIDENCE_THRESHOLD)
    if need_curator and not output.need_curator:
        logger.info(
            "[%s] need_curator set by low confidence | %.3f < %.3f",
            ctx, confidence, settings.CONFIDENCE_THRESHOLD,
        )
        output = output.model_copy(update={
            "need_curator": True,
            "curator_reason": f"Low confidence: {confidence:.3f} < {settings.CONFIDENCE_THRESHOLD}",
        })

    # Get current status name for logging
    status_before_name = None
    if dialog.current_status_id:
        status_before_obj = await db.get(DialogStatusConfig, dialog.current_status_id)
        status_before_name = status_before_obj.name if status_before_obj else None

    # Update dialog status based on AI output
    if output.need_curator and output.next_status == "ЧС":
        logger.info("[%s] need_curator cleared — status ЧС is terminal", ctx)
        output = output.model_copy(update={"need_curator": False, "curator_reason": None})

    if output.need_curator and not output.next_status:
        output = output.model_copy(update={"next_status": CURATOR_STATUS_NAME})

    # Жёсткий гейт: из «горячего» единственный разрешённый переход —
    # «Ждем предоплату». Любой другой next_status сбрасываем (статус не меняется);
    # need_curator при этом сохраняется — уведомление куратора работает как раньше.
    if (
        is_hot(status_before_name)
        and output.next_status
        and output.next_status not in HOT_ALLOWED_NEXT
    ):
        output = output.model_copy(update={"next_status": None})

    # «Ждем предоплату» = ссылка на оплату/реквизиты уже отправлены.
    if (
        output.next_status == AWAITING_PREPAY
        and not can_await_prepay(status_before_name)
    ):
        logger.info(
            "[%s] blocked next_status 'Ждем предоплату' — status_before=%r too early",
            ctx, status_before_name,
        )
        output = output.model_copy(update={"next_status": None})

    # Стадия подходящая — но статус требует РЕАЛЬНО отправленной ссылки на оплату.
    # Модель ставит «Ждем предоплату» после собственного призыва «внесите предоплату»
    # без всякой ссылки, даже в ответ на отказ клиента (клиент 8522740) — и диалог
    # улетает в пинг-воронку after_payment. Ссылку ищем в текущем ответе и во всех
    # уже отправленных сообщениях менеджера/ИИ.
    if (
        output.next_status == AWAITING_PREPAY
        and status_before_name != AWAITING_PREPAY
        and not PAYMENT_LINK_RE.search(output.reply_text or "")
    ):
        if not await dialog_has_payment_link(db, dialog.id):
            logger.info(
                "[%s] blocked next_status 'Ждем предоплату' — no payment link sent in dialog",
                ctx,
            )
            output = output.model_copy(update={"next_status": None})

    # Вышивка и опт: и то и другое считается индивидуально, цены высокие, ошибка
    # дорого стоит — темы ведёт менеджер, не ИИ. Стоит последним, ПОСЛЕ всех гейтов
    # выше: иначе переход из «Горячий клиент» сбросил бы эскалацию обратно в None.
    # «Заказ не актуален» и «думаю, что вы мошенники» — не возражения, которые
    # отрабатывают скриптом: дальше разговор ведёт человек. Реплику отпускаем,
    # как и на прочих темах менеджера, и замолкаем.
    if honest in HONEST_CURATOR_OPTIONS:
        logger.info(
            "[%s] «начистоту»: %s — %s → куратор", ctx, honest, HONEST_OPTIONS[honest],
        )
        output = output.model_copy(update={
            "next_status": CURATOR_STATUS_NAME,
            "need_curator": False,
            "curator_reason": f"Клиент выбрал «{HONEST_OPTIONS[honest]}»",
        })
        dialog.ai_paused = True

    trigger = curator_trigger(text)
    if trigger:
        # На саму реплику с триггером отвечаем, дальше замолкаем и ждём менеджера.
        # Пауза заодно держит статус: без неё следующий же прогон перезаписал бы
        # «Нужен куратор» своим next_status, и эскалация пропадала бы из списка.
        #
        # need_curator снимаем принудительно: с ним вебхук придержал бы ответ
        # (webhook.py), и на живом трафике клиент на «а вышивка есть?» не получил
        # бы вообще ничего — а РОП просил отвечать общей формулировкой. Риск
        # ограничен одной репликой: сразу за ней диалог встаёт на паузу.
        logger.info(
            "[%s] trigger %r in client message -> status %r + ai paused "
            "(reply released to client, need_curator was %s)",
            ctx, trigger, CURATOR_STATUS_NAME, output.need_curator,
        )
        output = output.model_copy(update={
            "next_status": CURATOR_STATUS_NAME,
            "need_curator": False,
            "curator_reason": f"Тема менеджера: {trigger}",
        })
        dialog.ai_paused = True

    # «Заказ оформлен» = «Клиент внёс первую предоплату». Гейта не было вовсе, и
    # статус ставился по решению модели — в диалоге 142 в 14:13 при нулевой оплате.
    if output.next_status == ORDER_CREATED and not payment_confirmed:
        logger.info("[%s] blocked next_status 'Заказ оформлен' — оплата не подтверждена", ctx)
        output = output.model_copy(update={"next_status": None})

    if output.next_status:
        matching = next((s for s in active_statuses if s.name == output.next_status), None)
        if matching:
            if matching.id != dialog.current_status_id:
                logger.info(
                    "[%s] status updated | %s -> %s",
                    ctx, status_before_name, output.next_status,
                )
                dialog.current_status_id = matching.id
                # Статус меняется только локально — внешней системы статусов больше нет.
                if output.next_status == AWAITING_PREPAY:
                    # Trust the model's «Ждем предоплату» only when the dialog actually
                    # reached the price stage. With an early client photo the FunnelAgent
                    # can jump to contacts and the model asks for prepayment on the FIRST
                    # message (client 8465497) — forcing the after_payment ping funnel
                    # then nags a client who never saw a price.
                    if can_await_prepay(status_before_name):
                        from app.ping.worker import force_ping_funnel
                        from app.utils.time import msk_now
                        await force_ping_funnel(db, dialog, "after_payment", msk_now())
                    else:
                        logger.info(
                            "[%s] skip force after_payment — status_before=%r too early, funnel left to detect_funnel_with_ai",
                            ctx, status_before_name,
                        )
                elif output.next_status == ORDER_CREATED:
                    from app.db.models import DialogPingState
                    _ps_res = await db.execute(select(DialogPingState).where(DialogPingState.dialog_id == dialog.id))
                    _ps = _ps_res.scalar_one_or_none()
                    if _ps:
                        _ps.is_completed = True
                        logger.info("[%s] ping stopped — order placed", ctx)
        else:
            logger.warning(
                "[%s] unknown next_status from AI: %r", ctx, output.next_status
            )

    # Эскалация снимает машину с диалога. Раньше ответ придерживался, а ИИ
    # продолжал отвечать на каждую следующую реплику: диалог 68 — клиент просит
    # вернуть предоплату (сообщение 966, «на проверку»), пишет «?», и ИИ сам
    # предлагает «отменяем заказ окончательно?» (968, снова «на проверку»).
    # Куратор получал очередь непоказанных ответов вместо одного диалога на разбор.
    if output.need_curator and not dialog.ai_paused:
        dialog.ai_paused = True
        logger.info("[%s] need_curator=True — dialog paused for curator", ctx)

    # Эскалация без уведомления не работала: менеджер узнавал о диалоге, только
    # если сам открывал панель (ОП, 14:12: «Тут надо бросать диалог, должен
    # подключаться менеджер»).
    if dialog.ai_paused:
        from app.notify import notify_curator
        await notify_curator(
            dialog.id,
            output.curator_reason or "ИИ снят с диалога",
            last_message=text,
            vk_user_id=vk_user_id,
        )

    ai_run = AIRun(
        dialog_id=dialog.id,
        input_message_id=client_message.id,
        provider=dialog_provider,
        model=get_model_name(dialog_provider),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        cost_amount=cost,
        cost_currency="USD",
        cost_estimated=(input_tokens == 0),
        latency_ms=elapsed_ms,
        confidence_score=confidence,
        need_curator=output.need_curator,
        curator_reason=output.curator_reason,
        selected_script=output.selected_script,
        source_script_id=output.source_script_id,
        status_before=status_before_name,
        # Обрезаем: next_status приходит от модели, и хотя выше он сверяется со
        # списком статусов, в колонку он пишется сырым. Одна длинная строка от
        # модели не должна ронять весь ответ клиенту — так уже случилось с
        # selected_script (см. миграцию 042).
        status_after=_fit(output.next_status, 64),
        raw_response=output.model_dump(),
        full_context=full_context,
    )
    db.add(ai_run)
    await db.flush()

    reply_text = output.reply_text

    # Клиент подтвердил дизайн — дальше ровно один шаг: сумма заказа и способы
    # оплаты. Реплику модели тут не используем вовсе.
    #
    # Раньше её оставляли, а скрипт добавляли следом, и выходило два сообщения
    # об одном и том же: «Какой вариант оплаты выбираете: всю сумму сразу с
    # подарком или бронь 500 ₽?» — и сразу за ним скрипт с тем же вопросом
    # (диалог 85, 08:37). До этого модель успевала прыгнуть ещё дальше, к ФИО,
    # и счёт приходил после запроса контактов. Выбирать ей тут не из чего.
    if design_point:
        _checkout = await find_checkout_script(db, type_id)
        if _checkout is not None and (_checkout.phrase_text or "").strip():
            logger.info("[%s] дизайн подтверждён — отдаём скрипт оформления %s", ctx, _checkout.id)
            reply_text = resolve_spintax(_checkout.phrase_text)
            output = output.model_copy(update={"source_script_id": _checkout.id})
            design_point = False  # связку разворачивать больше нечем

    # Сверка дизайна — тоже скриптовый шаг: в нём раскладка нанесений, которую
    # клиент подтверждает. Пересказ модели её теряет — вместо «На груди по центру
    # - надпись «Орех»» клиент прочитал «расположение не уточнено» (диалог 89).
    #
    # Но и скрипт целиком отдавать нельзя: он записан под патриотическую линейку,
    # и клиент, заказавший одну надпись «Чебурек», получил в сверке ещё герб на
    # груди, флаг на рукаве и герб на спине, которых не просил (диалог 90, 11:53).
    # Оставляем те строки раскладки, элементы которых клиент называл сам.
    if design_review_point:
        _review = await find_design_review_script(db, type_id)
        if _review is not None and (_review.phrase_text or "").strip():
            _client_texts = [m.text for m in local_msgs if m.role == MessageRole.client]
            _client_texts.append(text)
            _rendered = render_design_review(
                resolve_spintax(_review.phrase_text), slots.get("inscription"), _client_texts,
            )
            if _rendered:
                logger.info(
                    "[%s] размер назван — отдаём сверку дизайна скриптом %s", ctx, _review.id,
                )
                reply_text = _rendered
                output = output.model_copy(update={"source_script_id": _review.id})

    # Плейсхолдеры скрипта модель переносит в ответ как есть — «Оплата доставки
    # уже при получении. [Имя], а цвет какой выберем?» ушло клиенту в прогоне
    # воронки. Раскрываем их на выходе, как и в дословных скриптах связки.
    reply_text = render_name_placeholder(reply_text, client.name if client else None)
    # Обращение по имени — только настоящим именем клиента. Надпись на кофте
    # моделью принимается за имя собеседника: «Иван, а цвет какой выберем?»
    # клиенту, у которого в профиле имени нет вовсе. Надпись из [Уже собрано]
    # снимаем и в середине реплики: за текстом скрипта модель дописывает
    # «\n\nОрех, а цвет для свитшота какой выберем?».
    reply_text = strip_foreign_name(
        reply_text, client.name if client else None, slots.get("inscription"),
    )
    reply_text = await render_price_placeholders(
        db, reply_text, type_id=type_id, dialog=dialog,
    )
    reply_text = render_order_placeholders(reply_text, slots)

    # Фото скрипта, на котором построен ответ, не должны потеряться при пересказе.
    if output.source_script_id:
        _src = await db.get(Script, output.source_script_id)
        if _src is not None:
            _before = reply_text
            # Скрипт «5. Оформление» кончается словами «Прикрепляю наши отзывы!»
            # и тремя токенами фото: фразу модель оставляет, токены теряет.
            reply_text = carry_over_attachments(reply_text, _src.phrase_text or "")
            if reply_text != _before:
                logger.info(
                    "[%s] script photos carried over | script=%s", ctx, output.source_script_id,
                )
    reply_text, image_urls = _split_image_urls(reply_text)
    reply_text = _normalize_dashes(reply_text)

    # Приветствие мы уже отправили этим диалогом (иначе сюда бы не дошли —
    # первое сообщение уходит скриптом), значит повторное здесь лишнее.
    before_strip = reply_text
    reply_text = strip_repeated_greeting(reply_text)
    if reply_text != before_strip:
        logger.info("[%s] stripped repeated greeting from reply", ctx)

    # Скрипты отработки возражений открываются словом «Понимаю» почти все, и
    # подряд идущие реплики выходят под копирку. Меняем первое слово, если
    # предыдущие наши сообщения начинались тем же.
    before_opener = reply_text
    reply_text = vary_repeated_opening(reply_text, manager_history_texts)
    if reply_text != before_opener:
        logger.info(
            "[%s] reply opened like the previous one — opener varied | %r -> %r",
            ctx, before_opener[:24], reply_text[:24],
        )

    # Hash the final attachment set so future turns dedup by content, not URL.
    file_hashes: list[str] = []
    if image_urls:
        from app.utils.media import hash_image_urls
        file_hashes = list((await hash_image_urls(image_urls)).values())

    ai_message = Message(
        dialog_id=dialog.id,
        role=MessageRole.ai,
        text=reply_text,
        msg_metadata={
            "ai_run_id": ai_run.id,
            "confidence": confidence,
            # В админке помечаем «на проверку» и по триггеру тоже, хотя ответ при
            # этом клиенту уходит: отдельная вторая метка про то же самое только
            # путала кураторов. Решение об отправке принимается по output.need_curator
            # (см. вебхук), а это поле — исключительно для интерфейса.
            "need_curator": output.need_curator or bool(trigger),
            # Причина, которая дописывается к метке: «на проверку: вышивка».
            "curator_trigger": trigger,
            "files": image_urls,
            "file_hashes": file_hashes,
        },
    )
    db.add(ai_message)
    await db.flush()

    ai_run.output_message_id = ai_message.id

    parts = [ReplyPart(text=reply_text, image_urls=image_urls, message=ai_message)]

    # Звенья связки уходят дословно и спрашивают своё независимо от того, что
    # клиент уже сказал: «2.3 Доставка» переспросила город через две минуты после
    # «Казань» (диалог 52), «5.1 Данные» — ФИО и телефон в том же ходу, где
    # клиент их прислал. Такие звенья пропускаем.
    # Реплика заканчивается сверкой — ход на ней и заканчивается: следующий шаг
    # воронки отвечает на согласие, которого клиент ещё не давал.
    holds_turn = awaits_client_answer(reply_text)
    if holds_turn:
        logger.info(
            "[%s] реплика ждёт ответа клиента — связку не разворачиваем | %r",
            ctx, reply_text[-60:],
        )
    else:
        parts.extend(await _build_follow_up_parts(
            db, dialog, output.source_script_id, client, ctx, known_slots=slots,
            skip_script_ids=skip_script_ids,
        ))

    # Две точки, где регламент требует отправить следующие шаги не дожидаясь
    # клиента: после похвалы (стоимость + доставка) и после подтверждения дизайна
    # (оформление + данные получателя). Обе связки развернутся, только если модель
    # сошлётся на нужный скрипт, — а она этого не делает: в диалоге 52 цена не
    # ушла вовсе, в прогоне воронки на «да всё верно» пришла та же сверка снова.
    # Достраиваем сами, когда своей связки в ответе не оказалось.
    # Шаг, который модель сделала сама, повторять скриптом нельзя: в прогоне она
    # на «да всё верно» написала свой пересказ оформления, и следом ушёл скрипт
    # #380 с тем же содержанием — клиент прочитал условия оплаты дважды.
    if len(parts) == 1 and not holds_turn:
        entry = None
        if praise_point and not _prices_in(reply_text):
            entry = await find_praise_script(db, type_id)
        elif design_point and not CHECKOUT_PRESENTED_RE.search(reply_text):
            entry = await find_design_fixed_script(db, type_id)
        if entry is not None:
            forced = await _build_follow_up_parts(
                db, dialog, entry.id, client, ctx, known_slots=slots,
                skip_script_ids=skip_script_ids,
            )
            if forced:
                logger.info(
                    "[%s] funnel chain forced | entry=%s | parts=%d",
                    ctx, entry.id, len(forced),
                )
                parts.extend(forced)

    # Клиент выбрал способ оплаты — теперь и только теперь уместен запрос данных
    # получателя. Отдельным шагом, а не связкой к «5. Оформление»: тот скрипт
    # заканчивается вопросом про способ оплаты, и оба сообщения одним ходом
    # означали реакцию на выбор, которого клиент ещё не сделал.
    if (
        payment_choice_point
        and len(parts) == 1
        and not holds_turn
        and asked_slot(reply_text) != "recipient"
    ):
        contacts = await find_contacts_script(db, type_id)
        if contacts is not None and not slot_is_filled("recipient", slots):
            part = await _render_script_part(db, dialog, contacts, client, slots)
            if part is not None:
                logger.info("[%s] contacts request forced | script=%s", ctx, contacts.id)
                parts.append(part)

    # Контакты получателя собраны — по регламенту следом идёт счёт. Ждать, пока
    # модель сама выберет скрипт 5.2, нельзя: в диалоге 37 она вместо ссылки
    # написала, что ссылка «уже отправлена ранее», хотя её никогда не было.
    #
    # Условие берём из самого регламента, а не из стадии: сумма и способы оплаты
    # уже показаны, ФИО с телефоном получены. Классификатор в этот момент держит
    # ход то на checkout, то ещё на design, и счёт съезжал на ход, которого не было.
    contacts_ready = bool(slots.get("recipient") and slots.get("phone"))
    if (
        (dialog.funnel_stage == "payment_link"
         or (contacts_ready and await checkout_presented(db, dialog.id)))
        and not await dialog_has_payment_link(db, dialog.id)
    ):
        if not payment_link_configured():
            # Счёта у нас пока нет — выставляет его человек. Реплику отпускаем
            # (клиент только что прислал ФИО и телефон, тишина в ответ хуже
            # всего), а диалог передаём куратору и замолкаем. Так же устроены
            # темы менеджера: см. curator_trigger ниже.
            logger.info("[%s] оплата: ссылка не настроена — передаём куратору", ctx)
            output = output.model_copy(update={
                "next_status": CURATOR_STATUS_NAME,
                "need_curator": False,
                "curator_reason": "Пора выставлять счёт — ссылки на оплату у ИИ нет",
            })
            dialog.ai_paused = True
            _apply_status(dialog, CURATOR_STATUS_NAME, active_statuses)
            ai_run.status_after = CURATOR_STATUS_NAME
        else:
            link_script = await find_payment_link_script(db, type_id)
            if link_script is not None and not PAYMENT_LINK_RE.search(reply_text):
                part = await _render_script_part(db, dialog, link_script, client, slots)
                if part is not None:
                    logger.info("[%s] payment link forced | script=%s", ctx, link_script.id)
                    parts.append(part)

    # Две разные суммы за один заказ. Клиент 44731492 получил подряд «5 990 ₽
    # (вместо 7 380 ₽)» и «4 990 ₽ (вместо 5 990 ₽)» — на стадии pricing лежат
    # девять активных скриптов с одним условием и разными числами, и связка со
    # скриптом модели разошлись. Пока прайс не почищен, второй ценой молчим.
    parts = _drop_conflicting_prices(parts, manager_history_texts, ctx)
    parts = _drop_duplicate_parts(parts, manager_history_texts, ctx)
    parts = _drop_repeated_offers(parts, manager_history_texts, ctx)
    parts = _drop_repeated_questions(parts, ctx)
    parts = _keep_one_question(parts, ctx)
    # Последним: предыдущие проверки умеют снимать вопрос, и ход может остаться
    # без единого — тогда клиенту нечего ответить и диалог обрывается.
    if dialog.funnel_stage != _TERMINAL_STAGE:
        parts = _ensure_question(parts, slots, ctx)

    await db.commit()
    await db.refresh(ai_run)

    logger.info(
        "[%s] run_ai done | ai_run_id=%s | ai_message_id=%s | parts=%d | need_curator=%s | selected_script=%s",
        ctx, ai_run.id, ai_message.id, len(parts), output.need_curator, output.selected_script,
    )

    return output, ai_run, parts


async def _run_scripted_greeting(
    db: AsyncSession,
    dialog: Dialog,
    client: Client | None,
    script: Script,
    ctx: str,
) -> tuple[AgentOutput, AIRun, list[ReplyPart]]:
    """Отдать приветствие дословно из скрипта, без обращения к модели.

    Модель этот шаблон переписывала и теряла из него фото (см. app.ai.greeting),
    а решать тут нечего: текст готов, вопрос следом задан регламентом. AIRun
    заводим с нулевой стоимостью — прогона модели не было, но диалогу нужна
    запись, на которую сошлётся output_message_id и дедуп вебхука.
    """
    # Текст берём через greeting_text: у приветствия под рекламную метку в
    # админке заполняют только картинки, и без подстановки общего текста клиент
    # получает три фото и сразу вопрос про имя.
    text = await _finalize_outgoing(
        db, dialog, await greeting_text(db, script, dialog.type_id), client,
    )
    text, image_urls = _split_image_urls(text)

    file_hashes: list[str] = []
    if image_urls:
        from app.utils.media import hash_image_urls
        file_hashes = list((await hash_image_urls(image_urls)).values())

    dialog.funnel_stage = "greeting"

    ai_run = AIRun(
        dialog_id=dialog.id,
        provider="script",
        model="greeting",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        cost_amount=0,
        cost_currency="USD",
        confidence_score=1,
        selected_script="greeting:scripted",
        source_script_id=script.id,
    )
    db.add(ai_run)
    await db.flush()

    message = Message(
        dialog_id=dialog.id,
        role=MessageRole.ai,
        text=text,
        msg_metadata={
            "ai_run_id": ai_run.id,
            "confidence": 1.0,
            "need_curator": False,
            "files": image_urls,
            "file_hashes": file_hashes,
            "source_script_id": script.id,
        },
    )
    db.add(message)
    await db.flush()
    ai_run.output_message_id = message.id

    parts = [ReplyPart(text=text, image_urls=image_urls, message=message)]
    parts.extend(await _build_follow_up_parts(db, dialog, script.id, client, ctx))

    await db.commit()
    await db.refresh(ai_run)

    output = AgentOutput(
        reply_text=text,
        confidence_score=1.0,
        selected_script="greeting:scripted",
        source_script_id=script.id,
    )
    logger.info(
        "[%s] scripted greeting sent | script=%s | photos=%d | parts=%d (модель не вызывалась)",
        ctx, script.id, len(image_urls), len(parts),
    )
    return output, ai_run, parts


# Воронка ОП — лестница: «2. Похвала» → «2.2 Стоимость» → «2.3 Доставка». Каждый
# шаг помечен «отправляем сразу после …», то есть уходит без ожидания клиента.
# Ограничение — страховка от кольцевой ссылки, выставленной в админке: без него
# клиент получил бы бесконечную простыню.
_MAX_FOLLOW_UP_CHAIN = 4


async def _build_follow_up_parts(
    db: AsyncSession,
    dialog: Dialog,
    source_script_id: int | None,
    client: Client | None,
    ctx: str,
    known_slots: dict[str, str] | None = None,
    skip_script_ids: set[int] | None = None,
) -> list[ReplyPart]:
    """Все реплики связки: разворачиваем цепочку, пока у скрипта есть follow_up.

    known_slots — факты, которые клиент уже назвал. Звено, спрашивающее такой
    факт, пропускаем, но цепочку не обрываем: за ним идут следующие шаги.

    skip_script_ids — звенья, которые в этом диалоге уже отработали (например
    прайс). Их тоже пропускаем, не обрывая цепочку: за прайсом идёт доставка, и
    её вопрос клиенту всё ещё нужен.
    """
    parts: list[ReplyPart] = []
    seen: set[int] = set()
    current_id = source_script_id
    while current_id and len(parts) < _MAX_FOLLOW_UP_CHAIN:
        if current_id in seen:
            logger.warning("[%s] follow-up chain loops at script %s — stopped", ctx, current_id)
            break
        seen.add(current_id)
        part, current_id = await _build_follow_up_part(
            db, dialog, current_id, client, ctx, known_slots=known_slots,
            skip_script_ids=skip_script_ids,
        )
        if part is not None:
            parts.append(part)
        elif current_id is None:
            break
    return parts


async def _build_follow_up_part(
    db: AsyncSession,
    dialog: Dialog,
    source_script_id: int | None,
    client: Client | None,
    ctx: str,
    known_slots: dict[str, str] | None = None,
    skip_script_ids: set[int] | None = None,
) -> tuple[ReplyPart | None, int | None]:
    """Одно звено связки: реплика и id скрипта, за которым идти дальше.

    Реплика None при непройденном звене; id при этом остаётся, чтобы цепочка
    продолжилась дальше по нему.
    """
    if not source_script_id:
        return None, None
    source = await db.get(Script, source_script_id)
    if not source or not source.follow_up_script_id:
        return None, None
    follow_up = await db.get(Script, source.follow_up_script_id)
    if not follow_up or not follow_up.is_active or not (follow_up.phrase_text or "").strip():
        logger.info(
            "[%s] follow-up script %s missing/inactive — skipped",
            ctx, source.follow_up_script_id,
        )
        return None, None

    if skip_script_ids and follow_up.id in skip_script_ids:
        logger.info("[%s] follow-up %s пропущен — уже отработал в диалоге", ctx, follow_up.id)
        return None, follow_up.id

    slot = asked_slot(follow_up.phrase_text or "")
    if slot and slot_is_filled(slot, known_slots or {}):
        logger.info(
            "[%s] follow-up %s skipped — %s already known", ctx, follow_up.id, slot,
        )
        return None, follow_up.id

    part = await _render_script_part(db, dialog, follow_up, client, known_slots)
    if part is None:
        return None, follow_up.id
    logger.info(
        "[%s] follow-up queued | script=%s -> %s", ctx, source.id, follow_up.id,
    )
    return part, follow_up.id


async def _finalize_outgoing(
    db: AsyncSession,
    dialog: Dialog,
    text: str,
    client: Client | None,
    slots: dict[str, str] | None = None,
) -> str:
    """Общая обработка ЛЮБОГО исходящего текста перед отправкой.

    Раньше её проходила только реплика модели: звенья связки и приветствие
    подставляли имя и цены, но не снимали чужое обращение — и «Михаил, а цвет для
    свитшота какой выберем?» ушло клиентке Анастасии именно скриптом (диалог 163,
    14:09), а не репликой модели.
    """
    slots = slots or {}
    name = client.name if client else None
    text = render_name_placeholder(resolve_spintax(text or ""), name)
    text = strip_foreign_name(text, name, slots.get("inscription"))
    text = await render_price_placeholders(
        db, text, type_id=dialog.type_id, dialog=dialog,
    )
    text = render_order_placeholders(text, slots)
    return normalize_dashes(text)


async def _render_script_part(
    db: AsyncSession,
    dialog: Dialog,
    script: Script,
    client: Client | None,
    slots: dict[str, str] | None = None,
) -> ReplyPart | None:
    """Дословная реплика по скрипту: имя, цены, ссылка на оплату и данные заказа
    подставлены, фото вынесены во вложения. Модель этот текст не переписывает."""
    text = await _finalize_outgoing(db, dialog, script.phrase_text, client, slots)
    text, image_urls = _split_image_urls(text)
    if not text.strip() and not image_urls:
        return None

    file_hashes: list[str] = []
    if image_urls:
        from app.utils.media import hash_image_urls
        file_hashes = list((await hash_image_urls(image_urls)).values())

    message = Message(
        dialog_id=dialog.id,
        role=MessageRole.ai,
        text=text,
        msg_metadata={
            "files": image_urls,
            "file_hashes": file_hashes,
            "source_script_id": script.id,
        },
    )
    db.add(message)
    await db.flush()
    return ReplyPart(text=text, image_urls=image_urls, message=message)
