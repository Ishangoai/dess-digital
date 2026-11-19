"""store exported and edited documents

Revision ID: 4564ee32af28
Revises: e40615f48731
Create Date: 2026-11-19 07:49:15.264948

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4564ee32af28"
down_revision: str | Sequence[str] | None = "e40615f48731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, JSON on SQLite (matches app.db.JSONType).
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
FEEDBACK_FK = "fk_draft_feedback_edited_document_id"


def upgrade() -> None:
    op.create_table(
        "exported_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("marks", JSON_TYPE, nullable=False),
        sa.Column("with_template", sa.Boolean(), nullable=False),
        sa.Column("recreated", sa.Boolean(), nullable=False),
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
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("sections", JSON_TYPE, nullable=False),
        sa.Column("summary", JSON_TYPE, nullable=False),
        sa.Column("comments", JSON_TYPE, nullable=False),
        sa.Column("answers", JSON_TYPE, nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classify_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["export_id"], ["exported_documents.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["draft_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "edit_alignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("edited_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("item_ref", sa.String(length=64), nullable=False),
        sa.Column("original_item_ref", sa.String(length=64), nullable=True),
        sa.Column("original_n", sa.Integer(), nullable=True),
        sa.Column("paragraph_id", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("final_text", sa.Text(), nullable=False),
        sa.Column("diff", JSON_TYPE, nullable=False),
        sa.Column("tracked", JSON_TYPE, nullable=False),
        sa.Column("comment_ids", JSON_TYPE, nullable=False),
        sa.ForeignKeyConstraint(["edited_id"], ["edited_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "edit_classifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("edited_id", sa.Uuid(), nullable=False),
        sa.Column("alignment_id", sa.Uuid(), nullable=False),
        sa.Column("hunk", sa.Integer(), nullable=False),
        sa.Column("before", sa.Text(), nullable=False),
        sa.Column("after", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("dimensions", JSON_TYPE, nullable=False),
        sa.Column("cause", sa.String(length=32), nullable=False),
        sa.Column("support", sa.String(length=32), nullable=False),
        sa.Column("evidence", JSON_TYPE, nullable=False),
        sa.Column("profile_basis", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("pattern", sa.String(length=255), nullable=False),
        sa.Column("route", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["alignment_id"], ["edit_alignments.id"]),
        sa.ForeignKeyConstraint(["edited_id"], ["edited_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Batch mode so SQLite can add the foreign key too.
    with op.batch_alter_table("draft_feedback") as batch:
        batch.add_column(sa.Column("edited_document_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(FEEDBACK_FK, "edited_documents", ["edited_document_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("draft_feedback") as batch:
        batch.drop_constraint(FEEDBACK_FK, type_="foreignkey")
        batch.drop_column("edited_document_id")
    op.drop_table("edit_classifications")
    op.drop_table("edit_alignments")
    op.drop_table("edited_documents")
    op.drop_table("exported_documents")
