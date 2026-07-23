"""add funnel_stage to scripts + backfill from prompt-derived mapping

Revision ID: 033
Revises: 032
Create Date: 2026-06-28

funnel_stage = earliest funnel step at which the script becomes valid
(greeting < format < calculation < timing < photo < contacts < prepayment < paid).
A gate may later block scripts whose stage is AFTER the dialog's current stage
(forward jumps), while leaving same/earlier-stage recovery scripts usable.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "033"
down_revision: Union[str, None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# stage -> script ids (derived from each script's condition vs the sales-funnel prompt)
STAGE_MAP: list[tuple[str, list[int]]] = [
    ("greeting", [3, 4, 10, 11, 26, 32, 33, 113, 114, 115, 116, 131, 132, 138, 139, 140, 141, 149, 150, 157, 160, 167, 168, 169]),
    ("format", [20, 23, 24, 25, 27, 117, 118, 119, 120, 143, 163, 164, 171]),
    ("calculation", [1, 5, 6, 7, 9, 16, 17, 18, 28, 29, 30, 31, 112, 121, 122, 123, 124, 125, 126, 130, 133, 134, 135, 137, 146, 147, 148, 153, 154, 155, 159, 172]),
    ("timing", [19, 21, 22, 142, 144, 145, 156, 162, 165, 166]),
    ("photo", [8, 12, 13, 14, 15, 35, 36, 127, 128, 129, 136, 158, 161]),
    ("contacts", [34, 151, 170]),
    ("paid", [37, 152]),
]


def upgrade() -> None:
    op.add_column("scripts", sa.Column("funnel_stage", sa.String(length=32), nullable=True))
    scripts = sa.table(
        "scripts",
        sa.column("id", sa.Integer),
        sa.column("funnel_stage", sa.String),
    )
    bind = op.get_bind()
    for stage, ids in STAGE_MAP:
        bind.execute(
            scripts.update().where(scripts.c.id.in_(ids)).values(funnel_stage=stage)
        )


def downgrade() -> None:
    op.drop_column("scripts", "funnel_stage")
