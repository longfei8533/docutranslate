"""Conservative MinerU Markdown to native DOCX conversion.

The converter deliberately gives up fixed PDF coordinates. Body text becomes
native Word paragraphs, tables become native Word tables, and pictures remain
inline objects. Conversion fails if text or supported structure disappears,
reorders, or becomes floating content.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile

from docx import Document as DocxDocument
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from docutranslate.ir.document import Document
from docutranslate.ir.markdown_document import MarkdownDocument


TABLE_RE = re.compile(r"<table\b.*?</table>", re.I | re.S)
INLINE_MATH_RE = re.compile(r"(?<!\\)\$(?!\$)(.*?)(?<!\\)\$", re.S)
CONVERTED_HTML_TABLE_CLASS = "mineru-converted-html-table"
MIN_HTML_TABLE_CHARACTER_COVERAGE = 0.999


@dataclass(frozen=True, slots=True)
class NativeDocxConversionResult:
    document: Document
    diagnostics: dict[str, Any]


class _VisibleHtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _run(
    command: list[str],
    *,
    cwd: Path,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def _extract_table_placeholders(source: str) -> tuple[str, dict[str, str]]:
    tables: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        marker = f"MINERU_NATIVE_TABLE_{len(tables):06d}"
        tables[marker] = match.group(0)
        return f"\n\n{marker}\n\n"

    return TABLE_RE.sub(replace, source), tables


def _pandoc_ast(markdown: str, cwd: Path) -> dict[str, Any]:
    result = _run(
        ["pandoc", "--from=markdown+raw_html+tex_math_dollars+raw_tex", "--to=json"],
        cwd=cwd,
        input_text=markdown,
    )
    if result.returncode:
        raise RuntimeError(f"Pandoc could not parse MinerU Markdown: {result.stderr[:1000]}")
    return json.loads(result.stdout)


def _html_table_blocks(raw_html: str, cwd: Path) -> list[dict[str, Any]]:
    result = _run(["pandoc", "--from=html", "--to=json"], cwd=cwd, input_text=raw_html)
    if result.returncode:
        return []
    return json.loads(result.stdout).get("blocks", [])


def _escape_math_angle_brackets_in_html(raw_html: str) -> str:
    return INLINE_MATH_RE.sub(
        lambda match: "$" + match.group(1).replace("<", "&lt;").replace(">", "&gt;") + "$",
        raw_html,
    )


def _html_visible_text(raw_html: str) -> str:
    parser = _VisibleHtmlTextParser()
    parser.feed(raw_html)
    parser.close()
    return "".join(parser.parts)


def _mark_converted_html_table(block: dict[str, Any]) -> None:
    if block.get("t") != "Table":
        raise ValueError("Only Pandoc Table blocks can be marked as converted HTML tables")
    content = block.get("c")
    if not isinstance(content, list) or not content:
        raise RuntimeError("Pandoc Table block has no attribute tuple")
    attributes = content[0]
    if not isinstance(attributes, list) or len(attributes) != 3:
        raise RuntimeError("Pandoc Table block has an unexpected attribute tuple")
    classes = attributes[1]
    if not isinstance(classes, list):
        raise RuntimeError("Pandoc Table block has an unexpected class list")
    if CONVERTED_HTML_TABLE_CLASS not in classes:
        classes.append(CONVERTED_HTML_TABLE_CLASS)


def _is_converted_html_table(block: dict[str, Any]) -> bool:
    if block.get("t") != "Table":
        return False
    content = block.get("c")
    if not isinstance(content, list) or not content:
        return False
    attributes = content[0]
    return (
        isinstance(attributes, list)
        and len(attributes) == 3
        and isinstance(attributes[1], list)
        and CONVERTED_HTML_TABLE_CLASS in attributes[1]
    )


def _stringify(value: Any) -> str:
    if isinstance(value, dict):
        kind = value.get("t")
        if kind in {"Str", "Code", "Math"}:
            content = value.get("c", "")
            return content[-1] if kind == "Math" and isinstance(content, list) else str(content)
        if kind in {"Space", "SoftBreak", "LineBreak"}:
            return " "
        return _stringify(value.get("c"))
    if isinstance(value, list):
        return "".join(_stringify(item) for item in value)
    return ""


def _normalize_nested_linebreaks(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("t") == "LineBreak":
            return {"t": "Space"}
        return {key: _normalize_nested_linebreaks(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_nested_linebreaks(item) for item in value]
    return value


def _count_nodes(value: Any, kind: str) -> int:
    if isinstance(value, dict):
        return int(value.get("t") == kind) + _count_nodes(value.get("c"), kind)
    if isinstance(value, list):
        return sum(_count_nodes(item, kind) for item in value)
    return 0


def _count_preformatted_linebreaks(value: Any) -> int:
    if isinstance(value, dict):
        if value.get("t") == "CodeBlock":
            content = value.get("c", [None, ""])
            return str(content[1] if isinstance(content, list) and len(content) > 1 else "").count("\n")
        return _count_preformatted_linebreaks(value.get("c"))
    if isinstance(value, list):
        return sum(_count_preformatted_linebreaks(item) for item in value)
    return 0


def _audit_chars(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _ordered_subsequence_coverage(source: str, target: str) -> float:
    source_chars, target_chars = _audit_chars(source), _audit_chars(target)
    if not source_chars:
        return 1.0
    source_index = 0
    for char in target_chars:
        if source_index < len(source_chars) and source_chars[source_index] == char:
            source_index += 1
    return source_index / len(source_chars)


def _multiset_coverage(source: str, target: str) -> float:
    source_counter, target_counter = Counter(_audit_chars(source)), Counter(_audit_chars(target))
    if not source_counter:
        return 1.0
    return sum((source_counter & target_counter).values()) / sum(source_counter.values())


def _ordered_ast_prose(value: Any, *, skip_converted_html_tables: bool = False) -> str:
    if isinstance(value, dict):
        kind = value.get("t")
        if skip_converted_html_tables and _is_converted_html_table(value):
            return ""
        if kind in {"Str", "Code"}:
            content = value.get("c", "")
            return str(content[-1] if kind == "Code" and isinstance(content, list) else content)
        if kind in {"Math", "Image", "RawBlock", "RawInline"}:
            return ""
        if kind == "Header":
            return _ordered_ast_prose(
                value.get("c", [None, None, []])[2],
                skip_converted_html_tables=skip_converted_html_tables,
            )
        if kind in {"Link", "Span"}:
            return _ordered_ast_prose(
                value.get("c", [None, []])[1],
                skip_converted_html_tables=skip_converted_html_tables,
            )
        if kind == "Div":
            return _ordered_ast_prose(
                value.get("c", [None, []])[1],
                skip_converted_html_tables=skip_converted_html_tables,
            )
        if kind in {"Space", "SoftBreak", "LineBreak"}:
            return " "
        return _ordered_ast_prose(value.get("c"), skip_converted_html_tables=skip_converted_html_tables)
    if isinstance(value, list):
        return "".join(
            _ordered_ast_prose(item, skip_converted_html_tables=skip_converted_html_tables)
            for item in value
        )
    return ""


def _prose_without_table_markers(ast: dict[str, Any], markers: set[str]) -> str:
    parts: list[str] = []
    consumed: set[str] = set()
    for block in ast.get("blocks", []):
        marker = _stringify(block).strip() if block.get("t") in {"Para", "Plain"} else ""
        if marker in markers:
            consumed.add(marker)
            continue
        parts.append(_ordered_ast_prose(block))
    missing = markers - consumed
    if missing:
        raise RuntimeError(f"Table placeholders were not found: {sorted(missing)[:10]}")
    return "".join(parts)


def _transform_ast_conservative(
    ast: dict[str, Any], cwd: Path, table_sources: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    transformed: list[dict[str, Any]] = []
    converted_tables = 0
    consumed_markers: set[str] = set()
    linebreaks = _count_nodes(ast.get("blocks", []), "LineBreak")
    table_order_coverages: list[float] = []
    table_character_coverages: list[float] = []
    table_reverse_character_coverages: list[float] = []

    for block in ast.get("blocks", []):
        marker = _stringify(block).strip() if block.get("t") in {"Para", "Plain"} else ""
        if marker in table_sources:
            sanitized_html = _escape_math_angle_brackets_in_html(table_sources[marker])
            replacement = _html_table_blocks(sanitized_html, cwd)
            tables = [item for item in replacement if item.get("t") == "Table"]
            if not replacement or not tables:
                raise RuntimeError(f"Pandoc could not convert HTML table {marker}")
            source_table_text = _html_visible_text(sanitized_html)
            ast_table_text = _ordered_ast_prose(tables)
            order_coverage = _ordered_subsequence_coverage(source_table_text, ast_table_text)
            character_coverage = _multiset_coverage(source_table_text, ast_table_text)
            reverse_character_coverage = _multiset_coverage(ast_table_text, source_table_text)
            table_order_coverages.append(order_coverage)
            table_character_coverages.append(character_coverage)
            table_reverse_character_coverages.append(reverse_character_coverage)
            if min(character_coverage, reverse_character_coverage) < MIN_HTML_TABLE_CHARACTER_COVERAGE:
                raise RuntimeError(
                    f"HTML table text coverage failed for {marker}: "
                    f"source_to_ast={character_coverage:.8f}, "
                    f"ast_to_source={reverse_character_coverage:.8f}"
                )
            for table in tables:
                _mark_converted_html_table(table)
            transformed.extend(_normalize_nested_linebreaks(item) for item in replacement)
            converted_tables += len(tables)
            consumed_markers.add(marker)
            continue
        transformed.append(_normalize_nested_linebreaks(block))

    missing_markers = sorted(set(table_sources) - consumed_markers)
    if missing_markers:
        raise RuntimeError(f"Table placeholders were not consumed: {missing_markers[:10]}")
    ast["blocks"] = transformed
    return ast, {
        "mode": "conservative-lossless",
        "deleted_blocks": 0,
        "merged_paragraphs": 0,
        "split_paragraphs": 0,
        "promoted_headings": 0,
        "linebreaks_replaced_with_spaces": linebreaks,
        "converted_html_tables": converted_tables,
        "native_ast_tables": sum(block.get("t") == "Table" for block in transformed),
        "html_table_source_to_ast_order_coverage": round(min(table_order_coverages, default=1.0), 8),
        "html_table_source_to_ast_character_coverage": round(
            min(table_character_coverages, default=1.0), 8
        ),
        "html_table_ast_to_source_character_coverage": round(
            min(table_reverse_character_coverages, default=1.0), 8
        ),
    }


def _set_run_font(run: Any, latin: str, east_asia: str, size: float | None = None) -> None:
    run.font.name = latin
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), east_asia)
    if size:
        run.font.size = Pt(size)


def _set_table_borders(table: Any) -> None:
    table_properties = table._tbl.tblPr
    borders = table_properties.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        table_properties.append(borders)
    for edge_name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        edge = borders.find(qn(f"w:{edge_name}"))
        if edge is None:
            edge = OxmlElement(f"w:{edge_name}")
            borders.append(edge)
        edge.set(qn("w:val"), "single")
        edge.set(qn("w:sz"), "6")
        edge.set(qn("w:space"), "0")
        edge.set(qn("w:color"), "000000")


def _style_docx(path: Path) -> dict[str, int]:
    doc = DocxDocument(path)

    def named_style(name: str) -> Any:
        return next(style for style in doc.styles if style.name == name)

    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(2.7)
    section.right_margin = Cm(2.7)

    for body_style_name in ("Normal", "Body Text", "First Paragraph"):
        body_style = named_style(body_style_name)
        body_style.font.name = "Times New Roman"
        body_style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "宋体")
        body_style.font.size = Pt(10.5)
        body_style.paragraph_format.line_spacing = 1.5
        body_style.paragraph_format.space_after = Pt(3)
        body_style.paragraph_format.first_line_indent = Cm(0.74)

    heading_specs = {1: (16, "黑体"), 2: (14, "黑体"), 3: (12, "黑体"), 4: (10.5, "黑体")}
    for level, (size, east_asia) in heading_specs.items():
        style = named_style(f"Heading {level}")
        style.font.name = "Arial"
        style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), east_asia)
        style.font.size = Pt(size)
        style.font.bold = True
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.first_line_indent = Cm(0)

    if "Caption" not in [style.name for style in doc.styles]:
        doc.styles.add_style("Caption", WD_STYLE_TYPE.PARAGRAPH)
    caption = named_style("Caption")
    caption.font.name = "Times New Roman"
    caption._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "宋体")
    caption.font.size = Pt(9)
    caption.paragraph_format.first_line_indent = Cm(0)

    body_paragraphs = 0
    caption_paragraphs = 0
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        contains_drawing = bool(paragraph._p.xpath(".//w:drawing"))
        if contains_drawing:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.first_line_indent = Cm(0)
        elif re.match(r"^(?:附?图|Figure)\s*\d", text, re.I):
            paragraph.style = caption
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            caption_paragraphs += 1
        elif paragraph.style.name in {"Normal", "Body Text", "First Paragraph"} and text:
            body_paragraphs += 1

    max_width = section.page_width - section.left_margin - section.right_margin
    resized_images = 0
    for shape in doc.inline_shapes:
        if shape.width > max_width:
            ratio = max_width / shape.width
            shape.width = max_width
            shape.height = int(shape.height * ratio)
            resized_images += 1

    for table in doc.tables:
        table.autofit = True
        _set_table_borders(table)
        for row in table.rows:
            row_properties = row._tr.get_or_add_trPr()
            if row_properties.find(qn("w:cantSplit")) is None:
                row_properties.append(OxmlElement("w:cantSplit"))
            for cell in row.cells:
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                for paragraph in cell.paragraphs:
                    paragraph.paragraph_format.first_line_indent = Cm(0)
                    paragraph.paragraph_format.line_spacing = 1.0
                    paragraph.paragraph_format.space_after = Pt(0)
                    for run in paragraph.runs:
                        _set_run_font(run, "Times New Roman", "宋体", 9)

    doc.core_properties.comments = "Translation-friendly native flow; no floating text boxes."
    doc.save(path)
    return {
        "body_paragraphs": body_paragraphs,
        "native_tables": len(doc.tables),
        "inline_images": len(doc.inline_shapes),
        "resized_images": resized_images,
        "caption_paragraphs": caption_paragraphs,
    }


def _validate_conservative_output(
    target: Path, non_table_source_prose: str, transformed_ast: dict[str, Any]
) -> dict[str, Any]:
    transformed_non_table_prose = _ordered_ast_prose(
        transformed_ast.get("blocks", []), skip_converted_html_tables=True
    )
    transformed_prose = _ordered_ast_prose(transformed_ast.get("blocks", []))
    ast_order = _ordered_subsequence_coverage(non_table_source_prose, transformed_non_table_prose)
    ast_chars = _multiset_coverage(non_table_source_prose, transformed_non_table_prose)

    with ZipFile(target) as archive:
        xml_bytes = archive.read("word/document.xml")
    document_xml = xml_bytes.decode("utf-8")
    root = ElementTree.fromstring(xml_bytes)
    word_text_tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
    docx_text = "".join(node.text or "" for node in root.iter(word_text_tag))
    docx_order = _ordered_subsequence_coverage(transformed_prose, docx_text)
    docx_chars = _multiset_coverage(transformed_prose, docx_text)
    doc = DocxDocument(target)
    expected_tables = _count_nodes(transformed_ast.get("blocks", []), "Table")
    expected_images = _count_nodes(transformed_ast.get("blocks", []), "Image")
    expected_manual_linebreaks = _count_preformatted_linebreaks(transformed_ast.get("blocks", []))
    actual_manual_linebreaks = document_xml.count("<w:br")

    validation = {
        "original_to_ast_order_coverage": round(ast_order, 8),
        "original_to_ast_character_coverage": round(ast_chars, 8),
        "original_to_ast_validation_scope": "non-html-table-prose",
        "ast_to_docx_order_coverage": round(docx_order, 8),
        "ast_to_docx_character_coverage": round(docx_chars, 8),
        "expected_tables": expected_tables,
        "docx_tables": len(doc.tables),
        "expected_images": expected_images,
        "docx_inline_images": len(doc.inline_shapes),
        "text_boxes": document_xml.count("<w:txbxContent") + document_xml.count("<v:textbox"),
        "floating_anchors": document_xml.count("<wp:anchor"),
        "expected_preformatted_linebreaks": expected_manual_linebreaks,
        "manual_linebreaks": actual_manual_linebreaks,
        "unexpected_manual_linebreaks": actual_manual_linebreaks - expected_manual_linebreaks,
    }
    failed = [
        ast_order < 1.0,
        ast_chars < 1.0,
        docx_order < 1.0,
        docx_chars < 1.0,
        expected_tables != len(doc.tables),
        expected_images != len(doc.inline_shapes),
        validation["text_boxes"] != 0,
        validation["floating_anchors"] != 0,
        validation["unexpected_manual_linebreaks"] != 0,
    ]
    if any(failed):
        raise RuntimeError(f"Conservative DOCX validation failed: {validation}")
    return validation


def convert_markdown_to_native_docx(
    document: MarkdownDocument,
    *,
    logger: logging.Logger | None = None,
) -> NativeDocxConversionResult:
    """Convert MinerU Markdown to a validated, translation-friendly DOCX."""
    if shutil.which("pandoc") is None:
        raise RuntimeError("Pandoc is required for the native DOCX route")
    try:
        source_text = document.content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError("MinerU Markdown must be UTF-8") from exc
    if not source_text.strip():
        raise RuntimeError("MinerU Markdown is empty")

    with tempfile.TemporaryDirectory(prefix="docutranslate-native-docx-") as temporary:
        workdir = Path(temporary)
        placeholder_markdown, table_sources = _extract_table_placeholders(source_text)
        ast = _pandoc_ast(placeholder_markdown, workdir)
        non_table_source_prose = _prose_without_table_markers(ast, set(table_sources))
        ast, diagnostics = _transform_ast_conservative(ast, workdir, table_sources)
        ast_path = workdir / "document.ast.json"
        ast_path.write_text(json.dumps(ast, ensure_ascii=False), encoding="utf-8")
        target = workdir / "document.docx"
        result = _run(
            ["pandoc", str(ast_path), "--from=json", "--to=docx", "--output", str(target)],
            cwd=workdir,
        )
        if result.returncode or not target.is_file():
            raise RuntimeError(f"Pandoc could not generate native DOCX: {result.stderr[:1000]}")
        style_stats = _style_docx(target)
        validation = _validate_conservative_output(target, non_table_source_prose, ast)
        if logger:
            logger.info(
                "Native DOCX conversion passed conservative validation",
                extra={"conversion": {**diagnostics, **style_stats, "validation": validation}},
            )
        return NativeDocxConversionResult(
            document=Document.from_bytes(
                content=target.read_bytes(),
                suffix=".docx",
                stem=document.stem,
            ),
            diagnostics={**diagnostics, **style_stats, "validation": validation},
        )
