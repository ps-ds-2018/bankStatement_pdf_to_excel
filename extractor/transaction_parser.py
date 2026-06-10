from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

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

def group_rows(words, tolerance=3):

    rows = []

    for word in sorted(words, key=lambda w: w.top):

        matched = False

        for row in rows:

            if abs(row["top"] - word.top) <= tolerance:

                row["words"].append(word)
                matched = True
                break

        if not matched:

            rows.append(
                {
                    "top": word.top,
                    "words": [word],
                }
            )

    return rows


# --------------------------------------------------
# COLUMN DETECTION
# --------------------------------------------------

def determine_column(
    x_center: float,
    layout: LayoutDetectionResult,
) -> Optional[str]:

    for header, boundary in layout.headers.items():

        if boundary.x0 <= x_center <= boundary.x1:
            return header

    return None


def build_row(
    row_words,
    layout: LayoutDetectionResult,
):

    result = {
        header: ""
        for header in layout.headers.keys()
    }

    for word in sorted(row_words, key=lambda w: w.x0):

        center = (word.x0 + word.x1) / 2

        column = determine_column(
            center,
            layout,
        )

        if not column:
            continue

        if result[column]:
            result[column] += " "

        result[column] += word.text

    return result


# --------------------------------------------------
# DATE COLUMN
# --------------------------------------------------

def identify_date_column(
    layout: LayoutDetectionResult,
):

    candidates = [
        "DATE",
        "Date",
        "Txn Date",
        "TXN DATE",
        "Transaction Date",
        "TRANSACTION DATE",
    ]

    for candidate in candidates:

        if candidate in layout.headers:
            return candidate

    return None


# --------------------------------------------------
# TRANSACTION START
# --------------------------------------------------

def row_starts_transaction(
    parsed_row: ParsedRow,
    date_column: str,
):

    value = parsed_row.values.get(
        date_column,
        ""
    ).strip()

    if DATE_PATTERN.match(value):
        return True

    # fallback:
    # check left-most word

    if parsed_row.row_words:

        leftmost = min(
            parsed_row.row_words,
            key=lambda w: w.x0
        )

        if DATE_PATTERN.match(
            leftmost.text.strip()
        ):
            return True

    return False


# --------------------------------------------------
# FILTER NOISE
# --------------------------------------------------

def is_footer_row(
    row: ParsedRow,
):

    text = " ".join(
        v for v in row.values.values()
        if v
    )

    text = text.upper()

    return (
        "PAGE " in text
        and " OF " in text
    )


def is_account_holder_row(
    row: ParsedRow,
):

    text = " ".join(
        v for v in row.values.values()
        if v
    )

    text = text.upper().strip()

    if text.startswith("MR."):
        return True

    if text.startswith("MRS."):
        return True

    if text.startswith("MS."):
        return True

    return False


# --------------------------------------------------
# MERGE ENGINE
# --------------------------------------------------

def merge_rows(
    parsed_rows: List[ParsedRow],
    date_column: str,
    page_number: int,
):

    transactions = []
    warnings = []

    current_txn = None

    for row in parsed_rows:

        if row_starts_transaction(
            row,
            date_column,
        ):

            if current_txn:

                transactions.append(
                    current_txn
                )

            current_txn = Transaction(
                data=row.values.copy(),
                source_page=page_number,
            )

            continue

        if current_txn:

            merged = False

            for key, value in row.values.items():

                value = value.strip()

                if not value:
                    continue

                existing = current_txn.data.get(
                    key,
                    ""
                ).strip()

                if existing:

                    current_txn.data[key] = (
                        existing
                        + " "
                        + value
                    )

                else:

                    current_txn.data[key] = value

                merged = True

            if merged:

                warnings.append(
                    WarningItem(
                        page=page_number,
                        transaction=current_txn.data.get(
                            date_column,
                            ""
                        ),
                        issue="Multiline merge performed",
                        severity="INFO",
                    )
                )

    if current_txn:
        transactions.append(
            current_txn
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

        date_column = identify_date_column(
            layout
        )

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

        rows = group_rows(
            page.words
        )

        # IMPORTANT:
        # ignore everything above table header

        rows = [
            row
            for row in rows
            if row["top"] > layout.header_y
        ]

        parsed_rows = []

        for row in rows:

            row_values = build_row(
                row["words"],
                layout,
            )

            parsed_row = ParsedRow(
                y=row["top"],
                values=row_values,
                row_words=row["words"],
            )

            if is_footer_row(parsed_row):
                continue

            if is_account_holder_row(parsed_row):
                continue

            parsed_rows.append(
                parsed_row
            )

        transactions, merge_warnings = (
            merge_rows(
                parsed_rows,
                date_column,
                page.page_number,
            )
        )

        warnings.extend(
            merge_warnings
        )

        return transactions, warnings