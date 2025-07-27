import bisect
from datetime import UTC, datetime
from typing import cast, override

import numpy as np
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
    QPen,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
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
        *,
        is_history: bool = False,
    ) -> None:
        super().__init__()
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
    drag_scene_start_y = "application/x-queue-entries-index"
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

    def get_y_pos(self, index: int) -> float:
        return QUEUE_ENTRY_SPACING + index * QUEUE_ENTRY_HEIGHT

    @override
    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if isinstance(item, QueueEntryGraphicsItem):
                drag = SongDrag(self, get_single_song_drag_text(item.music.name, item.music.artists))
                mime_data = QMimeData()
                mime_data.setData(self.drag_scene_start_y, QByteArray.number(self.mapToScene(event.pos()).y()))  # pyright: ignore[reportUnknownMemberType]
                mime_data.setData(MUSIC_IDS_MIMETYPE, music_ids_to_qbytearray([item.music.id]))
                drag.setMimeData(mime_data)
                drag.exec(self.possible_drop_actions)
        super().mouseMoveEvent(event)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.RightButton:
            super().mousePressEvent(event)


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

        pen = QPen(QColor(0, 0, 255, 100))
        pen.setWidth(3)
        self.drop_indicator_line_item = self.scene().addLine(QLineF(0, 0, self.viewport().width(), 0), pen)
        self.drop_indicator_line_item.setVisible(False)

        self.manual_queue_header_label = self.scene().addText("Next in queue")  # pyright: ignore[reportUnknownMemberType]
        self.manual_queue_header_label.setDefaultTextColor(Qt.GlobalColor.white)
        self.manual_queue_header_label.setVisible(False)

        self.queue_header_label = self.scene().addText("Next from:")  # pyright: ignore[reportUnknownMemberType]
        self.queue_header_label.setDefaultTextColor(Qt.GlobalColor.white)
        self.queue_header_label.setVisible(False)

        self.queue_header_collection_label = self.scene().addText("")  # pyright: ignore[reportUnknownMemberType]
        self.queue_header_collection_label.setDefaultTextColor(Qt.GlobalColor.white)
        self.queue_header_collection_label.setVisible(False)

        self.shared_signals.add_to_queue_signal.connect(self.add_to_queue)

    @property
    def queue_music_ids(self) -> list[int]:
        return [q.music.id for q in self.queue_entries]

    @property
    def manual_music_ids(self) -> list[int]:
        return [q.music.id for q in self.manual_entries]

    @property
    def current_queue_entries(self) -> list[QueueEntryGraphicsItem]:
        return self.queue_entries[self.current_queue_idx + 1 :]

    @property
    def current_entries(self):
        return self.manual_entries + self.current_queue_entries

    @property
    def past_entries(self):
        return self.queue_entries[: self.current_queue_idx + 1]

    def update_first_queue_index(self) -> None:
        for proxy in self.past_entries:
            if proxy.scene():
                self.scene().removeItem(proxy)
        for proxy in self.current_entries:
            if not proxy.scene():
                self.scene().addItem(proxy)
        self.update_scene()

    def _get_midpoints_and_heights(self):
        return sorted(
            {
                (item.scenePos().y() + item.boundingRect().height() / 2, item.boundingRect().height())
                for item in self.items()  # pyright: ignore[reportUnknownMemberType]
                if not isinstance(item, QGraphicsLineItem) and item.isVisible()
            }
        )

    def entry_at_pos_is_manual(self, y_pos: float) -> bool:
        return bool(self.manual_entries) and (
            not self.queue_entries
            or y_pos < self.queue_header_label.scenePos().y() + self.queue_header_label.boundingRect().height() / 2
        )

    @override
    def get_y_pos(self, index: int, *, is_queue_header: bool = False) -> float:
        manual_header_height = (
            self.manual_queue_header_label.boundingRect().height() if self.manual_queue_header_label.isVisible() else 0
        )
        queue_header_height = (
            self.queue_header_label.boundingRect().height()
            if not is_queue_header and index >= len(self.manual_entries) and self.queue_header_label.isVisible()
            else 0
        )
        return super().get_y_pos(index) + manual_header_height + queue_header_height

    @override
    def update_scene(self):
        if len(self.manual_entries):
            if not self.manual_queue_header_label.isVisible():
                self.manual_queue_header_label.setVisible(True)
            self.manual_queue_header_label.setPos(QUEUE_ENTRY_SPACING, QUEUE_ENTRY_SPACING)
        elif self.manual_queue_header_label.isVisible():
            self.manual_queue_header_label.setVisible(False)
        if len(self.current_queue_entries):
            if not self.queue_header_label.isVisible():
                self.queue_header_label.setVisible(True)
                self.queue_header_collection_label.setVisible(True)
            y_pos = self.get_y_pos(len(self.manual_entries), is_queue_header=True)
            self.queue_header_label.setPos(QUEUE_ENTRY_SPACING, y_pos)
            self.queue_header_collection_label.setPos(
                QUEUE_ENTRY_SPACING + self.queue_header_label.boundingRect().width(), y_pos
            )
        elif self.queue_header_label.isVisible():
            self.queue_header_label.setVisible(False)
            self.queue_header_collection_label.setVisible(False)
        super().update_scene()

    @override
    def dragEnterEvent(self, event, /):
        self.drop_indicator_line_item.setVisible(True)
        super().dragEnterEvent(event)

    @override
    def dragMoveEvent(self, event: QDragMoveEvent, /):
        source = event.source()
        assert (
            event.proposedAction() == Qt.DropAction.MoveAction
            if isinstance(source, QueueGraphicsView)
            else Qt.DropAction.CopyAction
        )

        midpoints_and_heights = self._get_midpoints_and_heights()
        if len(midpoints_and_heights):
            midpoints_index = bisect.bisect_right(
                [v[0] for v in midpoints_and_heights],
                self.mapToScene(event.pos()).y(),  # pyright: ignore[reportUnknownMemberType]
            )
            if midpoints_index == 0:
                midpoint, height = midpoints_and_heights[0]
                line_y = midpoint + height / 2
            elif midpoints_index == len(midpoints_and_heights):
                midpoint, height = midpoints_and_heights[-1]
                line_y = midpoint + height / 2
            else:
                midpoint, height = midpoints_and_heights[midpoints_index]
                line_y = midpoint - height / 2
            self.drop_indicator_line_item.setY(line_y)

        event.accept()

    @override
    def dragLeaveEvent(self, event: QDragLeaveEvent, /):
        self.drop_indicator_line_item.setVisible(False)
        super().dragLeaveEvent(event)

    @override
    def dropEvent(self, event: QDropEvent):
        def get_entries_tup(y_pos: float, *, is_from: bool) -> tuple[list[QueueEntryGraphicsItem], int, bool]:
            is_manual = self.entry_at_pos_is_manual(y_pos) if len(self.queue_entries) else True
            if len(self.queue_entries) or len(self.manual_entries):
                midpoints = [m for m, h in self._get_midpoints_and_heights() if h == QUEUE_ENTRY_HEIGHT]
                midpoints_index = (
                    (np.abs(np.asarray(midpoints) - y_pos)).argmin().astype(int)
                    if is_from
                    else bisect.bisect_right(midpoints, y_pos)
                )
                idx = (
                    midpoints_index
                    if is_manual
                    else self.current_queue_idx + 1 + midpoints_index - len(self.manual_entries)
                )
            else:
                idx = 0
            return (self.manual_entries if is_manual else self.queue_entries), idx, is_manual

        self.drop_indicator_line_item.setVisible(False)
        if Qt.MouseButton.RightButton in event.mouseButtons():
            event.ignore()
            return
        source = event.source()
        to_entries, to_idx, to_is_manual = get_entries_tup(self.mapToScene(event.pos()).y(), is_from=False)  # pyright: ignore[reportUnknownMemberType]
        if isinstance(source, QueueGraphicsView):
            drag_start_y, ok = cast(tuple[int, bool], event.mimeData().data(self.drag_scene_start_y).toInt(10))
            assert ok
            from_entries, from_entries_idx, from_is_manual = get_entries_tup(drag_start_y, is_from=True)
            same_entries = from_is_manual == to_is_manual
            to_entries_insert_idx = to_idx - 1 if same_entries and from_entries_idx < to_idx else to_idx
            if same_entries and from_entries_idx == to_entries_insert_idx:
                event.ignore()
                return
            to_entries.insert(to_entries_insert_idx, from_entries.pop(from_entries_idx))
        elif isinstance(source, (LibraryTableView, PlaylistTreeView)):
            music_ids_to_add = qbytearray_to_music_ids(event.mimeData().data(MUSIC_IDS_MIMETYPE))
            self.shared_signals.add_to_queue_signal.emit(music_ids_to_add, to_idx, to_is_manual)  # TODO

        self.update_scene()

    @Slot()
    @profile
    def add_to_queue(self, music_ids: list[int], insert_index: int, is_manual: bool):  # noqa: FBT001
        assert insert_index >= 0
        t = datetime.now(tz=UTC)
        items = [
            QueueEntryGraphicsItem(
                get_db_music_cache().get(music_id), self.shared_signals, start_width=self.viewport().width()
            )
            for music_id in music_ids
        ]
        if is_manual:
            self.manual_entries = self.manual_entries[:insert_index] + items + self.manual_entries[insert_index:]
        else:
            self.queue_entries = self.queue_entries[:insert_index] + items + self.queue_entries[insert_index:]
        self._insert_queue_entries_into_scene(items)
        print("add_to_queue", (datetime.now(tz=UTC) - t).microseconds / 1000)

    @Slot()
    def remove_from_queue(self, items: list[QueueEntryGraphicsItem]) -> None:
        for item in items:
            entries = self.manual_entries if self.entry_at_pos_is_manual(item.pos().y()) else self.queue_entries
            self.scene().removeItem(entries.pop(entries.index(item)))
        self.update_first_queue_index()

    @profile
    def load_music_ids(self, music_ids: tuple[int, ...], new_current_queue_idx: int = -1) -> None:
        """Load a list of music IDs into the queue."""
        self.queue_entries = []
        for item in self.scene().items():  # pyright: ignore[reportUnknownMemberType]
            if isinstance(item, QueueEntryGraphicsItem):
                self.scene().removeItem(item)
        for i, music_id in enumerate(music_ids, start=len(self.manual_entries)):
            qe = QueueEntryGraphicsItem(
                get_db_music_cache().get(music_id), self.shared_signals, self.viewport().width()
            )
            self.scene().addItem(qe)

            qe.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))
            self.queue_entries.append(qe)
        self.current_queue_idx = new_current_queue_idx
