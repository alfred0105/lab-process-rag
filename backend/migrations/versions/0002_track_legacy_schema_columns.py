"""Version previously implicit nullable legacy-schema upgrades.

Revision ID: 0002_legacy_columns
Revises: 0001_science_review
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "0002_legacy_columns"
down_revision = "0001_science_review"
branch_labels = None
depends_on = None


def _add_if_missing(table: str, column: sa.Column) -> None:
    if table not in inspect(op.get_bind()).get_table_names():
        return
    present={item["name"] for item in inspect(op.get_bind()).get_columns(table)}
    if column.name not in present:
        op.add_column(table,column)


def upgrade() -> None:
    # SQLite cannot add a column and its FK constraint with ALTER TABLE. The
    # legacy nullable columns are backfilled by the application; new tables
    # receive full FK constraints from metadata/Alembic.
    _add_if_missing("experiments",sa.Column("topic_id",sa.Integer(),nullable=True))
    _add_if_missing("experiments",sa.Column("method_version_id",sa.Integer(),nullable=True))
    _add_if_missing("experiments",sa.Column("method_run_number",sa.Integer(),nullable=True))
    _add_if_missing("experiments",sa.Column("duration_minutes",sa.Integer(),nullable=True))
    _add_if_missing("experiment_materials",sa.Column("source_material_id",sa.Integer(),nullable=True))
    _add_if_missing("papers",sa.Column("topic_id",sa.Integer(),nullable=True))
    _add_if_missing("material_analysis_runs",sa.Column("topic_id",sa.Integer(),nullable=True))
    _add_if_missing("material_analysis_runs",sa.Column("analysis_status",sa.String(30),server_default="completed",nullable=False))
    _add_if_missing("material_analysis_runs",sa.Column("result_key",sa.String(200),nullable=True))
    _add_if_missing("material_analysis_runs",sa.Column("process_step_id",sa.Integer(),nullable=True))
    _add_if_missing("method_versions",sa.Column("version_label",sa.String(40),nullable=True))
    _add_if_missing("integrated_analysis_sessions",sa.Column("simulation_run_ids",sa.JSON(),server_default="[]",nullable=False))
    if "method_versions" in inspect(op.get_bind()).get_table_names():
        op.execute(sa.text("UPDATE method_versions SET version_label = CAST(version_number AS TEXT) WHERE version_label IS NULL OR version_label = ''"))


def downgrade() -> None:
    # These columns predate Alembic tracking for existing installations and may
    # contain user data. Dropping them cannot be done safely in an automatic downgrade.
    raise RuntimeError("This compatibility revision only supports upgrade; restore the pre-upgrade SQLite backup to roll back.")
