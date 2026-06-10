from pathlib import Path
from typing import List

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill

from extractor.models import (
    Metadata,
    Transaction,
    WarningItem,
)


class ExcelExporter:

    INFO_FILL = PatternFill(
        fill_type="solid",
        fgColor="FFF2CC"
    )

    ERROR_FILL = PatternFill(
        fill_type="solid",
        fgColor="F4CCCC"
    )

    @staticmethod
    def export(
        output_path: str,
        metadata: Metadata,
        transactions: List[Transaction],
        warnings: List[WarningItem],
    ) -> None:

        output_file = Path(output_path)

        # -----------------------
        # Metadata Sheet
        # -----------------------

        metadata_rows = [
            ["Account Holder Name", metadata.account_holder_name],
            ["Account Number", metadata.account_number],
            ["Statement Period", metadata.statement_period],
            ["IFSC", metadata.ifsc],
            ["Branch", metadata.branch],
            ["Opening Balance", metadata.opening_balance],
            ["Closing Balance", metadata.closing_balance],
        ]

        metadata_df = pd.DataFrame(
            metadata_rows,
            columns=["Field", "Value"]
        )

        # -----------------------
        # Transactions Sheet
        # -----------------------

        all_headers = []

        for txn in transactions:

            for header in txn.data.keys():

                if header not in all_headers:
                    all_headers.append(header)


        transaction_rows = []

        for txn in transactions:

            row = {}

            for header in all_headers:
                row[header] = txn.data.get(header,"")

            transaction_rows.append(row)

        transaction_df = pd.DataFrame(transaction_rows, columns=all_headers)


        # -----------------------
        # Warnings Sheet
        # -----------------------

        warning_rows = []

        for w in warnings:
            warning_rows.append(
                {
                    "Page": w.page,
                    "Transaction": w.transaction,
                    "Issue": w.issue,
                    "Severity": w.severity,
                }
            )

        warnings_df = pd.DataFrame(warning_rows)

        with pd.ExcelWriter(
            output_file,
            engine="openpyxl"
        ) as writer:

            metadata_df.to_excel(
                writer,
                sheet_name="Metadata",
                index=False
            )

            transaction_df.to_excel(
                writer,
                sheet_name="Transactions",
                index=False
            )

            warnings_df.to_excel(
                writer,
                sheet_name="Warnings",
                index=False
            )

        wb = load_workbook(output_file)

        # -----------------------
        # Transactions formatting
        # -----------------------

        tx_sheet = wb["Transactions"]

        tx_sheet.freeze_panes = "A2"

        for column in tx_sheet.columns:

            max_len = 0

            for cell in column:
                value = str(cell.value or "")

                if len(value) > max_len:
                    max_len = len(value)

            tx_sheet.column_dimensions[
                column[0].column_letter
            ].width = min(max_len + 3, 60)

        # -----------------------
        # Warnings formatting
        # -----------------------

        warn_sheet = wb["Warnings"]

        severity_col = None

        for cell in warn_sheet[1]:
            if cell.value == "Severity":
                severity_col = cell.column

        if severity_col:

            for row in range(
                2,
                warn_sheet.max_row + 1
            ):

                severity = warn_sheet.cell(
                    row=row,
                    column=severity_col
                ).value

                fill = (
                    ExcelExporter.ERROR_FILL
                    if str(severity).upper() == "ERROR"
                    else ExcelExporter.INFO_FILL
                )

                for col in range(
                    1,
                    warn_sheet.max_column + 1
                ):
                    warn_sheet.cell(
                        row=row,
                        column=col
                    ).fill = fill

        wb.save(output_file)