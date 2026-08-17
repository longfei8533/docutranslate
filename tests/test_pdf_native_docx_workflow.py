from __future__ import annotations

from base64 import b64encode
from io import BytesIO
import logging

from docx import Document as DocxDocument
from PIL import Image
from pydantic import TypeAdapter, ValidationError
import pytest

from docutranslate.converter.md2docx import convert_markdown_to_native_docx
from docutranslate.core.factory import create_workflow_from_payload
from docutranslate.core.schemas import PdfNativeDocxWorkflowParams, TranslatePayload
from docutranslate.ir.markdown_document import MarkdownDocument
from docutranslate.workflow.pdf_native_docx_workflow import PdfNativeDocxWorkflow


def _payload(**overrides):
    values = {
        "workflow_type": "pdf_native_docx",
        "skip_translate": True,
        "convert_engine": "mineru_deploy",
        "mineru_deploy_base_url": "http://mineru:8000",
        "translation_review_enable": True,
    }
    values.update(overrides)
    return TypeAdapter(TranslatePayload).validate_python(values)


def test_pdf_native_docx_schema_accepts_only_mineru_engines():
    payload = _payload(mineru_deploy_backend="hybrid-engine")
    assert isinstance(payload, PdfNativeDocxWorkflowParams)
    assert payload.mineru_deploy_backend == "hybrid-engine"

    with pytest.raises(ValidationError):
        _payload(convert_engine="pypdf")


def test_factory_reuses_docx_translation_options():
    workflow = create_workflow_from_payload(_payload())

    assert isinstance(workflow, PdfNativeDocxWorkflow)
    translator = workflow.config.docx_workflow_config.translator_config
    assert translator.skip_translate is True
    assert translator.translation_review_enable is True
    assert workflow.config.convert_engine == "mineru_deploy"


def test_native_conversion_preserves_mineru_html_table_and_math():
    markdown = MarkdownDocument.from_bytes(
        content=(
            b"Before\n\n"
            b"<table><tr><td>METRIC</td><td>$<E_{o}$</td></tr>"
            b"<tr><td>HMS</td><td>$\\geq 9.3$</td></tr></table>\n\n"
            b"After\n"
        ),
        suffix=".md",
        stem="sample",
    )

    result = convert_markdown_to_native_docx(markdown)
    docx = DocxDocument(BytesIO(result.document.content))

    assert result.document.suffix == ".docx"
    assert len(docx.tables) == 1
    assert "<E" in "".join(cell.text for row in docx.tables[0].rows for cell in row.cells)
    assert result.diagnostics["converted_html_tables"] == 1
    assert result.diagnostics["validation"]["ast_to_docx_character_coverage"] == 1.0


def test_native_conversion_preserves_inline_images():
    image = BytesIO()
    Image.new("RGB", (2, 2), "red").save(image, format="PNG")
    markdown = MarkdownDocument.from_bytes(
        content=(
            "Before\n\n"
            f"![sample](data:image/png;base64,{b64encode(image.getvalue()).decode()})\n\n"
            "After\n"
        ).encode(),
        suffix=".md",
        stem="image-sample",
    )

    result = convert_markdown_to_native_docx(markdown)
    docx = DocxDocument(BytesIO(result.document.content))

    assert result.diagnostics["validation"]["expected_images"] == 1
    assert len(docx.inline_shapes) == 1
    assert result.diagnostics["validation"]["docx_inline_images"] == 1


@pytest.mark.asyncio
async def test_composite_workflow_returns_only_translated_docx(monkeypatch):
    class FakeMineruConverter:
        def __init__(self, _config):
            pass

        async def convert_async(self, document):
            return MarkdownDocument.from_bytes(
                content=b"# Heading\n\nBody text for translation.\n",
                suffix=".md",
                stem=document.stem,
            )

    payload = _payload()
    workflow = create_workflow_from_payload(payload, logger=logging.getLogger("test-native-docx"))
    monkeypatch.setitem(workflow._converter_factory, "mineru_deploy", FakeMineruConverter)
    workflow.read_bytes(b"%PDF-1.7\n", stem="sample", suffix=".pdf")

    await workflow.translate_async()

    exported = workflow.export_to_docx()
    result_docx = DocxDocument(BytesIO(exported))
    assert "Heading" in "\n".join(paragraph.text for paragraph in result_docx.paragraphs)
    assert workflow.get_attachment().attachment_dict == {}
    assert workflow.get_statistics()["conversion"]["validation"]["ast_to_docx_order_coverage"] == 1.0
