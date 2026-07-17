from __future__ import annotations

import re

SECTION_HEADINGS = {
    "Summary of activities (24 Hours)": "summary_activities",
    "Summary of planned activities (24 Hours)": "summary_planned_activities",
    "Operations": "operations",
    "Drilling Fluid": "drilling_fluid",
    "Pore Pressure": "pore_pressure",
    "Survey Station": "survey_station",
    "Lithology Information": "lithology_information",
    "Equipment Failure Information": "equipment_failure_information",
    "Gas Reading Information": "gas_reading_information",
    "Stratigraphic Information": "stratigraphic_information",
    "Bit Record": "bit_record",
    "Log Information": "log_information",
    "Casing Liner Tubing": "casing_liner_tubing",
    "Core Information": "core_information",
    "Perforation Information": "perforation_information",
    "Welltest Information": "welltest_information",
}


def normalized_heading(line: str) -> tuple[str, str] | None:
    candidate = " ".join(line.split())
    for heading, section_type in SECTION_HEADINGS.items():
        if candidate.casefold() == heading.casefold():
            return heading, section_type
    return None


def split_page_sections(text: str, page_number: int) -> list[dict[str, object]]:
    lines = text.splitlines()
    starts: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        match = normalized_heading(line)
        if match:
            starts.append((index, match[0], match[1]))
    sections: list[dict[str, object]] = []
    for position, (start, heading, section_type) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body = "\n".join(lines[start + 1 : end]).strip()
        sections.append({
            "section_type": section_type,
            "heading_raw": heading,
            "page_number": page_number,
            "text": body,
        })
    return sections


def extract_summary(full_text: str, heading: str) -> str | None:
    headings = "|".join(re.escape(value) for value in SECTION_HEADINGS)
    pattern = re.compile(
        rf"{re.escape(heading)}\s*\n(?P<body>.*?)(?=\n(?:{headings})\s*(?:\n|$)|\Z)",
        re.I | re.S,
    )
    match = pattern.search(full_text)
    return match.group("body").strip() if match else None

