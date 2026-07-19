"""Track idempotent production seed imports."""

from alembic import op
from sqlalchemy import inspect

from ddr_ai.db.models import SeedVersion

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "seed_versions" not in inspect(bind).get_table_names():
        SeedVersion.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    if "seed_versions" in inspect(bind).get_table_names():
        SeedVersion.__table__.drop(bind=bind)
