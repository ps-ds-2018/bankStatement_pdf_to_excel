from __future__ import annotations

import re
from typing import Dict, List, Optional

from extractor.models import (
    PDFPage,
    Transaction,
    WarningItem,
)

from extractor.layout_detector import (
    LayoutDetectionResult,
)


DATE_PATTERN = re.compile(
    r"^\d{2}[-/]\d{2}[-/](?:\d{2}|\d{4})$"
)


class ParsedRow:

    def __init__(
        self,
        y: float,
        values: Dict[str, str],
        row_words=None,
    ):
        self.y = y
        self.values = values
        self.row_words = row_words or []


# --------------------------------------------------
# ROW GROUPING
# --------------------------------------------------

def group_rows(words, tolerance=5):
    rows = []

    for word in sorted(words, key=lambda w: (w.top + w.bottom) / 2):
        center = (word.top + word.bottom) / 2
        matched = False

        for row in rows:
            if abs(row["center"] - center) <= tolerance:
                row["words"].append(word)
                row["center"] = (
                    row["center"] * (len(row["words"]) - 1) + center
                ) / len(row["words"])
                matched = True
                break

        if not matched:
            rows.append({
                "center": center,
                "top": word.top,
                "words": [word],
            })

    for row in rows:
        row["top"] = min(w.top for w in row["words"])

    return rows


# --------------------------------------------------
# COLUMN ASSIGNMENT
# --------------------------------------------------

def determine_column(
    x_center: float,
    layout: LayoutDetectionResult,
) -> Optional[str]:
    for header, boundary in layout.headers.items():
        if boundary.x0 <= x_center <= boundary.x1:
            return header
    return None


def build_row(row_words, layout: LayoutDetectionResult):
    result = {header: "" for header in layout.headers.keys()}

    for word in sorted(row_words, key=lambda w: w.x0):
        center = (word.x0 + word.x1) / 2
        column = determine_column(center, layout)
        if not column:
            continue
        if result[column]:
            result[column] += " "
        result[column] += word.text

    return result


# --------------------------------------------------
# DATE COLUMN DETECTION
# --------------------------------------------------

def identify_date_column(layout: LayoutDetectionResult) -> Optional[str]:
    candidates = {
        "DATE", "TXN DATE", "TRANSACTION DATE",
        "VALUE DATE", "VALUE DT",
    }
    for header in layout.headers:
        if header.upper().replace(":", "").replace("*", "").strip() in candidates:
            return header
    return None


# --------------------------------------------------
# TRANSACTION START
# --------------------------------------------------

def row_starts_transaction(
    parsed_row: ParsedRow,
    date_column: str,
) -> bool:
    value = parsed_row.values.get(date_column, "").strip()
    if DATE_PATTERN.match(value):
        return True

    if parsed_row.row_words:
        leftmost = min(parsed_row.row_words, key=lambda w: w.x0)
        if DATE_PATTERN.match(leftmost.text.strip()):
            return True

    return False


# --------------------------------------------------
# NOISE FILTERS
# --------------------------------------------------

def is_footer_row(row: ParsedRow) -> bool:
    text = " ".join(v for v in row.values.values() if v).upper()
    return "PAGE " in text and " OF " in text


def is_account_holder_row(row: ParsedRow) -> bool:
    text = " ".join(v for v in row.values.values() if v).upper().strip()
    return (
        text.startswith("MR.")
        or text.startswith("MRS.")
        or text.startswith("MS.")
    )


def is_effectively_empty(row: ParsedRow) -> bool:
    return not any(v.strip() for v in row.values.values())


# --------------------------------------------------
# AMOUNT HELPERS
# --------------------------------------------------

def _looks_like_amount(value: str) -> bool:
    """Matches Indian-format currency: 1,000.00 / 1,10,279.64"""
    return bool(re.match(r"^[\d,]+(?:\.\d{1,2})?$", value.strip()))


def _is_numeric_column(header: str, layout: LayoutDetectionResult) -> bool:
    boundary = layout.headers.get(header)
    if boundary and boundary.is_numeric:
        return True
    upper = header.upper()
    NUMERIC_KEYS = {
        "WITHDRAWAL", "WITHDRAWALS", "DEBIT", "DEBITS",
        "DEPOSIT", "DEPOSITS", "CREDIT", "CREDITS",
        "BALANCE", "CLOSING BALANCE", "AMOUNT",
    }
    return any(k in upper for k in NUMERIC_KEYS)


# --------------------------------------------------
# TRANSACTION GROUPING  ← the core fix
# --------------------------------------------------

def group_into_transaction_blocks(
    parsed_rows: List[ParsedRow],
    date_column: str,
) -> List[List[ParsedRow]]:
    """
    Splits the flat list of parsed rows into blocks where each block
    is exactly one transaction: one anchor row (has a date) followed
    by zero or more continuation rows (no date).

    A new block starts ONLY when a date row is encountered.
    All rows between two date rows — regardless of what columns they
    fill — belong to the preceding date row's transaction.

    This means: iterate through ALL continuation rows of a transaction
    before moving on to the next, which prevents partial narration
    lines from bleeding into adjacent transactions.
    """
    blocks: List[List[ParsedRow]] = []
    current_block: List[ParsedRow] = []

    for row in parsed_rows:
        if row_starts_transaction(row, date_column):
            if current_block:
                blocks.append(current_block)
            current_block = [row]
        else:
            # Continuation row — always belongs to the current block
            if current_block:
                current_block.append(row)
            # Rows before the very first date (page headers, etc.) → skip

    if current_block:
        blocks.append(current_block)

    return blocks


# --------------------------------------------------
# BLOCK → TRANSACTION
# --------------------------------------------------

def build_transaction_from_block(
    block: List[ParsedRow],
    date_column: str,
    layout: LayoutDetectionResult,
    page_number: int,
) -> Transaction:
    """
    Collapses a block (anchor row + continuation rows) into a single
    Transaction by iterating through every row in the block fully
    before moving on — exactly as you suggested.

    Rules per continuation row:
    - Numeric columns: accept only values that look like amounts.
      This stops UPI hash fragments from entering amount cells.
    - Text columns: append with a space separator.
    """
    # Start with the anchor row's values
    txn = Transaction(
        data=block[0].values.copy(),
        source_page=page_number,
    )

    for row in block[1:]:  # continuation rows
        for key, value in row.values.items():
            value = value.strip()
            if not value:
                continue

            if _is_numeric_column(key, layout):
                if _looks_like_amount(value):
                    txn.data[key] = value
                # Non-numeric text in an amount column → discard
            else:
                existing = txn.data.get(key, "").strip()
                txn.data[key] = (existing + " " + value).strip() if existing else value

    return txn


# --------------------------------------------------
# MERGE ENGINE (now just orchestrates the two steps)
# --------------------------------------------------

def merge_rows(
    parsed_rows: List[ParsedRow],
    date_column: str,
    layout: LayoutDetectionResult,
    page_number: int,
):
    blocks = group_into_transaction_blocks(parsed_rows, date_column)

    transactions = []
    warnings = []

    for block in blocks:
        txn = build_transaction_from_block(
            block, date_column, layout, page_number
        )
        transactions.append(txn)

        if len(block) > 1:
            warnings.append(
                WarningItem(
                    page=page_number,
                    transaction=txn.data.get(date_column, ""),
                    issue=f"Multiline merge performed ({len(block)} rows)",
                    severity="INFO",
                )
            )

    return transactions, warnings


# --------------------------------------------------
# MAIN PARSER
# --------------------------------------------------

class TransactionParser:

    @staticmethod
    def parse_page(
        page: PDFPage,
        layout: LayoutDetectionResult,
    ):
        warnings = []

        date_column = identify_date_column(layout)

        if not date_column:
            warnings.append(
                WarningItem(
                    page=page.page_number,
                    transaction="",
                    issue="Date column not detected",
                    severity="ERROR",
                )
            )
            return [], warnings

        rows = group_rows(page.words)
        rows = [row for row in rows if row["top"] > layout.header_y]

        parsed_rows = []

        for row in rows:
            row_values = build_row(row["words"], layout)
            parsed_row = ParsedRow(
                y=row["top"],
                values=row_values,
                row_words=row["words"],
            )

            if is_footer_row(parsed_row):
                continue
            if is_account_holder_row(parsed_row):
                continue
            if is_effectively_empty(parsed_row):
                continue

            parsed_rows.append(parsed_row)

        transactions, merge_warnings = merge_rows(
            parsed_rows,
            date_column,
            layout,
            page.page_number,
        )

        warnings.extend(merge_warnings)
        return transactions, warnings