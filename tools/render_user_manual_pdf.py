#!/usr/bin/env python3
"""Print a localized HTML manual to a tagged, bookmarked PDF using Chromium."""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("en", "zh-CN")


def render_pdf(source: Path, output: Path, language: str) -> None:
    if language not in LANGUAGES:
        raise ValueError(f"unsupported manual language: {language}")
    if not source.is_file():
        raise FileNotFoundError(f"manual source is missing: {source}")

    version_path = ROOT / "VERSION"
    version = version_path.read_text(encoding="utf-8").strip()
    if not version:
        raise ValueError(f"application version is empty: {version_path}")

    output.parent.mkdir(parents=True, exist_ok=True)
    brand = "OctoPus" if language == "en" else "章鱼简谱"
    title = "User Manual" if language == "en" else "用户手册"
    version_label = f"Version: {version}" if language == "en" else f"版本：{version}"
    footer = (
        '<div style="width:100%;font-size:8px;color:#63748a;padding:0 16mm;'
        'display:flex;justify-content:space-between">'
        f"<span>{brand} - {title}</span><span>"
        '<span class="pageNumber"></span> / <span class="totalPages"></span>'
        "</span></div>"
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(source.resolve().as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.evaluate(
                """() => {
                    for (const link of document.querySelectorAll('a[href]')) {
                        const href = link.getAttribute('href');
                        if (!href.startsWith('#') && new URL(href, document.baseURI).protocol === 'file:') {
                            link.remove();
                        }
                    }
                }"""
            )
            page.locator(".manual-version").evaluate(
                "(element, value) => { element.textContent = value; }", version_label
            )
            page.pdf(
                path=str(output),
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                display_header_footer=True,
                tagged=True,
                outline=True,
                header_template="<span></span>",
                footer_template=footer,
            )
            page.close()
        finally:
            browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=LANGUAGES, required=True)
    args = parser.parse_args()
    render_pdf(args.source, args.output, args.language)
    print(args.output)


if __name__ == "__main__":
    main()
