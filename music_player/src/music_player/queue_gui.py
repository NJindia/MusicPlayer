import bisect
from typing import cast, override

from line_profiler_pycharm import profile  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from PySide6.QtCore import QByteArray, QMimeData, QPoint, QRect, QRectF, Qt
from PySide6.QtGui import (
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsSceneHoverEvent,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
    QScrollArea,
    QStyleOptionGraphicsItem,
    QVBoxLayout,
    QWidget,
)

from music_player.common_gui import paint_artists
from music_player.constants import QUEUE_ENTRY_HEIGHT, QUEUE_ENTRY_SPACING
from music_player.db_types import DbMusic, get_db_music_cache
from music_player.signals import SharedSignals
from music_player.utils import get_pixmap
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


class QueueEntryGraphicsItem(QGraphicsItem):
    @profile
    def __init__(
        self,
        music: DbMusic,
        shared_signals: SharedSignals,
        start_width: int,
        *,
        manually_added: bool = False,
        is_history: bool = False,
    ) -> None:
        super().__init__()
        self.manually_added = manually_added
        self.is_history = is_history
        self.music: DbMusic = music
        self.shared_signals = shared_signals
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False
        self._hovered_text_rect = QRectF()

        self._bounding_rect = QRectF(0, 0, start_width, QUEUE_ENTRY_HEIGHT)

        album_size = QUEUE_ENTRY_HEIGHT - 2 * QUEUE_ENTRY_SPACING
        self._album_rect = QRectF(QUEUE_ENTRY_SPACING, QUEUE_ENTRY_SPACING, album_size, album_size)

        self._song_font = QFont()
        self._song_font_metrics = QFontMetrics(self._song_font)
        text_padding_left = QUEUE_ENTRY_HEIGHT  # Space for album + spacing

        song_height = self._song_font_metrics.height() + 2
        self._song_text_rect = QRectF(text_padding_left, QUEUE_ENTRY_SPACING, 0, song_height)

        self._artist_font = QFont()
        self._artists_bounding_rect = QRect(
            text_padding_left, song_height + QUEUE_ENTRY_SPACING * 2, 0, QFontMetrics(self._artist_font).height() + 2
        )
        self._artist_rects: list[QRect] = []

    @override
    def boundingRect(self):
        return self._bounding_rect

    @override
    @profile
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None):
        # Paint album art
        if self.music.img_path is not None:
            pixmap = get_pixmap(self.music.img_path, self._album_rect.size().toSize().height())
            painter.drawPixmap(self._album_rect.topLeft(), pixmap)

        # Paint song name rect
        available_width = int(self.boundingRect().width() - QUEUE_ENTRY_HEIGHT - QUEUE_ENTRY_SPACING)
        elided_text = self._song_font_metrics.elidedText(self.music.name, Qt.TextElideMode.ElideRight, available_width)
        self._song_text_rect.setWidth(self._song_font_metrics.horizontalAdvance(elided_text))
        self._song_font.setUnderline(self._song_text_rect == self._hovered_text_rect)
        painter.setFont(self._song_font)  # pyright: ignore[reportUnknownMemberType]
        painter.drawText(self._song_text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_text)

        # Paint artist name rect(s)
        self._artists_bounding_rect.setWidth(available_width)
        self._artist_rects = paint_artists(
            self.music.artists,
            painter,
            option,
            QRect(self._artists_bounding_rect),
            QFont(self._artist_font),
            lambda r: r == self._hovered_text_rect,
        )

    @override
    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent):
        self._hovered = True
        self._update_hover_text_rect(event)
        self.update()
        super().hoverEnterEvent(event)

    @override
    def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent):
        previous_hovered = self._hovered_text_rect
        self._update_hover_text_rect(event)
        if previous_hovered != self._hovered_text_rect:
            self.update()
        super().hoverMoveEvent(event)

    @override
    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
        self._hovered = False
        self._hovered_text_rect = QRectF()
        self.update()
        super().hoverLeaveEvent(event)

    @override
    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        if self._song_text_rect.contains(event.pos()):
            self.shared_signals.play_from_queue_signal.emit(self)
        elif self._album_rect.contains(event.pos()):
            self.shared_signals.library_load_album_signal.emit(self.music.album_id)
        else:
            for i, artist_rect in enumerate(self._artist_rects):
                if artist_rect.contains(event.pos().toPoint()):
                    self.shared_signals.library_load_artist_signal.emit(self.music.artist_ids[i])
                    break
        super().mouseReleaseEvent(event)

    @override
    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.shared_signals.play_from_queue_signal.emit(self)
        super().mouseDoubleClickEvent(event)

    def _update_hover_text_rect(self, event: QGraphicsSceneHoverEvent):
        self._hovered_text_rect = (
            self._song_text_rect
            if self._song_text_rect.contains(event.pos())
            else next((r for r in self._artist_rects if r.contains(event.pos().toPoint())), QRectF())
        )

    def resize(self, resize_event: QResizeEvent) -> None:
        self.prepareGeometryChange()
        self._bounding_rect.setWidth(resize_event.size().width())


class QueueEntryGraphicsView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setScene(QGraphicsScene())
        self.setStyleSheet("QueueEntryGraphicsView {border: none; margin: 0px;}")
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_entries: list[QueueEntryGraphicsItem] = []

    @override
    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        for entry in self.queue_entries:
            entry.resize(event)

    def item_at(self, pos: QPoint, /) -> QueueEntryGraphicsItem | None:
        item = self.itemAt(pos)
        if item is not None:  # Can be None... # pyright: ignore[reportUnnecessaryComparison]
            assert isinstance(item, QueueEntryGraphicsItem)
        return item

    @property
    def current_entries(self):
        return self.queue_entries

    @profile
    def update_scene(self):
        scene_items = self.scene().items()  # pyright: ignore[reportUnknownMemberType]
        for i, proxy in enumerate(self.current_entries):
            proxy.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))
        assert len(self.current_entries) == len(scene_items), f"{len(self.current_entries), len(scene_items)}"
        # TODO REMOVE BAD ENTRIES

        self.setSceneRect(0, 0, self.width(), self.get_y_pos(len(scene_items)))  # Update scene size
        self.viewport().update()

    @profile
    def insert_queue_entries(self, queue_insert_index: int, entries: list[QueueEntryGraphicsItem]) -> None:
        self.queue_entries = self.queue_entries[:queue_insert_index] + entries + self.queue_entries[queue_insert_index:]
        for entry in entries:
            self.scene().addItem(entry)
        self.update_scene()

    @staticmethod
    def get_y_pos(index: int) -> float:
        return QUEUE_ENTRY_SPACING + index * (QUEUE_ENTRY_SPACING + QUEUE_ENTRY_HEIGHT)


class QueueGraphicsView(QueueEntryGraphicsView):
    mime_data_type = "application/x-queue-entries-index"

    def __init__(self, vlc_core: VLCCore, shared_signals: SharedSignals):
        super().__init__()
        self.setMouseTracking(True)
        self.core = vlc_core
        self.shared_signals = shared_signals
        self._is_dragging: bool = False
        self.setAcceptDrops(True)

    @profile
    def initialize_queue(self):
        self.queue_entries = []
        self.scene().clear()
        for i, list_idx in enumerate(self.core.list_indices):
            qe = QueueEntryGraphicsItem(
                get_db_music_cache().get(self.core.db_indices[list_idx]), self.shared_signals, self.viewport().width()
            )
            self.scene().addItem(qe)

            qe.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))
            self.queue_entries.append(qe)

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

    @property
    def midpoints(self):
        return [self.get_y_pos(i) + QUEUE_ENTRY_HEIGHT / 2 for i in range(len(self.current_entries))]

    @override
    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton:
            item = self.item_at(event.pos())
            if item:
                drag = QDrag(self)
                mime_data = QMimeData()
                mime_data.setData(self.mime_data_type, QByteArray.number(self.queue_entries.index(item)))
                drag.setMimeData(mime_data)
                drag.exec()
        super().mouseMoveEvent(event)

    @override
    def dragMoveEvent(self, event: QDragMoveEvent, /):
        assert event.proposedAction() == Qt.DropAction.MoveAction

        queue_index = self.core.current_media_idx + 1 + bisect.bisect_right(self.midpoints, event.pos().y())
        # TODO PAINT INDICATOR AT INDEX
        print(queue_index)
        event.accept()

    @override
    def dropEvent(self, event: QDropEvent):
        queue_entries_from_idx, ok = cast(tuple[int, bool], event.mimeData().data(self.mime_data_type).toInt(10))
        assert ok
        queue_entries_to_idx = self.core.current_media_idx + 1 + bisect.bisect_right(self.midpoints, event.pos().y())
        if queue_entries_to_idx in {queue_entries_from_idx, queue_entries_from_idx + 1}:
            event.ignore()
            return
        insert_idx = queue_entries_to_idx if queue_entries_from_idx > queue_entries_to_idx else queue_entries_to_idx - 1
        self.queue_entries.insert(insert_idx, self.queue_entries.pop(queue_entries_from_idx))
        self.update_scene()
        self.core.list_indices.insert(insert_idx, self.core.list_indices.pop(queue_entries_from_idx))

    @override
    def dragEnterEvent(self, event: QDragEnterEvent, /):
        print("CUSTOM_SORT DRAG")
        super().dragEnterEvent(event)
