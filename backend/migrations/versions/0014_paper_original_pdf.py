"""Track locally preserved original paper PDFs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0014_paper_original_pdf"
down_revision = "0013_paper_metadata"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("papers")}
    additions = (
        ("original_storage_key", sa.String(length=500)),
        ("original_sha256", sa.String(length=64)),
        ("original_size_bytes", sa.Integer()),
    )
    for name, column_type in additions:
        if name not in columns:
            op.add_column("papers", sa.Column(name, column_type, nullable=True))


def downgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in inspect(bind).get_columns("papers")}
    for name in ("original_size_bytes", "original_sha256", "original_storage_key"):
        if name in columns:
            op.drop_column("papers", name)
