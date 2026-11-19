"""store edit classifications

Revision ID: e1f4a8c27b31
Revises: d7e2b5c19a40
Create Date: 2026-11-19 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e1f4a8c27b31"
down_revision: str | Sequence[str] | None = "d7e2b5c19a40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, JSON on SQLite (matches app.db.JSONType).
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
STATUS = sa.Enum(
    "pending",
    "running",
    "completed",
    "failed",
    name="classificationstatus",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.add_column("document_comparisons", sa.Column("classification", JSON_TYPE, nullable=True))
    op.add_column("document_comparisons", sa.Column("classification_status", STATUS, nullable=True))
    op.add_column(
        "document_comparisons", sa.Column("classification_error", sa.Text(), nullable=True)
    )
    op.add_column(
        "document_comparisons",
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_comparisons", "classified_at")
    op.drop_column("document_comparisons", "classification_error")
    op.drop_column("document_comparisons", "classification_status")
    op.drop_column("document_comparisons", "classification")
