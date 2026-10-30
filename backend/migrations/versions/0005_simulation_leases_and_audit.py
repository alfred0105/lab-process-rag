"""Add simulation worker leases and append-only source correction audit."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0005_simulation_leases_audit"
down_revision = "0004_simulation_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind=op.get_bind()
    inspector=inspect(bind)
    if "simulation_runs" in inspector.get_table_names():
        present={column["name"] for column in inspector.get_columns("simulation_runs")}
        additions=(
            ("worker_id",sa.String(length=120),True),
            ("lease_expires_at",sa.DateTime(),True),
            ("heartbeat_at",sa.DateTime(),True),
            ("timeout_seconds",sa.Integer(),True),
            ("cancel_requested",sa.Boolean(),False),
            ("attempt",sa.Integer(),False),
            ("max_attempts",sa.Integer(),False),
            ("error_code",sa.String(length=100),False),
        )
        for name,column_type,nullable in additions:
            if name not in present:
                default=sa.text("0") if name=="cancel_requested" else sa.text("1") if name in {"attempt","max_attempts"} else sa.text("''") if name=="error_code" else None
                op.add_column("simulation_runs",sa.Column(name,column_type,nullable=nullable,server_default=default))
        current={index["name"] for index in inspect(bind).get_indexes("simulation_runs")}
        for field in ("worker_id","lease_expires_at"):
            index_name=f"ix_simulation_runs_{field}"
            if index_name not in current:
                op.create_index(index_name,"simulation_runs",[field])
    if "scientific_data_audit_events" not in inspector.get_table_names():
        op.create_table("scientific_data_audit_events",
            sa.Column("id",sa.Integer(),primary_key=True),
            sa.Column("entity_type",sa.String(length=60),nullable=False),
            sa.Column("entity_id",sa.Integer(),nullable=False),
            sa.Column("topic_id",sa.Integer(),nullable=True),
            sa.Column("field_name",sa.String(length=100),nullable=False),
            sa.Column("old_value",sa.JSON(),nullable=False),
            sa.Column("new_value",sa.JSON(),nullable=False),
            sa.Column("reason",sa.Text(),nullable=False),
            sa.Column("created_at",sa.DateTime(),nullable=False),
        )
        op.create_index("ix_scientific_data_audit_events_entity_type","scientific_data_audit_events",["entity_type"])
        op.create_index("ix_scientific_data_audit_events_entity_id","scientific_data_audit_events",["entity_id"])
        op.create_index("ix_scientific_data_audit_events_topic_id","scientific_data_audit_events",["topic_id"])
        op.create_index("ix_scientific_data_audit_events_created_at","scientific_data_audit_events",["created_at"])


def downgrade() -> None:
    raise RuntimeError("Simulation execution and provenance audit history must be preserved; restore a pre-migration backup to roll back.")
