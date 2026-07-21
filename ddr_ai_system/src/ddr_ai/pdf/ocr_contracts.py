from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OCRToken:
    text: str
    confidence: float
    x0: float
    y0: float
    x1: float
    y1: float
    block: int
    paragraph: int
    line: int
    page_number: int | None = None


@dataclass(frozen=True, slots=True)
class OCRResult:
    text: str
    confidence: float
    tokens: tuple[OCRToken, ...] = ()
