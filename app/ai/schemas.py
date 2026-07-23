from typing import Literal
from pydantic import BaseModel, Field


class AgentOutput(BaseModel):
    reply_text: str = Field(description="Message to send to the client")
    next_status: str | None = Field(
        default=None,
        description="Exact Russian name of the new dialog status (from the list in system prompt). null = no change.",
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0,
        description="Agent's confidence in this reply (0–1)",
    )
    need_curator: bool = Field(
        default=False,
        description="True if curator must review before sending",
    )
    curator_reason: str | None = Field(
        default=None,
        description="Why curator review is needed",
    )
    selected_script: str | None = Field(
        default=None,
        description="Script name used to generate this reply, if any",
    )
    source_script_id: int | None = Field(
        default=None,
        description=(
            "ID of the script whose phrase text was used as the basis for reply_text. "
            "Set it to the script_id you fetched via get_script_phrase and built this reply on. "
            "null = reply was not based on any script."
        ),
    )
    detected_objection: str | None = Field(
        default=None,
        description="Objection type detected in client message, if any",
    )
    action_hint: Literal["send_reply", "wait", "close_dialog", "escalate"] = Field(
        default="send_reply",
        description="Recommended action after this turn",
    )
