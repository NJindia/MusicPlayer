from typing import Any

import pandas as pd
from PySide6.QtCore import (
    QAbstractTableModel,
    Qt,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QRect,
    Signal,
    QEvent,
    Slot,
)
from PySide6.QtGui import QFontMetrics, QFont, QPainter, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QTableView,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
)

from music_player.common import Playlist
from music_player.music_importer import get_music_df
from music_player.signals import SharedSignals
from music_player.utils import datetime_to_age_string, datetime_to_date_str, get_pixmap

PADDING = 5
ROW_HEIGHT = 50
ICON_SIZE = ROW_HEIGHT - PADDING * 2
BUFFER_CHARS = {",", " ", "…"}


class AlbumItemDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex):
        album_text: str = index.data(Qt.ItemDataRole.DisplayRole)
        view: MusicLibraryTable = option.widget  # pyright: ignore[reportAttributeAccessIssue]
        font_metrics: QFontMetrics = option.fontMetrics  # pyright: ignore[reportAttributeAccessIssue]
        index_rect: QRect = option.rect  # pyright: ignore[reportAttributeAccessIssue]
        text_rect = index_rect.adjusted(PADDING, PADDING, -PADDING, -PADDING)

        elided_text = font_metrics.elidedText(album_text, Qt.TextElideMode.ElideRight, text_rect.width())
        elided_text_size = font_metrics.boundingRect(elided_text).size()
        h_space = (text_rect.width() - elided_text_size.width()) - 2
        v_space = (text_rect.height() - elided_text_size.height()) - 2
        text_rect.adjust(0, v_space // 2, -h_space, -v_space // 2)

        painter.save()
        if text_rect.contains(view.current_hovered_pos):
            view.hovered_text_rect = text_rect
            view.hovered_data = album_text
            font = QFont(option.font)  # pyright: ignore[reportAttributeAccessIssue]
            font.setUnderline(True)
            painter.setFont(font)
            view.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            view.setCursor(Qt.CursorShape.ArrowCursor)
        painter.drawText(text_rect, option.displayAlignment | Qt.TextFlag.TextSingleLine, album_text)  # pyright: ignore[reportAttributeAccessIssue]
        painter.restore()


class ArtistsItemDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex):
        artists: list[str] = index.data(Qt.ItemDataRole.DisplayRole)

        view: MusicLibraryTable = option.widget  # pyright: ignore[reportAttributeAccessIssue]
        font = QFont(option.font)  # pyright: ignore[reportAttributeAccessIssue]
        font_metrics: QFontMetrics = option.fontMetrics  # pyright: ignore[reportAttributeAccessIssue]
        index_rect: QRect = option.rect  # pyright: ignore[reportAttributeAccessIssue]
        text_rect = index_rect.adjusted(PADDING, PADDING, -PADDING, -PADDING)

        text = ", ".join(artists)
        elided_text = font_metrics.elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width())
        v_space = (text_rect.height() - font_metrics.boundingRect(elided_text).height()) - 2
        text_rect.adjust(0, v_space // 2, 0, -v_space // 2)
        text_flag = option.displayAlignment | Qt.TextFlag.TextSingleLine  # pyright: ignore[reportAttributeAccessIssue]

        hovered: bool = False
        unconsumed_start_idx: int = 0
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
            text_rect.setLeft(artist_rect.right() + 1)

            if not hovered and artist_rect.contains(view.current_hovered_pos):
                hovered = True
                view.hovered_text_rect = artist_rect
                view.hovered_data = artist
                font.setUnderline(True)
                painter.setFont(font)
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

        view.setCursor(Qt.CursorShape.PointingHandCursor if hovered else Qt.CursorShape.ArrowCursor)


class SongItemDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()

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
        view: MusicLibraryTable = option.widget  # pyright: ignore[reportAttributeAccessIssue]
        text = font_metrics.elidedText(text, Qt.TextElideMode.ElideRight, view.columnWidth(index.column()) - ROW_HEIGHT)
        text_size = font_metrics.boundingRect(text).size()
        h_space = (text_rect.width() - text_size.width()) - 2
        v_space = (text_rect.height() - text_size.height()) - 2
        text_rect.adjust(0, v_space // 2, -h_space, -v_space // 2)

        if text_rect.contains(view.current_hovered_pos):
            view.hovered_text_rect = text_rect
            view.hovered_data = text
            font = QFont(option.font)  # pyright: ignore[reportAttributeAccessIssue]
            font.setUnderline(True)
            painter.setFont(font)
            view.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            view.setCursor(Qt.CursorShape.ArrowCursor)
        painter.drawText(text_rect, option.displayAlignment | Qt.TextFlag.TextSingleLine, text)  # pyright: ignore[reportAttributeAccessIssue]

        painter.restore()


class MusicTableModel(QAbstractTableModel):
    def __init__(self, parent: "MusicLibraryTable"):
        super(MusicTableModel, self).__init__(parent)
        self.music_data: pd.DataFrame = pd.DataFrame()
        self.view = parent

    @property
    def display_df(self):
        cols = [c for c in ["title", "artists", "album", "duration", "date added"] if c in self.music_data.columns]
        return self.music_data[cols]

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
            display_cols = self.display_df.columns
            if "date added" in display_cols and index.column() == display_cols.get_loc("date added"):
                return self.music_data["_date_added"].iloc[index.row()]
            data = self.data(index, Qt.ItemDataRole.DisplayRole)
            text = ", ".join(data) if index.column() == 1 else data
            column_width = self.view.columnWidth(index.column()) - (ROW_HEIGHT if index.column() == 0 else PADDING * 2)
            if self.view.font_metrics.horizontalAdvance(text) > column_width:
                return text
        if role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
            return get_pixmap(self.music_data["album_cover_bytes"].iloc[index.row()]).scaledToHeight(
                ICON_SIZE, Qt.TransformationMode.SmoothTransformation
            )
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        """Returns flags for given index."""
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class MusicLibraryWidget(QWidget):
    def __init__(self, playlist: Playlist, shared_signals: SharedSignals):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.playlist: Playlist | None = playlist

        shared_signals.library_load_artist_signal.connect(self.load_artist)
        shared_signals.library_load_album_signal.connect(self.load_album)

        header_widget = QWidget()
        header_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        header_widget.setFixedHeight(100)
        header_layout = QHBoxLayout()
        header_widget.setLayout(header_layout)

        self.header_img = QLabel()
        self.header_img.setPixmap(
            QPixmap("../icons/folder.svg").scaledToHeight(100, Qt.TransformationMode.SmoothTransformation)
        )
        header_layout.addWidget(self.header_img)

        self.table_view = MusicLibraryTable(shared_signals, self)
        self.load_playlist(self.playlist)

        layout = QVBoxLayout()
        layout.addWidget(header_widget)
        layout.addWidget(self.table_view)
        self.setLayout(layout)

    @Slot()
    def remove_item_from_playlist(self, item_index: int):
        assert self.playlist is not None
        self.playlist.remove_item(item_index)
        self.load_playlist(self.playlist)

    def load_playlist(self, playlist: Playlist):
        # TODO LOAD IMG
        self.playlist = playlist

        model = self.table_view.model_
        playlist_df = get_music_df().iloc[playlist.indices].copy()
        dates = [i.added_on for i in playlist.playlist_items]
        playlist_df["_date_added"] = [datetime_to_date_str(d) for d in dates]
        playlist_df["date added"] = [datetime_to_age_string(d) for d in dates]
        model.beginResetModel()
        model.music_data = playlist_df
        model.endResetModel()

    @Slot()
    def load_artist(self, artist: str):
        # TODO LOAD IMG
        self.playlist = None
        model = self.table_view.model_
        model.beginResetModel()
        model.music_data = get_music_df().loc[get_music_df()["artists"].apply(lambda x: artist in x)]
        model.endResetModel()

    @Slot()
    def load_album(self, album: str):
        # TODO LOAD IMG
        self.playlist = None
        model = self.table_view.model_
        model.beginResetModel()
        model.music_data = get_music_df().loc[get_music_df()["album"] == album]
        model.endResetModel()


class MusicLibraryTable(QTableView):
    song_clicked = Signal(int)

    def __init__(self, shared_signals: SharedSignals, parent: MusicLibraryWidget):
        super().__init__(parent)
        self.shared_signals = shared_signals

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

        self.song_delegate = SongItemDelegate()
        self.setItemDelegateForColumn(0, self.song_delegate)
        self.artists_delegate = ArtistsItemDelegate()
        self.setItemDelegateForColumn(1, self.artists_delegate)
        self.album_delegate = AlbumItemDelegate()
        self.setItemDelegateForColumn(2, self.album_delegate)

        self.model_ = MusicTableModel(self)
        self.setModel(self.model_)

        self.hovered_text_rect = QRect()
        self.hovered_data: Any = None
        self.current_hovered_pos = QPoint()

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
                        self.song_clicked.emit(index.row())
                    case 1:
                        self.shared_signals.library_load_artist_signal.emit(self.hovered_data)
                    case 2:
                        self.shared_signals.library_load_album_signal.emit(self.hovered_data)
                    case _:
                        raise NotImplementedError
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.current_hovered_pos = QPoint()
        self.hovered_text_rect = QRect()
        self.viewport().update()
        super().leaveEvent(event)
