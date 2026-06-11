import sys
from dataclasses import replace as dc_replace
from datetime import datetime
from pathlib import Path

from extractor.pdf_reader import PDFReader
from extractor.layout_detector import LayoutDetector
from extractor.transaction_parser import TransactionParser
from extractor.metadata_extractor import MetadataExtractor
from validator.validator import Validator
from extractor.models import ExtractionResult, WarningItem
from exporter.excel_exporter import ExcelExporter


def extract_statement(
    pdf_path: str,
    password: str | None = None,
) -> ExtractionResult:

    pages = PDFReader.read_pdf(pdf_path, password)

    metadata = MetadataExtractor.extract(pages)

    all_transactions = []
    all_warnings = []

    # Last layout that had a full set of column headers (confidence > 0.3).
    # Continuation pages in multi-page statements often omit the header row
    # entirely, so we propagate the most recent good layout to those pages
    # rather than skipping them.
    last_good_layout = None

    for page in pages:

        layout = LayoutDetector.detect(
            page=page,
            page_width=page.width,
        )

        # A layout with no headers (partial detection) is treated the same
        # as no layout — fall back to propagation.
        layout_has_headers = layout and layout.headers

        if not layout_has_headers:
            if last_good_layout is None:
                # Nothing to propagate yet — genuinely cannot parse this page.
                all_warnings.append(
                    WarningItem(
                        page=page.page_number,
                        transaction="",
                        issue="Header not detected and no prior layout to propagate",
                        severity="ERROR",
                    )
                )
                continue

            # Reuse the previous page's layout, but update the page number
            # in the result so source attribution stays correct.
            layout = dc_replace(last_good_layout, page_number=page.page_number)
            all_warnings.append(
                WarningItem(
                    page=page.page_number,
                    transaction="",
                    issue="Header not detected — using propagated layout from previous page",
                    severity="INFO",
                )
            )
        else:
            # Only promote to last_good_layout when headers are fully resolved.
            last_good_layout = layout

        if layout.warning:
            all_warnings.append(
                WarningItem(
                    page=page.page_number,
                    transaction="",
                    issue=layout.warning,
                    severity="INFO",
                )
            )

        transactions, warnings = TransactionParser.parse_page(
            page=page,
            layout=layout,
        )

        all_transactions.extend(transactions)
        all_warnings.extend(warnings)

    validation_warnings = Validator.validate_transactions(all_transactions)
    all_warnings.extend(validation_warnings)

    return ExtractionResult(
        metadata=metadata,
        transactions=all_transactions,
        warnings=all_warnings,
    )


def build_output_path(pdf_path: str, output_dir: Path) -> Path:
    """
    Derives the output filename from the input PDF name + timestamp.

    e.g. hdfc_june.pdf  →  output/hdfc_june_20240701_143022.xlsx
    """
    stem = Path(pdf_path).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"{stem}_{timestamp}.xlsx"


def main():

    if len(sys.argv) < 2:
        print(
            "Usage:\n"
            "  python main.py statement.pdf\n"
            "  python main.py statement.pdf password123"
        )
        sys.exit(1)

    pdf_path = sys.argv[1]
    password = sys.argv[2] if len(sys.argv) >= 3 else None

    result = extract_statement(pdf_path=pdf_path, password=password)

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    output_file = build_output_path(pdf_path, output_dir)

    ExcelExporter.export(
        output_path=str(output_file),
        metadata=result.metadata,
        transactions=result.transactions,
        warnings=result.warnings,
    )

    print(f"Workbook generated: {output_file}")

    # Summary line
    error_count = sum(
        1 for w in result.warnings
        if w.severity == "ERROR"
    )
    print(
        f"  {len(result.transactions)} transactions | "
        f"{len(result.warnings)} warnings "
        f"({error_count} errors)"
    )


if __name__ == "__main__":
    main()