# Bank Statement PDF → Excel POC

Deterministic extraction engine for Indian bank statement PDFs.

## Features

- Password-protected PDF support
- Non-password PDF support
- Extract page text
- Extract word coordinates
- No OCR
- No AI
- No ML
- No Camelot
- No Tabula

## Installation

```bash
python -m venv .venv

source .venv/bin/activate
# Windows:
# .venv\Scripts\activate

pip install -r requirements.txt
```

## Usage

Without password:

```bash
python main.py statement.pdf
```

With password:

```bash
python main.py statement.pdf mypassword
```

Output:

```text
output/
└── statement_output.xlsx
```

Workbook sheets:

- Metadata
- Transactions
- Warnings