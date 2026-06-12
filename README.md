# Savings Bank Statement PDF → Excel POC

PDF to Excel conversion engine for Indian bank savings account statement PDFs (ICICI, HDFC, and Bank of India) with scope to modify for other banks or updated formats in future.

## Features

- Password-protected PDF support
- Non-password PDF support
- Extract page text
- Extract word coordinates
- No OCR
- pdfplumber

## Installation

### Option 1: Using uv (Recommended)

```bash
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

#create and activate virtual environment
uv venv

# Linux / macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

# install dependencies
uv pip install -r requirements.txt
```

### Option 2: Using pip
```bash
#create virtual environment
python -m venv .venv

# Linux / macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate

# install dependencies
pip install -r requirements.txt
```

## Usage

#Add an output folder and then proceed with this

Without password:

```bash
uv run main.py pdf_name.pdf
or
python main.py pdf_name.pdf
```

With password:

```bash
uv run main.py pdf_name.pdf mypassword
or
python main.py pdf_name.pdf mypassword
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