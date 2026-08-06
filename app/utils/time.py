from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3))


def msk_now() -> datetime:
    return datetime.now(MSK).replace(tzinfo=None)


# Названия по-русски собираем сами: локали ru_RU в контейнере нет, а модели дата
# нужна в том же виде, в котором её называет клиент («к 9 августа»).
_WEEKDAYS = (
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
)
_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def human_msk_now(now: datetime | None = None) -> str:
    """«четверг, 6 августа 2026, 21:40 (МСК)» — строка даты для контекста модели.

    Без неё модель не знает, какое сегодня число: на «хочу к 9 августа» она не
    могла понять, три это дня или три месяца, и отвечала «подстроимся под Вас»
    вместо честного «не успеем» (замечание ОП от 6 августа).
    """
    dt = now or msk_now()
    return (
        f"{_WEEKDAYS[dt.weekday()]}, {dt.day} {_MONTHS[dt.month - 1]} {dt.year}, "
        f"{dt:%H:%M} (МСК)"
    )


def to_naive_msk(dt: datetime | None) -> datetime | None:
    """Convert an (aware or naive) datetime to naive MSK to match DB storage.

    DB columns store naive MSK (see msk_now). Aware datetimes from API clients
    (e.g. UTC ISO strings) must be converted to MSK before stripping tzinfo,
    not stripped raw — stripping raw UTC shifts the value by the MSK offset.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(MSK)
    return dt.replace(tzinfo=None)
