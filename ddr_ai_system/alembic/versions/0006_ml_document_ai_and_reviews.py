"""Add ML provenance, anomaly review history, and model-run metadata."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from ddr_ai.db.models import AnomalyReview, ModelRun

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _column_names(bind: object, table: str) -> set[str]:
    return {str(item["name"]) for item in inspect(bind).get_columns(table)}


def _index_names(bind: object, table: str) -> set[str]:
    return {str(item["name"]) for item in inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    operation_columns = _column_names(bind, "operations")
    with op.batch_alter_table("operations") as batch:
        if "classification_method" not in operation_columns:
            batch.add_column(
                sa.Column(
                    "classification_method",
                    sa.String(length=32),
                    nullable=False,
                    server_default=sa.text("'source_rule'"),
                )
            )
        if "classification_confidence" not in operation_columns:
            batch.add_column(
                sa.Column(
                    "classification_confidence",
                    sa.Float(),
                    nullable=True,
                    server_default=sa.text("1.0"),
                )
            )
        if "classification_model_version" not in operation_columns:
            batch.add_column(
                sa.Column("classification_model_version", sa.String(length=128), nullable=True)
            )
        if "classification_evidence_json" not in operation_columns:
            batch.add_column(
                sa.Column(
                    "classification_evidence_json",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'{}'"),
                )
            )
    operation_indexes = _index_names(bind, "operations")
    if "ix_operations_classification_method" not in operation_indexes:
        op.create_index(
            "ix_operations_classification_method",
            "operations",
            ["classification_method"],
        )

    anomaly_columns = _column_names(bind, "anomalies")
    with op.batch_alter_table("anomalies") as batch:
        if "detector_type" not in anomaly_columns:
            batch.add_column(
                sa.Column(
                    "detector_type",
                    sa.String(length=32),
                    nullable=False,
                    server_default=sa.text("'rule'"),
                )
            )
        if "model_version" not in anomaly_columns:
            batch.add_column(sa.Column("model_version", sa.String(length=128), nullable=True))
        if "candidate_key" not in anomaly_columns:
            batch.add_column(sa.Column("candidate_key", sa.String(length=64), nullable=True))
    op.execute(
        sa.text(
            "UPDATE anomalies SET detector_type = 'data_quality' "
            "WHERE category = 'source_data_quality'"
        )
    )
    anomaly_indexes = _index_names(bind, "anomalies")
    if "ix_anomalies_detector_model" not in anomaly_indexes:
        op.create_index(
            "ix_anomalies_detector_model", "anomalies", ["detector_type", "model_version"]
        )
    if "uq_anomalies_candidate_key" not in anomaly_indexes:
        op.create_index(
            "uq_anomalies_candidate_key", "anomalies", ["candidate_key"], unique=True
        )

    tables = set(inspect(bind).get_table_names())
    if "anomaly_reviews" not in tables:
        AnomalyReview.__table__.create(bind=bind)
    if "model_runs" not in tables:
        ModelRun.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "model_runs" in tables:
        ModelRun.__table__.drop(bind=bind)
    if "anomaly_reviews" in tables:
        AnomalyReview.__table__.drop(bind=bind)

    anomaly_columns = _column_names(bind, "anomalies")
    with op.batch_alter_table("anomalies") as batch:
        for name in ("candidate_key", "model_version", "detector_type"):
            if name in anomaly_columns:
                batch.drop_column(name)

    operation_columns = _column_names(bind, "operations")
    with op.batch_alter_table("operations") as batch:
        for name in (
            "classification_evidence_json",
            "classification_model_version",
            "classification_confidence",
            "classification_method",
        ):
            if name in operation_columns:
                batch.drop_column(name)
