"""store proposed profile amendments learned from edits

Revision ID: f3b6d9e21c42
Revises: e1f4a8c27b31
Create Date: 2026-11-20 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f3b6d9e21c42"
down_revision: str | Sequence[str] | None = "e1f4a8c27b31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, JSON on SQLite (matches app.db.JSONType).
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=32)


def upgrade() -> None:
    op.create_table(
        "amendment_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("edited_document_id", sa.Uuid(), nullable=False),
        sa.Column("profile_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            _enum("classificationstatus", "pending", "running", "completed", "failed"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_version_id", sa.Uuid(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_by", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["edited_document_id"], ["edited_documents.id"]),
        sa.ForeignKeyConstraint(["profile_version_id"], ["minutes_profile_versions.id"]),
        sa.ForeignKeyConstraint(["applied_version_id"], ["minutes_profile_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("edited_document_id"),
    )
    op.create_table(
        "amendment_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("set_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("pattern_id", sa.String(length=16), nullable=False),
        sa.Column("change_ids", JSON_TYPE, nullable=False),
        sa.Column("dimension", sa.String(length=8), nullable=False),
        sa.Column("operation", _enum("operation", "add", "replace", "remove"), nullable=False),
        sa.Column("target_rule_id", sa.String(length=128), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("proposed_text", sa.Text(), nullable=True),
        sa.Column(
            "kind",
            _enum(
                "provisionkind",
                "evidential_fundamental",
                "requirement",
                "professional_default",
                "preference",
            ),
            nullable=False,
        ),
        sa.Column(
            "provenance",
            _enum(
                "provenance",
                "dess_standard",
                "inferred",
                "explicit_requirement",
                "professional_preference",
            ),
            nullable=False,
        ),
        sa.Column("overlap", _enum("overlap", "none", "duplicate", "conflict"), nullable=False),
        sa.Column("overlap_with", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("refused", sa.Text(), nullable=True),
        sa.Column(
            "status",
            _enum("proposalstatus", "proposed", "accepted", "rejected", "deferred"),
            nullable=False,
        ),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["set_id"], ["amendment_sets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("amendment_proposals")
    op.drop_table("amendment_sets")
