from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from extractor.models import PDFPage


# -----------------------------------------
# Banking Header Vocabulary
# -----------------------------------------

HEADER_KEYWORDS = {
    "DATE",
    "TXN DATE",
    "TRANSACTION DATE",
    "VALUE DT",
    "VALUE DATE",
    "NARRATION",
    "DESCRIPTION",
    "PARTICULARS",
    "DETAILS",
    "MODE",
    "CHQ",
    "CHQ.",
    "CHQ./REF.NO.",
    "REF",
    "REF.NO",
    "REF NO",
    "WITHDRAWAL",
    "WITHDRAWALS",
    "DEBIT",
    "DEBITS",
    "DEPOSIT",
    "DEPOSITS",
    "CREDIT",
    "CREDITS",
    "BALANCE",
    "CLOSING BALANCE",
    "AMOUNT",
}


#DATA STRUCTURES

@dataclass
class HeaderCell:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass
class ColumnBoundary:
    header: str
    x0: float
    x1: float


@dataclass
class LayoutDetectionResult:
    page_number: int
    header_y: float
    headers: Dict[str, ColumnBoundary]
    confidence: float
    warning: Optional[str] = None

#NORMALIZE HEADER TEXT

def normalize_text(value: str) -> str:
    return (
        value.upper()
        .replace(":", "")
        .replace("*", "")
        .strip()
    )

#GROUP WORDS INTO VISUAL ROWS

def group_words_by_row(words, tolerance=3):
    rows = []

    for word in sorted(words, key=lambda w: w.top):

        placed = False

        for row in rows:

            if abs(row["top"] - word.top) <= tolerance:
                row["words"].append(word)
                placed = True
                break

        if not placed:
            rows.append(
                {
                    "top": word.top,
                    "words": [word]
                }
            )

    return rows

#RECONSTRUCT ROW TEXT

def build_row_text(words) -> str:

    ordered = sorted(
        words,
        key=lambda w: w.x0
    )

    return " ".join(
        w.text.strip()
        for w in ordered
    ).strip()

#HEADER LINE DETECTION

def score_header_row(row_text: str) -> int:

    score = 0

    upper = row_text.upper()

    for keyword in HEADER_KEYWORDS:

        if keyword in upper:
            score += 1

    return score

#DETECT HEADER ROW

def detect_header_row(page: PDFPage):

    rows = group_words_by_row(page.words)

    best_row = None
    best_score = 0

    for row in rows:

        text = build_row_text(row["words"])

        score = score_header_row(text)

        if score > best_score:
            best_score = score
            best_row = row

    if best_score < 2:
        return None

    return best_row

#SORT HEADER WORDS

def sorted_header_words(words):

    return sorted(
        words,
        key=lambda w: w.x0
    )

#MERGE ADJACENT WORDS

def merge_header_tokens(words):

    merged = []

    current = None

    for word in words:

        if current is None:
            current = {
                "text": word.text,
                "x0": word.x0,
                "x1": word.x1,
                "top": word.top,
                "bottom": word.bottom,
            }
            continue

        gap = word.x0 - current["x1"]

        if gap <= 15:

            current["text"] += " " + word.text
            current["x1"] = word.x1

        else:

            merged.append(current)

            current = {
                "text": word.text,
                "x0": word.x0,
                "x1": word.x1,
                "top": word.top,
                "bottom": word.bottom,
            }

    if current:
        merged.append(current)

    return merged

#FILTER VALID HEADERS

def is_header_candidate(text: str):

    text = normalize_text(text)

    for keyword in HEADER_KEYWORDS:

        if keyword == text:
            return True

    return False

#BUILD BOUNDARIES

def build_boundaries(
    header_cells,
    page_width
):
    boundaries = {}

    for idx, cell in enumerate(header_cells):

        if idx == 0:
            left = 0
        else:
            prev = header_cells[idx - 1]
            left = (
                prev["x1"] + cell["x0"]
            ) / 2

        if idx == len(header_cells) - 1:
            right = page_width
        else:
            nxt = header_cells[idx + 1]
            right = (
                cell["x1"] + nxt["x0"]
            ) / 2

        boundaries[cell["text"]] = ColumnBoundary(
            header=cell["text"],
            x0=left,
            x1=right
        )

    return boundaries

#MAIN DETECTOR

class LayoutDetector:

    @staticmethod
    def detect(
        page: PDFPage,
        page_width: float
    ) -> Optional[LayoutDetectionResult]:

        header_row = detect_header_row(page)

        if not header_row:
            return None

        merged_headers = merge_header_tokens(
            sorted_header_words(
                header_row["words"]
            )
        )

        valid_headers = []

        for cell in merged_headers:

            if is_header_candidate(
                cell["text"]
            ):
                valid_headers.append(cell)

        if len(valid_headers) < 3:

            return LayoutDetectionResult(
                page_number=page.page_number,
                header_y=header_row["top"],
                headers={},
                confidence=0.30,
                warning="Header partially detected"
            )

        boundaries = build_boundaries(
            valid_headers,
            page_width
        )

        confidence = min(
            1.0,
            len(valid_headers) / 6
        )

        return LayoutDetectionResult(
            page_number=page.page_number,
            header_y=header_row["top"],
            headers=boundaries,
            confidence=confidence,
            warning=None
        )
    
