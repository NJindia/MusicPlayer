from typing import Any, Sequence

import pandas as pd
from PySide6.QtCore import (
    QAbstractTableModel,
    Qt,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QObject,
    Signal,
    QEvent,
    Slot,
)
from PySide6.QtGui import QFontMetrics, QFont, QPainter, QMouseEvent
from PySide6.QtWidgets import QTableView, QSizePolicy, QStyledItemDelegate, QStyleOptionViewItem

from music_player.common import Playlist
from music_player.music_importer import get_music_df
from music_player.utils import timestamp_to_str, datetime_to_age_string, datetime_to_date_str, get_pixmap

PADDING = 5
ROW_HEIGHT = 50
ICON_SIZE = ROW_HEIGHT - PADDING * 2


class LibrarySignal(QObject):
    song_clicked = Signal(Playlist, int)

    def song_is_clicked(self, playlist: Playlist, playlist_index: int) -> None:
        self.song_clicked.emit(playlist, playlist_index)


class SongItemDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()
        self.hovered_mouse_pos = QPoint()

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        painter.save()

        text = index.data(Qt.ItemDataRole.DisplayRole)
        pixmap = index.data(Qt.ItemDataRole.DecorationRole)

        index_rect: QRect = option.rect  # pyright: ignore[reportAttributeAccessIssue]
        icon_rect = QRect(index_rect.topLeft() + QPoint(0, PADDING), pixmap.size())
        painter.drawPixmap(icon_rect, pixmap)
        text_rect = index_rect.adjusted(0, PADDING, -PADDING, -PADDING)
        text_rect.setLeft(icon_rect.right() + 5)

        font_metrics: QFontMetrics = option.fontMetrics  # pyright: ignore[reportAttributeAccessIssue]
        view: MusicLibrary = option.widget  # pyright: ignore[reportAttributeAccessIssue]
        text = font_metrics.elidedText(text, Qt.TextElideMode.ElideRight, view.columnWidth(index.column()) - ROW_HEIGHT)
        text_size = font_metrics.boundingRect(text).size()
        h_space = (text_rect.width() - text_size.width()) - 2
        v_space = (text_rect.height() - text_size.height()) - 2
        text_rect.adjust(0, v_space // 2, -h_space, -v_space // 2)

        if text_rect.contains(view.current_hovered_pos):
            view.hovered_text_rect = text_rect
            font = QFont(option.font)  # pyright: ignore[reportAttributeAccessIssue]
            font.setUnderline(True)
            painter.setFont(font)
            view.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            view.setCursor(Qt.CursorShape.ArrowCursor)
        painter.drawText(text_rect, option.displayAlignment | Qt.TextFlag.TextSingleLine, text)  # pyright: ignore[reportAttributeAccessIssue]

        painter.restore()


class MusicTableModel(QAbstractTableModel):
    def __init__(self, parent: "MusicLibrary"):
        super(MusicTableModel, self).__init__(parent)
        self.music_data: pd.DataFrame = pd.DataFrame()
        self.view = parent

    def get_table_df(self, indices: Sequence[int] | None = None) -> pd.DataFrame:
        df = (get_music_df().iloc[indices] if indices is not None else get_music_df()).copy()
        df["duration"] = df["duration_timestamp"].round().apply(timestamp_to_str)
        return df[["title", "artists", "album", "duration", "album_cover_bytes"]]

    @property
    def display_df(self):
        return self.music_data[["title", "artists", "album", "duration", "date added"]]

    def rowCount(self, parent=None):
        """Returns number of rows in table."""
        return len(self.music_data)

    def columnCount(self, parent=None):
        """Returns number of columns in table."""
        return len(self.display_df.columns)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = ...) -> Any:
        """Returns header data for given role."""
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return list(self.display_df.columns)[section].capitalize()
        return None

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = ...) -> Any:
        """Returns data for given index."""
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            return self.display_df.iloc[index.row()].iloc[index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        if role == Qt.ItemDataRole.ToolTipRole:
            if index.column() == self.display_df.columns.get_loc("date added"):
                return self.music_data["_date_added"].iloc[index.row()]
            text = self.data(index, Qt.ItemDataRole.DisplayRole)
            if self.view.font_metrics.horizontalAdvance(text) > self.view.columnWidth(index.column()) - ROW_HEIGHT:
                return text
            return None
        if role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
            return get_pixmap(self.music_data["album_cover_bytes"].iloc[index.row()]).scaledToHeight(
                ICON_SIZE, Qt.TransformationMode.SmoothTransformation
            )
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        """Returns flags for given index."""
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class MusicLibrary(QTableView):
    def __init__(self, playlist: Playlist):
        super().__init__()
        self.playlist = playlist

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setShowGrid(False)
        self.setMouseTracking(True)
        self.setWordWrap(False)
        self.setStyleSheet("""
            QTableView::item {
                padding: 0px;
                padding-left: 0px;
                margin-left: 0px;
            }""")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.horizontalHeader().setSectionsClickable(False)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.setFont(QFont())
        self.font_metrics = QFontMetrics(self.font())

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.signal = LibrarySignal()

        self.setItemDelegateForColumn(0, SongItemDelegate())
        self.model_ = MusicTableModel(self)
        self.load_playlist(self.playlist)
        self.setModel(self.model_)

        self.hovered_text_rect = QRect()
        self.current_hovered_pos = QPoint()

    @Slot()
    def remove_item_from_playlist(self, item_index: int):
        self.playlist.remove_item(item_index)
        self.load_playlist(self.playlist)

    def load_playlist(self, playlist: Playlist):
        model = self.model_
        playlist_df = model.get_table_df(playlist.indices)
        dates = [i.added_on for i in playlist.playlist_items]
        playlist_df["_date_added"] = [datetime_to_date_str(d) for d in dates]
        playlist_df["date added"] = [datetime_to_age_string(d) for d in dates]
        model.beginResetModel()
        model.music_data = playlist_df
        model.endResetModel()

        self.playlist = playlist

    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.pos()
        index = self.indexAt(pos)
        if not index.isValid():
            return
        if not self.hovered_text_rect.contains(pos):
            self.current_hovered_pos = pos
            self.hovered_text_rect = QRect()
            self.viewport().update(self.visualRect(index))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            if self.hovered_text_rect.contains(pos):
                index = self.indexAt(pos)
                match index.column():
                    case 0:
                        self.signal.song_is_clicked(self.playlist, index.row())
                    case _:
                        raise NotImplementedError
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.current_hovered_pos = QPoint()
        self.hovered_text_rect = QRect()
        self.viewport().update()
        super().leaveEvent(event)
