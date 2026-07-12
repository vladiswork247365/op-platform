"""init: presets + jobs

Revision ID: 0001_init
Revises:
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "presets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=True),
        sa.Column("voice", sa.Text(), nullable=True),
        sa.Column("subtitle_style", postgresql.JSONB(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("length", sa.Integer(), nullable=True),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_presets_name", "presets", ["name"])

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("preset_id", sa.Integer(), sa.ForeignKey("presets.id"), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="accepted"),
        sa.Column("stage", sa.String(16), nullable=True),
        sa.Column("settings_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("external_job_id", sa.Text(), nullable=True),
        sa.Column("source_stored_url", sa.Text(), nullable=True),
        sa.Column("tool_output_url", sa.Text(), nullable=True),
        sa.Column("master_url", sa.Text(), nullable=True),
        sa.Column("preview_url", sa.Text(), nullable=True),
        sa.Column("cost", sa.Numeric(12, 4), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_external_job_id", "jobs", ["external_job_id"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("presets")
