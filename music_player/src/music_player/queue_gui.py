from PySide6.QtCore import Qt, Slot, Signal, QRectF, QObject
from PySide6.QtGui import (
    QPainter,
    QColor,
    QBrush,
    QPen,
    QFont,
    QFontMetricsF,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QScrollArea,
    QGraphicsView,
    QGraphicsScene,
    QSizePolicy,
    QGraphicsItem,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
)
from typing_extensions import override

from music_player.utils import get_pixmap
from music_player.constants import (
    QUEUE_ENTRY_HEIGHT,
    QUEUE_ENTRY_WIDTH,
    QUEUE_ENTRY_SPACING,
    QUEUE_WIDTH,
)
from music_player.music_importer import Music
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
    def __init__(self, music: Music):
        super().__init__()
        self.music = music
        self.signal = QueueSignal()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False
        self._bounding_rect = QRectF(0, 0, QUEUE_ENTRY_WIDTH, QUEUE_ENTRY_HEIGHT)
        album_size = self.boundingRect().height() - 2 * QUEUE_ENTRY_SPACING
        self._album_rect = QRectF(QUEUE_ENTRY_SPACING, QUEUE_ENTRY_SPACING, album_size, album_size)

        self._song_font = QFont()
        padding_left = self.boundingRect().height()  # Space for album + spacing

        font_rect = QFontMetricsF(self._song_font).boundingRect(self.music.title)
        song_width, song_height = font_rect.width() + 2, font_rect.height() + 2
        self._song_text_rect = HoverRect(padding_left, QUEUE_ENTRY_SPACING, song_width, song_height)

        self._artist_font = QFont()
        self._artist_rects: list[HoverRect] = []
        curr_start = padding_left
        for i, artist in enumerate(self.music.artists):
            text = artist if i == len(self.music.artists) - 1 else f"{artist},"
            font_rect = QFontMetricsF(self._artist_font).boundingRect(text)
            text_width, text_height = font_rect.width() + 2, font_rect.height() + 2
            self._artist_rects.append(
                HoverRect(curr_start, song_height + QUEUE_ENTRY_SPACING * 2, text_width, text_height)
            )
            curr_start += text_width + QUEUE_ENTRY_SPACING

    def boundingRect(self):
        return self._bounding_rect

    def paint(self, painter: QPainter, option, widget=None):
        bg_color = QColor("#e6e6f0") if self._hovered else QColor("#1b4af5")
        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(self.boundingRect(), 4, 4)

        if self.music.album_cover_bytes is not None:
            pixmap = get_pixmap(self.music.album_cover_bytes).scaled(
                self._album_rect.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(self._album_rect.topLeft(), pixmap)

        self._song_font.setUnderline(self._song_text_rect.hovered)
        painter.setFont(self._song_font)
        painter.setPen(QPen(Qt.GlobalColor.black))
        # painter.drawRect(self._song_text_rect)  # TODO REMOVE
        painter.drawText(self._song_text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.music.title)

        for i, (artist, artist_rect) in enumerate(zip(self.music.artists, self._artist_rects, strict=True)):
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
            print("TODO: GO TO ALBUM")
        else:
            for artist_rect in self._artist_rects:
                if artist_rect.contains(event.pos()):
                    print("TODO: GO TO ARTIST")
                    break
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            print("CLICKED ENTRY")
            self.signal.song_is_clicked(self)
        super().mouseDoubleClickEvent(event)


class QueueEntryGraphicsView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene())
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFixedWidth(int(QUEUE_WIDTH * 1.1))
        self.queue_entries: list[QueueEntryGraphicsItem] = []

    @property
    def current_entries(self):
        return self.queue_entries

    def update_scene(self, from_index: int = 0):
        for i, proxy in enumerate(self.current_entries[from_index:], start=from_index):
            proxy.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))

        # TODO REMOVE BAD ENTRIES

        assert all(e in self.scene().items() for e in self.current_entries)
        self.setSceneRect(0, 0, self.width(), self.get_y_pos(len(self.scene().items())))  # Update scene size

    def insert_queue_entry(self, queue_index: int, entry: QueueEntryGraphicsItem) -> None:
        self.queue_entries.insert(queue_index, entry)
        self.scene().addItem(entry)
        self.update_scene(queue_index)

    @staticmethod
    def get_y_pos(index: int) -> float:
        return QUEUE_ENTRY_SPACING + index * (QUEUE_ENTRY_SPACING + QUEUE_ENTRY_HEIGHT)


class QueueGraphicsView(QueueEntryGraphicsView):
    def __init__(self, vlc_core: VLCCore):
        super().__init__()
        self.core = vlc_core
        self.initialize_queue()

    def initialize_queue(self):
        self.queue_entries = []
        self.scene().clear()
        for i, list_index in enumerate(self.core.list_indices):
            qe = QueueEntryGraphicsItem(self.core.music_list[list_index])
            qe.signal.song_clicked.connect(self.play_queue_song)
            self.scene().addItem(qe)

            qe.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))
            self.queue_entries.append(qe)

    @Slot(QueueEntryGraphicsView)
    def play_queue_song(self, queue_entry: QueueEntryGraphicsItem):
        self.core.jump_play_index(self.ordered_entries.index(queue_entry))

    @property
    def current_entries(self):
        return self.ordered_entries[self.core.current_media_idx + 1 :]

    @property
    def past_entries(self):
        return self.ordered_entries[: self.core.current_media_idx + 1]

    @property
    def ordered_entries(self):
        assert len(self.queue_entries) == len(self.core.list_indices)
        return [self.queue_entries[i] for i in self.core.list_indices]

    def update_first_queue_index(self) -> None:
        for proxy in self.past_entries:
            if proxy.scene():
                self.scene().removeItem(proxy)
        for proxy in self.current_entries:
            if not proxy.scene():
                self.scene().addItem(proxy)
        self.update_scene()

    @override
    def insert_queue_entry(self, queue_index: int, entry: QueueEntryGraphicsItem) -> None:
        assert queue_index > self.core.current_media_idx, "Can't insert queue entry before current queue index"
        super().insert_queue_entry(queue_index, entry)
