"""Page-level content evidence extracted from MinerU result archives."""

from __future__ import annotations

import json
from zipfile import BadZipFile, ZipFile
from io import BytesIO
from typing import Any

from docutranslate.ir.markdown_document import MarkdownDocument


_TRANSLATABLE_FIELDS = (
    "text",
    "table_body",
    "table_caption",
    "table_footnote",
    "image_caption",
    "image_footnote",
    "equation",
    "latex",
)
_NON_BODY_CONTENT_TYPES = frozenset(
    {"header", "footer", "page_header", "page_footer", "page_number"}
)


class MineruMarkdownDocument(MarkdownDocument):
    """Markdown plus zero-based pages for which MinerU returned content."""

    def __init__(
        self,
        *,
        suffix: str,
        content: bytes,
        stem: str | None = None,
        path=None,
        mineru_content_pages: frozenset[int] | None = None,
    ):
        super().__init__(suffix=suffix, content=content, stem=stem, path=path)
        self.mineru_content_pages = mineru_content_pages

    @classmethod
    def from_bytes(
        cls,
        content: bytes,
        suffix: str,
        stem: str | None,
        *,
        mineru_content_pages: frozenset[int] | None = None,
    ) -> "MineruMarkdownDocument":
        return cls(
            content=content,
            suffix=suffix,
            stem=stem,
            mineru_content_pages=mineru_content_pages,
        )


def _has_translatable_content(item: dict[str, Any]) -> bool:
    if str(item.get("type", "")).lower() in _NON_BODY_CONTENT_TYPES:
        return False
    for field in _TRANSLATABLE_FIELDS:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, list) and any(
            isinstance(part, str) and part.strip() for part in value
        ):
            return True
    return False


def mineru_content_pages_from_zip(content: bytes) -> frozenset[int] | None:
    """Read standard MinerU content-list evidence; return ``None`` if unavailable."""

    try:
        with ZipFile(BytesIO(content)) as archive:
            candidates = sorted(
                name
                for name in archive.namelist()
                if name.lower().endswith("_content_list.json")
                and not name.lower().endswith("_content_list_v2.json")
            )
            for name in candidates:
                try:
                    items = json.loads(archive.read(name))
                except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if not isinstance(items, list):
                    continue
                pages = {
                    int(item["page_idx"])
                    for item in items
                    if isinstance(item, dict)
                    and isinstance(item.get("page_idx"), int)
                    and _has_translatable_content(item)
                }
                return frozenset(pages)
    except BadZipFile:
        return None
    return None


def offset_mineru_content_pages(
    pages: frozenset[int] | None,
    page_offset: int,
) -> frozenset[int] | None:
    if pages is None:
        return None
    return frozenset(page + page_offset for page in pages)
