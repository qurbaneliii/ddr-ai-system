from __future__ import annotations

import csv
import json
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image
from pypdf import PdfReader

from ddr_ai.common.hashing import sha256_file
from ddr_ai.document_ai.sections import SECTION_HEADINGS
from ddr_ai.pdf.filename import canonicalize_wellbore, parse_ddr_filename
from ddr_ai.pdf.parser import PERIOD_RE, SENTINEL_RE

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
DOCS = ROOT / "docs"

AUDIT_PERIOD_RE = re.compile(
    r"Wellbore:\s*(?:Wellbore:\s*)?(?P<wellbore>[^\r\n]+)\s+"
    r"Period:\s*(?:Period:\s*)?(?P<start>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*-\s*"
    r"(?P<end>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})",
    re.I,
)


def _pdf_audit(paths: list[Path]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pages = Counter()
    versions = Counter()
    creators = Counter()
    wellbores = Counter()
    dates: set[str] = set()
    sections = Counter()
    records: list[dict[str, Any]] = []
    valid = encrypted = digital = scanned = identity_matches = date_matches = sentinel_count = image_objects = 0
    suspicious: list[str] = []
    for path in paths:
        record: dict[str, Any] = {"path": str(path), "file_name": path.name, "sha256": sha256_file(path),
                                  "bytes": path.stat().st_size, "kind": "ddr_pdf"}
        try:
            reader = PdfReader(path)
            encrypted += int(reader.is_encrypted)
            if reader.is_encrypted:
                raise ValueError("encrypted")
            page_count = len(reader.pages)
            pages[page_count] += 1
            versions[str(getattr(reader, "pdf_header", "unknown"))] += 1
            metadata = reader.metadata or {}
            creators[str(metadata.get("/Creator", "unknown"))] += 1
            a4_portrait = True
            for page in reader.pages:
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                a4_portrait = a4_portrait and width < height and abs(width - 595) < 5 and abs(height - 842) < 5
            all_text = [page.extract_text() or "" for page in reader.pages]
            native_character_count = sum(len(text) for text in all_text)
            route_name = "digital_pdf" if native_character_count >= 80 else "scanned_pdf"
            digital += int(route_name == "digital_pdf")
            scanned += int(route_name == "scanned_pdf")
            for page in reader.pages:
                try:
                    resources = page.get("/Resources", {}).get_object()
                    objects = resources.get("/XObject", {}).get_object()
                    image_objects += sum(
                        item.get_object().get("/Subtype") == "/Image" for item in objects.values()
                    )
                except (AttributeError, KeyError, TypeError):
                    pass
            full_text = "\n".join(all_text)
            first = all_text[0] if all_text else ""
            period = PERIOD_RE.search(first) or AUDIT_PERIOD_RE.search(first)
            filename = parse_ddr_filename(path)
            header_wellbore = canonicalize_wellbore(period.group("wellbore")) if period else None
            period_end = datetime.strptime(period.group("end"), "%Y-%m-%d %H:%M") if period else None
            identity_match = bool(filename and header_wellbore == filename.wellbore)
            date_match = bool(filename and period_end and period_end.date() == filename.report_date)
            identity_matches += int(identity_match)
            date_matches += int(date_match)
            if header_wellbore:
                wellbores[header_wellbore] += 1
            if period_end:
                dates.add(period_end.date().isoformat())
            for heading, section_type in SECTION_HEADINGS.items():
                if re.search(rf"(?m)^{re.escape(heading)}\s*$", full_text, re.I):
                    sections[section_type] += 1
            file_sentinels = len(SENTINEL_RE.findall(full_text))
            sentinel_count += file_sentinels
            if period_end and "Spud Date:" in first:
                spud_match = re.search(r"Spud Date:\s*(\d{4}-\d{2}-\d{2})", first)
                if spud_match and period_end.date() < datetime.strptime(spud_match.group(1), "%Y-%m-%d").date():
                    suspicious.append(path.name)
            record.update({"status": "valid", "page_count": page_count, "pdf_version": str(getattr(reader, "pdf_header", "unknown")),
                           "a4_portrait": a4_portrait, "route": route_name,
                           "filename_identity_match": identity_match, "filename_date_match": date_match,
                           "wellbore": header_wellbore, "period_end": period_end.isoformat() if period_end else None,
                           "sentinel_count": file_sentinels})
            valid += 1
        except Exception as exc:
            record.update({"status": "invalid", "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        records.append(record)
    summary = {
        "discovered": len(paths), "valid": valid, "invalid": len(paths) - valid, "encrypted": encrypted,
        "page_count_total": sum(count * frequency for count, frequency in pages.items()),
        "page_count_distribution": {str(key): value for key, value in sorted(pages.items())},
        "pdf_versions": dict(versions), "creators": dict(creators), "digital": digital, "scanned": scanned,
        "image_object_count": image_objects, "wellbore_count": len(wellbores), "wellbore_report_counts": dict(sorted(wellbores.items())),
        "unique_period_end_dates": len(dates), "filename_identity_matches": identity_matches,
        "filename_date_matches": date_matches, "section_coverage": dict(sorted(sections.items())),
        "sentinel_occurrences": sentinel_count, "suspicious_period_before_spud": suspicious,
    }
    return summary, records


def _image_audit(paths: list[Path], kind: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dimensions = Counter()
    dpi_values = Counter()
    records: list[dict[str, Any]] = []
    for path in paths:
        with Image.open(path) as image:
            dimensions[f"{image.width}x{image.height}"] += 1
            dpi = tuple(round(float(value)) for value in image.info.get("dpi", (0, 0)))
            dpi_values[str(dpi)] += 1
            records.append({"path": str(path), "file_name": path.name, "sha256": sha256_file(path),
                            "bytes": path.stat().st_size, "kind": kind, "status": "valid",
                            "width": image.width, "height": image.height, "mode": image.mode, "dpi": dpi})
    return {"discovered": len(paths), "valid": len(records), "invalid": 0,
            "dimensions": dict(dimensions), "dpi": dict(dpi_values)}, records


def _markdown(audit: dict[str, Any]) -> str:
    pdf = audit["ddr_pdfs"]
    profiles = audit["pressure_profiles"]
    times = audit["pressure_time_plots"]
    lines = [
        "# Data Audit", "", f"Generated: {audit['generated_at']}", "",
        "## Independently verified results", "",
        f"- DDR PDFs: {pdf['discovered']} discovered, {pdf['valid']} valid, {pdf['invalid']} invalid.",
        f"- Pages: {pdf['page_count_total']} total; distribution {pdf['page_count_distribution']}.",
        f"- Native digital route: {pdf['digital']}; scanned/OCR route: {pdf['scanned']}.",
        f"- Filename/header identity matches: {pdf['filename_identity_matches']}/{pdf['valid']}.",
        f"- Filename/period-end date matches: {pdf['filename_date_matches']}/{pdf['valid']}.",
        f"- Wellbores: {pdf['wellbore_count']}; unique period-end dates: {pdf['unique_period_end_dates']}.",
        f"- Embedded PDF image objects: {pdf['image_object_count']}.",
        f"- Missing-value sentinel occurrences in extracted text: {pdf['sentinel_occurrences']}.",
        f"- Suspicious period-before-spud reports: {pdf['suspicious_period_before_spud']}.",
        f"- Pressure profiles: {profiles['discovered']} valid images; dimensions {profiles['dimensions']}.",
        f"- Pressure-time plots: {times['discovered']} valid images; dimensions {times['dimensions']}.",
        "", "## Page-count distribution", "",
    ]
    lines.extend(f"- {count} page(s): {frequency}" for count, frequency in pdf["page_count_distribution"].items())
    lines.extend(["", "## Reports per wellbore", ""])
    lines.extend(f"- {name}: {count}" for name, count in pdf["wellbore_report_counts"].items())
    lines.extend(["", "## Section coverage", ""])
    lines.extend(f"- {name}: {count}" for name, count in pdf["section_coverage"].items())
    lines.extend([
        "", "## Expected versus verified", "",
        "The supplied preliminary figures were treated as hypotheses. The values above were recomputed from every supplied file.",
        "Plot digitization counts, band classifications, calibration evidence, and processing failures are added by `scripts/process_all.py` and `scripts/evaluate_pipeline.py`.",
        "", "## Limitations", "",
        "- Report creation timestamps are metadata only and are not used as operational dates.",
        "- Missing sections are treated as optional, not as parser failures.",
        "- SoR remains undefined in the supplied material.",
        "- Pressure-time y-axis units and cross-namespace well mappings remain unresolved.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    started = time.perf_counter()
    PROCESSED.mkdir(parents=True, exist_ok=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    pdf_paths = sorted((RAW / "ddr_pdfs").rglob("*.pdf"))
    profile_paths = sorted((RAW / "pressure_profiles").rglob("*.png"))
    time_paths = sorted((RAW / "pressure_time_plots").rglob("*.png"))
    pdf_summary, pdf_records = _pdf_audit(pdf_paths)
    profile_summary, profile_records = _image_audit(profile_paths, "pressure_profile")
    time_summary, time_records = _image_audit(time_paths, "pressure_time")
    audit = {
        "generated_at": datetime.now(UTC).isoformat(), "audit_version": "0.1.0",
        "ddr_pdfs": pdf_summary, "pressure_profiles": profile_summary,
        "pressure_time_plots": time_summary, "duration_seconds": round(time.perf_counter() - started, 3),
    }
    (PROCESSED / "audit_summary.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    records = pdf_records + profile_records + time_records
    fieldnames = sorted({key for record in records for key in record})
    with (PROCESSED / "input_inventory.csv").open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    (DOCS / "DATA_AUDIT.md").write_text(_markdown(audit), encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
