"""create minutes profile and draft tables

Revision ID: ae488c16e032
Revises: 4b1fd23c0eba
Create Date: 2026-11-13 09:06:21.002664

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ae488c16e032"
down_revision: str | Sequence[str] | None = "4b1fd23c0eba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, JSON on SQLite (matches app.db.JSONType).
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "minutes_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("body_name", sa.String(length=255), nullable=True),
        sa.Column("based_on_profile_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["based_on_profile_id"],
            ["minutes_profiles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "minutes_profile_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "proposed",
                "reviewed",
                "confirmed",
                "withdrawn",
                name="profileversionstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "content",
            JSON_TYPE,
            nullable=False,
        ),
        sa.Column("content_schema_version", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
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
        sa.Column("parent_version_id", sa.Uuid(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.String(length=255), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["minutes_profile_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["minutes_profiles.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "version_number"),
    )
    op.create_table(
        "draft_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "analysing",
                "awaiting_mapping_review",
                "blocked",
                "drafting",
                "completed",
                "failed",
                name="draftstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "meeting_info",
            JSON_TYPE,
            nullable=False,
        ),
        sa.Column(
            "analysis",
            JSON_TYPE,
            nullable=True,
        ),
        sa.Column(
            "mapping",
            JSON_TYPE,
            nullable=True,
        ),
        sa.Column(
            "selection",
            JSON_TYPE,
            nullable=True,
        ),
        sa.Column(
            "draft_initial",
            JSON_TYPE,
            nullable=True,
        ),
        sa.Column(
            "validation",
            JSON_TYPE,
            nullable=True,
        ),
        sa.Column(
            "reconsideration",
            JSON_TYPE,
            nullable=True,
        ),
        sa.Column(
            "draft",
            JSON_TYPE,
            nullable=True,
        ),
        sa.Column(
            "lint",
            JSON_TYPE,
            nullable=True,
        ),
        sa.Column("mapping_edited", sa.Boolean(), nullable=False),
        sa.Column(
            "blocked_reasons",
            JSON_TYPE,
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_stage", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["profile_version_id"],
            ["minutes_profile_versions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "draft_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "agenda",
                "transcript",
                "notes",
                "paper",
                name="sourcerole",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(length=8), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["draft_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["draft_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("llm_calls")
    op.drop_table("draft_documents")
    op.drop_table("draft_runs")
    op.drop_table("minutes_profile_versions")
    op.drop_table("minutes_profiles")
