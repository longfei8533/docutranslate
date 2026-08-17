"""Markdown to translation-friendly native DOCX conversion."""

from docutranslate.converter.md2docx.native_docx import (
    NativeDocxConversionResult,
    convert_markdown_to_native_docx,
)

__all__ = ["NativeDocxConversionResult", "convert_markdown_to_native_docx"]
