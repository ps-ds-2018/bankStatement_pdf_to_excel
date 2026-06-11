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
        """
        Validates PDF access.

        Many Indian bank statement PDFs are technically "encrypted"
        with a blank-string owner password for permissions metadata,
        even though they require no password to open. pypdf marks
        these as is_encrypted=True. We handle this by always trying
        an empty-string decrypt first before raising an error.
        """
        reader = PdfReader(pdf_path)

        if reader.is_encrypted:
            # Always try blank password first — covers permission-only
            # encrypted PDFs that open without a real password.
            result = reader.decrypt(password or "")

            if result == 0:
                # Blank didn't work. If the caller supplied a real
                # password it's genuinely wrong; otherwise prompt them.
                if password:
                    raise ValueError("Invalid PDF password.")
                else:
                    raise ValueError(
                        "PDF is encrypted. Password required."
                    )

    @staticmethod
    def read_pdf(
        pdf_path: str,
        password: Optional[str] = None
    ) -> List[PDFPage]:

        PDFReader.validate_pdf(pdf_path, password)

        pages: List[PDFPage] = []

        # pdfplumber also needs the password (or "" for blank-encrypted).
        open_password = password or ""

        with pdfplumber.open(
            pdf_path,
            password=open_password
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