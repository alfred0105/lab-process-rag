"""Add DOI, original abstract, and field-level metadata provenance to papers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0013_paper_metadata"
down_revision = "0012_experiment_campaigns"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("papers")}
    if "doi" not in columns:
        op.add_column("papers", sa.Column("doi", sa.String(length=300), nullable=True))
    if "abstract" not in columns:
        op.add_column("papers", sa.Column("abstract", sa.Text(), nullable=True))
    if "metadata_sources" not in columns:
        op.add_column("papers", sa.Column("metadata_sources", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("papers")}
    for name in ("metadata_sources", "abstract", "doi"):
        if name in columns:
            op.drop_column("papers", name)
