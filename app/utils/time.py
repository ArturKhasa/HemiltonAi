from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3))


def msk_now() -> datetime:
    return datetime.now(MSK).replace(tzinfo=None)


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
