"""Document-level helpers for SVG output."""

from __future__ import annotations

import html

from re_tomato.jps import JPS_EXTENSION
from re_tomato.normalization.types import ScoreModel


def wrap_html(
    svg_content: str,
    model: ScoreModel,
    *,
    page_number: int = 1,
    page_count: int = 1,
    title: str | None = None,
) -> str:
    """Wrap one rendered SVG page in the project's standalone HTML shell."""
    escaped_title = html.escape(
        document_title(model, page_number=page_number, page_count=page_count, title=title)
    )
    return (
        '<!DOCTYPE html>\n'
        "<html>\n<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{escaped_title}</title>\n"
        "<style>\n"
        "body { margin: 0; padding: 20px; background: #f5f5f5; }\n"
        ".page-wrapper { background: white; margin: 0 auto; padding: 20px; "
        "box-shadow: 0 2px 8px rgba(0,0,0,0.1); page-break-after: always; }\n"
        "svg { max-width: 100%; height: auto; }\n"
        "@media print { body { background: white; } .page-wrapper { "
        "box-shadow: none; padding: 0; } }\n"
        "</style>\n"
        "</head>\n<body>\n"
        '<div class="page-wrapper">\n'
        f"{svg_content}\n"
        "</div>\n</body>\n</html>"
    )


def document_title(
    model: ScoreModel,
    *,
    page_number: int = 1,
    page_count: int = 1,
    title: str | None = None,
) -> str:
    """Return a generic or caller-supplied title without source provenance."""
    del model
    base = " ".join((title or "score").split()) or "score"
    title = f"{base}{JPS_EXTENSION}"
    if page_count > 1:
        title += f" - Page {page_number}/{page_count}"
    return title


__all__ = ["document_title", "wrap_html"]
