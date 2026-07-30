from decimal import Decimal, ROUND_HALF_UP

FALLBACK_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4o": (Decimal("2.5000"), Decimal("10.0000")),
    "gpt-4o-mini": (Decimal("0.1500"), Decimal("0.6000")),
    "gpt-4.1": (Decimal("2.0000"), Decimal("8.0000")),
    "gpt-4.1-mini": (Decimal("0.4000"), Decimal("1.6000")),
    "gpt-4.1-nano": (Decimal("0.1000"), Decimal("0.4000")),
    "gpt-5.4": (Decimal("2.5000"), Decimal("15.0000")),
    "gpt-5.4-mini": (Decimal("0.7500"), Decimal("4.5000")),
    "gpt-5.4-nano": (Decimal("0.2000"), Decimal("1.2500")),
    "gpt-5.5": (Decimal("5.0000"), Decimal("30.0000")),
    # Luna — дешёвая модель линейки 5.6 под высоконагруженные диалоги. Именно "-luna":
    # алиас "gpt-5.6" маршрутизируется на Sol, это другая модель и другой прайс.
    "gpt-5.6-luna": (Decimal("0.2000"), Decimal("1.2000")),
    "claude-3-5-sonnet-20241022": (Decimal("3.0000"), Decimal("15.0000")),
    "claude-3-haiku-20240307": (Decimal("0.2500"), Decimal("1.2500")),
    "claude-haiku-4-5-20251001": (Decimal("0.8000"), Decimal("4.0000")),
    "claude-haiku-4-5": (Decimal("0.8000"), Decimal("4.0000")),
    "claude-sonnet-4-6": (Decimal("3.0000"), Decimal("15.0000")),
    "MiniMax-M2.7": (Decimal("1.0000"), Decimal("4.0000")),
    "MiniMax-M3": (Decimal("0.3000"), Decimal("1.2000")),
    "MiniMax-M3-512k": (Decimal("0.3000"), Decimal("1.2000")),
    # Qwen via MuleRouter — verify against actual gateway billing; these are DashScope intl list prices.
    "qwen3-max": (Decimal("1.2000"), Decimal("6.0000")),
    "qwen-max-latest": (Decimal("1.6000"), Decimal("6.4000")),
    "qwen-max": (Decimal("1.6000"), Decimal("6.4000")),
}


def get_model_pricing(model: str) -> tuple[Decimal, Decimal]:
    """Return (input_price_per_1m, output_price_per_1m) in USD."""
    return FALLBACK_PRICES.get(model, (Decimal("5.0000"), Decimal("15.0000")))


# Prompt-cache multipliers applied to the input price.
# Anthropic:
#   cache read   = 0.1x  input price
#   cache write  = 1.25x input price (5-minute ephemeral, the default)
# MiniMax's Anthropic-compatible endpoint returns 0 cache tokens, so these
# terms vanish there.
# OpenAI has no separate cache-write cost, but its cached-input discount differs
# per family (gpt-4.1 = 0.25x, gpt-5/gpt-4o-mini = 0.1x, gpt-4o = 0.5x). The
# caller passes the right read multiplier via cache_read_mult; default is the
# Anthropic 0.1x.
DEFAULT_CACHE_READ_MULT = Decimal("0.1")
CACHE_READ_MULT = DEFAULT_CACHE_READ_MULT  # backwards-compat alias for Anthropic callers
CACHE_WRITE_MULT = Decimal("1.25")

# OpenAI cached-input multiplier (cached price / input price), keyed by the same
# model name used in FALLBACK_PRICES. Models absent here fall back to 0.1x.
CACHE_READ_MULT_BY_MODEL: dict[str, Decimal] = {
    "gpt-4o": Decimal("0.5"),
    "gpt-4o-mini": Decimal("0.5"),
    "gpt-4.1": Decimal("0.25"),
    "gpt-4.1-mini": Decimal("0.25"),
    "gpt-4.1-nano": Decimal("0.25"),
    "gpt-5.4": Decimal("0.1"),
    "gpt-5.4-mini": Decimal("0.1"),
    "gpt-5.4-nano": Decimal("0.1"),
    "gpt-5.5": Decimal("0.1"),
    "gpt-5.6-luna": Decimal("0.1"),  # cached $0.02 / input $0.20
    # Qwen (Alibaba Model Studio): implicit cache hit billed at $0.24/M vs $1.20/M
    # tier-1 input = 0.2x — confirmed against qwencloud daysummary billing export
    # (July 2026). Requires the gateway to report cached_tokens in usage; if it
    # returns 0 this is a no-op.
    "qwen3-max": Decimal("0.2"),
}


def calculate_cost(
    input_tokens: int,
    output_tokens: int,
    input_price_per_1m: Decimal,
    output_price_per_1m: Decimal,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_read_mult: Decimal = DEFAULT_CACHE_READ_MULT,
) -> Decimal:
    cost = (
        Decimal(input_tokens) * input_price_per_1m / Decimal("1000000")
        + Decimal(output_tokens) * output_price_per_1m / Decimal("1000000")
        + Decimal(cache_read_tokens) * input_price_per_1m * cache_read_mult / Decimal("1000000")
        + Decimal(cache_write_tokens) * input_price_per_1m * CACHE_WRITE_MULT / Decimal("1000000")
    )
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
