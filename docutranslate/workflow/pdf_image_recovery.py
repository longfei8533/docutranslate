"""Restore raster images that MinerU explicitly reduced to empty text blocks.

Recovery requires a source-image bounding box and an unambiguous following
Markdown context. Unknown layouts remain subject to the strict image gate.
"""

from base64 import b64encode
from io import BytesIO
import json
import re
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader
from pypdf._xobj_image_helpers import _xobj_to_image

from docutranslate.workflow.pdf_visual_inventory import _drawn_image_area_ratios


def _overlap(left, right):
    area = max(0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0, min(left[3], right[3]) - max(left[1], right[1])
    )
    denominator = max(
        (left[2] - left[0]) * (left[3] - left[1]),
        (right[2] - right[0]) * (right[3] - right[1]),
    )
    return area / denominator if denominator > 0 else 0


def _following_context(markdown, blocks, index):
    parts = []
    for block in blocks[index + 1:]:
        if block.get('page_idx') != blocks[index]['page_idx'] or block.get('type') != 'text':
            break
        text = block.get('text', '').strip()
        if not text:
            break
        parts.append(re.escape(text))
        matches = list(re.finditer(
            r'^(?:#{1,6} )?' + r'\s+'.join(parts) + r'(?=\n|$)',
            markdown, flags=re.MULTILINE,
        ))
        if len(matches) == 1:
            return matches[0].start()
        if not matches:
            break
    return None


def _png_data(image_object):
    # pypdf skips soft masks whose dimensions differ from the base image.
    # PDF masks are mapped onto the same unit square, so resample explicitly.
    _, _, image = _xobj_to_image(image_object)
    mask = image_object.get('/SMask')
    if mask is not None:
        _, _, alpha = _xobj_to_image(mask.get_object())
        image = image.convert('RGBA')
        image.putalpha(alpha.convert('L').resize(image.size))
    out = BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def recover_empty_image_blocks(source: bytes, markdown: str, archive: bytes) -> tuple[str, int]:
    """Return repaired Markdown and count; never append unlocated source images."""
    try:
        with ZipFile(BytesIO(archive)) as z:
            names = [n for n in z.namelist() if n.endswith('_content_list.json')]
            if len(names) != 1:
                return markdown, 0
            blocks = json.loads(z.read(names[0]))
        if not isinstance(blocks, list) or not all(isinstance(b, dict) for b in blocks):
            return markdown, 0
    except (BadZipFile, ValueError, KeyError):
        return markdown, 0

    reader = PdfReader(BytesIO(source))
    insertions = []
    used = set()
    for index, block in enumerate(blocks):
        if block.get('type') != 'text' or block.get('text') != '':
            continue
        page_index, bbox = block.get('page_idx'), block.get('bbox')
        if not isinstance(page_index, int) or not 0 <= page_index < len(reader.pages):
            continue
        if not isinstance(bbox, list) or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
            continue
        position = _following_context(markdown, blocks, index)
        if position is None:
            continue
        page = reader.pages[page_index]
        if page.rotation:
            continue
        box = page.cropbox
        placements = []
        _drawn_image_area_ratios(page.get_contents(), page.get('/Resources'), reader,
                                 page_area=float(box.width * box.height), placements=placements)
        candidates = []
        for reference, matrix in placements:
            a, b, c, d, x, y = matrix
            # Rotated/skewed layouts need stronger placement evidence.
            if b or c or a <= 0 or d <= 0:
                continue
            image_bbox = [(x - float(box.left)) / float(box.width) * 1000,
                          (float(box.top) - y - d) / float(box.height) * 1000,
                          (x + a - float(box.left)) / float(box.width) * 1000,
                          (float(box.top) - y) / float(box.height) * 1000]
            obj = reference.get_object()
            # OCR boxes follow ink and can exclude a raster's blank margins.
            if bool(obj.get('/ImageMask', False)) or _overlap(image_bbox, bbox) < 0.65:
                continue
            # Do not duplicate an image that already has MinerU image evidence.
            if any(other.get('page_idx') == page_index and other.get('type') == 'image'
                   and isinstance(other.get('bbox'), list) and len(other['bbox']) == 4
                   and _overlap(image_bbox, other['bbox']) >= 0.5 for other in blocks):
                continue
            candidates.append((reference, obj))
        if len(candidates) != 1:
            continue
        reference, obj = candidates[0]
        key = (page_index, reference.idnum)
        if key in used:
            continue
        data = _png_data(obj)
        uri = 'data:image/png;base64,' + b64encode(data).decode('ascii')
        if uri in markdown:
            continue
        insertions.append((position, '\n\n![](' + uri + ')\n\n'))
        used.add(key)
    for position, image in sorted(insertions, reverse=True):
        markdown = markdown[:position] + image + markdown[position:]
    return markdown, len(insertions)
