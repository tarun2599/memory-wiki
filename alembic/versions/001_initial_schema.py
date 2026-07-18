"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-07-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    processing_status = postgresql.ENUM(
        "pending", "processing", "completed", "failed", name="processing_status", create_type=True
    )
    processing_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "transcripts",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.UUID(as_uuid=False), primary_key=True),
        sa.Column("transcript_id", sa.UUID(as_uuid=False), sa.ForeignKey("transcripts.id"), nullable=False),
        sa.Column("status", processing_status, nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("files_written", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_processing_jobs_transcript_id", "processing_jobs", ["transcript_id"])


def downgrade() -> None:
    op.drop_index("ix_processing_jobs_transcript_id", table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_table("transcripts")
    op.execute("DROP TYPE IF EXISTS processing_status")
