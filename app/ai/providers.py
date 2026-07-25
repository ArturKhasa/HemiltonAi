"""Build openai-agents compatible model string for LiteLLM routing."""
import json as _json_mod
import re
from functools import lru_cache

from app.config import settings


@lru_cache(maxsize=4)
def _qwen_model(model_name: str):
    """OpenAIChatCompletionsModel pointed at the MuleRouter OpenAI-compatible gateway.

    Cached per model name so we reuse one AsyncOpenAI client instead of rebuilding it
    on every agent construction (once per message).
    """
    from openai import AsyncOpenAI
    from agents import OpenAIChatCompletionsModel

    client = AsyncOpenAI(api_key=settings.QWEN_API_KEY, base_url=settings.QWEN_BASE_URL)
    return OpenAIChatCompletionsModel(model=model_name, openai_client=client)


def _xml_to_dict(xml_str: str) -> dict | None:
    """Convert flat XML like <result><key>val</key></result> to a dict.

    Handles only one level of nesting — enough for MiniMax structured output.
    Returns None if parsing fails or input is not XML.
    """
    xml_str = xml_str.strip()
    if not xml_str.startswith("<"):
        return None
    try:
        # Strip outer wrapper tag if present
        m_outer = re.match(r"^<\w+>([\s\S]*)</\w+>$", xml_str, re.DOTALL)
        inner = m_outer.group(1) if m_outer else xml_str
        obj: dict = {}
        for m in re.finditer(r"<(\w+)>([\s\S]*?)</\1>", inner):
            key, val = m.group(1), m.group(2).strip()
            # Coerce numeric strings and null
            if val == "null":
                obj[key] = None
            else:
                try:
                    obj[key] = int(val)
                except ValueError:
                    try:
                        obj[key] = float(val)
                    except ValueError:
                        obj[key] = val
        return obj if obj else None
    except Exception:
        return None


def _patch_agents_json() -> None:
    """Strip <think> blocks and markdown fences from model output before JSON validation.

    Reasoning models (e.g. MiniMax-M2.7) emit <think>...</think> + ```json...``` which
    breaks the openai-agents SDK's raw-JSON parser.
    """
    try:
        from agents.util import _json as agents_json
    except ImportError:
        return

    if getattr(agents_json, "_thinking_patch_applied", False):
        return

    _orig = agents_json.validate_json

    # *args/**kwargs — newer openai-agents versions pass extra kwargs (e.g. strict);
    # accept and forward them so the patch survives SDK upgrades.
    def _patched(json_str: str, type_adapter, *args, **kwargs):
        cleaned = re.sub(r"<think>.*?</think>", "", json_str, flags=re.DOTALL).strip()
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if m:
            cleaned = m.group(1).strip()
        # MiniMax may emit XML instead of JSON — convert to JSON
        if cleaned.startswith("<"):
            xml_obj = _xml_to_dict(cleaned)
            if xml_obj is not None:
                cleaned = _json_mod.dumps(xml_obj, ensure_ascii=False)
        # MiniMax reasoning models sometimes emit "reasoning" or "comment" instead of "reason"
        try:
            obj = _json_mod.loads(cleaned)
            if isinstance(obj, dict) and "reason" not in obj:
                for alias in ("reasoning", "comment"):
                    if alias in obj:
                        obj["reason"] = obj.pop(alias)
                        break
                cleaned = _json_mod.dumps(obj, ensure_ascii=False)
        except Exception:
            pass
        return _orig(cleaned, type_adapter, *args, **kwargs)

    agents_json.validate_json = _patched
    agents_json._thinking_patch_applied = True


_patch_agents_json()


def parse_agent_output(raw: str, model_cls=None):
    """Parse a model's free-text reply into a pydantic model.

    Used for the qwen path, which drops output_type (response_format kills tool_calls),
    so the SDK returns a plain string instead of a validated object. Strips <think>
    blocks and ```json fences, then validates against model_cls (default AgentOutput).
    """
    if model_cls is None:
        from app.ai.schemas import AgentOutput
        model_cls = AgentOutput

    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if m:
        cleaned = m.group(1).strip()
    # Fall back to the first balanced-looking {...} span if there's stray prose around it.
    if not cleaned.startswith("{"):
        brace = re.search(r"\{[\s\S]*\}", cleaned)
        if brace:
            cleaned = brace.group(0)
    return model_cls.model_validate_json(cleaned)


def pick_ai_provider(client_id: int) -> str:
    """Split dialogs 70/30 across openai/qwen by client id.

    client_id % 10 in 0..6 → openai (70%), 7..9 → qwen (30%). Deterministic per
    client, so all of a client's dialogs stay on one provider; across many
    clients the split is ~70/30.

    ВРЕМЕННО ОТКЛЮЧЕНО (100% openai): QWEN_API_KEY в .env пустой — каждый диалог,
    попавший в qwen-корзину, падал на построении клиента без единого ответа
    клиенту. Раскомментировать split ниже, когда появится рабочий ключ.
    """
    return "openai"
    # return "openai" if client_id % 10 < 7 else "qwen"


def get_model_string(provider: str | None = None, model_name: str | None = None) -> str:
    """Return model string for openai-agents SDK.

    openai-agents uses litellm under the hood — prefix with provider name
    for non-OpenAI providers. Pass model_name to override the provider's default
    model (e.g. a cheaper model for pings) while keeping the same routing.
    """
    p = (provider or settings.AI_PROVIDER).lower()

    if p == "openai":
        return model_name or settings.MODEL_NAME
    elif p == "qwen":
        # Returns a Model object (not a string) — Agent(model=...) accepts both.
        return _qwen_model(model_name or settings.QWEN_MODEL_NAME)
    elif p == "anthropic":
        return f"litellm/anthropic/{model_name or settings.ANTHROPIC_MODEL_NAME}"
    elif p == "minimax":
        return f"litellm/minimax/{model_name or settings.MINIMAX_MODEL_NAME}"
    elif p == "litellm":
        return model_name or settings.MODEL_NAME
    else:
        return f"{p}/{model_name or settings.MODEL_NAME}"


def get_model_name(provider: str | None = None, model_name: str | None = None) -> str:
    """Return just the model name (no prefix) for cost tracking.

    Pass model_name to override the provider's default (keeps cost lookup accurate
    when a non-default model is used, e.g. haiku for pings).
    """
    if model_name:
        return model_name
    p = (provider or settings.AI_PROVIDER).lower()
    if p == "anthropic":
        return settings.ANTHROPIC_MODEL_NAME
    if p == "minimax":
        return settings.MINIMAX_MODEL_NAME
    if p == "qwen":
        return settings.QWEN_MODEL_NAME
    return settings.MODEL_NAME
