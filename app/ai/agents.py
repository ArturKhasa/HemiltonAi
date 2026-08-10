from agents import Agent

from app.ai.providers import get_model_string
from app.ai.schemas import AgentOutput
from app.ai.tools import (
    make_get_script_phrase,
    make_list_scripts,
    make_search_products,
    make_get_product_photo,
    make_find_similar_examples,
)

# qwen3-max can't combine tools with response_format: setting json_schema OR json_object
# suppresses tool_calls entirely (verified against DashScope compatible-mode). openai-agents
# sends response_format whenever output_type is set, so for qwen we DROP output_type (tools
# fire) and ask for the JSON in the prompt, then parse final_output by hand in the runner.
QWEN_JSON_INSTRUCTION = """

# ФОРМАТ ОТВЕТА
Сначала вызови нужные инструменты (list_scripts, get_script_phrase).
Затем верни ТОЛЬКО один JSON-объект (без markdown-обёрток, без текста до/после) со схемой:
{
  "reply_text": "<текст ответа клиенту>",
  "next_status": "<точное русское имя нового статуса из списка выше, или null>",
  "confidence_score": <число 0.0-1.0>,
  "need_curator": <true|false>,
  "curator_reason": "<почему нужен куратор, или null>",
  "selected_script": "<имя использованного скрипта, или null>",
  "source_script_id": <id скрипта, текст которого использован как основа reply_text, или null>,
  "detected_objection": "<тип возражения клиента, или null>",
  "action_hint": "<send_reply|wait|close_dialog|escalate>"
}"""


def build_sales_agent(
    instructions: str,
    type_id: int | None = None,
    provider: str | None = None,
    client_id: int | None = None,
    funnel_stage: str | None = None,
    exclude_script_ids: set[int] | None = None,
    client_product: str | None = None,
    dialog_id: int | None = None,
) -> Agent:
    tools = [
        make_list_scripts(
            type_id, client_id=client_id, current_stage=funnel_stage,
            exclude_script_ids=exclude_script_ids, client_product=client_product,
        ),
        make_get_script_phrase(type_id, dialog_id),
        make_search_products(type_id),
        make_get_product_photo(type_id),
        make_find_similar_examples(type_id),
    ]

    from app.config import settings
    p = (provider or settings.AI_PROVIDER).lower()
    if p == "qwen":
        # No output_type — response_format would kill tool_calls. JSON requested via prompt,
        # parsed manually (parse_agent_output) in the runner.
        return Agent(
            name="SalesAgent",
            instructions=instructions + QWEN_JSON_INSTRUCTION,
            model=get_model_string(provider),
            tools=tools,
        )

    return Agent(
        name="SalesAgent",
        instructions=instructions,
        model=get_model_string(provider),
        tools=tools,
        output_type=AgentOutput,
    )
