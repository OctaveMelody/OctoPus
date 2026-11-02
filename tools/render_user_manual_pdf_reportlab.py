#!/usr/bin/env python3
"""Render the authored offline user manual as a reflowed PDF with ReportLab.

This is a fallback for environments where the browser print renderer cannot load
local files. It keeps the authored section order, figures, tables, code samples,
external links, internal section links, a linked contents page, and PDF bookmarks.
The browser-generated tagged-PDF structure is not reproduced.
"""

from __future__ import annotations

import argparse
import html
import re
import tempfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents


DASHES = str.maketrans({
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",
})
VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
BLOCK_TAGS = {"article", "aside", "div", "footer", "header", "main", "nav", "section"}
CONTINUATION_ARROW_SRC: str | None = None


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Node | str] = field(default_factory=list)


class ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag, {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].children.append(Node(tag, {key: value or "" for key, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def descendants(node: Node, tag: str) -> Iterable[Node]:
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if child.tag == tag:
            yield child
        yield from descendants(child, tag)


def text_content(node: Node, *, preserve: bool = False) -> str:
    pieces: list[str] = []
    for child in node.children:
        if isinstance(child, str):
            pieces.append(child)
        elif child.tag == "br":
            pieces.append("\n" if preserve else " ")
        else:
            pieces.append(text_content(child, preserve=preserve))
    value = "".join(pieces).translate(DASHES)
    return value if preserve else re.sub(r"\s+", " ", value).strip()


def inline_markup(node: Node | str, *, code: bool = False) -> str:
    if isinstance(node, str):
        value = node.translate(DASHES)
        if not code:
            value = re.sub(r"\s+", " ", value)
        result = html.escape(value, quote=False)
        if not code and CONTINUATION_ARROW_SRC and "↳" in value:
            image_src = html.escape(CONTINUATION_ARROW_SRC.replace("\\", "/"), quote=True)
            image_markup = (
                f'<img src="{image_src}" width="11" height="10" valign="middle"/>'
            )
            result = result.replace("↳", image_markup)
        return result

    tag = node.tag
    if tag == "br":
        return "<br/>"
    content = "".join(inline_markup(child, code=code or tag == "code") for child in node.children)
    if tag in {"b", "strong"}:
        return f"<b>{content}</b>"
    if tag in {"i", "em"}:
        return f"<i>{content}</i>"
    if tag == "code":
        return f'<font name="ManualCode" color="#344b5e">{content}</font>'
    if tag == "a":
        href = node.attrs.get("href", "")
        if href:
            href = html.escape(href.translate(DASHES), quote=True)
            return f'<link href="{href}" color="#146ba0">{content}</link>'
    if tag in {"sub", "sup"}:
        return f"<{tag}>{content}</{tag}>"
    return content


def inline_children(node: Node, *, code: bool = False) -> str:
    return "".join(inline_markup(child, code=code) for child in node.children)


def find_article(root: Node) -> Node:
    for node in descendants(root, "article"):
        return node
    raise ValueError("No article element found in the manual source")


class ManualHeading(Paragraph):
    def __init__(
        self,
        text: str,
        style: ParagraphStyle,
        *,
        title: str,
        anchor: str,
        outline_level: int,
        toc: bool = False,
    ) -> None:
        super().__init__(text, style)
        self.manual_title = title
        self.manual_anchor = anchor
        self.manual_outline_level = outline_level
        self.manual_toc = toc


class Bookmark(Spacer):
    def __init__(self, key: str) -> None:
        super().__init__(0, 0)
        self.manual_anchor = key
        self.manual_outline_level = -1
        self.manual_title = ""
        self.manual_toc = False


class FramedImage(Image):
    def draw(self) -> None:
        super().draw()
        self.canv.saveState()
        self.canv.setStrokeColor(colors.HexColor("#dbe3ed"))
        self.canv.setLineWidth(0.6)
        self.canv.rect(0, 0, self.drawWidth, self.drawHeight, stroke=1, fill=0)
        self.canv.restoreState()


class ManualDocTemplate(SimpleDocTemplate):
    def __init__(self, filename: str, *, title: str, home_label: str) -> None:
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=17 * mm,
            rightMargin=17 * mm,
            topMargin=17 * mm,
            bottomMargin=16 * mm,
            title=title,
            author="OctaveMelody",
            subject="OctoPus User Manual",
            keywords="OctoPus, Jianpu, JPS, user manual",
            pageCompression=1,
        )
        self.home_label = home_label
        self.onFirstPage = page_chrome(home_label)
        self.onLaterPages = page_chrome(home_label)

    def afterFlowable(self, flowable) -> None:  # noqa: N802 - ReportLab API
        anchor = getattr(flowable, "manual_anchor", None)
        if not anchor:
            return
        self.canv.bookmarkPage(anchor)
        outline_level = getattr(flowable, "manual_outline_level", -1)
        title = getattr(flowable, "manual_title", "")
        if outline_level >= 0 and title:
            self.canv.addOutlineEntry(title, anchor, level=outline_level, closed=True)
        if getattr(flowable, "manual_toc", False):
            self.notify("TOCEntry", (0, title, self.page, anchor))


def page_chrome(home_label: str) -> Callable:
    def draw(canvas, doc) -> None:
        page_width, page_height = A4
        canvas.saveState()
        if doc.page > 1:
            canvas.setFillColor(colors.HexColor("#14394a"))
            canvas.setFont("ManualBold", 8)
            canvas.drawString(doc.leftMargin, page_height - 10 * mm, "OctoPus")
            canvas.setStrokeColor(colors.HexColor("#dbe3ed"))
            canvas.setLineWidth(0.5)
            canvas.line(
                doc.leftMargin,
                page_height - 12 * mm,
                page_width - doc.rightMargin,
                page_height - 12 * mm,
            )
            canvas.setFillColor(colors.HexColor("#146ba0"))
            canvas.setFont("ManualRegular", 8)
            label_width = pdfmetrics.stringWidth(home_label, "ManualRegular", 8)
            x = page_width - doc.rightMargin - label_width
            y = page_height - 10 * mm
            canvas.drawString(x, y, home_label)
            canvas.linkRect(
                "",
                "manual-cover",
                (x - 2, y - 2, x + label_width + 2, y + 9),
                relative=0,
                thickness=0,
            )
        canvas.setStrokeColor(colors.HexColor("#dbe3ed"))
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, 12 * mm, page_width - doc.rightMargin, 12 * mm)
        canvas.setFillColor(colors.HexColor("#63748a"))
        canvas.setFont("ManualRegular", 7.5)
        canvas.drawRightString(page_width - doc.rightMargin, 7.5 * mm, str(doc.page))
        canvas.restoreState()
    return draw


def register_fonts(source: Path, article: Node) -> None:
    regular = source.parent / "assets" / "NotoSansSC-Regular.ttf"
    bold = source.parent / "assets" / "NotoSansSC-Bold.ttf"
    if not regular.exists() or not bold.exists():
        raise FileNotFoundError("The manual's Noto Sans SC font subset is missing")

    def chars_in(node: Node) -> set[str]:
        result: set[str] = set()
        for child in node.children:
            if isinstance(child, str):
                result.update(child.translate(DASHES))
            elif child.tag not in {"nav", "script", "style"}:
                result.update(chars_in(child))
                if child.tag == "img":
                    result.update(child.attrs.get("alt", ""))
        return result

    used = chars_in(article)
    regular_font = TTFont("ManualProbe", str(regular))
    bold_font = TTFont("ManualBoldProbe", str(bold))
    missing = {
        char
        for char in used
        if not char.isspace() and ord(char) not in regular_font.face.charWidths
    }
    missing.update(
        char
        for char in used
        if not char.isspace() and ord(char) not in bold_font.face.charWidths
    )
    # Draw the one continuation symbol missing from the documented subset as
    # an inline vector-like raster, keeping it visually faithful in both PDFs.
    missing.discard("↳")
    if missing:
        full_dir = source.parent.parent.parent / "src" / "octopus" / "assets" / "fonts"
        fallback_regular = full_dir / "NotoSansSC-Regular.ttf"
        fallback_bold = full_dir / "NotoSansSC-Bold.ttf"
        if not fallback_regular.exists() or not fallback_bold.exists():
            chars = "".join(sorted(missing))
            raise ValueError(f"Manual font subset is missing used characters: {chars!r}")
        regular, bold = fallback_regular, fallback_bold
        for path in (regular, bold):
            font = TTFont(f"CoverageProbe{len(pdfmetrics._fonts)}", str(path))
            not_covered = {
                char
                for char in missing
                if not char.isspace() and ord(char) not in font.face.charWidths
            }
            if not_covered:
                raise ValueError(f"No bundled manual font covers: {''.join(sorted(not_covered))!r}")

    pdfmetrics.registerFont(TTFont("ManualRegular", str(regular), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("ManualBold", str(bold), subfontIndex=0))
    pdfmetrics.registerFontFamily(
        "ManualRegular",
        normal="ManualRegular",
        bold="ManualBold",
        italic="ManualRegular",
        boldItalic="ManualBold",
    )
    pdfmetrics.registerFontFamily(
        "ManualBold",
        normal="ManualRegular",
        bold="ManualBold",
        italic="ManualRegular",
        boldItalic="ManualBold",
    )
    pdfmetrics.registerFont(TTFont("ManualCode", str(regular), subfontIndex=0))


def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["BodyText"]
    return {
        "cover_eyebrow": ParagraphStyle(
            "ManualEyebrow",
            parent=base,
            fontName="ManualBold",
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#408699"),
            spaceAfter=12,
        ),
        "cover_title": ParagraphStyle(
            "ManualCoverTitle",
            parent=base,
            fontName="ManualBold",
            fontSize=27,
            leading=34,
            textColor=colors.HexColor("#14394a"),
            spaceAfter=10,
        ),
        "cover_version": ParagraphStyle(
            "ManualCoverVersion",
            parent=base,
            fontName="ManualRegular",
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#52657b"),
            spaceAfter=16,
        ),
        "toc_title": ParagraphStyle(
            "ManualContentsTitle",
            parent=base,
            fontName="ManualBold",
            fontSize=16,
            leading=22,
            textColor=colors.HexColor("#14394a"),
            spaceBefore=13,
            spaceAfter=8,
        ),
        "toc_entry": ParagraphStyle(
            "ManualContentsEntry",
            parent=base,
            fontName="ManualRegular",
            fontSize=8.4,
            leading=11.4,
            leftIndent=0,
            firstLineIndent=0,
            textColor=colors.HexColor("#223249"),
            spaceAfter=2,
        ),
        "h2": ParagraphStyle(
            "ManualH2",
            parent=base,
            fontName="ManualBold",
            fontSize=15.5,
            leading=20.5,
            textColor=colors.HexColor("#14394a"),
            spaceBefore=18,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "ManualH3",
            parent=base,
            fontName="ManualBold",
            fontSize=11.2,
            leading=15.5,
            textColor=colors.HexColor("#24566a"),
            spaceBefore=12,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "ManualBody",
            parent=base,
            fontName="ManualRegular",
            fontSize=9.1,
            leading=13.2,
            textColor=colors.HexColor("#223249"),
            spaceAfter=6,
            allowWidows=0,
            allowOrphans=0,
            splitLongWords=True,
            wordWrap="CJK",
        ),
        "small": ParagraphStyle(
            "ManualSmall",
            parent=base,
            fontName="ManualRegular",
            fontSize=7.8,
            leading=10.6,
            textColor=colors.HexColor("#52657b"),
            spaceAfter=5,
            splitLongWords=True,
            wordWrap="CJK",
        ),
        "caption": ParagraphStyle(
            "ManualCaption",
            parent=base,
            fontName="ManualRegular",
            fontSize=7.6,
            leading=10.2,
            textColor=colors.HexColor("#52657b"),
            spaceBefore=5,
            spaceAfter=1,
            splitLongWords=True,
            wordWrap="CJK",
        ),
        "table": ParagraphStyle(
            "ManualTableCell",
            parent=base,
            fontName="ManualRegular",
            fontSize=7.7,
            leading=10.1,
            textColor=colors.HexColor("#223249"),
            splitLongWords=True,
            wordWrap="CJK",
        ),
        "table_header": ParagraphStyle(
            "ManualTableHeader",
            parent=base,
            fontName="ManualBold",
            fontSize=7.7,
            leading=10.1,
            textColor=colors.HexColor("#14394a"),
            splitLongWords=True,
            wordWrap="CJK",
        ),
        "code": ParagraphStyle(
            "ManualCodeBlock",
            parent=base,
            fontName="ManualCode",
            fontSize=7.3,
            leading=9.6,
            textColor=colors.HexColor("#223249"),
            leftIndent=6,
            rightIndent=6,
            borderColor=colors.HexColor("#dbe3ed"),
            borderWidth=0.5,
            borderPadding=6,
            backColor=colors.HexColor("#f2f6fa"),
            spaceBefore=4,
            spaceAfter=8,
            splitLongWords=True,
            wordWrap="CJK",
        ),
        "note": ParagraphStyle(
            "ManualNote",
            parent=base,
            fontName="ManualRegular",
            fontSize=8.1,
            leading=11.4,
            textColor=colors.HexColor("#496075"),
            splitLongWords=True,
            wordWrap="CJK",
        ),
    }


def collect_rows(table: Node) -> tuple[list[Node], bool]:
    rows = [node for node in descendants(table, "tr")]
    has_header = bool(
        rows
        and any(
            child.tag == "th" for child in rows[0].children if isinstance(child, Node)
        )
    )
    return rows, has_header


def render_table(node: Node, width: float, styles: dict[str, ParagraphStyle]) -> Table | None:
    rows, has_header = collect_rows(node)
    data = []
    for row in rows:
        cells = [
            child
            for child in row.children
            if isinstance(child, Node) and child.tag in {"td", "th"}
        ]
        if not cells:
            continue
        data.append(
            [
                Paragraph(
                    inline_children(cell),
                    styles["table_header"] if cell.tag == "th" else styles["table"],
                )
                for cell in cells
            ]
        )
    if not data:
        return None
    columns = max(len(row) for row in data)
    if columns == 1:
        ratios = [1.0]
    elif columns == 2:
        ratios = [0.28, 0.72]
    elif columns == 3:
        ratios = [0.20, 0.25, 0.55]
    else:
        ratios = [0.16] * (columns - 1) + [0.16 + (1 - 0.16 * columns)]
    widths = [width * ratio for ratio in ratios]
    result = Table(
        data,
        colWidths=widths,
        repeatRows=1 if has_header else 0,
        hAlign="LEFT",
        splitByRow=1,
    )
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#dbe3ed")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if has_header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eff4f9")))
    result.setStyle(TableStyle(commands))
    result.spaceBefore = 5
    result.spaceAfter = 9
    return result


def render_pre(node: Node, styles: dict[str, ParagraphStyle]) -> Paragraph:
    raw = (
        text_content(node, preserve=True)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .translate(DASHES)
    )
    lines = []
    for line in raw.split("\n"):
        leading = len(line) - len(line.lstrip(" \t"))
        body = line[leading:].rstrip()
        prefix = "&#160;" * leading
        escaped = html.escape(body, quote=False).replace("  ", "&#160; ")
        lines.append(prefix + escaped)
    markup = "<br/>".join(lines) or "&#160;"
    return Paragraph(markup, styles["code"])


def render_list(node: Node, styles: dict[str, ParagraphStyle]) -> ListFlowable:
    items = []
    list_items = [
        child for child in node.children if isinstance(child, Node) and child.tag == "li"
    ]
    for item in list_items:
        nested = [
            child
            for child in item.children
            if isinstance(child, Node) and child.tag in {"ul", "ol"}
        ]
        inline_nodes = [
            child
            for child in item.children
            if not (isinstance(child, Node) and child.tag in {"ul", "ol"})
        ]
        item_markup = "".join(inline_markup(child) for child in inline_nodes)
        content: list[Flowable] = [Paragraph(item_markup, styles["body"])]
        for sublist in nested:
            content.append(render_list(sublist, styles))
        items.append(ListItem(content, leftIndent=12, bulletColor=colors.HexColor("#408699")))
    return ListFlowable(
        items,
        bulletType="1" if node.tag == "ol" else "bullet",
        start="1",
        leftIndent=14,
        bulletFontName="ManualRegular",
        bulletFontSize=7.5,
        bulletOffsetY=1,
        spaceBefore=1,
        spaceAfter=5,
    )


def render_figure(
    node: Node, source: Path, width: float, styles: dict[str, ParagraphStyle]
) -> KeepTogether:
    image_node = next(descendants(node, "img"), None)
    caption_node = next(descendants(node, "figcaption"), None)
    if image_node is None:
        return KeepTogether([])
    image_path = (source.parent / image_node.attrs.get("src", "")).resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"Image referenced by the manual is missing: {image_path}")
    from PIL import Image as PILImage

    with PILImage.open(image_path) as image_file:
        image_width, image_height = image_file.size
    draw_width = min(width - 8, 505)
    draw_height = draw_width * image_height / image_width
    max_height = 405
    if draw_height > max_height:
        scale = max_height / draw_height
        draw_width *= scale
        draw_height *= scale
    image = FramedImage(
        str(image_path),
        width=draw_width,
        height=draw_height,
        kind="proportional",
        hAlign="CENTER",
    )
    items = [Spacer(1, 4), image]
    if caption_node:
        caption = inline_children(caption_node)
    else:
        caption = html.escape(image_node.attrs.get("alt", ""), quote=False)
    if caption:
        items.append(Paragraph(caption, styles["caption"]))
    items.append(Spacer(1, 7))
    return KeepTogether(items)


def render_block(
    node: Node | str,
    source: Path,
    section_id: str,
    h3_index: list[int],
    styles: dict[str, ParagraphStyle],
    width: float,
) -> Flowable | list[Flowable] | None:
    if isinstance(node, str):
        if node.strip():
            return Paragraph(html.escape(node.translate(DASHES), quote=False), styles["body"])
        return None
    tag = node.tag
    if tag in {"nav", "script", "style", "h1", "h2", "footer"}:
        return None
    if tag == "h3":
        h3_index[0] += 1
        title = text_content(node)
        anchor = node.attrs.get("id") or f"{section_id}-sub-{h3_index[0]}"
        return ManualHeading(
            inline_children(node),
            styles["h3"],
            title=title,
            anchor=anchor,
            outline_level=1,
        )
    if tag == "p":
        markup = inline_children(node)
        if not markup.strip():
            return None
        class_name = node.attrs.get("class", "")
        if "sample-provenance" in class_name:
            style = styles["small"]
        elif "screenshot-note" in class_name:
            note = Table([[Paragraph(markup, styles["note"])]], colWidths=[width], hAlign="LEFT")
            note.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eff6f8")),
                ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor("#408699")),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            note.spaceBefore, note.spaceAfter = 8, 11
            return note
        else:
            style = styles["body"]
        return Paragraph(markup, style)
    if tag == "pre":
        return render_pre(node, styles)
    if tag == "table":
        return render_table(node, width, styles)
    if tag == "figure":
        return render_figure(node, source, width, styles)
    if tag in {"ul", "ol"}:
        return render_list(node, styles)
    if tag == "hr":
        return Spacer(1, 8)
    if tag in BLOCK_TAGS or tag in {
        "thead",
        "tbody",
        "tr",
        "td",
        "th",
        "figcaption",
        "img",
        "small",
    }:
        return [
            render_block(child, source, section_id, h3_index, styles, width)
            for child in node.children
        ]
    if tag in {"b", "i", "em", "strong", "code", "a", "span", "sub", "sup", "br"}:
        markup = inline_markup(node)
        return Paragraph(markup, styles["body"]) if markup.strip() else None
    return [
        render_block(child, source, section_id, h3_index, styles, width)
        for child in node.children
    ]


def append_result(
    story: list[Flowable], result: Flowable | list[Flowable] | None
) -> None:
    if result is None:
        return
    if isinstance(result, list):
        for child in result:
            append_result(story, child)
        return
    story.append(result)


def build_pdf(source: Path, output: Path, language: str) -> tuple[int, int]:
    global CONTINUATION_ARROW_SRC
    parser = ArticleParser()
    parser.feed(source.read_text(encoding="utf-8"))
    article = find_article(parser.root)
    register_fonts(source, article)
    arrow_path: Path | None = None
    if any("↳" in text_content(node, preserve=True) for node in descendants(article, "p")):
        from PIL import Image as PILImage, ImageDraw

        with tempfile.NamedTemporaryFile(
            prefix="octopus-manual-arrow-", suffix=".png", delete=False
        ) as arrow_file:
            arrow_path = Path(arrow_file.name)
        scale = 4
        arrow_image = PILImage.new("RGBA", (48 * scale, 40 * scale), (255, 255, 255, 0))
        draw = ImageDraw.Draw(arrow_image)
        ink = (34, 50, 73, 255)
        draw.line(
            [(8 * scale, 4 * scale), (8 * scale, 25 * scale), (34 * scale, 25 * scale)],
            fill=ink,
            width=3 * scale,
            joint="curve",
        )
        draw.polygon(
            [(26 * scale, 17 * scale), (39 * scale, 25 * scale), (26 * scale, 33 * scale)],
            fill=ink,
        )
        arrow_image.save(arrow_path)
        CONTINUATION_ARROW_SRC = str(arrow_path)
    styles = make_styles()
    chinese = language.lower().startswith("zh")
    title = "章鱼简谱用户手册" if chinese else "OctoPus User Manual"
    eyebrow = "章鱼简谱 · OctaveMelody" if chinese else "OctoPus · OctaveMelody"
    version_path = Path(__file__).resolve().parents[1] / "VERSION"
    app_version = version_path.read_text(encoding="utf-8").strip()
    if not app_version:
        raise ValueError(f"Application version is empty: {version_path}")
    version = f"版本：{app_version}" if chinese else f"Version: {app_version}"
    home_label = "首页" if chinese else "Home"

    sections = [
        child
        for child in article.children
        if isinstance(child, Node) and child.tag == "section"
    ]
    toc = TableOfContents()
    toc.levelStyles = [styles["toc_entry"]]
    toc.dotsMinLevel = 0
    story: list = [
        Bookmark("manual-cover"),
        Paragraph(html.escape(eyebrow, quote=False), styles["cover_eyebrow"]),
        Paragraph(html.escape(title, quote=False), styles["cover_title"]),
        Paragraph(html.escape(version, quote=False), styles["cover_version"]),
        Paragraph("Contents" if not chinese else "目录", styles["toc_title"]),
        toc,
        PageBreak(),
    ]

    h3_index = [0]
    for section in sections:
        section_id = section.attrs.get("id", f"section-{len(story)}")
        h2 = next(
            (
                child
                for child in section.children
                if isinstance(child, Node) and child.tag == "h2"
            ),
            None,
        )
        if h2:
            h2_title = text_content(h2)
            story.append(
                ManualHeading(
                    inline_children(h2),
                    styles["h2"],
                    title=h2_title,
                    anchor=section_id,
                    outline_level=0,
                    toc=True,
                )
            )
        for child in section.children:
            if isinstance(child, Node) and child.tag == "h2":
                continue
            append_result(
                story,
                render_block(
                    child,
                    source,
                    section_id,
                    h3_index,
                    styles,
                    210 * mm - 34 * mm,
                ),
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    doc = ManualDocTemplate(str(output), title=title, home_label=home_label)
    try:
        doc.multiBuild(story, maxPasses=6)
    finally:
        CONTINUATION_ARROW_SRC = None
        if arrow_path and arrow_path.exists():
            arrow_path.unlink()
    image_count = sum(1 for _ in descendants(article, "img"))
    return len(sections), image_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--language", required=True, choices=("en", "zh-CN"))
    args = parser.parse_args()
    sections, images = build_pdf(args.source.resolve(), args.output.resolve(), args.language)
    print(f"Wrote {args.output} with {sections} sections and {images} embedded figures")


if __name__ == "__main__":
    main()
