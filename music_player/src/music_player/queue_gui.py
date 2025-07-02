from typing import cast, override

from line_profiler_pycharm import profile  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QRectF, QSize, QSortFilterProxyModel, Qt
from PySide6.QtGui import QFont, QFontMetrics, QMouseEvent, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QListView, QStyledItemDelegate, QStyleOptionViewItem

from music_player.common_gui import paint_artists
from music_player.constants import ID_ROLE, QUEUE_ENTRY_HEIGHT, QUEUE_ENTRY_SPACING
from music_player.db_types import DbMusic, get_db_music_cache
from music_player.signals import SharedSignals
from music_player.utils import get_pixmap
from music_player.vlc_core import VLCCore

MUSIC_NAME_ROLE = Qt.ItemDataRole.UserRole + 2
ALBUM_ID_ROLE = Qt.ItemDataRole.UserRole + 3
ARTISTS_ROLE = Qt.ItemDataRole.UserRole + 4
ARTIST_IDS_ROLE = Qt.ItemDataRole.UserRole + 5
IMG_PATH_ROLE = Qt.ItemDataRole.UserRole + 6
MANUALLY_ADDED_ROLE = Qt.ItemDataRole.UserRole + 7


class QueueFilterModel(QSortFilterProxyModel):
    def __init__(self, core: VLCCore):
        super().__init__()
        self.core = core

    @override
    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex, /) -> bool:
        return source_row > self.core.current_media_idx

    @override
    def sourceModel(self, /) -> QStandardItemModel:
        source_model = super().sourceModel()
        assert isinstance(source_model, QStandardItemModel), "Source model must be a QStandardItemModel"
        return source_model


class QueueEntryDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()
        self._artist_font = QFont()
        self._song_font = QFont()
        self._song_font_metrics = QFontMetrics(self._song_font)

        text_padding_left = QUEUE_ENTRY_HEIGHT  # Space for album + spacing
        song_height = self._song_font_metrics.height() + 2
        self._song_text_rect = QRectF(text_padding_left, QUEUE_ENTRY_SPACING, 0, song_height)

        album_size = QUEUE_ENTRY_HEIGHT - 2 * QUEUE_ENTRY_SPACING
        self._album_rect = QRectF(QUEUE_ENTRY_SPACING, QUEUE_ENTRY_SPACING, album_size, album_size)

        self._artists_bounding_rect = QRect(
            text_padding_left, song_height + QUEUE_ENTRY_SPACING * 2, 0, QFontMetrics(self._artist_font).height() + 2
        )
        print("done")

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        """This is REQUIRED - tells the view how big each item should be"""
        print("sizeHint", option, index)
        return QSize(-1, QUEUE_ENTRY_HEIGHT)  # -1 means use available width

    @override
    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        painter.save()
        # Paint album art
        if (img_path := index.data(IMG_PATH_ROLE)) is not None:
            pixmap = get_pixmap(img_path, self._album_rect.size().toSize().height())
            painter.drawPixmap(self._album_rect.topLeft(), pixmap)

        # Paint song name rect
        rect = cast(QRect, option.rect)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        available_width = int(rect.width() - QUEUE_ENTRY_HEIGHT - QUEUE_ENTRY_SPACING)
        elided_text = self._song_font_metrics.elidedText(
            index.data(MUSIC_NAME_ROLE), Qt.TextElideMode.ElideRight, available_width
        )
        self._song_text_rect.setWidth(self._song_font_metrics.horizontalAdvance(elided_text))
        # self._song_font.setUnderline(self._song_text_rect == self._hovered_text_rect)
        painter.setFont(self._song_font)  # pyright: ignore[reportUnknownMemberType]
        painter.drawText(self._song_text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_text)

        # Paint artist name rect(s)
        self._artists_bounding_rect.setWidth(available_width)
        paint_artists(
            index.data(ARTISTS_ROLE),
            painter,
            option,
            QRect(self._artists_bounding_rect),
            QFont(self._artist_font),
            lambda r: r == None,  # self._hovered_text_rect,
        )
        painter.restore()

    # self._bounding_rect = QRectF(0, 0, start_width, QUEUE_ENTRY_HEIGHT)

    # @override
    # def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent):
    #     self._hovered = True
    #     self._update_hover_text_rect(event)
    #     self.update()
    #     super().hoverEnterEvent(event)
    #
    # @override
    # def hoverMoveEvent(self, event: QGraphicsSceneHoverEvent):
    #     previous_hovered = self._hovered_text_rect
    #     self._update_hover_text_rect(event)
    #     if previous_hovered != self._hovered_text_rect:
    #         self.update()
    #     super().hoverMoveEvent(event)
    #
    # @override
    # def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent):
    #     self._hovered = False
    #     self._hovered_text_rect = QRectF()
    #     self.update()
    #     super().hoverLeaveEvent(event)
    #
    # def _update_hover_text_rect(self, event: QGraphicsSceneHoverEvent):
    #     self._hovered_text_rect = (
    #         self._song_text_rect
    #         if self._song_text_rect.contains(event.pos())
    #         else next((r for r in self._artist_rects if r.contains(event.pos().toPoint())), QRectF())
    #     )
    #
    # def resize(self, resize_event: QResizeEvent) -> None:
    #     self.prepareGeometryChange()
    #     self._bounding_rect.setWidth(resize_event.size().width())


class QueueEntryGraphicsView(QListView):
    def __init__(self, shared_signals: SharedSignals):
        super().__init__()
        self._signals = shared_signals
        self.setStyleSheet("border: 1px solid red;")

        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.setModel(QStandardItemModel())

        self.setItemDelegate(QueueEntryDelegate())

    def source_model(self) -> QStandardItemModel:
        sm = self.model()
        assert isinstance(sm, QStandardItemModel)
        return sm

    @override
    def mouseReleaseEvent(self, event: QMouseEvent):
        index = self.indexAt(event.pos())
        if not index.isValid():
            return
        if self._song_text_rect.contains(event.pos()):
            self.play_index(index)
        elif self._album_rect.contains(event.pos()):
            self._signals.library_load_album_signal.emit(index.data(ALBUM_ID_ROLE))
        else:
            for i, artist_rect in enumerate(self._artist_rects):
                if artist_rect.contains(event.pos()):
                    self._signals.library_load_artist_signal.emit(index.data(ARTIST_IDS_ROLE)[i])
                    break
        super().mouseReleaseEvent(event)

    @override
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        index = self.indexAt(event.pos())
        if not index.isValid():
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.play_index(index)
        super().mouseDoubleClickEvent(event)

    @profile
    def insert_music_into_queue(
        self, queue_insert_index: int, music_to_add: list[DbMusic], *, manually_added: bool
    ) -> None:
        model = self.source_model()
        model.insertRows(queue_insert_index, len(music_to_add))
        for i, music in enumerate(music_to_add):
            item = QStandardItem()
            item.setData(music.id, Qt.ItemDataRole.DisplayRole)
            item.setData(music.id, ID_ROLE)
            item.setData(music.name, MUSIC_NAME_ROLE)
            item.setData(music.album_id, ALBUM_ID_ROLE)
            item.setData(music.artists, ARTISTS_ROLE)
            item.setData(music.artist_ids, ARTIST_IDS_ROLE)
            item.setData(music.img_path, IMG_PATH_ROLE)
            item.setData(manually_added, MANUALLY_ADDED_ROLE)
            model.setItem(queue_insert_index + i, 0, item)
            print(model.item(i, 0))

    @staticmethod
    def get_y_pos(index: int) -> float:
        return QUEUE_ENTRY_SPACING + index * (QUEUE_ENTRY_SPACING + QUEUE_ENTRY_HEIGHT)

    def play_index(self, index: QModelIndex) -> None:
        self._signals.play_history_song_signal.emit(index.data(ID_ROLE))


class QueueListView(QueueEntryGraphicsView):
    def __init__(self, vlc_core: VLCCore, shared_signals: SharedSignals):
        super().__init__(shared_signals)
        self.core = vlc_core
        proxy_model = QueueFilterModel(self.core)
        proxy_model.setSourceModel(super().model())
        self.setModel(proxy_model)

    @override
    def model(self) -> QueueFilterModel:
        model = super().model()
        assert isinstance(model, QueueFilterModel), "Model must be a QueueFilterModel"
        return model

    @override
    def source_model(self) -> QStandardItemModel:
        return self.model().sourceModel()

    @override
    def play_index(self, index: QModelIndex) -> None:
        self.core.jump_play_index(self.core.list_indices[self.core.current_media_idx + 1 + index.row()])

    @profile
    def initialize_queue(self):
        self.model().sourceModel().clear()
        music_list = [get_db_music_cache().get(self.core.db_indices[list_idx]) for list_idx in self.core.list_indices]
        self.insert_music_into_queue(0, music_list)
