"""Lightweight, local PDF text extraction for the platform integration."""

import asyncio
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

from docutranslate.converter.x2md.base import X2MarkdownConverter, X2MarkdownConverterConfig
from docutranslate.ir.document import Document
from docutranslate.ir.markdown_document import MarkdownDocument


@dataclass(kw_only=True)
class ConverterPyPdfConfig(X2MarkdownConverterConfig):
    def gethash(self):
        return "pypdf-v1"


class ConverterPyPdf(X2MarkdownConverter):
    def convert(self, document: Document) -> MarkdownDocument:
        reader = PdfReader(BytesIO(document.content))
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            pages.append(f"<!-- page: {index} -->\n\n{text}")
        content = "\n\n---\n\n".join(pages).encode("utf-8")
        return MarkdownDocument.from_bytes(content=content, suffix=".md", stem=document.stem)

    async def convert_async(self, document: Document) -> MarkdownDocument:
        return await asyncio.to_thread(self.convert, document)

    def support_format(self) -> list[str]:
        return [".pdf"]
