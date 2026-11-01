"""Add persistent approval-gated experiment optimization campaigns."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0012_experiment_campaigns"
down_revision = "0011_decision_snapshot_safety_contract"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "experiment_campaigns" not in tables:
        op.create_table(
        "experiment_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id", ondelete="SET NULL")),
        sa.Column("method_version_id", sa.Integer(), sa.ForeignKey("method_versions.id", ondelete="SET NULL")),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("target_property", sa.String(200), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("variables_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("fixed_conditions_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("max_iterations", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("iteration_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(40), nullable=False, server_default="CREATED"),
        sa.Column("selected_action", sa.String(40), nullable=False, server_default=""),
        sa.Column("decision_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("current_workflow_id", sa.Integer(), sa.ForeignKey("workflow_runs.id", ondelete="SET NULL")),
        sa.Column("current_model_run_id", sa.Integer(), sa.ForeignKey("optimization_model_runs.id", ondelete="SET NULL")),
        sa.Column("current_recommendation_id", sa.Integer(), sa.ForeignKey("optimization_recommendation_runs.id", ondelete="SET NULL")),
        sa.Column("candidate_json", sa.JSON()),
        sa.Column("review_status", sa.String(40), nullable=False, server_default="NOT_REQUESTED"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    for column in ("topic_id", "experiment_id", "method_version_id", "mode", "state", "current_workflow_id", "created_at", "updated_at"):
        if f"ix_experiment_campaigns_{column}" not in {i["name"] for i in inspect(bind).get_indexes("experiment_campaigns")}:
            op.create_index(f"ix_experiment_campaigns_{column}", "experiment_campaigns", [column])

    if "campaign_events" not in set(inspect(bind).get_table_names()):
        op.create_table(
        "campaign_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("experiment_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("campaign_id", "idempotency_key", name="uq_campaign_event_idempotency"),
        )
    for name, columns in (("ix_campaign_events_campaign_id", ["campaign_id"]), ("ix_campaign_events_event_type", ["event_type"]), ("ix_campaign_events_created_at", ["created_at"])):
        if name not in {i["name"] for i in inspect(bind).get_indexes("campaign_events")}:
            op.create_index(name, "campaign_events", columns)

    if "campaign_observations" not in set(inspect(bind).get_table_names()):
        op.create_table(
        "campaign_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("experiment_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conditions_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("target_unit", sa.String(100), nullable=False, server_default="dimensionless"),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("review_status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("reviewer", sa.String(200)),
        sa.Column("review_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.UniqueConstraint("campaign_id", "idempotency_key", name="uq_campaign_observation_idempotency"),
        )
    for name, columns in (("ix_campaign_observations_campaign_id", ["campaign_id"]), ("ix_campaign_observations_source_type", ["source_type"]), ("ix_campaign_observations_review_status", ["review_status"]), ("ix_campaign_observations_created_at", ["created_at"])):
        if name not in {i["name"] for i in inspect(bind).get_indexes("campaign_observations")}:
            op.create_index(name, "campaign_observations", columns)


def downgrade():
    op.drop_table("campaign_observations")
    op.drop_table("campaign_events")
    op.drop_table("experiment_campaigns")
