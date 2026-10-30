"""Add database-enforced simulation execution idempotency.

Revision ID: 0004_simulation_idempotency
Revises: 0003_science_compat
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0004_simulation_idempotency"
down_revision = "0003_science_compat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector=inspect(op.get_bind())
    if "simulation_runs" not in inspector.get_table_names(): return
    columns={item["name"] for item in inspector.get_columns("simulation_runs")}
    if "idempotency_key" not in columns:
        op.add_column("simulation_runs",sa.Column("idempotency_key",sa.String(length=64),nullable=True))
    indexes={item["name"] for item in inspector.get_indexes("simulation_runs")}
    if "uq_simulation_run_idempotency_key" not in indexes:
        op.create_index("uq_simulation_run_idempotency_key","simulation_runs",["idempotency_key"],unique=True)


def downgrade() -> None:
    raise RuntimeError("Simulation idempotency keys are execution history; restore a pre-migration backup to roll back.")
