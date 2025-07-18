import bisect
from datetime import UTC, datetime
from typing import cast, override

from line_profiler_pycharm import profile  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from PySide6.QtCore import QByteArray, QLineF, QMimeData, QPoint, QRect, QRectF, Qt, Slot
from PySide6.QtGui import (
    QColor,
    QDragLeaveEvent,
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
    QStyleOptionGraphicsItem,
    QWidget,
)

from music_player.common_gui import SongDrag, paint_artists
from music_player.constants import MUSIC_IDS_MIMETYPE, QUEUE_ENTRY_HEIGHT, QUEUE_ENTRY_SPACING
from music_player.db_types import DbMusic, get_db_music_cache
from music_player.signals import SharedSignals
from music_player.utils import get_pixmap, get_single_song_drag_text, music_ids_to_qbytearray, qbytearray_to_music_ids
from music_player.view_types import LibraryTableView, PlaylistTreeView, StackGraphicsView
from music_player.vlc_core import VLCCore


class QueueEntryGraphicsItem(QGraphicsItem):
    @profile
    def __init__(
        self,
        music: DbMusic,
        shared_signals: SharedSignals,
        start_width: int,
        manually_added: bool = False,
        *,
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


class HistoryGraphicsView(StackGraphicsView):
    queue_entries_mimetype = "application/x-queue-entries-index"
    possible_drop_actions = Qt.DropAction.CopyAction

    def __init__(self):
        super().__init__()
        self.setObjectName("StackGraphicsView")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setScene(QGraphicsScene())
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
        for i, proxy in enumerate(self.current_entries):
            proxy.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))
        # TODO REMOVE BAD ENTRIES
        self.setSceneRect(0, 0, self.width(), self.get_y_pos(len(self.current_entries)))  # Update scene size

    @profile
    def _insert_queue_entries_into_scene(self, entries: list[QueueEntryGraphicsItem]) -> None:
        for entry in entries:
            self.scene().addItem(entry)
        self.update_scene()

    @profile
    def insert_queue_entries(self, queue_insert_index: int, entries: list[QueueEntryGraphicsItem]) -> None:
        self.queue_entries = self.queue_entries[:queue_insert_index] + entries + self.queue_entries[queue_insert_index:]
        self._insert_queue_entries_into_scene(entries)

    @staticmethod
    def get_y_pos(index: int) -> float:
        return QUEUE_ENTRY_SPACING + index * (QUEUE_ENTRY_SPACING + QUEUE_ENTRY_HEIGHT)

    @override
    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton:
            item = self.item_at(event.pos())
            if item:
                drag = SongDrag(self, get_single_song_drag_text(item.music.name, item.music.artists))
                mime_data = QMimeData()
                mime_data.setData(self.queue_entries_mimetype, QByteArray.number(self.queue_entries.index(item)))
                mime_data.setData(MUSIC_IDS_MIMETYPE, music_ids_to_qbytearray([item.music.id]))
                drag.setMimeData(mime_data)
                drag.exec(self.possible_drop_actions)
        super().mouseMoveEvent(event)


class QueueGraphicsView(HistoryGraphicsView):
    possible_drop_actions = Qt.DropAction.MoveAction | Qt.DropAction.CopyAction

    def __init__(self, vlc_core: VLCCore, shared_signals: SharedSignals):
        super().__init__()
        self.core = vlc_core
        self.shared_signals = shared_signals
        self._is_dragging: bool = False
        self.current_queue_idx: int = -1

        self.setMouseTracking(True)
        self.setAcceptDrops(True)

        self.manual_entries: list[QueueEntryGraphicsItem] = []
        self.drop_indicator_line_item = self.scene().addLine(QLineF(), QColor(0, 0, 255, 100))

        self.shared_signals.add_to_queue_signal.connect(self.add_to_queue)

    @property
    def queue_music_ids(self) -> list[int]:
        return [q.music.id for q in self.queue_entries]

    @property
    def manual_music_ids(self) -> list[int]:
        return [q.music.id for q in self.manual_entries]

    @property
    def current_entries(self):
        return self.manual_entries + self.queue_entries[self.current_queue_idx + 1 :]

    @property
    def past_entries(self):
        return self.queue_entries[: self.current_queue_idx + 1]

    @profile
    def insert_manual_entries(self, manual_insert_index: int, entries: list[QueueEntryGraphicsItem]) -> None:
        self.manual_entries = (
            self.manual_entries[:manual_insert_index] + entries + self.manual_entries[manual_insert_index:]
        )
        self._insert_queue_entries_into_scene(entries)

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
    def dragMoveEvent(self, event: QDragMoveEvent, /):
        source = event.source()
        assert (
            event.proposedAction() == Qt.DropAction.MoveAction
            if isinstance(source, QueueGraphicsView)
            else Qt.DropAction.CopyAction
        )

        midpoints = self.midpoints
        midpoints_index = bisect.bisect_right(midpoints, self.mapToScene(event.pos()).y())  # pyright: ignore[reportUnknownMemberType]
        line_y = (self.midpoints[midpoints_index - 1] + QUEUE_ENTRY_HEIGHT / 2) if midpoints_index > 0 else 0
        self.drop_indicator_line_item.setLine(0, line_y, self.viewport().width(), line_y)

        event.accept()

    @override
    def dropEvent(self, event: QDropEvent):
        self.drop_indicator_line_item.setLine(QLineF())
        source = event.source()
        scene_y = self.mapToScene(event.pos()).y()  # pyright: ignore[reportUnknownMemberType]
        queue_entries_to_idx = self.current_queue_idx + 1 + bisect.bisect_right(self.midpoints, scene_y)
        if isinstance(source, QueueGraphicsView):
            queue_entries_from_idx, ok = cast(
                tuple[int, bool], event.mimeData().data(self.queue_entries_mimetype).toInt(10)
            )
            assert ok
            if queue_entries_to_idx in {queue_entries_from_idx, queue_entries_from_idx + 1}:
                event.ignore()
                return
            insert_idx = (
                queue_entries_to_idx if queue_entries_from_idx > queue_entries_to_idx else queue_entries_to_idx - 1
            )
            self.queue_entries.insert(insert_idx, self.queue_entries.pop(queue_entries_from_idx))
        elif isinstance(source, (LibraryTableView, PlaylistTreeView)):
            music_ids_to_add = qbytearray_to_music_ids(event.mimeData().data(MUSIC_IDS_MIMETYPE))
            self.shared_signals.add_to_queue_signal.emit(music_ids_to_add, queue_entries_to_idx)

        self.update_scene()

    @override
    def dragLeaveEvent(self, event: QDragLeaveEvent, /):
        self.drop_indicator_line_item.setLine(QLineF())
        super().dragLeaveEvent(event)

    @Slot()
    @profile
    def add_to_queue(self, music_ids: list[int], insert_index: int):
        assert insert_index >= 0
        t = datetime.now(tz=UTC)
        items = [
            QueueEntryGraphicsItem(
                get_db_music_cache().get(music_id), self.shared_signals, start_width=self.viewport().width()
            )
            for music_id in music_ids
        ]

        if insert_index <= len(self.manual_entries):
            print("MANUAL")
            self.insert_manual_entries(insert_index, items)
        else:
            print("QUEUE")
            self.insert_queue_entries(insert_index - len(self.manual_entries), items)
        print("add_to_queue", (datetime.now(tz=UTC) - t).microseconds / 1000)

    @Slot()
    def remove_from_queue(self, items: list[QueueEntryGraphicsItem]) -> None:
        for item in items:
            entries = self.manual_entries if item.manually_added else self.queue_entries
            self.scene().removeItem(entries.pop(entries.index(item)))
        self.update_first_queue_index()

    @profile
    def load_music_ids(self, music_ids: tuple[int, ...]) -> None:
        """Load a list of music IDs into the queue."""
        for item in self.scene().items():  # pyright: ignore[reportUnknownMemberType]
            if isinstance(item, QueueEntryGraphicsItem):
                self.scene().removeItem(item)
        for i, music_id in enumerate([i + 1 for i in range(len((*self.manual_music_ids, *music_ids)))]):
            qe = QueueEntryGraphicsItem(
                get_db_music_cache().get(music_id), self.shared_signals, self.viewport().width()
            )
            self.scene().addItem(qe)

            qe.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))
            self.queue_entries.append(qe)
