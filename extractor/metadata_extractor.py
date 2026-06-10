from __future__ import annotations

import re
from typing import List, Optional

from extractor.models import (
    Metadata,
    PDFPage,
)

#COMMON REGEX PATTERNS

ACCOUNT_NUMBER_PATTERNS = [

    re.compile(
        r'Account\s*Number\s*[:\-]?\s*([0-9Xx*]{8,30})',
        re.IGNORECASE
    ),

    re.compile(
        r'A\/C\s*No\.?\s*[:\-]?\s*([0-9Xx*]{8,30})',
        re.IGNORECASE
    ),

    re.compile(
        r'Account\s*No\.?\s*[:\-]?\s*([0-9Xx*]{8,30})',
        re.IGNORECASE
    ),
]


IFSC_PATTERN = re.compile(
    r'\b[A-Z]{4}0[A-Z0-9]{6}\b'
)

STATEMENT_PERIOD_PATTERNS = [

    re.compile(
        r'From\s*[:\-]?\s*(.*?)\s*To\s*[:\-]?\s*(.*)',
        re.IGNORECASE
    ),

    re.compile(
        r'Statement\s*Period\s*[:\-]?\s*(.*)',
        re.IGNORECASE
    ),
]

#BALANCE PATTERN

OPENING_BALANCE_PATTERNS = [

    re.compile(
        r'Opening\s*Balance\s*[:\-]?\s*([0-9,.\-]+)',
        re.IGNORECASE
    ),

    re.compile(
        r'Opening\s*Bal(?:ance)?\s*[:\-]?\s*([0-9,.\-]+)',
        re.IGNORECASE
    ),

    re.compile(
        r'Op\s*Bal\s*[:\-]?\s*([0-9,.\-]+)',
        re.IGNORECASE
    ),
]

CLOSING_BALANCE_PATTERNS = [

    re.compile(
        r'Closing\s*Balance\s*[:\-]?\s*([0-9,.\-]+)',
        re.IGNORECASE
    ),

    re.compile(
        r'Closing\s*Bal(?:ance)?\s*[:\-]?\s*([0-9,.\-]+)',
        re.IGNORECASE
    ),

    re.compile(
        r'Cl\s*Bal\s*[:\-]?\s*([0-9,.\-]+)',
        re.IGNORECASE
    ),
]

#NORMALIZE WHITESPACE

def clean_text(text: str) -> str:

    return re.sub(
        r'\s+',
        ' ',
        text
    ).strip()

#FIRST MATCH HELPER

def first_match(
    patterns,
    text: str
) -> str:

    for pattern in patterns:

        match = pattern.search(text)

        if match:
            return clean_text(
                match.group(1)
            )

    return ""

#EXTRACT ACCOUNT NUMBER

def extract_account_number(
    text: str
) -> str:

    return first_match(
        ACCOUNT_NUMBER_PATTERNS,
        text
    )

#EXTRACT IFSC

def extract_ifsc(
    text: str
) -> str:

    match = IFSC_PATTERN.search(text)

    if match:
        return match.group(0)

    return ""

#EXTRACT STATEMENT PERIOD

def extract_statement_period(
    text: str
) -> str:

    for pattern in STATEMENT_PERIOD_PATTERNS:

        match = pattern.search(text)

        if match:

            if len(match.groups()) == 2:

                return (
                    clean_text(match.group(1))
                    + " to "
                    + clean_text(match.group(2))
                )

            return clean_text(
                match.group(1)
            )

    return ""

#EXTRACT OPERNING BALANCE

def extract_opening_balance(
    text: str
) -> str:

    return first_match(
        OPENING_BALANCE_PATTERNS,
        text
    )

#EXTRACT CLOSING BALANCE

def extract_closing_balance(
    text: str
) -> str:

    return first_match(
        CLOSING_BALANCE_PATTERNS,
        text
    )

#EXTRACT ACCOUNT HOLDER NAME

#CANDIDATE RULES

BANK_WORDS = {

    "STATEMENT",
    "ACCOUNT",
    "BANK",
    "DETAILS",
    "BRANCH",
    "PERIOD",
    "DATE",
    "BALANCE",
    "SUMMARY",
}

def looks_like_name(
    line: str
) -> bool:

    line = clean_text(line)

    if not line:
        return False

    words = line.split()

    if len(words) < 2:
        return False

    if len(words) > 5:
        return False

    alpha_ratio = (
        sum(
            c.isalpha()
            for c in line
        )
        / max(len(line), 1)
    )

    if alpha_ratio < 0.7:
        return False

    upper = line.upper()

    for keyword in BANK_WORDS:

        if keyword in upper:
            return False

    return True

#EXTRACT NAME

def extract_account_holder_name(
    pages: List[PDFPage]
) -> str:

    first_page = pages[0]

    lines = [
        clean_text(line)
        for line in first_page.text.splitlines()
    ]

    for idx, line in enumerate(lines):

        if (
            "CUSTOMER NAME"
            in line.upper()
        ):

            if idx + 1 < len(lines):

                candidate = lines[idx + 1]

                if looks_like_name(
                    candidate
                ):
                    return candidate

    for idx, line in enumerate(lines):

        if (
            "ACCOUNT"
            in line.upper()
            and
            "STATEMENT"
            in line.upper()
        ):

            for j in range(
                idx + 1,
                min(idx + 6, len(lines))
            ):

                candidate = lines[j]

                if looks_like_name(
                    candidate
                ):
                    return candidate

    for line in lines[:20]:

        if looks_like_name(line):
            return line

    return ""

#BRANCH EXTRACTION

BRANCH_PATTERNS = [

    re.compile(
        r'Branch\s*[:\-]?\s*(.*)',
        re.IGNORECASE
    ),

    re.compile(
        r'Home\s*Branch\s*[:\-]?\s*(.*)',
        re.IGNORECASE
    ),
]

def extract_branch(
    text: str
) -> str:

    return first_match(
        BRANCH_PATTERNS,
        text
    )

#MAIN EXTRACTOR

class MetadataExtractor:

    @staticmethod
    def extract(
        pages: List[PDFPage]
    ) -> Metadata:

        full_text = "\n".join(
            page.text
            for page in pages
        )

        metadata = Metadata()

        metadata.account_holder_name = (
            extract_account_holder_name(
                pages
            )
        )

        metadata.account_number = (
            extract_account_number(
                full_text
            )
        )

        metadata.statement_period = (
            extract_statement_period(
                full_text
            )
        )

        metadata.ifsc = (
            extract_ifsc(
                full_text
            )
        )

        metadata.branch = (
            extract_branch(
                full_text
            )
        )

        metadata.opening_balance = (
            extract_opening_balance(
                full_text
            )
        )

        metadata.closing_balance = (
            extract_closing_balance(
                full_text
            )
        )

        return metadata