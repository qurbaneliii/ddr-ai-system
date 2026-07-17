"""Add row-level equipment failures and operation correlations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from ddr_ai.db.models import EquipmentFailure, FailureOperationMatch

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


OPERATION_COLUMNS = {
    "start_datetime": sa.Column("start_datetime", sa.DateTime(), nullable=True),
    "end_datetime": sa.Column("end_datetime", sa.DateTime(), nullable=True),
    "temporal_status": sa.Column(
        "temporal_status", sa.String(length=64), nullable=False,
        server_default=sa.text("'unprocessed'"),
    ),
    "temporal_ambiguity": sa.Column("temporal_ambiguity", sa.Text(), nullable=True),
    "raw_values_json": sa.Column(
        "raw_values_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"),
    ),
    "normalized_values_json": sa.Column(
        "normalized_values_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'"),
    ),
    "validation_status": sa.Column(
        "validation_status", sa.String(length=32), nullable=False,
        server_default=sa.text("'unreviewed'"),
    ),
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    operation_columns = {item["name"] for item in inspector.get_columns("operations")}
    missing = [column for name, column in OPERATION_COLUMNS.items() if name not in operation_columns]
    if missing:
        with op.batch_alter_table("operations") as batch:
            for column in missing:
                batch.add_column(column)

    tables = set(inspect(bind).get_table_names())
    if "equipment_failures" not in tables:
        EquipmentFailure.__table__.create(bind=bind)
    if "failure_operation_matches" not in tables:
        FailureOperationMatch.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "failure_operation_matches" in tables:
        FailureOperationMatch.__table__.drop(bind=bind)
    if "equipment_failures" in tables:
        EquipmentFailure.__table__.drop(bind=bind)
    operation_columns = {item["name"] for item in inspect(bind).get_columns("operations")}
    existing = [name for name in OPERATION_COLUMNS if name in operation_columns]
    if existing:
        with op.batch_alter_table("operations") as batch:
            for name in existing:
                batch.drop_column(name)
