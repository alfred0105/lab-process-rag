"""Persist evidence-grounded structured paper analysis."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0015_paper_structured_analysis"
down_revision = "0014_paper_original_pdf"
branch_labels = None
depends_on = None


def upgrade():
    if "paper_structured_analyses" not in inspect(op.get_bind()).get_table_names():
        op.create_table(
            "paper_structured_analyses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("paper_id", sa.Integer(), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("analysis_version", sa.String(40), nullable=False, server_default="1"),
            sa.Column("analysis_json", sa.JSON(), nullable=False),
            sa.Column("provider", sa.String(80), nullable=False),
            sa.Column("model", sa.String(200), nullable=False),
            sa.Column("used_evidence_ids", sa.JSON(), nullable=False),
            sa.Column("analysis_status", sa.String(30), nullable=False, server_default="COMPLETED"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_paper_structured_analyses_paper_id", "paper_structured_analyses", ["paper_id"], unique=True)


def downgrade():
    if "paper_structured_analyses" in inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_paper_structured_analyses_paper_id", table_name="paper_structured_analyses")
        op.drop_table("paper_structured_analyses")
