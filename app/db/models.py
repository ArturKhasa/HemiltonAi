import enum
from datetime import datetime

from app.utils.time import msk_now

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Enum as SAEnum, ForeignKey, Index,
    Integer, Numeric, String, Text, JSON, UniqueConstraint, text as sa_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from pgvector.sqlalchemy import Vector

EMBEDDING_DIM = 1536  # OpenAI text-embedding-3-small


class Base(DeclarativeBase):
    pass


class UserRole(enum.Enum):
    admin = "admin"
    curator = "curator"


class MessageRole(enum.Enum):
    client = "client"
    ai = "ai"
    curator = "curator"
    system = "system"


class DialogStatusConfig(Base):
    __tablename__ = "dialog_statuses"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    pattern = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=msk_now)


class DialogType(Base):
    __tablename__ = "dialog_types"
    id = Column(Integer, primary_key=True)
    name = Column(String(128), unique=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    successful_clients_file = Column(String(512), nullable=True)
    # Отвечает ли ИИ клиентам, пришедшим БЕЗ ref-метки (органика, поиск по группе,
    # старые клиенты). Чужая реклама — метка есть, но не в белом списке — блокируется
    # независимо от этого флага. См. миграцию 044 и app.sales.ref_tags.
    answer_untagged = Column(Boolean, nullable=False, default=True, server_default="true")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=msk_now)



class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.curator)
    created_at = Column(DateTime, default=msk_now)
    updated_at = Column(DateTime, default=msk_now, onupdate=msk_now)


class UserDialogType(Base):
    """Доступ куратора к направлению (dialog_type). Админы видят всё без записей здесь.

    Пользователь без единой записи не видит ни одного диалога.
    """
    __tablename__ = "user_dialog_types"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    type_id = Column(Integer, ForeignKey("dialog_types.id", ondelete="CASCADE"), primary_key=True)


class VkGroup(Base):
    """Подключённое сообщество ВКонтакте. Токен и секреты живут только в БД —
    групп много, их добавляют через админку, не через env."""
    __tablename__ = "vk_groups"
    id = Column(Integer, primary_key=True)
    group_id = Column(BigInteger, unique=True, nullable=False)  # числовой ID сообщества
    name = Column(String(255), nullable=False)
    access_token = Column(Text, nullable=False)  # ключ доступа сообщества (права: messages)
    confirmation_code = Column(String(255), nullable=False)  # строка подтверждения Callback API
    secret_key = Column(String(255), nullable=True)  # секрет Callback API
    dialog_type_id = Column(Integer, ForeignKey("dialog_types.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=msk_now)


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True)
    vk_user_id = Column(BigInteger, nullable=True)  # None для тестовых клиентов из чата
    vk_group_id = Column(Integer, ForeignKey("vk_groups.id"), nullable=True)
    # Имя для обращения в диалоге. Фамилия держится отдельно намеренно: по
    # фамилии обращаться нельзя, а в списке лидов нужно показывать обе.
    name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    source = Column(String(255), nullable=True)
    # Локальные маркетинговые теги клиента. Variant: в тестах на SQLite JSONB не рендерится.
    marketing_tags = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    created_at = Column(DateTime, default=msk_now)
    updated_at = Column(DateTime, default=msk_now, onupdate=msk_now)
    __table_args__ = (UniqueConstraint("vk_group_id", "vk_user_id", name="uq_client_vk_group_user"),)


class Dialog(Base):
    __tablename__ = "dialogs"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    type_id = Column(Integer, ForeignKey("dialog_types.id"), nullable=True, server_default="1")
    current_status_id = Column(Integer, ForeignKey("dialog_statuses.id"), nullable=True)
    assigned_curator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_test = Column(Boolean, default=False)
    # Живой оператор ответил из интерфейса ВК — ИИ на паузе, снимает куратор из UI.
    ai_paused = Column(Boolean, default=False, nullable=False, server_default="false")
    # Клиент запретил сообщения от сообщества (ошибки ВК 901/902) — не ретраить отправку.
    vk_blocked = Column(Boolean, default=False, nullable=False, server_default="false")
    # Переписка с этим клиентом велась до нас: он писал в неё раньше или ему
    # отвечал кто-то другой. Такой диалог ИИ не берёт, а если человек вернёт его
    # вручную — знакомиться заново нельзя (миграция 049).
    prior_history = Column(Boolean, default=False, nullable=False, server_default="false")
    ai_provider = Column(String(32), nullable=False, default="openai", server_default="openai")
    # Стадия скрипта продаж (greeting/pricing/options/sizing/design/checkout/payment_link/post_payment/paid).
    # Детектится FunnelAgent на каждое сообщение клиента ПЕРЕД SalesAgent. Ортогональна
    # funnel_type (температура лида) и status (CRM-статусов больше нет, статусы локальные). Оба агента (Sales, Ping) читают это поле.
    funnel_stage = Column(String(32), nullable=True)
    # Цены, уже названные клиенту в этом диалоге: {название товара: сумма}.
    # Матрица — источник правды для НОВОГО диалога; идущий диалог держит своё
    # число, иначе правка прайса поднимает цену человеку, с которым уже
    # договорились (см. миграцию 045).
    quoted_prices = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)
    # Момент, когда оплату подтвердил человек. До него шаги «после оплаты»
    # (благодарность за заказ, адрес ПВЗ, статус «Заказ оформлен») запрещены:
    # ИИ проходил их сам, не получив ни рубля (миграция 047).
    payment_confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=msk_now)
    updated_at = Column(DateTime, default=msk_now, onupdate=msk_now)
    last_message_at = Column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("client_id", "type_id", name="uq_dialog_client_type"),)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    dialog_id = Column(Integer, ForeignKey("dialogs.id", ondelete="CASCADE"), nullable=False)
    role = Column(SAEnum(MessageRole), nullable=False)
    text = Column(Text, nullable=False)
    external_message_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=msk_now)
    msg_metadata = Column("metadata", JSON, nullable=True)
    __table_args__ = (
        Index(
            "uq_message_dialog_external_id",
            "dialog_id",
            "external_message_id",
            unique=True,
            postgresql_where=sa_text("external_message_id IS NOT NULL"),
        ),
    )



class AIRun(Base):
    __tablename__ = "ai_runs"
    id = Column(Integer, primary_key=True)
    dialog_id = Column(Integer, ForeignKey("dialogs.id", ondelete="CASCADE"), nullable=False)
    input_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    output_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    provider = Column(String(64), nullable=False)
    model = Column(String(128), nullable=False)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    # Prompt-cache token counts as reported by the provider. OpenAI/qwen:
    # input_tokens INCLUDES cache_read_tokens; Anthropic: input_tokens excludes
    # them (cache tokens come in separate usage fields). NULL = run predates
    # cache tracking (migration 034), 0 = tracked but nothing cached.
    cache_read_tokens = Column(Integer, nullable=True)
    cache_write_tokens = Column(Integer, nullable=True)
    cost_amount = Column(Numeric(12, 6), nullable=True)
    cost_currency = Column(String(8), default="USD")
    cost_estimated = Column(Boolean, default=False)
    latency_ms = Column(Integer, nullable=True)
    confidence_score = Column(Numeric(4, 3), nullable=True)
    need_curator = Column(Boolean, default=False)
    curator_reason = Column(Text, nullable=True)
    # Text, а не varchar: сюда модель кладёт название/условие применённого скрипта,
    # а условия правятся в админке и длину их никто не ограничивает (миграция 042).
    selected_script = Column(Text, nullable=True)
    source_script_id = Column(Integer, nullable=True)
    status_before = Column(String(64), nullable=True)
    status_after = Column(String(64), nullable=True)
    raw_response = Column(JSON, nullable=True)
    full_context = Column(JSON, nullable=True)
    # 'ok' | 'failed' | 'timeout'. Failed/timed-out runs carry whatever usage was
    # recoverable — the provider billed them even though no reply was produced.
    status = Column(String(16), nullable=False, default="ok", server_default="ok")
    created_at = Column(DateTime, default=msk_now)



class VkAttachmentCache(Base):
    """Кэш перезаливки чужих фото на СВОЁ сообщество: VK принимает attachment в
    messages.send только на объекты, принадлежащие токену отправителя, поэтому
    ссылки на фото из внешних источников (Wazzup24, товарная матрица) один раз
    скачиваются и перезаливаются через photos.getMessagesUploadServer, а результат
    кэшируется здесь по (vk_group_id, source_url), чтобы не перезаливать повторно."""
    __tablename__ = "vk_attachment_cache"
    id = Column(Integer, primary_key=True)
    vk_group_id = Column(Integer, ForeignKey("vk_groups.id", ondelete="CASCADE"), nullable=False)
    source_url = Column(Text, nullable=False)
    attachment = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=msk_now)
    __table_args__ = (UniqueConstraint("vk_group_id", "source_url", name="uq_attachment_cache_group_url"),)


class DialogExampleEmbedding(Base):
    """Пары (реплика клиента → ответ менеджера) из реальных диалогов с эмбеддингом
    client_text — семантический поиск похожих вопросов для инструмента
    find_similar_examples (RAG поверх исторических переписок, не жёсткий скрипт)."""
    __tablename__ = "dialog_example_embeddings"
    id = Column(Integer, primary_key=True)
    type_id = Column(Integer, ForeignKey("dialog_types.id", ondelete="CASCADE"), nullable=False)
    client_text = Column(Text, nullable=False)
    manager_text = Column(Text, nullable=False)
    source = Column(String(64), nullable=True)
    embedding = Column(Vector(EMBEDDING_DIM), nullable=False)
    model = Column(String(128), nullable=False)
    created_at = Column(DateTime, default=msk_now)


class Product(Base):
    """Товарная матрица: справочник товаров с ценой и размерной сеткой для
    инструмента search_products (агент подбирает точную цену/сетку по названию)."""
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    type_id = Column(Integer, ForeignKey("dialog_types.id"), nullable=True, server_default="1")
    name = Column(String(255), nullable=False)
    # Лестница уступок сверху вниз: «Цена» → «Цена со скидкой» → «Минимальная».
    # Клиенту первой называют price; ниже спускаются по одной ступени за раз и
    # только на повторное возражение (см. app.sales.price_placeholder).
    price = Column(Numeric(10, 2), nullable=True)
    # Средняя ступень. Необязательна: не заполнена — лестница двухступенчатая.
    discount_price = Column(Numeric(10, 2), nullable=True)
    min_price = Column(Numeric(10, 2), nullable=True)
    size_chart = Column(String(255), nullable=True)
    photo_url = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=msk_now)


class Script(Base):
    __tablename__ = "scripts"
    id = Column(Integer, primary_key=True)
    type_id = Column(Integer, ForeignKey("dialog_types.id"), nullable=True, server_default="1")
    condition = Column(Text, nullable=False)
    # Готовый текст ответа (поддерживает spintax {a|b|c}); хранится локально, CRM-фраз больше нет.
    phrase_text = Column(Text, nullable=False)
    marketing_tag = Column(String(64), nullable=True)
    funnel_stage = Column(String(32), nullable=True)  # earliest valid funnel step; see migration 033
    # Скрипт, который уходит клиенту вторым сообщением сразу за этим, не дожидаясь
    # ответа (регламент ОП: приветствие + вопрос про имя/фамилию). См. миграцию 041.
    # Этот скрипт — вариант другого шага под рекламную метку: расчёт со
    # свитшотом и жилеткой вместо общего расчёта. Связка воронки идёт по общему
    # скрипту, а на месте подставляет вариант, если метка клиента совпала
    # (миграция 050).
    variant_of_script_id = Column(
        Integer, ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True
    )
    # Вариант шага не под метку, а для заказа на двоих: клиент назвал две надписи
    # («Шишкин Кирилл и Виктория Шишкина») — расчёт и сумма заказа считаются за
    # два изделия. См. миграцию 051.
    is_pair_variant = Column(Boolean, nullable=False, server_default=sa_text("false"))
    follow_up_script_id = Column(
        Integer, ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True
    )
    # Скрипт отправляет только человек: ИИ его не видит и предложить не может.
    # «Ваш макет готов!» уходил от ИИ, хотя макета не существовало (миграция 047).
    manual_only = Column(Boolean, default=False, nullable=False, server_default="false")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=msk_now)
    updated_at = Column(DateTime, default=msk_now, onupdate=msk_now)




class RefTag(Base):
    """Метка рекламной ссылки (?ref=adb_r&ref_source=rusover449 → «rusover449»).

    Белый список: ИИ отвечает только клиентам с перечисленными здесь метками, и
    у каждой кампании своё приветствие. Пока таблица ПУСТА, список не
    применяется и ИИ отвечает всем — см. app.vk.webhook и миграцию 043.
    """
    __tablename__ = "ref_tags"
    id = Column(Integer, primary_key=True)
    type_id = Column(Integer, ForeignKey("dialog_types.id", ondelete="CASCADE"), nullable=True)
    tag = Column(String(128), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    greeting_script_id = Column(
        Integer, ForeignKey("scripts.id", ondelete="SET NULL"), nullable=True
    )
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=msk_now)
    updated_at = Column(DateTime, default=msk_now, onupdate=msk_now)
    __table_args__ = (UniqueConstraint("type_id", "tag", name="uq_ref_tag_type_tag"),)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    id = Column(Integer, primary_key=True)
    type_id = Column(Integer, ForeignKey("dialog_types.id"), nullable=True, server_default="1")
    name = Column(String(128), nullable=False)
    version = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=msk_now)
    __table_args__ = (UniqueConstraint("type_id", "name", "version"),)


class PingPromptVersion(Base):
    __tablename__ = "ping_prompt_versions"
    id = Column(Integer, primary_key=True)
    type_id = Column(Integer, ForeignKey("dialog_types.id"), nullable=True, server_default="1")
    name = Column(String(128), nullable=False)
    version = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=msk_now)
    __table_args__ = (UniqueConstraint("type_id", "name", "version"),)


class PingRule(Base):
    __tablename__ = "ping_rules"
    id = Column(Integer, primary_key=True)
    type_id = Column(Integer, ForeignKey("dialog_types.id"), nullable=True, server_default="1")
    funnel_type = Column(String(32), nullable=False)
    step = Column(Integer, nullable=False)
    delay_seconds = Column(Integer, nullable=False)
    # Текст пинг-шага (поддерживает spintax); агент может адаптировать его под диалог.
    phrase_text = Column(Text, nullable=False, default="")
    manual_text = Column(Text, nullable=True)
    after_status = Column(String(255), nullable=True)
    marketing_tag = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=msk_now)
    updated_at = Column(DateTime, default=msk_now, onupdate=msk_now)
    __table_args__ = (UniqueConstraint("type_id", "funnel_type", "step", "marketing_tag", name="uq_ping_rule_type_funnel_step_tag"),)


class DialogPingState(Base):
    __tablename__ = "dialog_ping_states"
    id = Column(Integer, primary_key=True)
    dialog_id = Column(Integer, ForeignKey("dialogs.id", ondelete="CASCADE"), unique=True, nullable=False)
    funnel_type = Column(String(32), nullable=False)
    funnel_reason = Column(Text, nullable=True)
    current_step = Column(Integer, nullable=False, default=0)
    last_ping_sent_at = Column(DateTime, nullable=True)
    next_ping_due_at = Column(DateTime, nullable=True)
    is_completed = Column(Boolean, default=False, nullable=False)
    misfire_count = Column(Integer, nullable=False, server_default="0", default=0)
    marketing_tag = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=msk_now)
    updated_at = Column(DateTime, default=msk_now, onupdate=msk_now)


class MessageFeedback(Base):
    __tablename__ = "message_feedbacks"
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True)
    type_id = Column(Integer, ForeignKey("dialog_types.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    rule_text = Column(Text, nullable=False)
    is_ping = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=msk_now)
    updated_at = Column(DateTime, default=msk_now, onupdate=msk_now)


