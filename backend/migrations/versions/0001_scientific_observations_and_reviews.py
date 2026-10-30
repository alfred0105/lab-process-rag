"""Add normalized scientific observations and measurement review history.

Revision ID: 0001_science_review
Revises:
Create Date: 2026-10-30
"""
from alembic import op

from app.db.models import MeasurementReviewEvent, ScientificObservation

revision = "0001_science_review"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    ScientificObservation.__table__.create(bind=bind, checkfirst=True)
    MeasurementReviewEvent.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    observations=bind.exec_driver_sql("SELECT COUNT(*) FROM scientific_observations").scalar_one()
    reviews=bind.exec_driver_sql("SELECT COUNT(*) FROM measurement_review_events").scalar_one()
    if observations or reviews:
        raise RuntimeError("Refusing to drop scientific data. Export or back up both extension tables first.")
    MeasurementReviewEvent.__table__.drop(bind=bind, checkfirst=True)
    ScientificObservation.__table__.drop(bind=bind, checkfirst=True)
