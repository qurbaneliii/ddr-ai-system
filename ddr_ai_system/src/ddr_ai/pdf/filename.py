from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

FILENAME_RE = re.compile(r"^(?P<identity>.+)_(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})\.pdf$", re.I)


@dataclass(frozen=True, slots=True)
class FilenameIdentity:
    wellbore: str
    report_date: date


def canonicalize_wellbore(value: str) -> str:
    text = " ".join(value.strip().replace("–", "-").split())
    text = re.sub(r"\s*-\s*", "-", text)
    return text.upper()


def parse_ddr_filename(path: str | Path) -> FilenameIdentity | None:
    match = FILENAME_RE.match(Path(path).name)
    if not match:
        return None
    tokens = match.group("identity").split("_")
    if len(tokens) < 3:
        return None
    if len(tokens) >= 4 and tokens[2].upper() == "F":
        wellbore = f"{tokens[0]}/{tokens[1]}-F-{tokens[3]}"
        suffix = tokens[4:]
    else:
        wellbore = f"{tokens[0]}/{tokens[1]}-{tokens[2]}"
        suffix = tokens[3:]
    if suffix:
        wellbore += " " + " ".join(suffix)
    try:
        report_date = date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None
    return FilenameIdentity(canonicalize_wellbore(wellbore), report_date)

