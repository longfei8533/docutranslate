"""PDF -> MinerU Markdown -> native DOCX -> DOCX translation workflow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from docutranslate.converter.md2docx import convert_markdown_to_native_docx
from docutranslate.converter.x2md.base import X2MarkdownConverter, X2MarkdownConverterConfig
from docutranslate.converter.x2md.converter_mineru import ConverterMineru
from docutranslate.converter.x2md.converter_mineru_deploy import ConverterMineruDeploy
from docutranslate.exporter.base import ExporterConfig
from docutranslate.exporter.docx.docx2docx_exporter import Docx2DocxExporter
from docutranslate.exporter.md.types import ConvertEngineType
from docutranslate.ir.document import Document
from docutranslate.workflow.base import Workflow, WorkflowConfig
from docutranslate.workflow.docx_workflow import DocxWorkflow, DocxWorkflowConfig
from docutranslate.workflow.interfaces import DocxExportable


@dataclass(kw_only=True)
class PdfNativeDocxWorkflowConfig(WorkflowConfig):
    convert_engine: ConvertEngineType
    converter_config: X2MarkdownConverterConfig
    docx_workflow_config: DocxWorkflowConfig


class PdfNativeDocxWorkflow(
    Workflow[PdfNativeDocxWorkflowConfig, Document, Document],
    DocxExportable[ExporterConfig],
):
    _converter_factory = {
        "mineru": ConverterMineru,
        "mineru_deploy": ConverterMineruDeploy,
    }

    def __init__(self, config: PdfNativeDocxWorkflowConfig):
        super().__init__(config=config)
        if config.convert_engine not in self._converter_factory:
            raise ValueError("pdf_native_docx only supports mineru and mineru_deploy")
        self._docx_workflow: DocxWorkflow | None = None
        self._conversion_diagnostics: dict = {}

    def _prepare(self) -> tuple[X2MarkdownConverter, Document]:
        if self.document_original is None:
            raise RuntimeError("File has not been read yet. Call read_path or read_bytes first.")
        if self.document_original.suffix.lower() != ".pdf":
            raise ValueError("pdf_native_docx only supports PDF input")
        converter_class = self._converter_factory[self.config.convert_engine]
        converter = converter_class(self.config.converter_config)
        return converter, self.document_original

    def _translate_docx(self, document: Document) -> DocxWorkflow:
        workflow = DocxWorkflow(self.config.docx_workflow_config)
        workflow.read_bytes(document.content, stem=document.stem or "document", suffix=".docx")
        workflow.translate()
        return workflow

    async def _translate_docx_async(self, document: Document) -> DocxWorkflow:
        workflow = DocxWorkflow(self.config.docx_workflow_config)
        workflow.read_bytes(document.content, stem=document.stem or "document", suffix=".docx")
        await workflow.translate_async()
        return workflow

    def _accept_docx_workflow(self, workflow: DocxWorkflow) -> None:
        self._docx_workflow = workflow
        self.document_translated = workflow.document_translated

    def translate(self) -> Self:
        converter, source = self._prepare()
        self.progress_tracker.update(percent=10, message="正在解析文档...")
        markdown = converter.convert(source)
        self.progress_tracker.update(percent=20, message="正在生成 Word...")
        converted = convert_markdown_to_native_docx(markdown, logger=self.logger)
        self._conversion_diagnostics = converted.diagnostics
        self._accept_docx_workflow(self._translate_docx(converted.document))
        return self

    async def translate_async(self) -> Self:
        converter, source = self._prepare()
        self.progress_tracker.update(percent=10, message="正在解析文档...")
        markdown = await converter.convert_async(source)
        self.progress_tracker.update(percent=20, message="正在生成 Word...")
        converted = await asyncio.to_thread(
            convert_markdown_to_native_docx,
            markdown,
            logger=self.logger,
        )
        self._conversion_diagnostics = converted.diagnostics
        self._accept_docx_workflow(await self._translate_docx_async(converted.document))
        return self

    def get_statistics(self) -> dict:
        statistics = self._docx_workflow.get_statistics() if self._docx_workflow else {}
        return {**statistics, "conversion": self._conversion_diagnostics}

    def export_to_docx(self, _: ExporterConfig | None = None) -> bytes:
        return self._export(Docx2DocxExporter()).content

    def save_as_docx(
        self,
        name: str | None = None,
        output_dir: Path | str = "./output",
        _: ExporterConfig | None = None,
    ) -> Self:
        self._save(exporter=Docx2DocxExporter(), name=name, output_dir=output_dir)
        return self
