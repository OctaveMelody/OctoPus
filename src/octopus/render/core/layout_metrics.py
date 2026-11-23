"""Page-level metric configuration for layout."""

from __future__ import annotations

from octopus.normalization.types import ScoreModel

from .layout_types import (
    DEFAULT_FOOTER_CREDIT,
    DEFAULT_NOTE_SIZE,
    DEFAULT_SCORE_TEXT_FONT,
    PageMetrics,
)

DEFAULT_PAGE_WIDTH = 1000
DEFAULT_PAGE_HEIGHT = 1415

_PAGE_SIZES = {
    "A4": (1000, 1415),
    "A5": (840, 1193),
}
_MAX_FONT_SIZE = 256
_MAX_FOOTNOTE_LENGTH = 24
_MAX_VERTICAL_SPACING = 512


def _config_int(
    page_config: dict[str, object],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = page_config.get(key, default)
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parsed if minimum <= parsed <= maximum else default


def page_metrics(model: ScoreModel) -> PageMetrics:
    page_config = model.page_config
    page_name = str(page_config.get("page", "A4")).upper()
    width, height = _PAGE_SIZES.get(page_name, (DEFAULT_PAGE_WIDTH, DEFAULT_PAGE_HEIGHT))
    margin_top = _config_int(
        page_config, "margin_top", 40, minimum=0, maximum=height - 1
    )
    margin_bottom = _config_int(
        page_config, "margin_bottom", 40, minimum=0, maximum=height - 1
    )
    margin_left = _config_int(
        page_config, "margin_left", 60, minimum=0, maximum=width - 1
    )
    margin_right = _config_int(
        page_config, "margin_right", 60, minimum=0, maximum=width - 1
    )
    if margin_top + margin_bottom >= height:
        margin_top, margin_bottom = 40, 40
    if margin_left + margin_right >= width:
        margin_left, margin_right = 60, 60
    available_height = height - margin_top - margin_bottom
    body_margin_top = _config_int(
        page_config,
        "body_margin_top",
        40,
        minimum=0,
        maximum=available_height,
    )
    footer_text = page_config.get("footer_credit_text", DEFAULT_FOOTER_CREDIT)
    if isinstance(footer_text, str):
        words = footer_text.split(maxsplit=_MAX_FOOTNOTE_LENGTH)[:_MAX_FOOTNOTE_LENGTH]
        footer_text = " ".join(words)[:_MAX_FOOTNOTE_LENGTH].rstrip()
    else:
        footer_text = DEFAULT_FOOTER_CREDIT
    footer_position = page_config.get("footer_credit_position")
    number_position = page_config.get("footer_page_number_position")
    return PageMetrics(
        width=width,
        height=height,
        margin_top=margin_top,
        margin_bottom=margin_bottom,
        margin_left=margin_left,
        margin_right=margin_right,
        body_margin_top=body_margin_top,
        title_font=str(page_config.get("biaoti_font", "Microsoft YaHei")),
        note_font={"regular": "a", "italic": "c", "bold": "b"}.get(
            str(page_config.get("shuzi_font", "b")).casefold(),
            str(page_config.get("shuzi_font", "b")),
        ),
        lyric_font=str(page_config.get("geci_font", DEFAULT_SCORE_TEXT_FONT)),
        title_size=_config_int(
            page_config, "biaoti_size", 36, minimum=1, maximum=_MAX_FONT_SIZE
        ),
        subtitle_size=_config_int(
            page_config, "fubiaoti_size", 20, minimum=1, maximum=_MAX_FONT_SIZE
        ),
        lyric_size=_config_int(
            page_config, "geci_size", 16, minimum=1, maximum=_MAX_FONT_SIZE
        ),
        subtitle_font=str(
            page_config.get(
                "fubiaoti_font",
                page_config.get("biaoti_font", "Microsoft YaHei"),
            )
        ),
        note_size=_config_int(
            page_config, "shuzi_size", DEFAULT_NOTE_SIZE, minimum=1, maximum=_MAX_FONT_SIZE
        ),
        footer_credit=page_config.get("footer_credit") is True,
        footer_credit_text=footer_text,
        footer_credit_position=footer_position
        if footer_position in ("center", "right") else "left",
        footer_page_number=str(page_config.get("footer_page_number", "off")),
        footer_page_number_position=number_position
        if number_position in ("left", "center", "null") else "right",
        height_quci=_config_int(
            page_config, "height_quci", 12, minimum=0, maximum=_MAX_VERTICAL_SPACING
        ),
        height_cici=_config_int(
            page_config, "height_cici", 10, minimum=0, maximum=_MAX_VERTICAL_SPACING
        ),
        height_ciqu=_config_int(
            page_config, "height_ciqu", 20, minimum=0, maximum=_MAX_VERTICAL_SPACING
        ),
        height_shengbu=_config_int(
            page_config, "height_shengbu", 10, minimum=0, maximum=_MAX_VERTICAL_SPACING
        ),
        lianyinxian_type=str(page_config.get("lianyinxian_type", "0")).strip(),
        time_sig=next(
            (item.value for item in reversed(model.headers) if item.prefix == "P"),
            "",
        ),
    )
