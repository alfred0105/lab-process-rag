"""Reconcile extension tables created before Alembic tracking.

Revision ID: 0003_science_compat
Revises: 0002_legacy_columns
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0003_science_compat"
down_revision = "0002_legacy_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "scientific_observations" in tables and "topic_id" not in {c["name"] for c in inspector.get_columns("scientific_observations")}:
        op.add_column("scientific_observations", sa.Column("topic_id", sa.Integer(), nullable=True))

    if "measurement_review_events" not in tables:
        return
    event_columns = {c["name"]: c for c in inspector.get_columns("measurement_review_events")}
    if "observation_id" not in event_columns:
        # Rebuild SQLite's legacy table so observations and analysis runs can
        # both have immutable review events. The batch operation copies rows.
        with op.batch_alter_table("measurement_review_events", recreate="always") as batch:
            if "analysis_run_id" in event_columns and not event_columns["analysis_run_id"]["nullable"]:
                batch.alter_column("analysis_run_id", existing_type=sa.Integer(), nullable=True)
            batch.add_column(sa.Column("observation_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_review_event_observation", "scientific_observations", ["observation_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_check_constraint(
                "ck_review_exactly_one_target",
                "(analysis_run_id IS NOT NULL) != (observation_id IS NOT NULL)",
            )


def downgrade() -> None:
    raise RuntimeError("This compatibility revision preserves legacy review rows; restore the pre-upgrade SQLite backup to roll back.")
