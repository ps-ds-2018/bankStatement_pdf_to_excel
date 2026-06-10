from typing import List, Dict, Optional

from pydantic import BaseModel, Field


class Word(BaseModel):
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


class PDFPage(BaseModel):
    page_number: int
    text: str
    words: List[Word]


class Metadata(BaseModel):
    account_holder_name: str = ""
    account_number: str = ""
    statement_period: str = ""
    ifsc: str = ""
    branch: str = ""
    opening_balance: str = ""
    closing_balance: str = ""


class Transaction(BaseModel):
    data: Dict[str, str] = Field(default_factory=dict)
    source_page: int = 0


class WarningItem(BaseModel):
    page: int
    transaction: str
    issue: str
    severity: str = "INFO"


class ExtractionResult(BaseModel):
    metadata: Metadata
    transactions: List[Transaction]
    warnings: List[WarningItem]

class ColumnBoundary(BaseModel):
    header: str
    x0: float
    x1: float

class PDFPage(BaseModel):
    page_number: int
    text: str
    width: float
    height: float
    words: List[Word]