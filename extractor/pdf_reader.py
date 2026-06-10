from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pdfplumber
from pypdf import PdfReader

from extractor.models import PDFPage, Word


class PDFReader:
    """
    Reads digital PDFs using pdfplumber.

    Returns:
        page text
        page words
        word coordinates

    Does not use OCR.
    """

    @staticmethod
    def validate_pdf(
        pdf_path: str,
        password: Optional[str] = None
    ) -> None:

        reader = PdfReader(pdf_path)

        if reader.is_encrypted:
            if not password:
                raise ValueError(
                    "PDF is encrypted. Password required."
                )

            result = reader.decrypt(password)

            if result == 0:
                raise ValueError(
                    "Invalid PDF password."
                )

    @staticmethod
    def read_pdf(
        pdf_path: str,
        password: Optional[str] = None
    ) -> List[PDFPage]:

        PDFReader.validate_pdf(pdf_path, password)

        pages: List[PDFPage] = []

        with pdfplumber.open(
            pdf_path,
            password=password
        ) as pdf:

            for page_index, page in enumerate(pdf.pages, start=1):

                text = page.extract_text() or ""

                words = []

                for w in page.extract_words():

                    words.append(
                        Word(
                            text=w.get("text", ""),
                            x0=float(w.get("x0", 0)),
                            x1=float(w.get("x1", 0)),
                            top=float(w.get("top", 0)),
                            bottom=float(w.get("bottom", 0)),
                        )
                    )

                pages.append(
                    PDFPage(
                        page_number=page_index,
                        text=text,
                        width=float(page.width),
                        height=float(page.height),
                        words=words,
                    )
                )

        return pages


def read_pdf(
    pdf_path: str,
    password: Optional[str] = None
) -> List[PDFPage]:

    return PDFReader.read_pdf(
        pdf_path=pdf_path,
        password=password
    )