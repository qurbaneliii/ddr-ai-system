"""Add unified retrieval chunks and bounded upload asset storage."""

from alembic import op
from sqlalchemy import inspect

from ddr_ai.db.models import RetrievalChunk, StoredAsset

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "retrieval_chunks" not in tables:
        RetrievalChunk.__table__.create(bind=bind)
    if "stored_assets" not in tables:
        StoredAsset.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "stored_assets" in tables:
        StoredAsset.__table__.drop(bind=bind)
    if "retrieval_chunks" in tables:
        RetrievalChunk.__table__.drop(bind=bind)
