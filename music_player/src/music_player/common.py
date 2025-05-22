from typing import Callable

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPainter, QFont, QFontMetrics
from PySide6.QtWidgets import QStyleOptionViewItem, QStyleOptionGraphicsItem

BUFFER_CHARS = {",", " ", "…"}


def paint_artists(
    artists: list[str],
    painter: QPainter,
    option: QStyleOptionViewItem | QStyleOptionGraphicsItem,
    text_rect: QRect,
    font: QFont,
    hover_condition: Callable[[QRect], bool],
) -> tuple[tuple[QRect, str] | None, list[QRect]]:
    font_metrics: QFontMetrics = option.fontMetrics  # pyright: ignore[reportAttributeAccessIssue]

    v_space = (int if isinstance(text_rect, QRect) else float)((text_rect.height() - font_metrics.height() - 2) / 2)
    text_rect.adjust(0, v_space, 0, -v_space)

    text = ", ".join(artists)
    elided_text = font_metrics.elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width())
    text_flag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter  # TODO SINGLE LINE?

    hovered_artist_rect_artist_tup: tuple[QRect, str] | None = None
    unconsumed_start_idx: int = 0
    artist_rects: list[QRect] = []
    for i, artist in enumerate(artists):
        if unconsumed_start_idx == len(elided_text):
            break

        painter.save()

        artist_text = (
            artist
            if artist in elided_text[unconsumed_start_idx:]
            else elided_text[unconsumed_start_idx : len(elided_text) - 1]
        )
        unconsumed_start_idx += len(artist_text)
        text_size = font_metrics.boundingRect(artist_text).size()
        h_space = (text_rect.width() - text_size.width()) - 2
        artist_rect = text_rect.adjusted(0, 0, -h_space, 0)
        artist_rects.append(artist_rect)
        text_rect.setLeft(artist_rect.right() + 1)

        if hovered_artist_rect_artist_tup is None and hover_condition(artist_rect):
            hovered_artist_rect_artist_tup = artist_rect, artist
            font.setUnderline(True)
        else:
            font.setUnderline(False)
        painter.setFont(font)

        painter.drawText(artist_rect, text_flag, artist_text)
        painter.restore()

        if unconsumed_start_idx == len(elided_text):
            break
        if elided_text[unconsumed_start_idx] in [",", "…"]:  # Elide can cut off comma
            buffer_text_idx = next(
                (
                    i
                    for i, c in enumerate(elided_text[unconsumed_start_idx:], start=unconsumed_start_idx)
                    if c not in BUFFER_CHARS
                ),
                len(elided_text),
            )
            buffer_text = elided_text[unconsumed_start_idx:buffer_text_idx]
            comma_text_width = font_metrics.boundingRect(buffer_text).width()
            comma_rect = text_rect.adjusted(0, 0, -(text_rect.width() - comma_text_width - 2), 0)
            unconsumed_start_idx += len(buffer_text)
            painter.drawText(comma_rect, text_flag, buffer_text)
            text_rect.setLeft(comma_rect.right())

    return hovered_artist_rect_artist_tup, artist_rects
