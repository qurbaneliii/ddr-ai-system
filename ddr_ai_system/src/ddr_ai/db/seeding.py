from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

from sqlalchemy import Table, func, select, text

from ddr_ai.db.bootstrap import sqlite_path, validate_sqlite
from ddr_ai.db.models import Base, SeedVersion, SourceDocument
from ddr_ai.db.session import dispose_engine, get_engine, upgrade_schema


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def seed_database(
    source_url: str,
    target_url: str,
    *,
    seed_version: str,
) -> dict[str, int | str]:
    """Copy the validated demo dataset once into an empty production database."""

    source_path = sqlite_path(source_url)
    if source_path is None:
        raise ValueError("The seed source must be SQLite.")
    validate_sqlite(source_path)
    if source_url == target_url:
        raise ValueError("Seed source and target must be different databases.")
    upgrade_schema(target_url)
    source_engine = get_engine(source_url)
    target_engine = get_engine(target_url)
    counts: dict[str, int | str] = {"seed_version": seed_version}
    with target_engine.begin() as target:
        existing = target.execute(
            select(SeedVersion.version).where(SeedVersion.version == seed_version)
        ).scalar_one_or_none()
        if existing:
            return {"seed_version": seed_version, "status": "already_applied"}
        current_documents = target.execute(select(func.count(SourceDocument.id))).scalar_one()
        if current_documents:
            raise RuntimeError(
                "Production seeding refused because the target already contains documents."
            )
        with source_engine.connect() as source:
            for raw_table in Base.metadata.sorted_tables:
                table = cast(Table, raw_table)
                if table.name == "seed_versions":
                    continue
                rows = source.execute(select(table)).mappings()
                inserted = 0
                batch: list[dict[str, object]] = []
                for row in rows:
                    batch.append(dict(row))
                    if len(batch) == 1000:
                        target.execute(table.insert(), batch)
                        inserted += len(batch)
                        batch.clear()
                if batch:
                    target.execute(table.insert(), batch)
                    inserted += len(batch)
                counts[table.name] = inserted
        seed_table = cast(Table, SeedVersion.__table__)
        target.execute(
            seed_table.insert(),
            {
                "version": seed_version,
                "source_sha256": _sha256(source_path),
            },
        )
        if target.dialect.name == "postgresql":
            for raw_table in Base.metadata.sorted_tables:
                table = cast(Table, raw_table)
                if "id" in table.c:
                    target.execute(
                        text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                            f"COALESCE((SELECT MAX(id) FROM {table.name}), 1), "
                            f"(SELECT MAX(id) IS NOT NULL FROM {table.name}))"
                        )
                    )
    dispose_engine(target_url)
    counts["status"] = "applied"
    return counts
