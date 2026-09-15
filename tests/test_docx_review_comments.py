from io import BytesIO
import zipfile

import pytest
from docx import Document as DocxDocument
from lxml import etree

from docutranslate.ir.document import Document
from docutranslate.translator.ai_translator.docx_translator import (
    DocxTranslator,
    DocxTranslatorConfig,
)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W_NS, "pr": REL_NS}


def build_source_docx() -> bytes:
    doc = DocxDocument()
    paragraph = doc.add_paragraph("Hello world")
    doc.add_comment(paragraph.runs[0], "Existing", author="Human", initials="H")
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "Payment terms"
    doc.sections[0].header.paragraphs[0].text = "Header text"
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def translate_with_comments(insert_mode: str) -> bytes:
    translator = DocxTranslator(DocxTranslatorConfig(
        skip_translate=True,
        insert_mode=insert_mode,
        separator="\n",
    ))
    source = Document(content=build_source_docx(), suffix=".docx")
    doc, elements, originals = translator._pre_translate(source)
    translated = [f"译文-{index}" for index in range(len(originals))]
    reviews = {index: f"审校意见-{index}" for index in range(len(originals))}
    return translator._after_translate(doc, elements, translated, originals, reviews)


@pytest.mark.parametrize("insert_mode", ["replace", "append", "prepend"])
def test_review_comments_are_word_comments_and_preserve_existing_comments(insert_mode):
    output = translate_with_comments(insert_mode)
    with zipfile.ZipFile(BytesIO(output)) as package:
        comments = etree.fromstring(package.read("word/comments.xml"))
        comment_nodes = comments.xpath(".//w:comment", namespaces=NS)
        authors = [node.get(f"{{{W_NS}}}author") for node in comment_nodes]
        assert authors.count("Human") == 1
        assert authors.count("AI Review") == 3

        ids = [node.get(f"{{{W_NS}}}id") for node in comment_nodes]
        assert len(ids) == len(set(ids))

        all_story_xml = b"".join(
            package.read(name)
            for name in package.namelist()
            if name == "word/document.xml" or name.startswith("word/header")
        )
        for comment_id in ids:
            assert f'w:id="{comment_id}"'.encode() in all_story_xml

        rels = etree.fromstring(package.read("word/_rels/document.xml.rels"))
        assert rels.xpath(
            ".//pr:Relationship[contains(@Type, '/comments')]", namespaces=NS
        )
        header_rels = etree.fromstring(package.read("word/_rels/header1.xml.rels"))
        assert header_rels.xpath(
            ".//pr:Relationship[contains(@Type, '/comments')]", namespaces=NS
        )
        content_types = package.read("[Content_Types].xml")
        assert b"/word/comments.xml" in content_types


def test_disabled_review_does_not_add_ai_review_comments():
    translator = DocxTranslator(DocxTranslatorConfig(skip_translate=True))
    source = Document(content=build_source_docx(), suffix=".docx")
    doc, elements, originals = translator._pre_translate(source)
    output = translator._after_translate(doc, elements, originals, originals, {})
    with zipfile.ZipFile(BytesIO(output)) as package:
        comments = etree.fromstring(package.read("word/comments.xml"))
        authors = comments.xpath(".//w:comment/@w:author", namespaces=NS)
        assert authors == ["Human"]


def docx_bytes(doc):
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize('shape', [(1, 5), (5, 1), (2, 3)])
@pytest.mark.parametrize('insert_mode', ['replace', 'append', 'prepend'])
def test_merged_cell_is_translated_and_reviewed_once(shape, insert_mode):
    doc = DocxDocument()
    rows, cols = shape
    table = doc.add_table(rows=rows, cols=cols)
    cell = table.cell(0, 0).merge(table.cell(rows - 1, cols - 1))
    cell.text = 'Single merged passage'
    translator = DocxTranslator(DocxTranslatorConfig(skip_translate=True, insert_mode=insert_mode))
    parsed, elements, texts = translator._pre_translate(Document(content=docx_bytes(doc), suffix='.docx'))
    assert texts == ['Single merged passage']
    output = translator._after_translate(parsed, elements, ['唯一译文'], texts, {0: 'One issue'})
    with zipfile.ZipFile(BytesIO(output)) as package:
        comments = etree.fromstring(package.read('word/comments.xml'))
        body = etree.fromstring(package.read('word/document.xml'))
        assert len(comments) == 1
        assert body.xpath('.//w:t/text()', namespaces=NS).count('唯一译文') == 1


def test_nested_merged_cells_and_distinct_identical_passages():
    doc = DocxDocument()
    table = doc.add_table(rows=1, cols=3)
    cell = table.cell(0, 0).merge(table.cell(0, 2))
    nested = cell.add_table(rows=1, cols=2)
    nested.cell(0, 0).merge(nested.cell(0, 1)).text = 'Repeated wording'
    doc.add_paragraph('Repeated wording')
    translator = DocxTranslator(DocxTranslatorConfig(skip_translate=True))
    _, elements, texts = translator._pre_translate(Document(content=docx_bytes(doc), suffix='.docx'))
    assert texts == ['Repeated wording', 'Repeated wording']
    assert len({e['paragraph']._p for e in elements}) == 2


def test_shared_headers_are_extracted_once_and_state_resets_between_documents():
    doc = DocxDocument()
    doc.sections[0].header.paragraphs[0].text = 'Shared header'
    doc.add_section()
    translator = DocxTranslator(DocxTranslatorConfig(skip_translate=True))
    for _ in range(2):
        _, _, texts = translator._pre_translate(Document(content=docx_bytes(doc), suffix='.docx'))
        assert texts == ['Shared header']


def test_duplicate_anchor_comments_are_suppressed_without_losing_distinct_issues():
    doc = DocxDocument()
    doc.add_paragraph('First location')
    doc.add_paragraph('Second location')
    translator = DocxTranslator(DocxTranslatorConfig(skip_translate=True))
    parsed, elements, texts = translator._pre_translate(Document(content=docx_bytes(doc), suffix='.docx'))
    # Recreate duplicate segment IDs pointing at one physical run, as in the production bug.
    elements += [elements[0], elements[0]]
    texts += [texts[0], texts[0]]
    output = translator._after_translate(parsed, elements, texts, texts,
                                        {0: 'Same issue', 1: 'Same issue', 2: 'Same issue', 3: 'Different issue'})
    with zipfile.ZipFile(BytesIO(output)) as package:
        comments = etree.fromstring(package.read('word/comments.xml'))
        bodies = [''.join(c.xpath('.//w:t/text()', namespaces=NS)) for c in comments]
        assert bodies.count('Same issue') == 2  # One at each distinct location.
        assert bodies.count('Different issue') == 1
