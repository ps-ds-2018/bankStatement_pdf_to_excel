from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from extractor.models import PDFPage

import re

# -----------------------------------------
# Banking Header Vocabulary
# -----------------------------------------

HEADER_KEYWORDS = {
    "DATE",
    "TXN DATE",
    "TRANSACTION DATE",
    "VALUE DT",
    "VALUE DATE",
    "VALUEDT",           
    "NARRATION",
    "DESCRIPTION",
    "PARTICULARS",
    "DETAILS",
    "REMARKS",
    "MODE",
    "CHQ",
    "CHQ.",
    "CHQ./REF.NO.",
    "CHQ/REF NO",
    "CHQ NO",
    "REF",
    "REF.NO",
    "REF NO",
    "REF.NO.",
    "WITHDRAWAL",
    "WITHDRAWALS",
    "WITHDRAWAL AMT",
    "WITHDRAWAL AMT.",
    "WITHDRAWALAMT",     
    "WITHDRAWALAMT.",
    "DEBIT",
    "DEBITS",
    "DEPOSIT",
    "DEPOSITS",
    "DEPOSIT AMT",
    "DEPOSIT AMT.",
    "DEPOSITAMT",        
    "DEPOSITAMT.",
    "CREDIT",
    "CREDITS",
    "BALANCE",
    "CLOSING BALANCE",
    "CLOSINGBALANCE",    
    "AMOUNT",
}

NUMERIC_COLUMN_KEYWORDS = {
    "WITHDRAWAL", "WITHDRAWALS", "WITHDRAWAL AMT", "WITHDRAWAL AMT.",
    "WITHDRAWALAMT", "WITHDRAWALAMT.",
    "DEBIT", "DEBITS",
    "DEPOSIT", "DEPOSITS", "DEPOSIT AMT", "DEPOSIT AMT.",
    "DEPOSITAMT", "DEPOSITAMT.",
    "CREDIT", "CREDITS",
    "BALANCE", "CLOSING BALANCE", "CLOSINGBALANCE",
    "AMOUNT",
}

NARRATION_COLUMN_KEYWORDS = {
    "NARRATION", "DESCRIPTION", "PARTICULARS", "DETAILS", "REMARKS",
}

# These pairs of keywords are always separate columns even when their
# header words appear close together on the page.  We split any merged
# token that contains more than one of these.
ALWAYS_SEPARATE_KEYWORDS = [
    "DEPOSITS",
    "WITHDRAWALS",
    "DEPOSIT AMT",
    "WITHDRAWAL AMT",
    "DEPOSITAMT",
    "WITHDRAWALAMT",
    "DEPOSIT",
    "WITHDRAWAL",
    "DEBIT",
    "DEBITS",
    "CREDIT",
    "CREDITS",
    "BALANCE",
    "CLOSINGBALANCE",
    "AMOUNT",
    "VALUE DT",
    "VALUE DATE",
    "VALUEDT",
    "DATE",
    "MODE",
    "PARTICULARS",
    "NARRATION",
    "DESCRIPTION",
    "REMARKS",
]


# -----------------------------------------
# DATA STRUCTURES
# -----------------------------------------

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
    is_numeric: bool = False
    is_narration: bool = False


@dataclass
class LayoutDetectionResult:
    page_number: int
    header_y: float
    headers: Dict[str, ColumnBoundary]
    confidence: float
    warning: Optional[str] = None


# -----------------------------------------
# NORMALIZE
# -----------------------------------------

def normalize_text(value: str) -> str:
    return (
        value.upper()
        .replace(":", "")
        .replace("*", "")
        .replace("**", "")
        .strip()
    )


# -----------------------------------------
# GROUP WORDS INTO VISUAL ROWS
# -----------------------------------------

def group_words_by_row(words, tolerance=6):
    rows = []

    for word in sorted(words, key=lambda w: (w.top + w.bottom) / 2):
        center = (word.top + word.bottom) / 2
        placed = False

        for row in rows:
            if abs(row["center"] - center) <= tolerance:
                row["words"].append(word)
                row["center"] = (
                    row["center"] * (len(row["words"]) - 1) + center
                ) / len(row["words"])
                placed = True
                break

        if not placed:
            rows.append({"center": center, "top": word.top, "words": [word]})

    for row in rows:
        row["top"] = min(w.top for w in row["words"])

    return rows


# -----------------------------------------
# ROW TEXT
# -----------------------------------------

def build_row_text(words) -> str:
    ordered = sorted(words, key=lambda w: w.x0)
    return " ".join(w.text.strip() for w in ordered).strip()


# -----------------------------------------
# HEADER SCORING
# -----------------------------------------

def score_header_row(row_text: str) -> int:
    score = 0
    upper = row_text.upper()
    for keyword in HEADER_KEYWORDS:
        if keyword in upper:
            score += 1
    return score


def detect_header_row(page: PDFPage):
    rows = group_words_by_row(page.words)
    best_row = None
    best_score = 0

    # A real column-header row is never in the bottom 15% of the page.
    # Rejecting rows in that zone prevents the HDFC footer block
    # (printed near the page bottom and containing embedded keywords
    # like BALANCE and DATE inside camelCase tokens) from being
    # mistaken for the table header on continuation pages.
    footer_threshold = page.height * 0.85

    for row in rows:
        if row["top"] >= footer_threshold:
            continue
        text = build_row_text(row["words"])
        score = score_header_row(text)
        if score > best_score:
            best_score = score
            best_row = row

    if best_score < 2:
        return None

    return best_row


def sorted_header_words(words):
    return sorted(words, key=lambda w: w.x0)


# -----------------------------------------
# MERGE HEADER TOKENS
# -----------------------------------------

def _count_known_keywords(text: str) -> int:
    """Count how many distinct ALWAYS_SEPARATE_KEYWORDS appear in text."""
    upper = normalize_text(text)
    return sum(1 for kw in ALWAYS_SEPARATE_KEYWORDS if kw in upper)


def _split_merged_token(token: dict) -> List[dict]:
    """
    If a merged token contains more than one known column keyword
    (e.g. 'DEPOSITS WITHDRAWALS'), split it back into individual
    word-level tokens using the original word objects stored in the
    token's 'words' list.

    Falls back to returning the token as-is if 'words' is absent.
    """
    words = token.get("words")
    if not words or _count_known_keywords(token["text"]) <= 1:
        return [token]

    # Re-emit one token per word
    return [
        {
            "text": w.text,
            "x0": w.x0,
            "x1": w.x1,
            "top": w.top,
            "bottom": w.bottom,
            "words": [w],
        }
        for w in words
    ]


def merge_header_tokens(words, page_width: float = 600.0):
    """
    Merges words that belong to the same multi-word header cell
    (e.g. 'TXN DATE', 'CHQ./REF.NO.') but keeps known separate
    column names apart even when the gap is small.

    Strategy:
    1. Merge adjacent words whose gap is within threshold.
    2. After merging, scan each resulting token: if it contains
       more than one distinct column keyword, split it back to
       individual words.  This handles 'DEPOSITS WITHDRAWALS'
       printed close together on narrow statements.
    """
    # Scale gap threshold with page width but keep it modest —
    # we'd rather under-merge (caught by step 2) than over-merge.
    gap_threshold = max(14.0, page_width * 0.025)

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
                "words": [word],
            }
            continue

        gap = word.x0 - current["x1"]

        if gap <= gap_threshold:
            current["text"] += " " + word.text
            current["x1"] = word.x1
            current["words"].append(word)
        else:
            merged.append(current)
            current = {
                "text": word.text,
                "x0": word.x0,
                "x1": word.x1,
                "top": word.top,
                "bottom": word.bottom,
                "words": [word],
            }

    if current:
        merged.append(current)

    # Pass 2: split any token that swallowed multiple column names
    result = []
    for token in merged:
        result.extend(_split_merged_token(token))

    return result


# -----------------------------------------
# HEADER CANDIDATE FILTER
# -----------------------------------------

def is_header_candidate(text: str) -> bool:
    normalized = normalize_text(text)

    if normalized in HEADER_KEYWORDS:
        return True

    for keyword in HEADER_KEYWORDS:
        if keyword in normalized:
            return True

    return False


# -----------------------------------------
# BUILD COLUMN BOUNDARIES
# -----------------------------------------

def build_boundaries(
    header_cells,
    page_width: float,
) -> Dict[str, ColumnBoundary]:
    boundaries = {}

    for idx, cell in enumerate(header_cells):

        left = (
            0.0
            if idx == 0
            else (header_cells[idx - 1]["x1"] + cell["x0"]) / 2
        )

        is_last = idx == len(header_cells) - 1
        if is_last:
            right = page_width
        else:
            next_cell = header_cells[idx + 1]
            midpoint = (cell["x1"] + next_cell["x0"]) / 2

            # Use the midpoint between this column's header x1 and the next
            # column's header x0 as the boundary between them.  This is the
            # most reliable split point regardless of column types; previous
            # special-case rules for narration and numeric columns caused
            # boundaries to be set too wide (HDFC: Date swallowed narration
            # text) or too narrow (Bank of India: date text fell outside the
            # Date column).
            right = midpoint

        normalized = normalize_text(cell["text"])

        boundaries[cell["text"]] = ColumnBoundary(
            header=cell["text"],
            x0=left,
            x1=right,
            is_numeric=normalized in NUMERIC_COLUMN_KEYWORDS,
            is_narration=normalized in NARRATION_COLUMN_KEYWORDS,
        )

    return boundaries


# -----------------------------------------
# DATA-CALIBRATED BOUNDARY REFINEMENT
# -----------------------------------------

_AMOUNT_PATTERN = re.compile(r"^[\d,]+(?:\.\d{1,2})?$")


def _collect_numeric_x_centers(page: PDFPage, header_y: float) -> List[float]:
    """
    Return the x-centers of all words below header_y that look like
    Indian-format currency amounts (e.g. '4000.00', '1,23,456.78').
    These are used to calibrate the boundaries of numeric columns.
    """
    centers = []
    for w in page.words:
        if w.top <= header_y:
            continue
        text = w.text.strip().lstrip("₹").strip()
        if _AMOUNT_PATTERN.match(text):
            centers.append((w.x0 + w.x1) / 2)
    return centers


def _recalibrate_numeric_boundaries(
    boundaries: Dict[str, ColumnBoundary],
    data_centers: List[float],
    page_width: float,
) -> Dict[str, ColumnBoundary]:
    """
    When numeric column headers are printed at positions that don't align
    with their data (a known Bank of India quirk), the midpoint boundaries
    derived from header positions will mis-assign amounts to the wrong
    column.

    Strategy: for each pair of adjacent numeric columns, collect all data
    x-centers that fall anywhere between the left edge of the first and the
    right edge of the second, then use the largest gap in that set as the
    true boundary between them.  This correctly splits Debit vs Credit vs
    Balance regardless of where the header words happen to be printed.
    """
    # Only act when there are at least 2 numeric columns.
    numeric_cols = [
        name for name, b in boundaries.items() if b.is_numeric
    ]
    if len(numeric_cols) < 2:
        return boundaries

    # Sort numeric columns left-to-right by their current x0.
    numeric_cols.sort(key=lambda n: boundaries[n].x0)

    # Build a mutable copy so we can update boundaries in place.
    result = dict(boundaries)

    for i in range(len(numeric_cols) - 1):
        left_name  = numeric_cols[i]
        right_name = numeric_cols[i + 1]
        left_b  = result[left_name]
        right_b = result[right_name]

        # Collect data x-centers in the combined span of both columns.
        span_x0 = left_b.x0
        span_x1 = right_b.x1
        span_centers = sorted(
            c for c in data_centers if span_x0 <= c <= span_x1
        )

        if len(span_centers) < 2:
            continue  # Not enough data to recalibrate this pair.

        # Find the largest gap between consecutive x-centers.
        max_gap = 0.0
        split_x = (left_b.x1 + right_b.x0) / 2  # fallback: current midpoint

        for j in range(len(span_centers) - 1):
            gap = span_centers[j + 1] - span_centers[j]
            if gap > max_gap:
                max_gap = gap
                split_x = (span_centers[j] + span_centers[j + 1]) / 2

        # Only update if the gap-based split differs meaningfully from
        # the current boundary (avoids jitter on already-correct layouts).
        current_boundary = (left_b.x1 + right_b.x0) / 2
        if abs(split_x - current_boundary) > 5.0:
            result[left_name]  = ColumnBoundary(
                header=left_b.header,
                x0=left_b.x0,
                x1=split_x,
                is_numeric=left_b.is_numeric,
                is_narration=left_b.is_narration,
            )
            result[right_name] = ColumnBoundary(
                header=right_b.header,
                x0=split_x,
                x1=right_b.x1,
                is_numeric=right_b.is_numeric,
                is_narration=right_b.is_narration,
            )

    return result


# -----------------------------------------
# MAIN DETECTOR
# -----------------------------------------

class LayoutDetector:

    @staticmethod
    def detect(
        page: PDFPage,
        page_width: float,
    ) -> Optional[LayoutDetectionResult]:

        header_row = detect_header_row(page)

        if not header_row:
            return None

        merged_headers = merge_header_tokens(
            sorted_header_words(header_row["words"]),
            page_width=page_width,
        )

        valid_headers = [
            cell for cell in merged_headers
            if is_header_candidate(cell["text"])
        ]

        if len(valid_headers) < 3:
            return LayoutDetectionResult(
                page_number=page.page_number,
                header_y=header_row["top"],
                headers={},
                confidence=0.30,
                warning="Header partially detected",
            )

        boundaries = build_boundaries(valid_headers, page_width)

        # Refine numeric column boundaries using the actual x-positions of
        # amount values in the data rows.  This corrects for statements where
        # the column header words are not centred over their data columns
        # (e.g. Bank of India: Debit/Credit/Balance headers misaligned).
        data_centers = _collect_numeric_x_centers(page, header_row["top"])
        boundaries = _recalibrate_numeric_boundaries(
            boundaries, data_centers, page_width
        )

        confidence = min(1.0, len(valid_headers) / 6)

        return LayoutDetectionResult(
            page_number=page.page_number,
            header_y=header_row["top"],
            headers=boundaries,
            confidence=confidence,
            warning=None,
        )