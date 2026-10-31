"""Additive raw/final action provenance for immutable decision snapshots."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0011_decision_snapshot_safety_contract"
down_revision = "0010_decision_feedback_learning"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("decision_snapshots")}
    additions = (
        ("raw_predicted_action", sa.String(40)),
        ("confidence", sa.Float()),
        ("calibration_status", sa.String(50)),
        ("ood_reasons_json", sa.JSON()),
        ("abstention_reason", sa.Text()),
        ("safety_override", sa.Boolean()),
        ("safety_override_reason", sa.Text()),
        ("decision_contract_version", sa.String(50)),
    )
    for name, column_type in additions:
        if name not in columns:
            op.add_column("decision_snapshots", sa.Column(name, column_type, nullable=True))
    if "ix_decision_snapshots_decision_contract_version" not in {
        index["name"] for index in inspect(bind).get_indexes("decision_snapshots")
    }:
        op.create_index(
            "ix_decision_snapshots_decision_contract_version",
            "decision_snapshots",
            ["decision_contract_version"],
        )


def downgrade():
    raise RuntimeError(
        "Snapshot safety provenance is immutable; restore a pre-migration backup to roll back."
    )
