from __future__ import annotations

import re

from typing import List

from extractor.models import (
    Transaction,
    WarningItem,
)


NUMERIC_PATTERN = re.compile(
    r"""
    ^
    [+-]?
    \d{1,3}
    (
        ,\d{3}
    )*
    (
        \.\d+
    )?
    $
    """,
    re.VERBOSE,
)


class Validator:

    @staticmethod
    def looks_numeric(
        value: str
    ) -> bool:

        value = value.strip()

        if not value:
            return False

        return bool(
            NUMERIC_PATTERN.match(value)
        )

    @staticmethod
    def validate_transactions(
        transactions: List[Transaction]
    ) -> List[WarningItem]:

        warnings = []

        for txn in transactions:

            values = txn.data

            # missing date

            first_value = ""

            if values:
                first_value = next(
                    iter(values.values())
                )

            if not first_value:

                warnings.append(
                    WarningItem(
                        page=txn.source_page,
                        transaction="",
                        issue="Missing date",
                        severity="ERROR",
                    )
                )

            # numeric validation

            for column, value in values.items():

                upper = column.upper()

                if any(
                    keyword in upper
                    for keyword in [
                        "BALANCE",
                        "DEBIT",
                        "WITHDRAW",
                        "CREDIT",
                        "DEPOSIT",
                        "AMOUNT",
                    ]
                ):

                    if value and not Validator.looks_numeric(
                        value.replace("CR", "")
                             .replace("DR", "")
                             .strip()
                    ):
                        warnings.append(
                            WarningItem(
                                page=txn.source_page,
                                transaction=first_value,
                                issue=(
                                    f"Invalid numeric amount "
                                    f"in column '{column}'"
                                ),
                                severity="ERROR",
                            )
                        )

        return warnings