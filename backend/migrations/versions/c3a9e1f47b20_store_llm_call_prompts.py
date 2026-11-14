"""store llm call prompts and output

Revision ID: c3a9e1f47b20
Revises: ae488c16e032
Create Date: 2026-11-14 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a9e1f47b20"
down_revision: str | Sequence[str] | None = "ae488c16e032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("system_prompt", sa.Text(), nullable=True))
    op.add_column("llm_calls", sa.Column("prompt", sa.Text(), nullable=True))
    op.add_column("llm_calls", sa.Column("output", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_calls", "output")
    op.drop_column("llm_calls", "prompt")
    op.drop_column("llm_calls", "system_prompt")
