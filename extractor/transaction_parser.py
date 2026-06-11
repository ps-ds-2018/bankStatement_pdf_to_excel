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

#Matches the start of a UPI/NEFT/IMPS/RTGS narration line.
#These lines always begin the narration block for the next transaction
#and should never be treated as continuations of the current one
_NARRATION_LEAD_PATTERN = re.compile(
    r"^(?:UPI|NEFT|IMPS|RTGS|INF|INFT|ACH|ECS|CHQ|CLG|ATM|POS|IFT|FT)[/\s\-]",
    re.IGNORECASE,
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
# NARRATION LEAD-IN DETECTION
# --------------------------------------------------

def _row_is_narration_lead(row: ParsedRow, narration_col: Optional[str]) -> bool:
    """"
    Returns True if this continuation row is the start of a new 
    transaction's narration lead-in (eg. 'UPI/...', 'NEFT/....').

    Once a narration-lead row is seen in the inter-anchor gap, all
    subsequent rows in that gap also belong to the next transaction.
    """
    if narration_col is None:
        return False
    text = row.values.get(narration_col,"").strip()
    return bool(_NARRATION_LEAD_PATTERN.match(text))


# --------------------------------------------------
# ANCHOR-FIRST BLOCK STRATEGY
# --------------------------------------------------

def _split_inter_anchor_rows(
        inter_rows: List[ParsedRow],
        narration_col: Optional[str],
) -> tuple[List[ParsedRow], List[ParsedRow]]:
    """"
    Split the rows between two anchors into:
    (post_rows, lead_in_rows)

    post_rows ---- continuation of the current (earlier) row
    lead_in_rows ---- lead-in narration for the next (later) row

    Split point: the first row that matches _NARRATION_LEAD_PATTERN.
    Everything before it --- post; it and everything after --- lead-in.
    """
    split_idx = len(inter_rows)   #default: all post, no lead-in

    for idx, row in enumerate(inter_rows):
        if _row_is_narration_lead(row, narration_col):
            split_idx = idx
            break

    return inter_rows[:split_idx], inter_rows[split_idx:]


def _find_narration_column(values: Dict[str, str]) -> Optional[str]:
    NARRATION_NAMES = {
        "PARTICULARS", "NARRATION", "DESCRIPTION",
        "TRANSACTION DETAILS", "DETAILS", "REMARKS",
    }

    for key in values:
        normalized = key.upper().replace(":", "").replace("*", "").strip()
        if normalized in NARRATION_NAMES:
            return key
    return None

def _collect_narration_text(
        rows: List[ParsedRow],
        narration_col: str,
) -> str:
    parts = []
    for row in rows:
        text = row.values.get(narration_col,"").strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def group_into_transaction_blocks(
        parsed_rows: List[ParsedRow],
        date_column: str,
) -> List[List[ParsedRow]]:
    """"
    Anchor-first block strategy.

    For each anchor row, collects the rows between the previous anchor
    and this one, splits them into post-anchor continuation rows (for
    the previous transaction) and lead-in rows (for this transaction), 
    then patches this anchor's PARTICULARS with the lead-in text 
    prepended.

    Returns blocks as [anchor_row, *post_anchor_continuation_rows].
    The lead-in narration is already baked into anchor_row.values.
    """
    anchor_indices = [
        idx for idx, row in enumerate(parsed_rows)
        if row_starts_transaction(row, date_column)
    ]

    if not anchor_indices:
        return []
    
    #Resolve narration column from the first anchor row
    narration_col = _find_narration_column(parsed_rows[anchor_indices[0]].values)

    blocks: List[List[ParsedRow]] = []

    for slot, anchor_idx in enumerate(anchor_indices):
        anchor_row = parsed_rows[anchor_idx]

        #Rows between the previous anchor (exclusive) and this one (exclusive)
        prev_anchor_idx = anchor_indices[slot - 1] if slot > 0 else -1
        inter_rows = parsed_rows[prev_anchor_idx + 1 : anchor_idx]

        #Split: rows before first UPI/NEFT/.... ----- post of previous txn
        #       rows from first UPI/NEFT/....   ----- lead-in of this txn
        _post_of_prev, lead_in_rows = _split_inter_anchor_rows(inter_rows, narration_col)

        #_post_of_prev was already appended to the previous block; we
        # record lead_in_rows here to patch the current anchor.

        #Patch anchor's PARTICULARS: preprend lead-in text
        if narration_col and lead_in_rows:
            lead_in_text = _collect_narration_text(lead_in_rows, narration_col)
            if lead_in_text:
                existing = anchor_row.values.get(narration_col, "").strip()
                anchor_row.values[narration_col] = (
                    (lead_in_text + " " + existing).strip() if existing else lead_in_text
                )


        #Rows after this anchor up to the next anchor (exclusive)
        if slot + 1 < len(anchor_indices):
            next_anchor_idx = anchor_indices[slot + 1]
        else:
            next_anchor_idx = len(parsed_rows)

        inter_after  = parsed_rows[anchor_idx + 1 : next_anchor_idx]
        
        #The post_rows for THIS block  = rows before the first narration-lead
        post_rows, _lead_in_of_next = _split_inter_anchor_rows(inter_after, narration_col)

        blocks.append([anchor_row] + post_rows)

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
    Collapses a block (anchor row + post-anchor continuation rows) into a single
    Transaction. 

    Lead-in narration was already merged into anchor_row.values by
    group_into_transaction_blocks(); only post-anchor remain here.
    """
    
    txn = Transaction(
        data=block[0].values.copy(),
        source_page=page_number,
    )

    for row in block[1:]:  
        for key, value in row.values.items():
            value = value.strip()
            if not value:
                continue

            if _is_numeric_column(key, layout):
                if _looks_like_amount(value):
                    txn.data[key] = value
                
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