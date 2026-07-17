"""Add normalized generic section table rows."""

from alembic import op
from sqlalchemy import inspect

from ddr_ai.db.models import SectionTableRow

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "section_table_rows" not in inspect(bind).get_table_names():
        SectionTableRow.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    if "section_table_rows" in inspect(bind).get_table_names():
        SectionTableRow.__table__.drop(bind=bind)

