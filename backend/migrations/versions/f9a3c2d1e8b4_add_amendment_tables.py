"""add amendment tables

Revision ID: f9a3c2d1e8b4
Revises: c3a9e1f47b20
Create Date: 2026-11-19 15:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f9a3c2d1e8b4"
down_revision: str | Sequence[str] | None = "c3a9e1f47b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, JSON on SQLite (matches app.db.JSONType).
# Included for consistency with the rest of the migration suite.
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "profile_amendment_sets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "origin",
            sa.Enum(
                "seed",
                "api",
                "customisation",
                "feedback",
                name="versionorigin",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_version_id"],
            ["minutes_profile_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "profile_amendment_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("amendment_set_id", sa.Uuid(), nullable=False),
        sa.Column("target_dimension", sa.String(length=8), nullable=False),
        sa.Column("target_provision", sa.String(length=255), nullable=True),
        sa.Column(
            "target_type",
            sa.Enum(
                "provision",
                "application_note",
                name="amendmenttargettype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "operation",
            sa.Enum(
                "add",
                "replace",
                "remove",
                name="amendmentoperation",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("proposed_text", sa.Text(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "evidential_fundamental",
                "requirement",
                "professional_default",
                "preference",
                name="provisionkind",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "provenance",
            sa.Enum(
                "dess_standard",
                "inferred",
                "explicit_requirement",
                "professional_preference",
                name="provenance",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("scope", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "proposed",
                "accepted",
                "rejected",
                "deferred",
                name="amendmentstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("decided_by", sa.String(length=255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("conflict_warning", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["amendment_set_id"],
            ["profile_amendment_sets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("profile_amendment_proposals")
    op.drop_table("profile_amendment_sets")
