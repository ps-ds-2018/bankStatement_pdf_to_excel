from __future__ import annotations

import re
from typing import List, Optional

from extractor.models import (
    Transaction,
    WarningItem,
)


# --------------------------------------------------
# PATTERNS
# --------------------------------------------------

# Indian number format: 1,10,279.64 (lakh grouping)
# Also handles standard international: 1,000.00
# Optional leading +/- and trailing CR/DR suffix.
NUMERIC_PATTERN = re.compile(
    r"""
    ^
    [+-]?
    (
        # Formatted with commas: Indian lakh or international grouping
        \d{1,3}(,\d{2,3})+
        |
        # Unformatted: any digit run without commas (e.g. 4000.00, 95000)
        \d+
    )
    (
        \.\d{1,2}    # optional decimal — at most 2 places for currency
    )?
    $
    """,
    re.VERBOSE,
)

DATE_PATTERN = re.compile(
    r"^\d{2}[-/]\d{2}[-/](?:\d{2}|\d{4})$"
)

# Columns whose values must be numeric (after stripping CR/DR suffix)
NUMERIC_COLUMN_KEYWORDS = {
    "BALANCE", "DEBIT", "WITHDRAW",
    "CREDIT", "DEPOSIT", "AMOUNT",
}


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def _strip_cr_dr(value: str) -> str:
    """Remove trailing CR/DR markers that some banks append."""
    return (
        value.strip()
        .upper()
        .removesuffix("CR")
        .removesuffix("DR")
        .strip()
    )


def _is_numeric_column(column: str) -> bool:
    upper = column.upper()
    return any(k in upper for k in NUMERIC_COLUMN_KEYWORDS)


def _get_date_value(txn: Transaction) -> str:
    """Return the first non-empty value — expected to be the date."""
    if txn.data:
        return next(
            (v for v in txn.data.values() if v.strip()),
            "",
        )
    return ""


# --------------------------------------------------
# VALIDATOR
# --------------------------------------------------

class Validator:

    @staticmethod
    def looks_numeric(value: str) -> bool:
        value = value.strip()
        if not value:
            return False
        return bool(NUMERIC_PATTERN.match(value))

    @staticmethod
    def validate_transactions(
        transactions: List[Transaction],
    ) -> List[WarningItem]:

        warnings = []

        for txn in transactions:

            values = txn.data
            date_value = _get_date_value(txn)

            # --- 1. Missing or malformed date ---
            if not date_value:
                warnings.append(
                    WarningItem(
                        page=txn.source_page,
                        transaction="",
                        issue="Missing date",
                        severity="ERROR",
                    )
                )
            elif not DATE_PATTERN.match(date_value.strip()):
                warnings.append(
                    WarningItem(
                        page=txn.source_page,
                        transaction=date_value,
                        issue=f"Unexpected date format: '{date_value}'",
                        severity="WARNING",
                    )
                )

            # --- 2. Numeric column validation ---
            for column, value in values.items():

                if not value or not _is_numeric_column(column):
                    continue

                cleaned = _strip_cr_dr(value)

                # Empty after stripping suffix is fine — not every
                # transaction has a debit AND a credit.
                if not cleaned:
                    continue

                if not Validator.looks_numeric(cleaned):
                    warnings.append(
                        WarningItem(
                            page=txn.source_page,
                            transaction=date_value,
                            issue=(
                                f"Non-numeric value '{value}' "
                                f"in column '{column}' — "
                                f"likely a misclassified narration fragment"
                            ),
                            severity="ERROR",
                        )
                    )

            # --- 3. Narration sanity check ---
            # If a transaction has no narration/particulars at all,
            # flag it — it usually means the layout detector missed
            # the column boundary for that page.
            narration_keys = [
                k for k in values
                if any(
                    kw in k.upper()
                    for kw in ("NARRATION", "PARTICULARS", "DESCRIPTION", "DETAILS")
                )
            ]

            if narration_keys:
                narration = " ".join(
                    values[k].strip() for k in narration_keys
                ).strip()

                if not narration:
                    warnings.append(
                        WarningItem(
                            page=txn.source_page,
                            transaction=date_value,
                            issue="Empty narration/particulars",
                            severity="WARNING",
                        )
                    )

        return warnings