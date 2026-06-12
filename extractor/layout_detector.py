from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

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
    "VALUEDT",           # HDFC compact: "ValueDt"
    "NARRATION",
    "DESCRIPTION",
    "PARTICULARS",
    "DETAILS",
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
    "WITHDRAWALAMT",     # HDFC compact: "WithdrawalAmt."
    "WITHDRAWALAMT.",
    "DEBIT",
    "DEBITS",
    "DEPOSIT",
    "DEPOSITS",
    "DEPOSIT AMT",
    "DEPOSIT AMT.",
    "DEPOSITAMT",        # HDFC compact: "DepositAmt."
    "DEPOSITAMT.",
    "CREDIT",
    "CREDITS",
    "BALANCE",
    "CLOSING BALANCE",
    "CLOSINGBALANCE",    # HDFC compact: "ClosingBalance"
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
    "NARRATION", "DESCRIPTION", "PARTICULARS", "DETAILS",
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

        confidence = min(1.0, len(valid_headers) / 6)

        return LayoutDetectionResult(
            page_number=page.page_number,
            header_y=header_row["top"],
            headers=boundaries,
            confidence=confidence,
            warning=None,
        )