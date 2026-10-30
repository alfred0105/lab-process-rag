"""Add durable DAG workflow nodes and fencing generations."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0006_durable_workflows"
down_revision = "0005_simulation_leases_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind=op.get_bind()
    inspector=inspect(bind)
    if "simulation_runs" in inspector.get_table_names():
        columns={item["name"] for item in inspect(bind).get_columns("simulation_runs")}
        if "lease_generation" not in columns:
            op.add_column("simulation_runs",sa.Column("lease_generation",sa.Integer(),nullable=False,server_default="0"))
    tables=set(inspect(bind).get_table_names())
    if "workflow_runs" not in tables:
        op.create_table("workflow_runs",
            sa.Column("id",sa.Integer(),primary_key=True),
            sa.Column("topic_id",sa.Integer(),sa.ForeignKey("research_topics.id",ondelete="CASCADE"),nullable=False),
            sa.Column("experiment_id",sa.Integer(),sa.ForeignKey("experiments.id",ondelete="CASCADE"),nullable=False),
            sa.Column("goal",sa.Text(),nullable=False),
            sa.Column("status",sa.String(30),nullable=False,server_default="QUEUED"),
            sa.Column("graph_json",sa.JSON(),nullable=False,server_default="{}"),
            sa.Column("result_json",sa.JSON(),nullable=True),
            sa.Column("error_text",sa.Text(),nullable=False,server_default=""),
            sa.Column("cancel_requested",sa.Boolean(),nullable=False,server_default=sa.text("0")),
            sa.Column("created_at",sa.DateTime(),nullable=False),
            sa.Column("started_at",sa.DateTime(),nullable=True),
            sa.Column("finished_at",sa.DateTime(),nullable=True),
        )
    tables=set(inspect(bind).get_table_names())
    if "workflow_nodes" not in tables:
        op.create_table("workflow_nodes",
            sa.Column("id",sa.Integer(),primary_key=True),
            sa.Column("workflow_id",sa.Integer(),sa.ForeignKey("workflow_runs.id",ondelete="CASCADE"),nullable=False),
            sa.Column("node_key",sa.String(100),nullable=False),
            sa.Column("tool_id",sa.String(120),nullable=False),
            sa.Column("dependency_keys",sa.JSON(),nullable=False,server_default="[]"),
            sa.Column("input_json",sa.JSON(),nullable=False,server_default="{}"),
            sa.Column("output_json",sa.JSON(),nullable=True),
            sa.Column("result_type",sa.String(40),nullable=False,server_default=""),
            sa.Column("result_id",sa.Integer(),nullable=True),
            sa.Column("approval_confirmed",sa.Boolean(),nullable=False,server_default=sa.text("0")),
            sa.Column("status",sa.String(30),nullable=False,server_default="QUEUED"),
            sa.Column("worker_id",sa.String(120),nullable=True),
            sa.Column("lease_expires_at",sa.DateTime(),nullable=True),
            sa.Column("heartbeat_at",sa.DateTime(),nullable=True),
            sa.Column("lease_generation",sa.Integer(),nullable=False,server_default="0"),
            sa.Column("timeout_seconds",sa.Integer(),nullable=False,server_default="300"),
            sa.Column("cancel_requested",sa.Boolean(),nullable=False,server_default=sa.text("0")),
            sa.Column("attempt",sa.Integer(),nullable=False,server_default="0"),
            sa.Column("max_attempts",sa.Integer(),nullable=False,server_default="2"),
            sa.Column("error_code",sa.String(100),nullable=False,server_default=""),
            sa.Column("error_text",sa.Text(),nullable=False,server_default=""),
            sa.Column("created_at",sa.DateTime(),nullable=False),
            sa.Column("started_at",sa.DateTime(),nullable=True),
            sa.Column("finished_at",sa.DateTime(),nullable=True),
            sa.UniqueConstraint("workflow_id","node_key",name="uq_workflow_node_key"),
        )
    for table,fields in (("workflow_runs",("topic_id","experiment_id","status","created_at")),
                         ("workflow_nodes",("workflow_id","status","worker_id","lease_expires_at","created_at"))):
        indexes={index["name"] for index in inspect(bind).get_indexes(table)}
        for field in fields:
            name=f"ix_{table}_{field}"
            if name not in indexes:
                op.create_index(name,table,[field])


def downgrade() -> None:
    raise RuntimeError("Workflow execution history must be preserved; restore a pre-migration backup to roll back.")
