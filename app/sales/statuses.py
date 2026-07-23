from app.db.models import DialogStatus

ALLOWED_TRANSITIONS: dict[DialogStatus, list[DialogStatus]] = {
    DialogStatus.interested: [
        DialogStatus.calculated,
        DialogStatus.needs_curator,
        DialogStatus.lost,
        DialogStatus.no_response,
        DialogStatus.spam,
    ],
    DialogStatus.calculated: [
        DialogStatus.hot,
        DialogStatus.waiting_prepayment,
        DialogStatus.needs_curator,
        DialogStatus.lost,
        DialogStatus.no_response,
    ],
    DialogStatus.hot: [
        DialogStatus.waiting_prepayment,
        DialogStatus.needs_curator,
        DialogStatus.lost,
    ],
    DialogStatus.waiting_prepayment: [
        DialogStatus.order_created,
        DialogStatus.needs_curator,
        DialogStatus.lost,
    ],
    DialogStatus.order_created: [],
    DialogStatus.needs_curator: [
        DialogStatus.interested,
        DialogStatus.calculated,
        DialogStatus.hot,
        DialogStatus.waiting_prepayment,
        DialogStatus.lost,
    ],
    DialogStatus.lost: [],
    DialogStatus.no_response: [
        DialogStatus.interested,
        DialogStatus.lost,
    ],
    DialogStatus.spam: [],
    DialogStatus.test: [DialogStatus.test],
}


def allowed_next_statuses(current: DialogStatus) -> list[DialogStatus]:
    return ALLOWED_TRANSITIONS.get(current, [])


def can_transition(current: DialogStatus, target: DialogStatus) -> bool:
    return target in allowed_next_statuses(current)
