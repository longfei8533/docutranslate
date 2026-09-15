from io import BytesIO
import json
import logging
from zipfile import ZipFile

from docx import Document
import pytest

from test_pdf_native_docx_workflow import _pdf_with_inline_raster_images, _payload
from docutranslate.core.factory import create_workflow_from_payload
from docutranslate.converter.x2md.converter_mineru_deploy import ConverterMineruDeploy
from docutranslate.ir.attachment_manager import AttachMent
from docutranslate.ir.document import Document as SourceDocument
from docutranslate.converter.md2docx import convert_markdown_to_native_docx
from docutranslate.ir.markdown_document import MarkdownDocument
from docutranslate.workflow.pdf_image_recovery import recover_empty_image_blocks


def archive(blocks):
    out = BytesIO()
    with ZipFile(out, 'w') as z:
        z.writestr('sample_content_list.json', json.dumps(blocks))
    return out.getvalue()


def blocks():
    return [
        {'type': 'text', 'text': '', 'bbox': [0, 800, 200, 1000], 'page_idx': 0},
        {'type': 'text', 'text': 'Date', 'bbox': [300, 800, 400, 820], 'page_idx': 0},
        {'type': 'text', 'text': 'Unique following paragraph', 'bbox': [300, 830, 600, 860], 'page_idx': 0},
    ]


def test_empty_ocr_block_restores_source_image_at_unique_context():
    md = 'Date\n\nEarlier paragraph\n\nDate\n\nUnique following paragraph'
    fixed, count = recover_empty_image_blocks(_pdf_with_inline_raster_images(1), md, archive(blocks()))
    assert count == 1
    assert fixed.index('data:image/png;base64,') > fixed.index('Earlier paragraph')
    assert fixed.index('data:image/png;base64,') < fixed.rindex('Date')
    result = convert_markdown_to_native_docx(MarkdownDocument.from_bytes(fixed.encode(), suffix='.md', stem='test'))
    assert len(Document(BytesIO(result.document.content)).inline_shapes) == 1
    assert recover_empty_image_blocks(_pdf_with_inline_raster_images(1), fixed, archive(blocks())) == (fixed, 0)


@pytest.mark.parametrize('case', ['nonempty', 'image', 'outside', 'ambiguous', 'missing_evidence', 'wrong_page', 'substring', 'already_represented'])
def test_recovery_requires_empty_block_spatial_match_and_unique_context(case):
    items = blocks()
    md = 'Date\n\nUnique following paragraph'
    if case == 'nonempty': items[0]['text'] = 'Recognized content'
    if case == 'image': items[0]['type'] = 'image'
    if case == 'outside': items[0]['bbox'] = [600, 0, 900, 200]
    if case == 'ambiguous': md += '\n\n' + md
    if case == 'missing_evidence': items = []
    if case == 'wrong_page': items[0]['page_idx'] = 1
    if case == 'substring': md = 'Prefix Date suffix\n\nPrefix Unique following paragraph suffix'
    if case == 'already_represented': items.append({'type': 'image', 'page_idx': 0, 'bbox': [0, 800, 200, 1000]})
    fixed, count = recover_empty_image_blocks(_pdf_with_inline_raster_images(1), md, archive(items))
    assert (fixed, count) == (md, 0)


@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('recoverable', [False, True])
async def test_workflow_recovers_empty_ocr_image_and_preserves_strict_gate(monkeypatch, asynchronous, recoverable):
    monkeypatch.setenv("PDF_IMAGE_INTEGRITY_CHECK_ENABLED", "true")
    items = blocks() if recoverable else []

    def convert(self, source):
        self.attachments.append(AttachMent('mineru_deploy', SourceDocument.from_bytes(
            archive(items), suffix='.zip', stem='mineru_deploy')))
        return MarkdownDocument.from_bytes(b'Date\n\nUnique following paragraph', suffix='.md', stem=source.stem)

    async def convert_async(self, source):
        return convert(self, source)

    monkeypatch.setattr(ConverterMineruDeploy, 'convert', convert)
    monkeypatch.setattr(ConverterMineruDeploy, 'convert_async', convert_async)
    workflow = create_workflow_from_payload(_payload(), logger=logging.getLogger('test-recovery'))
    workflow.read_bytes(_pdf_with_inline_raster_images(1), stem='test', suffix='.pdf')

    async def run():
        if asynchronous:
            await workflow.translate_async()
        else:
            workflow.translate()

    if not recoverable:
        with pytest.raises(RuntimeError, match='source_inline_images=1, docx_inline_images=0'):
            await run()
        return
    await run()
    diagnostics = workflow.get_statistics()['conversion']
    assert diagnostics['recovered_source_images'] == 1
    assert diagnostics['mineru_parse_attempts'] == 1
    assert diagnostics['post_translation_validation']['docx_inline_images'] == 1
    assert len(Document(BytesIO(workflow.export_to_docx())).inline_shapes) == 1


def test_soft_mask_is_preserved_when_dimensions_differ():
    from PIL import Image
    from pypdf.generic import DecodedStreamObject, NameObject, NumberObject
    from docutranslate.workflow.pdf_image_recovery import _png_data

    def raster(width, height, color_space, data):
        obj = DecodedStreamObject()
        obj.set_data(data)
        obj.update({NameObject('/Type'): NameObject('/XObject'),
                    NameObject('/Subtype'): NameObject('/Image'),
                    NameObject('/Width'): NumberObject(width),
                    NameObject('/Height'): NumberObject(height),
                    NameObject('/BitsPerComponent'): NumberObject(8),
                    NameObject('/ColorSpace'): NameObject(color_space)})
        return obj

    obj = raster(4, 4, '/DeviceRGB', b'\xff\xff\xff' * 16)
    obj[NameObject('/SMask')] = raster(2, 2, '/DeviceGray', bytes([0, 255, 0, 255]))
    restored = Image.open(BytesIO(_png_data(obj)))
    assert restored.mode == 'RGBA'
    assert restored.getpixel((0, 0))[3] == 0
    assert restored.getpixel((3, 0))[3] == 255
