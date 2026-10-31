"""Add immutable decision snapshots, feedback, datasets and model governance."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0010_decision_feedback_learning"
down_revision = "0009_learned_decision_head"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    case_columns={c["name"] for c in inspector.get_columns("decision_cases")}
    if "snapshot_id" not in case_columns:
        op.add_column("decision_cases", sa.Column("snapshot_id", sa.String(36), nullable=True))
    if "feedback_id" not in case_columns:
        op.add_column("decision_cases", sa.Column("feedback_id", sa.Integer(), nullable=True))
    tables = set(inspect(bind).get_table_names())
    if "decision_snapshots" not in tables:
        op.create_table("decision_snapshots",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False),
            sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True),
            sa.Column("method_version_id", sa.Integer(), sa.ForeignKey("method_versions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("model_run_id", sa.Integer(), sa.ForeignKey("decision_model_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("decision_timestamp", sa.DateTime(), nullable=False),
            sa.Column("snapshot_timestamp", sa.DateTime(), nullable=False),
            sa.Column("data_availability_timestamp", sa.DateTime(), nullable=False),
            sa.Column("state_json", sa.JSON(), nullable=False),
            sa.Column("feature_vector_json", sa.JSON(), nullable=False),
            sa.Column("suggested_action", sa.String(40), nullable=False),
            sa.Column("probabilities_json", sa.JSON(), nullable=False),
            sa.Column("ood_status", sa.String(30), nullable=False, server_default="UNKNOWN"),
            sa.Column("feature_schema_version", sa.String(40), nullable=False),
            sa.Column("source_observation_ids_json", sa.JSON(), nullable=False),
            sa.Column("source_analysis_ids_json", sa.JSON(), nullable=False),
            sa.Column("source_simulation_ids_json", sa.JSON(), nullable=False),
            sa.Column("source_optimization_model_ids_json", sa.JSON(), nullable=False),
            sa.Column("provenance_json", sa.JSON(), nullable=False),
            sa.Column("snapshot_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False))
        for col in ("topic_id", "experiment_id", "method_version_id", "mode", "decision_timestamp", "snapshot_hash", "created_at"):
            op.create_index(f"ix_decision_snapshots_{col}", "decision_snapshots", [col])
    if bind.dialect.name != "sqlite" and "fk_decision_cases_snapshot_id" not in {fk["name"] for fk in inspect(bind).get_foreign_keys("decision_cases")}:
        op.create_foreign_key("fk_decision_cases_snapshot_id", "decision_cases", "decision_snapshots", ["snapshot_id"], ["id"], ondelete="SET NULL")
    if bind.dialect.name == "sqlite" and "ix_decision_cases_snapshot_id" not in {i["name"] for i in inspect(bind).get_indexes("decision_cases")}:
        op.create_index("ix_decision_cases_snapshot_id", "decision_cases", ["snapshot_id"])
    if bind.dialect.name == "sqlite" and "ix_decision_cases_feedback_id" not in {i["name"] for i in inspect(bind).get_indexes("decision_cases")}:
        op.create_index("ix_decision_cases_feedback_id", "decision_cases", ["feedback_id"])

    tables = set(inspect(bind).get_table_names())
    if "decision_feedback" not in tables:
        op.create_table("decision_feedback",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False),
            sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("decision_snapshots.id", ondelete="CASCADE"), nullable=False),
            sa.Column("model_run_id", sa.Integer(), sa.ForeignKey("decision_model_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("feedback_type", sa.String(20), nullable=False),
            sa.Column("suggested_action", sa.String(40), nullable=False),
            sa.Column("final_reviewed_action", sa.String(40), nullable=True),
            sa.Column("reviewer", sa.String(200), nullable=False),
            sa.Column("reviewer_identity_status", sa.String(40), nullable=False, server_default="SELF_REPORTED_NOT_AUTHENTICATED"),
            sa.Column("review_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("review_status", sa.String(30), nullable=False, server_default="RESEARCHER_REVIEWED"),
            sa.Column("label_source", sa.String(50), nullable=False),
            sa.Column("model_version", sa.String(80), nullable=False),
            sa.Column("original_probabilities_json", sa.JSON(), nullable=False),
            sa.Column("ood_status", sa.String(30), nullable=False, server_default="UNKNOWN"),
            sa.Column("dataset_version", sa.String(80), nullable=True),
            sa.Column("supersedes_feedback_id", sa.Integer(), sa.ForeignKey("decision_feedback.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("snapshot_id", "model_run_id", "revision", name="uq_decision_feedback_revision"))
        for col in ("topic_id", "snapshot_id", "model_run_id", "feedback_type", "review_status", "created_at"):
            op.create_index(f"ix_decision_feedback_{col}", "decision_feedback", [col])

    tables = set(inspect(bind).get_table_names())
    if "decision_dataset_versions" not in tables:
        op.create_table("decision_dataset_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("dataset_version", sa.String(80), nullable=False),
            sa.Column("dataset_hash", sa.String(64), nullable=False),
            sa.Column("feature_schema_version", sa.String(40), nullable=False),
            sa.Column("label_mapping_version", sa.String(40), nullable=False, server_default="decision-actions-v1"),
            sa.Column("case_count", sa.Integer(), nullable=False),
            sa.Column("group_count", sa.Integer(), nullable=False),
            sa.Column("action_distribution_json", sa.JSON(), nullable=False),
            sa.Column("missingness_json", sa.JSON(), nullable=False),
            sa.Column("source_summary_json", sa.JSON(), nullable=False),
            sa.Column("manifest_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("topic_id", "mode", "dataset_version", name="uq_decision_dataset_topic_mode_version"))
        for col in ("topic_id", "mode", "dataset_hash", "created_at"):
            op.create_index(f"ix_decision_dataset_versions_{col}", "decision_dataset_versions", [col])

    tables = set(inspect(bind).get_table_names())
    if "decision_model_comparisons" not in tables:
        op.create_table("decision_model_comparisons",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("champion_model_id", sa.Integer(), sa.ForeignKey("decision_model_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("challenger_model_id", sa.Integer(), sa.ForeignKey("decision_model_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("evaluation_hash", sa.String(64), nullable=False),
            sa.Column("comparison_status", sa.String(30), nullable=False),
            sa.Column("report_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False))
        for col in ("topic_id", "mode", "champion_model_id", "challenger_model_id", "evaluation_hash", "comparison_status", "created_at"):
            op.create_index(f"ix_decision_model_comparisons_{col}", "decision_model_comparisons", [col])

    tables = set(inspect(bind).get_table_names())
    if "decision_active_shadow_models" not in tables:
        op.create_table("decision_active_shadow_models",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("model_run_id", sa.Integer(), sa.ForeignKey("decision_model_runs.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("topic_id", "mode", name="uq_decision_active_shadow_topic_mode"))
        for col in ("topic_id", "mode", "model_run_id", "updated_at"):
            op.create_index(f"ix_decision_active_shadow_models_{col}", "decision_active_shadow_models", [col])

    tables = set(inspect(bind).get_table_names())
    if "decision_model_activation_events" not in tables:
        op.create_table("decision_model_activation_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("research_topics.id", ondelete="CASCADE"), nullable=False),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("previous_model_id", sa.Integer(), sa.ForeignKey("decision_model_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("new_model_id", sa.Integer(), sa.ForeignKey("decision_model_runs.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("comparison_id", sa.Integer(), sa.ForeignKey("decision_model_comparisons.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reviewer", sa.String(200), nullable=False),
            sa.Column("reviewer_identity_status", sa.String(40), nullable=False, server_default="SELF_REPORTED_NOT_AUTHENTICATED"),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False))
        for col in ("topic_id", "mode", "new_model_id", "created_at"):
            op.create_index(f"ix_decision_model_activation_events_{col}", "decision_model_activation_events", [col])
    if bind.dialect.name != "sqlite":
        case_fks={fk["name"] for fk in inspect(bind).get_foreign_keys("decision_cases")}
        if "fk_decision_cases_snapshot_id" not in case_fks:
            op.create_foreign_key("fk_decision_cases_snapshot_id", "decision_cases", "decision_snapshots", ["snapshot_id"], ["id"], ondelete="SET NULL")
        if "fk_decision_cases_feedback_id" not in case_fks:
            op.create_foreign_key("fk_decision_cases_feedback_id", "decision_cases", "decision_feedback", ["feedback_id"], ["id"], ondelete="SET NULL")
    else:
        case_fks={fk["name"] for fk in inspect(bind).get_foreign_keys("decision_cases")}
        missing=[]
        if "fk_decision_cases_snapshot_id" not in case_fks: missing.append(("fk_decision_cases_snapshot_id","decision_snapshots","snapshot_id","id"))
        if "fk_decision_cases_feedback_id" not in case_fks: missing.append(("fk_decision_cases_feedback_id","decision_feedback","feedback_id","id"))
        if missing:
            with op.batch_alter_table("decision_cases", recreate="always") as batch:
                for name,referent,local_column,remote_column in missing:
                    batch.create_foreign_key(name,referent,[local_column],[remote_column],ondelete="SET NULL")


def downgrade():
    raise RuntimeError("Decision snapshots, feedback and model governance history are immutable; restore a pre-migration backup to roll back.")
