"""Coordinate layout, SVG element emission, serialization, and export modes."""

from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

from octopus.normalization.types import ScoreModel
from octopus.render.core.elements import RenderElement, SvgElement
from octopus.render.core.glyphs import load_all_glyphs
from octopus.render.core.layout_types import (  # noqa: F401 - compatibility re-export
    LayoutLyric,
    LayoutPage,
)

from .export import DEFAULT_EXPORT_MODE, EXPORT_MODES, ExportMode, export_svg_pages
from .layout_engine.page import layout_page
from .output import (
    publish_owned_files,
    read_owned_manifest,
    sha256_file,
    write_utf8_text,
)
from .svg_engine.custom import custom_elements as _custom_elements
from .svg_engine.custom import safe_custom_elements as _safe_custom_elements
from .svg_engine.defs import render_defs as _assemble_defs
from .svg_engine.document import wrap_html
from .svg_engine.event_stream import (
    _render_event_elements,
)
from .svg_engine.graces import (
    _catalog_grace_defs_by_id,
    _grace_render_plan,
    _uses_catalog_grace_glyphs,
)
from .svg_engine.header import header_elements as _header_elements
from .svg_engine.page import render_page_body_elements as _assemble_page_body_elements
from .svg_engine.pipeline import render_svg_document as _render_svg_document
from .svg_engine.score_stream import _score_stream_elements
from .svg_engine.serialize import SerializationProfile
from .svg_engine.serialize import render_svg_element as _serialize_svg_element
from .svg_engine.types import GraceRenderPlan

_wrap_html = wrap_html

_RENDER_MANIFEST_NAME = ".octopus_render_manifest.json"

_GLYPH_REF_RE = re.compile(r'(?:xlink:)?href="#([^"]+)"')
_GRACE_COMPOSITE_RE = re.compile(r"[qh]y\d+_\d+")


def render_score_model(
    model: ScoreModel,
    *,
    export_mode: ExportMode = DEFAULT_EXPORT_MODE,
    serialization_profile: SerializationProfile = "spaced",
) -> list[str]:
    return render_score_model_pages(
        model,
        range(len(model.pages)),
        export_mode=export_mode,
        serialization_profile=serialization_profile,
    )


def render_score_model_pages(
    model: ScoreModel,
    page_indices: Iterable[int],
    *,
    export_mode: ExportMode = DEFAULT_EXPORT_MODE,
    serialization_profile: SerializationProfile = "spaced",
) -> list[str]:
    """Render only the requested pages in the caller's requested order."""
    _validate_render_options(export_mode, serialization_profile)
    custom_elements = (
        _safe_custom_elements if export_mode == "safe-source" else _custom_elements
    )
    rendered: list[str] = []
    for page_index in page_indices:
        if type(page_index) is not int or not 0 <= page_index < len(model.pages):
            raise ValueError(f"page_index must identify an existing page: {page_index!r}")
        layout = layout_page(model, page_index)
        rendered.append(
            _render_page(
                model,
                layout,
                page_index,
                custom_elements=custom_elements,
                serialization_profile=serialization_profile,
            )
        )
    return export_svg_pages(rendered, export_mode)


def render_score_model_page_with_layout(
    model: ScoreModel,
    page_index: int,
    *,
    serialization_profile: SerializationProfile = "spaced",
) -> tuple[str, LayoutPage]:
    """Render one safe-source page and return the exact layout used for its SVG."""
    if type(page_index) is not int or not 0 <= page_index < len(model.pages):
        raise ValueError("page_index must identify an existing page")
    _validate_render_options(DEFAULT_EXPORT_MODE, serialization_profile)
    layout = layout_page(model, page_index)
    svg = _render_page(
        model,
        layout,
        page_index,
        custom_elements=_safe_custom_elements,
        serialization_profile=serialization_profile,
    )
    return export_svg_pages([svg], "safe-source")[0], layout


def render_score_model_to_html(
    model: ScoreModel,
    *,
    export_mode: ExportMode = DEFAULT_EXPORT_MODE,
    serialization_profile: SerializationProfile = "spaced",
    title: str | None = None,
) -> list[str]:
    pages = render_score_model(
        model,
        export_mode=export_mode,
        serialization_profile=serialization_profile,
    )
    return [
        _wrap_html(svg, model, page_number=index, page_count=len(pages), title=title)
        for index, svg in enumerate(pages, start=1)
    ]


def render_page_elements(
    model: ScoreModel, page_index: int, layout: LayoutPage | None = None
) -> list[RenderElement]:
    """Event-stream elements for one page.

    ``layout`` optionally reuses a pre-computed ``LayoutPage`` (shared-layout
    callers — see ``render_score_model_page_with_layout``) instead of paying for another
    layout pass; the default keeps the historical standalone behavior.
    """
    if layout is None:
        layout = layout_page(model, page_index)
    return _render_event_elements(layout)


def render_page_body_elements(
    model: ScoreModel,
    page_index: int,
    *,
    export_mode: ExportMode = DEFAULT_EXPORT_MODE,
) -> list[SvgElement]:
    if export_mode not in EXPORT_MODES:
        raise ValueError(f"Unknown export mode: {export_mode!r}")
    if export_mode == "browser-dom":
        raise ValueError("browser-dom requires serialized pages; use render_score_model()")
    layout = layout_page(model, page_index)
    grace_plan = _grace_render_plan(model, layout, page_index)
    custom_elements = (
        _safe_custom_elements if export_mode == "safe-source" else _custom_elements
    )
    return _render_page_body_elements(
        model,
        layout,
        page_index,
        grace_plan,
        custom_elements=custom_elements,
    )


def _render_page(
    model: ScoreModel,
    layout: LayoutPage,
    page_index: int,
    *,
    custom_elements: Callable[[ScoreModel, int], list[SvgElement]],
    serialization_profile: SerializationProfile,
) -> str:
    metrics = layout.metrics
    grace_plan = _grace_render_plan(model, layout, page_index)
    body_elements = _render_page_body_elements(
        model, layout, page_index, grace_plan, custom_elements=custom_elements
    )
    defs_body_elements = _render_page_body_elements(
        model,
        layout,
        page_index,
        grace_plan,
        custom_elements=custom_elements,
        score_stream_elements=_score_stream_elements_for_defs,
    )
    background, *score_elements = body_elements
    definitions = _render_defs(
        _defs_body_elements_with_glyph_precedence(defs_body_elements),
        grace_plan.defs,
        include_catalog_graces=_uses_catalog_grace_glyphs(layout),
        compact_profile=serialization_profile == "compact",
    )
    return _render_svg_document(
        width=metrics.width,
        height=metrics.height,
        background=background,
        definitions=definitions,
        score_elements=score_elements,
        serialize=lambda element: _render_svg_element(
            element, compact_profile=serialization_profile == "compact"
        ),
    )


def _validate_render_options(
    export_mode: ExportMode,
    serialization_profile: SerializationProfile,
) -> None:
    if export_mode not in EXPORT_MODES:
        raise ValueError(f"Unknown export mode: {export_mode!r}")
    if serialization_profile not in {"spaced", "compact"}:
        raise ValueError(f"Unknown serialization profile: {serialization_profile!r}")


def _render_page_body_elements(
    model: ScoreModel,
    layout: LayoutPage,
    page_index: int,
    grace_plan: GraceRenderPlan,
    *,
    score_stream_elements: Callable[
        [LayoutPage, GraceRenderPlan], list[SvgElement]
    ] = _score_stream_elements,
    custom_elements: Callable[[ScoreModel, int], list[SvgElement]] = _custom_elements,
) -> list[SvgElement]:
    return _assemble_page_body_elements(
        model,
        layout,
        page_index,
        grace_plan,
        header_elements=_header_elements,
        score_stream_elements=score_stream_elements,
        custom_elements=custom_elements,
    )


def _score_stream_elements_for_defs(
    layout: LayoutPage,
    grace_plan: GraceRenderPlan,
) -> list[SvgElement]:
    return _score_stream_elements(layout, grace_plan, accessory_order="legacy")


def _render_defs(
    body_elements: list[SvgElement],
    extra_defs: tuple[str, ...] = (),
    *,
    include_catalog_graces: bool = True,
    compact_profile: bool = False,
) -> str:
    available_defs = {glyph_id: xml.rstrip() for glyph_id, xml in load_all_glyphs().items()}
    if include_catalog_graces:
        available_defs.update(_catalog_grace_defs_by_id())
    return _assemble_defs(
        body_elements,
        extra_defs,
        available_defs=available_defs,
        extra_defs_by_id=_extra_defs_by_id,
        glyph_refs=_glyph_refs,
        grace_composite_re=_GRACE_COMPOSITE_RE,
        include_catalog_graces=include_catalog_graces,
        compact_profile=compact_profile,
    )


def _defs_body_elements_with_glyph_precedence(
    body_elements: list[SvgElement],
) -> list[SvgElement]:
    """Keep the composite lyric slur definition ahead of its endpoint glyph."""
    preferred = next(
        (item for item in body_elements if item.glyph_id == "lianyin_shuzi_3"),
        None,
    )
    anchor = next(
        (item for item in body_elements if item.glyph_id == "lianyinxian_zuo"),
        None,
    )
    if preferred is None or anchor is None:
        return body_elements
    if body_elements.index(preferred) < body_elements.index(anchor):
        return body_elements
    result = [item for item in body_elements if item is not preferred]
    before_index = result.index(anchor)
    result.insert(before_index, preferred)
    return result


def _extra_defs_by_id(defs: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for xml in defs:
        match = re.search(r'\bid="([^"]+)"', xml)
        if match is not None:
            result[html.unescape(match.group(1))] = xml.rstrip()
    return result


def _glyph_refs(xml: str) -> tuple[str, ...]:
    return tuple(html.unescape(match) for match in _GLYPH_REF_RE.findall(xml))


_render_svg_element = _serialize_svg_element


def render_jps(
    model: ScoreModel,
    out_dir: Path | None = None,
    *,
    export_mode: ExportMode = DEFAULT_EXPORT_MODE,
    serialization_profile: SerializationProfile = "spaced",
    title: str | None = None,
) -> list[str]:
    html_pages = render_score_model_to_html(
        model,
        export_mode=export_mode,
        serialization_profile=serialization_profile,
        title=title,
    )
    if out_dir is not None:
        out_dir = out_dir.resolve()
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        previous = read_owned_manifest(
            out_dir / _RENDER_MANIFEST_NAME,
            owner="render_jps",
        )
        current = {f"page_{index}.html" for index in range(1, len(html_pages) + 1)}
        staging = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}-", dir=out_dir.parent))
        try:
            staged_files: dict[str, Path] = {}
            for index, html_page in enumerate(html_pages, start=1):
                name = f"page_{index}.html"
                path = staging / name
                write_utf8_text(path, html_page)
                staged_files[name] = path
            manifest_path = staging / _RENDER_MANIFEST_NAME
            write_utf8_text(
                manifest_path,
                json.dumps(
                    {
                        "schema_version": 2,
                        "owner": "render_jps",
                        "files": sorted(current),
                        "hashes": {
                            name: sha256_file(staging / name) for name in sorted(current)
                        },
                    },
                    indent=2,
                )
                + "\n",
            )
            staged_files[_RENDER_MANIFEST_NAME] = manifest_path
            publish_owned_files(
                out_dir,
                staged_files,
                previous=previous,
                current=current,
                replaceable_names={_RENDER_MANIFEST_NAME},
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return html_pages
