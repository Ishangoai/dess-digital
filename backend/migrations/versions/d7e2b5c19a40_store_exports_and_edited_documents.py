"""store exported and edited Word documents

Revision ID: d7e2b5c19a40
Revises: c3a9e1f47b20
Create Date: 2026-11-19 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d7e2b5c19a40"
down_revision: str | Sequence[str] | None = "c3a9e1f47b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, JSON on SQLite (matches app.db.JSONType).
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "exported_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("used_template", sa.Boolean(), nullable=False),
        sa.Column("draft", JSON_TYPE, nullable=False),
        sa.Column("manifest", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["draft_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "edited_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("export_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["draft_runs.id"]),
        sa.ForeignKeyConstraint(["export_id"], ["exported_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "document_comparisons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("edited_document_id", sa.Uuid(), nullable=False),
        sa.Column("result", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["edited_document_id"], ["edited_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("edited_document_id"),
    )


def downgrade() -> None:
    op.drop_table("document_comparisons")
    op.drop_table("edited_documents")
    op.drop_table("exported_documents")
