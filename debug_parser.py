import sys
import os
from dataclasses import replace as dc_replace
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extractor.pdf_reader import PDFReader
from extractor.layout_detector import LayoutDetector
from extractor.transaction_parser import (
    group_rows, build_row, identify_date_column,
    row_starts_transaction, is_footer_row,
    is_account_holder_row, is_effectively_empty, ParsedRow
)

pdf_path = sys.argv[1]
password = sys.argv[2] if len(sys.argv) > 2 else None

output_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "debug_output.txt"
)

lines = []

def log(s=""):
    lines.append(s)
    print(s)

pages = PDFReader.read_pdf(pdf_path, password)

last_good_layout = None

for page_idx, page in enumerate(pages):

    log(f"\n{'='*60}")
    log(f"PAGE {page.page_number}  (width={page.width:.1f}  height={page.height:.1f})")
    log(f"{'='*60}")

    layout = LayoutDetector.detect(page=page, page_width=page.width)
    layout_has_headers = layout and layout.headers

    if not layout_has_headers:
        if last_good_layout is None:
            log("  [!] No layout detected for this page — skipping")
            continue
        layout = dc_replace(last_good_layout, page_number=page.page_number)
        log(f"  [~] No layout detected — using propagated layout from page {last_good_layout.page_number}")
    else:
        last_good_layout = layout

    log("\n--- DETECTED HEADERS ---")
    for name, boundary in layout.headers.items():
        log(f"  {name!r:30s}  x0={boundary.x0:6.1f}  x1={boundary.x1:6.1f}  numeric={boundary.is_numeric}  narration={boundary.is_narration}")

    log(f"\n  header_y (table starts below): {layout.header_y:.1f}")

    log(f"\n--- RAW WORDS below header_y ---")
    words_sorted = sorted(
        [w for w in page.words if w.top > layout.header_y],
        key=lambda w: (w.top, w.x0)
    )
    for w in words_sorted[:80]:
        log(f"  top={w.top:6.1f}  bot={w.bottom:6.1f}  x0={w.x0:6.1f}  x1={w.x1:6.1f}  text={w.text!r}")

    log(f"\n--- GROUPED ROWS (tolerance=5) ---")
    rows = group_rows(page.words)
    rows = [r for r in rows if r["top"] > layout.header_y]
    for i, row in enumerate(rows[:50]):
        words_in_row = sorted(row["words"], key=lambda w: w.x0)
        row_text = "  |  ".join(f"{w.text!r}@x{w.x0:.0f}" for w in words_in_row)
        log(f"  row {i:02d}  top={row['top']:6.1f}  words={len(row['words'])}  {row_text}")

    log(f"\n--- PARSED ROWS (column-assigned) ---")
    date_column = identify_date_column(layout)
    log(f"  date_column = {date_column!r}")
    for i, row in enumerate(rows[:50]):
        row_values = build_row(row["words"], layout)
        parsed = ParsedRow(y=row["top"], values=row_values, row_words=row["words"])
        if is_footer_row(parsed) or is_account_holder_row(parsed) or is_effectively_empty(parsed):
            log(f"  row {i:02d}  top={row['top']:6.1f}  [FILTERED]")
            continue
        is_txn = row_starts_transaction(parsed, date_column) if date_column else False
        vals = {k: v for k, v in row_values.items() if v.strip()}
        log(f"  row {i:02d}  top={row['top']:6.1f}  starts_txn={str(is_txn):5}  {vals}")

with open(output_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"\n[debug output saved to: {output_path}]")