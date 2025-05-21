import pandas as pd
from PySide6.QtCore import Qt, Slot, Signal, QRectF, QObject
from PySide6.QtGui import (
    QPainter,
    QFont,
    QFontMetricsF,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QScrollArea,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsItem,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
)

from music_player.signals import SharedSignals
from music_player.utils import get_pixmap
from music_player.constants import (
    QUEUE_ENTRY_HEIGHT,
    QUEUE_ENTRY_SPACING,
)
from music_player.vlc_core import VLCCore


class ScrollableLayout(QScrollArea):
    def __init__(self, layout: QVBoxLayout) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_widget.setLayout(layout)
        self.setWidget(scroll_widget)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)


class QueueSignal(QObject):
    song_clicked = Signal(object)

    def song_is_clicked(self, queue_entry: object) -> None:
        self.song_clicked.emit(queue_entry)


class HoverRect(QRectF):
    def __init__(self, left: float, top: float, width: float, height: float) -> None:
        super().__init__(left, top, width, height)
        self.hovered: bool = False


class QueueEntryGraphicsItem(QGraphicsItem):
    def __init__(self, music: pd.Series, shared_signals: SharedSignals, manually_added: bool = False):
        super().__init__()
        self.manually_added = manually_added
        self.music = music
        self.signal = QueueSignal()
        self.shared_signals = shared_signals
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False

        self._bounding_rect = QRectF(0, 0, 0, QUEUE_ENTRY_HEIGHT)

        album_size = QUEUE_ENTRY_HEIGHT - 2 * QUEUE_ENTRY_SPACING
        self._album_rect = QRectF(QUEUE_ENTRY_SPACING, QUEUE_ENTRY_SPACING, album_size, album_size)

        self._song_font = QFont()
        self._song_font_metrics = QFontMetricsF(self._song_font)
        text_padding_left = QUEUE_ENTRY_HEIGHT  # Space for album + spacing

        font_rect = self._song_font_metrics.boundingRect(self.music["title"])
        song_width, song_height = font_rect.width() + 2, font_rect.height() + 2
        self._song_text_rect = HoverRect(text_padding_left, QUEUE_ENTRY_SPACING, song_width, song_height)

        self._artist_font = QFont()
        self._artist_rects: list[HoverRect] = []
        curr_start = text_padding_left
        for i, artist in enumerate(self.music["artists"]):
            text = artist if i == len(self.music["artists"]) - 1 else f"{artist},"
            font_rect = QFontMetricsF(self._artist_font).boundingRect(text)
            text_width, text_height = font_rect.width() + 2, font_rect.height() + 2
            self._artist_rects.append(
                HoverRect(curr_start, song_height + QUEUE_ENTRY_SPACING * 2, text_width, text_height)
            )
            curr_start += text_width + QUEUE_ENTRY_SPACING

    def boundingRect(self):
        return self._bounding_rect

    def resize(self, resize_event: QResizeEvent) -> None:
        self._bounding_rect.setWidth(resize_event.size().width())

    def paint(self, painter: QPainter, option, widget=None):
        # Paint album art
        if self.music["album_cover_bytes"] is not None:
            pixmap = get_pixmap(self.music["album_cover_bytes"]).scaled(
                self._album_rect.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(self._album_rect.topLeft(), pixmap)

        # Paint song name rect
        available_width = self.boundingRect().width() - QUEUE_ENTRY_HEIGHT - QUEUE_ENTRY_SPACING
        elided_text = self._song_font_metrics.elidedText(
            self.music["title"], Qt.TextElideMode.ElideRight, available_width
        )
        self._song_text_rect.setWidth(self._song_font_metrics.horizontalAdvance(elided_text))
        self._song_font.setUnderline(self._song_text_rect.hovered)  # TODO THIS SEEMS OFF
        painter.setFont(self._song_font)
        painter.drawText(self._song_text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_text)

        # Paint artist name rect(s)
        for i, (artist, artist_rect) in enumerate(zip(self.music["artists"], self._artist_rects, strict=True)):
            self._artist_font.setUnderline(artist_rect.hovered)
            painter.setFont(self._artist_font)
            # painter.drawRect(artist_rect)
            text = artist if i == len(self._artist_rects) - 1 else f"{artist}, "
            painter.drawText(artist_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, text)

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent):
        self._hovered = True
        if self._song_text_rect.contains(event.pos()):
            self._song_text_rect.hovered = True
        for artist_rect in self._artist_rects:
            if artist_rect.contains(event.pos()):
                artist_rect.hovered = True
            else:
                artist_rect.hovered = False
        self.update()
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent):
        if self._song_text_rect.contains(event.pos()):
            self._song_text_rect.hovered = True
        else:
            self._song_text_rect.hovered = False
        for artist_rect in self._artist_rects:
            if artist_rect.contains(event.pos()):
                artist_rect.hovered = True
            else:
                artist_rect.hovered = False
        self.update()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        self._hovered = False
        self._song_text_rect.hovered = False
        for artist_rect in self._artist_rects:
            artist_rect.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if self._song_text_rect.contains(event.pos()):
            self.signal.song_is_clicked(self)
        elif self._album_rect.contains(event.pos()):
            self.shared_signals.library_load_album_signal.emit(self.music["album"])
        else:
            for i, artist_rect in enumerate(self._artist_rects):
                if artist_rect.contains(event.pos()):
                    self.shared_signals.library_load_artist_signal.emit(self.music["artists"][i])
                    break
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.signal.song_is_clicked(self)
        super().mouseDoubleClickEvent(event)


class QueueEntryGraphicsView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setScene(QGraphicsScene())
        self.setStyleSheet("QueueEntryGraphicsView {border: none; margin: 0px;}")
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_entries: list[QueueEntryGraphicsItem] = []

    @property
    def current_entries(self):
        return self.queue_entries

    def update_scene(self):
        for i, proxy in enumerate(self.current_entries):
            proxy.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))

        # TODO REMOVE BAD ENTRIES

        assert all(e in self.scene().items() for e in self.current_entries)
        self.setSceneRect(0, 0, self.width(), self.get_y_pos(len(self.scene().items())))  # Update scene size

    def insert_queue_entry(self, queue_index: int, entry: QueueEntryGraphicsItem) -> None:
        self.queue_entries.insert(queue_index, entry)
        self.scene().addItem(entry)
        self.update_scene()

    @staticmethod
    def get_y_pos(index: int) -> float:
        return QUEUE_ENTRY_SPACING + index * (QUEUE_ENTRY_SPACING + QUEUE_ENTRY_HEIGHT)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        for entry in self.queue_entries:
            entry.resize(event)


class QueueGraphicsView(QueueEntryGraphicsView):
    def __init__(self, vlc_core: VLCCore, shared_signals: SharedSignals):
        super().__init__()
        self.core = vlc_core
        self.shared_signals = shared_signals
        self.initialize_queue()

    def initialize_queue(self):
        self.queue_entries = []
        self.scene().clear()
        for i, list_index in enumerate(self.core.list_indices):
            qe = QueueEntryGraphicsItem(self.core.current_music_df.iloc[list_index], self.shared_signals)
            qe.signal.song_clicked.connect(self.play_queue_song)
            self.scene().addItem(qe)

            qe.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))
            self.queue_entries.append(qe)

    @Slot(QueueEntryGraphicsView)
    def play_queue_song(self, queue_entry: QueueEntryGraphicsItem):
        self.core.jump_play_index(self.queue_entries.index(queue_entry))

    @property
    def current_entries(self):
        return self.queue_entries[self.core.current_media_idx + 1 :]

    @property
    def past_entries(self):
        return self.queue_entries[: self.core.current_media_idx + 1]

    def update_first_queue_index(self) -> None:
        for proxy in self.past_entries:
            if proxy.scene():
                self.scene().removeItem(proxy)
        for proxy in self.current_entries:
            if not proxy.scene():
                self.scene().addItem(proxy)
        self.update_scene()
