"""Classify source-PDF raster objects for native-DOCX fidelity checks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from pypdf import PdfReader
from pypdf.generic import ContentStream


CompressedMatrix = tuple[float, float, float, float, float, float]
ReferenceKey = tuple[int, int] | tuple[str, int]
IDENTITY_MATRIX: CompressedMatrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True, slots=True)
class PdfVisualInventory:
    """Semantic source-image inventory exposed to the native-DOCX workflow."""

    image_objects: int
    substantive_images: int
    inline_images: int
    scan_images: int
    scan_pages: tuple[int, ...]
    ignored_image_masks: int
    ignored_small_images: int

    def diagnostics(self) -> dict[str, int | list[int]]:
        return {
            "source_pdf_image_objects": self.image_objects,
            "source_pdf_substantive_images": self.substantive_images,
            "source_pdf_inline_images": self.inline_images,
            "source_pdf_scan_images": self.scan_images,
            "source_pdf_scan_pages": list(self.scan_pages),
            "source_pdf_ignored_image_masks": self.ignored_image_masks,
            "source_pdf_ignored_small_images": self.ignored_small_images,
        }


def _reference_key(reference: Any, fallback: Any) -> ReferenceKey:
    if reference is not None and hasattr(reference, "idnum"):
        return int(reference.idnum), int(getattr(reference, "generation", 0))
    return "direct", id(fallback)


def _matrix_multiply(left: CompressedMatrix, right: CompressedMatrix) -> CompressedMatrix:
    a, b, c, d, e, f = left
    g, h, i, j, k, l = right
    return (
        a * g + b * i,
        a * h + b * j,
        c * g + d * i,
        c * h + d * j,
        e * g + f * i + k,
        e * h + f * j + l,
    )


def _matrix_area(matrix: CompressedMatrix) -> float:
    return abs(matrix[0] * matrix[3] - matrix[1] * matrix[2])


def _dereference(value: Any) -> Any:
    return value.get_object() if value is not None and hasattr(value, "get_object") else value


def _drawn_image_area_ratios(
    stream: Any,
    resources: Any,
    reader: PdfReader,
    *,
    page_area: float,
    initial_matrix: CompressedMatrix = IDENTITY_MATRIX,
    active_forms: frozenset[ReferenceKey] = frozenset(),
    placements: list[tuple[Any, CompressedMatrix]] | None = None,
) -> dict[ReferenceKey, list[float]]:
    ratios: dict[ReferenceKey, list[float]] = defaultdict(list)
    if stream is None or resources is None:
        return ratios
    resources = _dereference(resources)
    xobjects = _dereference(resources.get("/XObject")) if resources else None
    if not xobjects:
        return ratios

    current = initial_matrix
    stack: list[CompressedMatrix] = []
    for operands, operator in ContentStream(stream, reader).operations:
        if operator == b"q":
            stack.append(current)
            continue
        if operator == b"Q":
            current = stack.pop() if stack else initial_matrix
            continue
        if operator == b"cm" and len(operands) == 6:
            local = tuple(float(value) for value in operands)
            current = _matrix_multiply(local, current)  # type: ignore[arg-type]
            continue
        if operator != b"Do" or not operands:
            continue

        reference = xobjects.get(operands[0])
        if reference is None:
            continue
        xobject = _dereference(reference)
        key = _reference_key(reference, xobject)
        subtype = str(xobject.get("/Subtype"))
        if subtype == "/Image":
            if placements is not None:
                placements.append((reference, current))
            ratios[key].append(_matrix_area(current) / page_area if page_area else 0.0)
            continue
        if subtype != "/Form" or key in active_forms:
            continue

        form_matrix_values = xobject.get("/Matrix", IDENTITY_MATRIX)
        form_matrix = tuple(float(value) for value in form_matrix_values)
        form_resources = xobject.get("/Resources") or resources
        nested = _drawn_image_area_ratios(
            xobject,
            form_resources,
            reader,
            page_area=page_area,
            initial_matrix=_matrix_multiply(form_matrix, current),  # type: ignore[arg-type]
            active_forms=active_forms | {key},
            placements=placements,
        )
        for nested_key, nested_ratios in nested.items():
            ratios[nested_key].extend(nested_ratios)
    return ratios


def inspect_pdf_visuals(
    content: bytes,
    *,
    min_substantive_image_bytes: int = 1024,
    scan_page_min_coverage: float = 0.80,
    scan_page_max_text_characters: int = 32,
) -> PdfVisualInventory:
    """Return a semantic image inventory without exposing source document content."""

    reader = PdfReader(BytesIO(content))
    image_objects = 0
    substantive_images = 0
    inline_images = 0
    scan_images = 0
    scan_pages: set[int] = set()
    ignored_image_masks = 0
    ignored_small_images = 0

    for page_number, page in enumerate(reader.pages, start=1):
        page_area = float(page.cropbox.width) * float(page.cropbox.height)
        draw_ratios = _drawn_image_area_ratios(
            page.get_contents(),
            page.get("/Resources"),
            reader,
            page_area=page_area,
        )
        text_characters = sum(
            not character.isspace() for character in (page.extract_text() or "")
        )
        for image in page.images:
            image_objects += 1
            reference = image.indirect_reference
            image_object = _dereference(reference)
            if image_object is not None and bool(image_object.get("/ImageMask", False)):
                ignored_image_masks += 1
                continue
            if len(image.data) < min_substantive_image_bytes:
                ignored_small_images += 1
                continue

            substantive_images += 1
            key = _reference_key(reference, image_object or image)
            coverage = max(draw_ratios.get(key, (0.0,)))
            if (
                coverage >= scan_page_min_coverage
                and text_characters <= scan_page_max_text_characters
            ):
                scan_images += 1
                scan_pages.add(page_number)
            else:
                inline_images += 1

    return PdfVisualInventory(
        image_objects=image_objects,
        substantive_images=substantive_images,
        inline_images=inline_images,
        scan_images=scan_images,
        scan_pages=tuple(sorted(scan_pages)),
        ignored_image_masks=ignored_image_masks,
        ignored_small_images=ignored_small_images,
    )
