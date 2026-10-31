"""Persist reviewed decision cases and learned decision models."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0009_learned_decision_head"
down_revision = "0008_gpbo_mvp"
branch_labels = None
depends_on = None


def upgrade():
    tables=set(inspect(op.get_bind()).get_table_names())
    if "decision_cases" not in tables:
      op.create_table(
        "decision_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("case_group_id", sa.String(200), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("features_json", sa.JSON(), nullable=False),
        sa.Column("feature_schema_version", sa.String(40), nullable=False),
        sa.Column("candidate_actions_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("selected_action", sa.String(40), nullable=False),
        sa.Column("label_source", sa.String(40), nullable=False),
        sa.Column("reviewer", sa.String(200), nullable=True),
        sa.Column("review_status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("dataset_version", sa.String(40), nullable=False, server_default="decision-dataset-v1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
      for column in ("topic_id", "experiment_id", "case_group_id", "selected_action", "label_source", "review_status", "created_at"):
          op.create_index(f"ix_decision_cases_{column}", "decision_cases", [column])

    tables=set(inspect(op.get_bind()).get_table_names())
    if "decision_model_runs" not in tables:
      op.create_table(
        "decision_model_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="COMPLETED"),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("feature_schema_version", sa.String(40), nullable=False),
        sa.Column("dataset_version", sa.String(40), nullable=False),
        sa.Column("model_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
      for column in ("topic_id", "mode", "status", "dataset_hash", "created_at"):
          op.create_index(f"ix_decision_model_runs_{column}", "decision_model_runs", [column])


def downgrade():
    raise RuntimeError("Decision training and review history is preserved; restore a pre-migration backup to roll back.")
