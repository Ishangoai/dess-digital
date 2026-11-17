"""create draft feedback table

Revision ID: e40615f48731
Revises: c3a9e1f47b20
Create Date: 2026-11-17 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e40615f48731"
down_revision: str | Sequence[str] | None = "c3a9e1f47b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, JSON on SQLite (matches app.db.JSONType).
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "draft_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "verdict",
            sa.Enum(
                "approved",
                "revision_requested",
                "edited",
                name="verdict",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("reward", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("comparison", JSON_TYPE, nullable=True),
        sa.Column("profile_version_id", sa.Uuid(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_version_id"], ["minutes_profile_versions.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["draft_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("draft_feedback")
