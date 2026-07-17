from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path


def test_original_148_report_failure_citation_list_remains_reproducible() -> None:
    project_root = Path(__file__).resolve().parents[2]
    database = project_root / "data" / "processed" / "ddr_ai.db"
    raw_root = project_root / "data" / "raw" / "ddr_pdfs"
    if not raw_root.exists():
        return
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT d.file_name, r.wellbore, r.filename_date, s.page_number
            FROM report_sections s
            JOIN reports r ON r.id = s.report_id
            JOIN source_documents d ON d.id = r.source_document_id
            WHERE s.section_type = 'equipment_failure_information'
            ORDER BY d.file_name
            """
        ).fetchall()
    source_names = {path.name for path in raw_root.rglob("*.pdf")}
    assert len(rows) == 148
    assert len({row[0] for row in rows}) == 148
    assert len({row[1] for row in rows}) == 9
    assert Counter(row[3] for row in rows) == Counter({1: 133, 2: 15})
    assert all(row[0] in source_names for row in rows)
    assert all(row[1] and row[2] for row in rows)
