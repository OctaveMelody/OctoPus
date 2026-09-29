"""Explicit export serialization, independent of score identity or reference data."""

from __future__ import annotations

from typing import Literal

ExportMode = Literal["server-source", "safe-source", "browser-dom"]
EXPORT_MODES = ("server-source", "safe-source", "browser-dom")
DEFAULT_EXPORT_MODE: ExportMode = "safe-source"


def _strip_custom_group(page: str) -> str:
    start = page.find('<g id="custom">')
    if start < 0:
        return page
    end = page.rfind("</g>")
    if end < start:
        raise ValueError("safe-source export found an unclosed custom group")
    return page[:start] + '<g id="custom"></g>' + page[end + len("</g>") :]


def export_svg_pages(pages: list[str], mode: ExportMode) -> list[str]:
    """Serialize inert SVG DOMs only when the caller explicitly requests it.

    The source mode deliberately does not import or launch Playwright. Browser mode
    uses Chromium's actual HTML parser and outerHTML serializer, including SVG
    namespace handling, rather than approximating their behavior with replacements.
    """
    if mode not in EXPORT_MODES:
        raise ValueError(f"Unknown export mode: {mode!r}")
    if mode == "server-source" or not pages:
        return pages
    if mode == "safe-source":
        return [_strip_custom_group(page) for page in pages]
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "browser-dom export requires the pixel extra and Playwright Chromium; "
            "install re-tomato[pixel] and run playwright install chromium"
        ) from exc
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(service_workers="block")
                context.route("**/*", lambda route: route.abort())
                page = context.new_page()
                # Never insert untrusted score markup into the active document.
                script = """source => {
                    const doc = new DOMParser().parseFromString(source, 'text/html');
                    const svg = doc.querySelector('svg');
                    if (!svg) throw new Error('No SVG root in export');
                    return svg.outerHTML;
                }"""
                return [str(page.evaluate(script, source)) for source in pages]
            finally:
                _close_browser(browser)
    except Error as exc:
        raise RuntimeError(
            "browser-dom export failed; ensure Playwright Chromium is installed: "
            "playwright install chromium"
        ) from exc


def _close_browser(browser: object) -> None:
    """Keep browser teardown from replacing a completed export result."""
    try:
        browser.close()  # type: ignore[attr-defined]
    except Exception:
        return
