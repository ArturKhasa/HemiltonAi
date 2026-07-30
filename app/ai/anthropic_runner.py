"""Anthropic-native runner with prompt caching. Used when AI provider is 'anthropic'."""
import logging
import time

import anthropic

from app.ai.schemas import AgentOutput
from app.config import settings

logger = logging.getLogger(__name__)

_MAX_TURNS = 5
# Image-decode retries get their own budget so a bad attachment can't crash the run.
_MAX_IMAGE_RETRIES = 6


def _strip_one_image_block(messages: list[dict]) -> str | None:
    """Replace the LAST image block with a text placeholder. Returns the dropped URL,
    or None if no image block was found.

    MiniMax (and Anthropic) reject the whole request as soon as one attachment fails to
    decode, without naming the bad URL. The newest attachment is the usual culprit, so
    strip images one at a time from the end and retry — this preserves earlier history
    images instead of blinding the model on the whole dialog at once.
    """
    for msg in reversed(messages):
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for i in range(len(content) - 1, -1, -1):
            block = content[i]
            if isinstance(block, dict) and block.get("type") == "image":
                url = block.get("source", {}).get("url", "")
                content[i] = {"type": "text", "text": f"[фото: {url}]"}
                return url
    return None

_TOOLS: list[dict] = [
    {
        "name": "list_scripts",
        "description": (
            "Return active scripts with their conditions and script IDs. "
            "Call this to see what scripts are available for the current situation. "
            "If the client has a marketing tag, only tagged scripts are shown."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_script_phrase",
        "description": (
            "Fetch the ready-to-send phrase text of a script by its script_id. "
            "Use the returned text as the basis for reply_text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"script_id": {"type": "integer", "description": "Script ID"}},
            "required": ["script_id"],
        },
    },
    {
        "name": "search_products",
        "description": (
            "Find products by name, e.g. 'свитшот', 'худи', 'чёрный свитшот'. Word order "
            "and adjective gender do not matter. Returns price, promo price (if any) and "
            "size chart. ALWAYS call before quoting a price or size chart, or saying "
            "anything about stock, if list_scripts has no ready phrase with that info. "
            "An empty result means the query did not match — NOT that the item is out of "
            "stock; retry with a single word and never tell the client it ran out."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Product name or part of it"}},
            "required": ["query"],
        },
    },
    {
        "name": "get_product_photo",
        "description": (
            "Find a product's photo by name (see search_products) and get a token to "
            "paste literally into reply_text — the system turns it into a real photo "
            "attachment on send. Do not paste a raw photo URL into reply_text without it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"product_name": {"type": "string", "description": "Product name or part of it"}},
            "required": ["product_name"],
        },
    },
    {
        "name": "find_similar_examples",
        "description": (
            "Semantic search over real past dialogs for similar client questions and how "
            "the manager answered. Use as a tone/argument reference for questions with no "
            "ready script in list_scripts — do NOT copy the found answer verbatim."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The client's question or message"}},
            "required": ["query"],
        },
    },
]

_OUTPUT_TOOL: dict = {
    "name": "generate_reply",
    "description": "Submit the final structured reply to the client. Call this when ready to respond.",
    "input_schema": AgentOutput.model_json_schema(),
    "cache_control": {"type": "ephemeral"},
}


def _serialize_content(content):
    """Make a message's content JSON-safe. Pre-run blocks are already dicts; in-run
    assistant turns hold Anthropic SDK block objects (TextBlock/ToolUseBlock) — dump those."""
    if isinstance(content, str):
        return content
    out = []
    for b in content:
        if isinstance(b, dict):
            out.append(b)
        elif hasattr(b, "model_dump"):
            out.append(b.model_dump(mode="json"))
        else:
            out.append(str(b))
    return out


def _build_context(system_text: str, messages: list[dict]) -> dict:
    """Full context the model accumulated this run: system prompt + every message turn
    (pre-run input plus in-run tool_use / tool_result turns)."""
    return {
        "system": system_text,
        "messages": [
            {"role": m["role"], "content": _serialize_content(m["content"])}
            for m in messages
        ],
    }


def _text_from(content) -> str:
    """Join plain-text blocks from an Anthropic response content list."""
    parts = [b.text for b in (content or []) if getattr(b, "type", None) == "text" and getattr(b, "text", None)]
    return "".join(parts).strip()


def _salvage(text: str) -> AgentOutput:
    """Wrap a plain-text reply into AgentOutput, flagged for curator review.

    MiniMax-M3 honors forced tool_choice only intermittently and sometimes ends its turn
    with the reply as plain text instead of calling generate_reply. Rather than failing the
    whole run, we send the text it produced and mark it for a human to double-check.
    """
    return AgentOutput(
        reply_text=text,
        confidence_score=0.5,
        need_curator=True,
        curator_reason="Модель вернула текст вместо structured generate_reply — нужна проверка",
    )


async def _run_tool(
    name: str, args: dict, type_id: int | None, client_id: int | None,
    funnel_stage: str | None = None,
    exclude_script_ids: set[int] | None = None,
) -> str:
    if name == "list_scripts":
        from app.sales.scripts import ScriptService
        from app.db.session import AsyncSessionLocal
        from app.ai.tools import fetch_client_tags, format_scripts_list
        async with AsyncSessionLocal() as db:
            scripts = await ScriptService(db).get_all_active(type_id=type_id)
        client_tags = await fetch_client_tags(client_id)
        return format_scripts_list(
            scripts, client_tags, current_stage=funnel_stage,
            exclude_script_ids=exclude_script_ids,
        )
    if name == "get_script_phrase":
        from app.ai.tools import get_script_phrase_text
        return await get_script_phrase_text(args["script_id"])
    if name == "search_products":
        from app.ai.tools import run_product_search
        return await run_product_search(args["query"], type_id)
    if name == "get_product_photo":
        from app.sales.products import ProductService
        from app.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            products = await ProductService(db).search(args["product_name"], type_id=type_id, limit=1)
        if not products or not products[0].photo_url:
            return "Фото не найдено для этого товара."
        return f"[photo-{products[0].photo_url}]"
    if name == "find_similar_examples":
        from app.sales.embeddings import find_similar
        from app.db.session import AsyncSessionLocal
        from app.ai.tools import format_similar_examples
        if type_id is None:
            return "Направление не определено."
        async with AsyncSessionLocal() as db:
            rows = await find_similar(db, type_id, args["query"])
        return format_similar_examples(rows)
    return f"Unknown tool: {name}"


def _convert_block(block: dict) -> dict:
    """Convert openai-agents content block format to Anthropic format."""
    t = block.get("type")
    if t == "input_text":
        return {"type": "text", "text": block["text"]}
    if t == "input_image":
        return {"type": "image", "source": {"type": "url", "url": block["image_url"]}}
    return block


def _build_messages(input_messages: list[dict], uncached_tail: int = 1) -> list[dict]:
    """Convert runner.py messages to Anthropic format.

    Adds a single cache breakpoint just before the uncached tail so that all static
    context (history, examples) is cached while the dynamic tail stays uncached.
    ``uncached_tail`` is the number of trailing messages to leave out of the cache —
    1 for just the current client message, or more when per-turn dynamic context
    (funnel stage, feedback rules) is appended before it. Those change every turn, so
    keeping them in the tail preserves the cached prefix.
    """
    out: list[dict] = []
    for msg in input_messages:
        content = msg["content"]
        if isinstance(content, list):
            out.append({"role": msg["role"], "content": [_convert_block(b) for b in content]})
        else:
            out.append({"role": msg["role"], "content": content})

    bp = len(out) - 1 - max(1, uncached_tail)
    if bp >= 0:
        target = out[bp]
        content = target["content"]
        if isinstance(content, str):
            target["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
        elif isinstance(content, list):
            for block in reversed(content):
                if isinstance(block, dict) and block.get("type") in ("text", "input_text"):
                    block["cache_control"] = {"type": "ephemeral"}
                    break

    return out


async def run_with_cache(
    instructions: str,
    input_messages: list[dict],
    type_id: int | None = None,
    client_id: int | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    allow_salvage: bool = True,
    cache_uncached_tail: int = 1,
    funnel_stage: str | None = None,
    exclude_script_ids: set[int] | None = None,
) -> tuple[AgentOutput, int, int, int, dict]:
    """Run sales agent via Anthropic SDK with prompt caching.

    Returns (output, input_tokens, output_tokens, elapsed_ms, full_context).
    System prompt and static context are cached; ~10x cheaper on cache hits.

    Defaults to Anthropic's own API. Pass api_key/base_url/model to target an
    Anthropic-compatible endpoint (e.g. MiniMax at /anthropic), so MiniMax-M3 tool
    calls arrive as structured tool_use blocks instead of [TOOL_CALL_BEGIN] text markup.
    """
    client = anthropic.AsyncAnthropic(
        api_key=api_key or settings.ANTHROPIC_API_KEY,
        base_url=base_url,
    )
    model = model or settings.ANTHROPIC_MODEL_NAME

    tools = [*_TOOLS, _OUTPUT_TOOL]

    system = [{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}]
    messages = _build_messages(input_messages, uncached_tail=cache_uncached_tail)

    def _ctx() -> dict:
        # messages is mutated in place across turns, so this captures the full accumulated context.
        return _build_context(instructions, messages)

    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_write = 0
    start_ms = int(time.time() * 1000)
    image_retries = 0

    async def _create(**extra):
        """messages.create with bad-image retry. On 'invalid image content' it drops one
        image from `messages` (mutated in place, so the fix persists across turns) and
        retries, sharing a single retry budget across the whole run."""
        nonlocal image_retries
        while True:
            try:
                return await client.messages.create(
                    model=model, max_tokens=1024, temperature=0, system=system,
                    tools=tools, messages=messages, **extra,
                )
            except anthropic.BadRequestError as e:
                dropped = None
                if "invalid image content" in str(e) and image_retries < _MAX_IMAGE_RETRIES:
                    dropped = _strip_one_image_block(messages)
                if dropped is None:
                    raise
                image_retries += 1
                logger.warning(
                    "[anthropic_runner] rejected an image, dropping one and retrying "
                    "(%d/%d) | client=%s | url=%s: %s",
                    image_retries, _MAX_IMAGE_RETRIES, client_id, dropped, e,
                )

    for turn in range(_MAX_TURNS):
        response = await _create()

        usage = response.usage
        total_input += getattr(usage, "input_tokens", 0)
        total_output += getattr(usage, "output_tokens", 0)

        cache_read = getattr(usage, "cache_read_input_tokens", 0)
        cache_write = getattr(usage, "cache_creation_input_tokens", 0)
        total_cache_read += cache_read
        total_cache_write += cache_write
        if cache_read or cache_write:
            logger.info(
                "[anthropic_runner] turn=%d cache_read=%d cache_write=%d",
                turn, cache_read, cache_write,
            )

        if response.stop_reason == "tool_use":
            tool_blocks = [b for b in response.content if b.type == "tool_use"]

            output_block = next((b for b in tool_blocks if b.name == "generate_reply"), None)
            if output_block:
                return (
                    AgentOutput(**output_block.input),
                    total_input,
                    total_output,
                    int(time.time() * 1000) - start_ms,
                    _ctx(),
                    total_cache_read,
                    total_cache_write,
                )

            tool_results = []
            for block in tool_blocks:
                logger.info("[anthropic_runner] tool=%s args=%s", block.name, block.input)
                try:
                    result = await _run_tool(
                        block.name, block.input, type_id, client_id, funnel_stage,
                        exclude_script_ids=exclude_script_ids,
                    )
                except Exception as e:
                    logger.warning("[anthropic_runner] tool %s failed: %s", block.name, e)
                    result = f"Error: {e}"
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            # end_turn without generate_reply — force structured output.
            logger.info("[anthropic_runner] end_turn at turn %d, forcing generate_reply", turn)
            text_reply = _text_from(response.content)
            messages.append({"role": "assistant", "content": response.content})
            forced = await _create(tool_choice={"type": "tool", "name": "generate_reply"})
            usage = forced.usage
            total_inputв += getattr(usage, "input_tokens", 0)
            total_output += getattr(usage, "output_tokens", 0)
            total_cache_read += getattr(usage, "cache_read_input_tokens", 0)
            total_cache_write += getattr(usage, "cache_creation_input_tokens", 0)
            output_block = next(
                (b for b in (forced.content or []) if hasattr(b, "name") and b.name == "generate_reply"),
                None,
            )
            if output_block is not None:
                return (
                    AgentOutput(**output_block.input),
                    total_input, total_output, int(time.time() * 1000) - start_ms, _ctx(),
                    total_cache_read, total_cache_write,
                )
            # MiniMax ignored the forced tool_choice — salvage the plain-text reply.
            salvage = text_reply or _text_from(forced.content)
            if salvage and allow_salvage:
                logger.warning(
                    "[anthropic_runner] forced generate_reply ignored | client=%s — salvaging plain-text reply",
                    client_id,
                )
                return (_salvage(salvage), total_input, total_output, int(time.time() * 1000) - start_ms, _ctx(), total_cache_read, total_cache_write)
            raise RuntimeError("generate_reply not called in forced response and no text to salvage")

    # Turn budget exhausted (M3 kept calling tools without finishing). Force a reply once more,
    # then salvage any plain text, before giving up.
    logger.info("[anthropic_runner] turn budget exhausted, forcing generate_reply")
    forced = await _create(tool_choice={"type": "tool", "name": "generate_reply"})
    total_input += getattr(forced.usage, "input_tokens", 0)
    total_output += getattr(forced.usage, "output_tokens", 0)
    total_cache_read += getattr(forced.usage, "cache_read_input_tokens", 0)
    total_cache_write += getattr(forced.usage, "cache_creation_input_tokens", 0)
    output_block = next(
        (b for b in (forced.content or []) if hasattr(b, "name") and b.name == "generate_reply"), None,
    )
    if output_block is not None:
        return (AgentOutput(**output_block.input), total_input, total_output, int(time.time() * 1000) - start_ms, _ctx(), total_cache_read, total_cache_write)
    salvage = _text_from(forced.content)
    if salvage and allow_salvage:
        logger.warning("[anthropic_runner] turn budget exhausted | client=%s — salvaging plain-text reply", client_id)
        return (_salvage(salvage), total_input, total_output, int(time.time() * 1000) - start_ms, _ctx(), total_cache_read, total_cache_write)
    raise RuntimeError(f"Exceeded {_MAX_TURNS} turns without output")
