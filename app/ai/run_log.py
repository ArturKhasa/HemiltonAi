"""Persist AI runs that failed mid-flight.

A failed run is still billed by the provider — the API call succeeded even if we
timed out waiting for it or its output failed to parse — so it must land in
ai_runs or cost reporting undercounts real spend. Uses a dedicated DB session:
the caller's session is typically rolled back together with the request that
raised, which would silently drop the row.
"""
import logging

from app.ai.cost import (
    CACHE_READ_MULT_BY_MODEL,
    DEFAULT_CACHE_READ_MULT,
    calculate_cost,
    get_model_pricing,
)
from app.db.session import AsyncSessionLocal
from app.db.models import AIRun

logger = logging.getLogger(__name__)


def usage_from_result(result) -> tuple[int, int, int]:
    """(input, output, cached) tokens summed over raw_responses.

    Zeros when result is None — the call never returned (timeout/network), so
    usage is unrecoverable client-side."""
    if result is None:
        return 0, 0, 0
    raw = getattr(result, "raw_responses", None) or []
    input_tokens = sum(getattr(r.usage, "input_tokens", 0) or 0 for r in raw)
    output_tokens = sum(getattr(r.usage, "output_tokens", 0) or 0 for r in raw)
    cached = sum(
        getattr(getattr(r.usage, "input_tokens_details", None), "cached_tokens", 0) or 0
        for r in raw
    )
    return input_tokens, output_tokens, cached


async def log_failed_run(
    *,
    dialog_id: int,
    provider: str,
    model: str,
    error: BaseException | str,
    status: str = "failed",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    elapsed_ms: int | None = None,
    label: str | None = None,
    input_message_id: int | None = None,
) -> None:
    """Best-effort: swallows its own errors so it never masks the original one."""
    try:
        in_price, out_price = get_model_pricing(model)
        # Same split as app/ai/runner.py: Anthropic/MiniMax report input_tokens
        # already excluding cache tokens; OpenAI-style usage includes them.
        if provider in ("anthropic", "minimax"):
            billable_input = input_tokens
            cache_read_mult = DEFAULT_CACHE_READ_MULT
        else:
            billable_input = max(input_tokens - cache_read_tokens, 0)
            cache_read_mult = CACHE_READ_MULT_BY_MODEL.get(model, DEFAULT_CACHE_READ_MULT)
        cost = calculate_cost(
            billable_input,
            output_tokens,
            in_price,
            out_price,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            cache_read_mult=cache_read_mult,
        )
        async with AsyncSessionLocal() as session:
            session.add(
                AIRun(
                    dialog_id=dialog_id,
                    input_message_id=input_message_id,
                    provider=provider,
                    model=model,
                    status=status,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                    cost_amount=cost,
                    cost_currency="USD",
                    cost_estimated=(input_tokens == 0),
                    latency_ms=elapsed_ms,
                    selected_script=label,
                    raw_response={"error": str(error)[:2000]},
                )
            )
            await session.commit()
        logger.info(
            "log_failed_run: saved | dialog=%s provider=%s status=%s in=%d out=%d cached=%d cost=%s",
            dialog_id, provider, status, input_tokens, output_tokens, cache_read_tokens, cost,
        )
    except Exception:
        logger.exception(
            "log_failed_run: persist failed | dialog=%s provider=%s", dialog_id, provider
        )
