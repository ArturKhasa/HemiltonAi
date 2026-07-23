"""remove tester role

Revision ID: 019
Revises: 018
Create Date: 2026-06-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # Move any tester users to curator
    bind.execute(sa.text("UPDATE users SET role = 'curator' WHERE role = 'tester'"))

    # Recreate enum without tester: VARCHAR → drop old enum → new enum → back to enum
    bind.execute(sa.text("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(50)"))
    bind.execute(sa.text("DROP TYPE IF EXISTS userrole"))
    bind.execute(sa.text("CREATE TYPE userrole AS ENUM ('admin', 'curator')"))
    bind.execute(sa.text("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::userrole"))


def downgrade() -> None:
    bind = op.get_bind()

    bind.execute(sa.text("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(50)"))
    bind.execute(sa.text("DROP TYPE IF EXISTS userrole"))
    bind.execute(sa.text("CREATE TYPE userrole AS ENUM ('admin', 'curator', 'tester')"))
    bind.execute(sa.text("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::userrole"))
