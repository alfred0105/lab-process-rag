"""Add persistent Phase 4 GP and recommendation runs."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0008_gpbo_mvp"
down_revision = "0007_workflow_approval_flag"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(inspect(op.get_bind()).get_table_names())
    if "optimization_model_runs" not in tables:
        op.create_table(
            "optimization_model_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("status", sa.String(30), nullable=False, server_default="COMPLETED"),
            sa.Column("dataset_hash", sa.String(64), nullable=False),
            sa.Column("model_version", sa.String(80), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("model_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("metrics_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_optimization_model_runs_topic_id", "optimization_model_runs", ["topic_id"])
        op.create_index("ix_optimization_model_runs_mode", "optimization_model_runs", ["mode"])
        op.create_index("ix_optimization_model_runs_status", "optimization_model_runs", ["status"])
        op.create_index("ix_optimization_model_runs_dataset_hash", "optimization_model_runs", ["dataset_hash"])
        op.create_index("ix_optimization_model_runs_created_at", "optimization_model_runs", ["created_at"])
    tables = set(inspect(op.get_bind()).get_table_names())
    if "optimization_recommendation_runs" not in tables:
        op.create_table(
            "optimization_recommendation_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("model_run_id", sa.Integer(), sa.ForeignKey("optimization_model_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False),
            sa.Column("acquisition", sa.String(20), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("candidates_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("approval_status", sa.String(30), nullable=False, server_default="PENDING_RESEARCHER_REVIEW"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        for column in ("model_run_id", "topic_id", "created_at"):
            op.create_index(f"ix_optimization_recommendation_runs_{column}", "optimization_recommendation_runs", [column])


def downgrade():
    raise RuntimeError("Optimization model and recommendation history is preserved; restore a pre-migration backup to roll back.")
