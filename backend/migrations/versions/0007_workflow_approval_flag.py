"""Add the persisted approval bit to durable workflow nodes."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision="0007_workflow_approval_flag"
down_revision="0006_durable_workflows"
branch_labels=None
depends_on=None


def upgrade():
    bind=op.get_bind()
    if "workflow_nodes" in inspect(bind).get_table_names():
        columns={item["name"] for item in inspect(bind).get_columns("workflow_nodes")}
        if "approval_confirmed" not in columns:
            op.add_column("workflow_nodes",sa.Column("approval_confirmed",sa.Boolean(),nullable=False,server_default=sa.text("0")))


def downgrade():
    # Keep an additive workflow schema for existing execution history.
    raise RuntimeError("Workflow approval history is append-only; restore a pre-migration backup to roll back.")
