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
    QObject,
    QTimer,
)
from PySide6.QtGui import QFontMetrics, QFont, QPainter, QMouseEvent, QResizeEvent
from PySide6.QtWidgets import (
    QTableView,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QHeaderView,
)

from music_player.common import paint_artists
from music_player.playlist import Playlist
from music_player.music_importer import get_music_df
from music_player.signals import SharedSignals
from music_player.utils import datetime_to_age_string, datetime_to_date_str, get_pixmap

PADDING = 5
ROW_HEIGHT = 50
ICON_SIZE = ROW_HEIGHT - PADDING * 2


def _get_total_length_string(music_df: pd.DataFrame) -> str:
    total_timestamp = round(sum(music_df["duration_timestamp"]))
    components: list[str] = []
    for item in ["second", "minute", "hour", "day"]:
        num = total_timestamp % 60
        if not num:
            break
        components.insert(0, f"{num} {item}{'s'[: num ^ 1]}")
        total_timestamp = total_timestamp // 60
    return " ".join(components)


def _get_meta_text(music_df: pd.DataFrame) -> str:
    return f"{len(music_df)} Track{'s'[: len(music_df) ^ 1]}, {_get_total_length_string(music_df)}"


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
        index_rect: QRect = option.rect  # pyright: ignore[reportAttributeAccessIssue]
        view: MusicLibraryTable = option.widget  # pyright: ignore[reportAttributeAccessIssue]
        text_rect = index_rect.adjusted(PADDING, PADDING, -PADDING, -PADDING)

        hovered_tup, _ = paint_artists(
            index.data(Qt.ItemDataRole.DisplayRole),
            painter,
            option,
            text_rect,
            option.font,  # pyright: ignore[reportAttributeAccessIssue]
            lambda r: r.contains(view.current_hovered_pos),
        )
        if hovered_tup:
            view.hovered_text_rect = hovered_tup[0]
            view.hovered_data = hovered_tup[1]

        view.setCursor(Qt.CursorShape.PointingHandCursor if hovered_tup else Qt.CursorShape.ArrowCursor)


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
        cols = [c for c in ["title", "artists", "album", "date added", "duration"] if c in self.music_data.columns]
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

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        # TODO: Sort by artist list
        sort_column = self.display_df.columns[column]
        match sort_column:
            case "duration":
                sort_key = "duration_timestamp"
            case "date added":
                sort_key = "_date_added"
            case _:
                sort_key = sort_column
        self.beginResetModel()
        self.music_data = (
            self.music_data.sort_values(
                sort_column, ascending=order == Qt.SortOrder.AscendingOrder, key=lambda _: self.music_data[sort_key]
            )
            if column != -1
            else self.music_data.sort_index()
        )
        self.endResetModel()


class TextLabel(QLabel):
    def __init__(self, font_size: int):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        type_font = QFont()
        type_font.setBold(True)
        type_font.setPointSize(font_size)
        self.setFont(type_font)


class MusicLibraryScrollArea(QScrollArea):
    def __init__(self, library: "MusicLibraryWidget"):
        super().__init__()
        self.library = library
        self.setStyleSheet("QScrollArea { border: 1px solid black; }")
        self.setWidgetResizable(True)
        self.setWidget(self.library)

        self.header = self.library.table_view.horizontalHeader()
        self.original_header_rect = self.header.rect()
        self.verticalScrollBar().valueChanged.connect(self.update_header)

    def _detach_header(self):
        if self.header.parent() is not self:
            header_height = self.header.height()
            self.header.setParent(self)
            self.setViewportMargins(0, header_height, 0, 0)
            self.header.setGeometry(
                0, 0, max(0, self.viewport().width() - self.verticalScrollBar().width()), header_height
            )
            self.header.show()
            self.header.raise_()

    def _attach_header(self):
        if self.header.parent() is self:
            self.header.setParent(self.library.table_view)
            self.library.table_view.setHorizontalHeader(self.header)
            self.setViewportMargins(0, 0, 0, 0)
            self.header.show()

    @Slot()
    def update_header(self):
        if self.verticalScrollBar().value() > self.library.header_widget.height():  # Header is somewhat or fully hidden
            self._detach_header()
        else:
            self._attach_header()


class MusicLibraryWidget(QWidget):
    header_img_size = 140
    header_padding = 5

    def __init__(self, playlist: Playlist, shared_signals: SharedSignals):
        super().__init__()
        self.setStyleSheet("""QWidget {
            margin: 0px;
            border: none;
        }""")
        self.playlist: Playlist | None = playlist

        shared_signals.library_load_artist_signal.connect(self.load_artist)
        shared_signals.library_load_album_signal.connect(self.load_album)

        self.header_widget = QWidget()
        self.header_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.header_widget.setFixedHeight(self.header_img_size + self.header_padding * 2)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(
            self.header_padding, self.header_padding, self.header_padding, self.header_padding
        )
        self.header_widget.setLayout(header_layout)
        # header_widget.setStyleSheet("""QWidget { background: transparent; }""")

        self.header_img = QLabel()
        header_layout.addWidget(self.header_img)

        header_text_layout = QVBoxLayout()
        header_text_layout.addStretch()
        header_layout.addLayout(header_text_layout)
        header_layout.addStretch()

        self.header_label_type = TextLabel(10)
        header_text_layout.addWidget(self.header_label_type)

        self.header_label_title = TextLabel(20)
        header_text_layout.addWidget(self.header_label_title)

        self.header_label_subtitle = TextLabel(12)
        header_text_layout.addWidget(self.header_label_subtitle)

        self.header_label_meta = TextLabel(12)
        header_text_layout.addWidget(self.header_label_meta)

        self.table_view = MusicLibraryTable(shared_signals, self)
        self.load_playlist(self.playlist)

        layout = QVBoxLayout()
        layout.addWidget(self.header_widget)
        layout.addWidget(self.table_view)
        self.setLayout(layout)

    @Slot()
    def remove_item_from_playlist(self, item_index: int):
        assert self.playlist is not None
        self.playlist.remove_item(item_index)
        self.load_playlist(self.playlist)

    def load_playlist(self, playlist: Playlist):
        playlist_df = get_music_df().iloc[playlist.indices].copy()
        dates = [i.added_on for i in playlist.playlist_items]
        playlist_df["_date_added"] = [datetime_to_date_str(d) for d in dates]
        playlist_df["date added"] = [datetime_to_age_string(d) for d in dates]

        self.header_img.setPixmap(
            playlist.thumbnail_pixmap.scaled(
                self.header_img_size,
                self.header_img_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.header_label_type.setText("Playlist")
        self.header_label_title.setText(playlist.title)
        self.header_label_subtitle.setVisible(False)
        self.header_label_meta.setText(_get_meta_text(playlist_df))

        self.playlist = playlist
        model = self.table_view.model_
        model.beginResetModel()
        model.music_data = playlist_df
        model.endResetModel()

    @Slot()
    def load_artist(self, artist: str):
        # TODO LOAD IMG
        artist_df = get_music_df().loc[get_music_df()["artists"].apply(lambda x: artist in x)]
        self.header_label_type.setText("Artist")
        self.header_label_title.setText(artist)
        self.header_label_subtitle.setVisible(False)
        self.header_label_meta.setText(_get_meta_text(artist_df))

        self.playlist = None
        model = self.table_view.model_
        model.beginResetModel()
        model.music_data = artist_df
        model.endResetModel()

    @Slot()
    def load_album(self, album: str):
        self.playlist = None
        album_df = get_music_df().loc[get_music_df()["album"] == album]
        assert len(set(album_df["album_cover_bytes"])) == 1
        assert len(set(album_df["album_artist"])) == 1  # TODO HANDLE THIS
        self.header_img.setPixmap(
            get_pixmap(album_df.iloc[0]["album_cover_bytes"]).scaled(
                self.header_img_size,
                self.header_img_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.header_label_type.setText("Album")
        self.header_label_title.setText(album)
        self.header_label_subtitle.setVisible(True)
        self.header_label_subtitle.setText(album_df.iloc[0]["album_artist"])
        self.header_label_meta.setText(_get_meta_text(album_df))

        model = self.table_view.model_
        model.beginResetModel()
        model.music_data = album_df
        model.endResetModel()


class TableHeader(QHeaderView):
    minimum_section_size = 100

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setSectionsClickable(True)
        self.setStyleSheet("""
            QHeaderView::section { background: red; }
            QHeaderView { background: blue; }
        """)
        self.setSortIndicatorClearable(True)
        self.setSortIndicatorShown(True)
        self.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumSectionSize(self.minimum_section_size)
        self.sectionResized.connect(self._resize)
        self._resizing_section_logical_index = -1
        self._initial_mouse_pos = QPoint()
        self._initial_section_size = 0
        self._initial_next_section_size = 0

    def _resize(self, logical_index: int, old_size: int, new_size: int):
        self.blockSignals(True)
        # Check if there's a next section to resize
        if logical_index + 1 < self.count():
            next_section_current_size = self.sectionSize(logical_index + 1)
            next_section_new_size = next_section_current_size - (new_size - old_size)

            # Prevent the next section from shrinking below minimum
            if next_section_new_size < self.minimum_section_size:
                # Set next section size to minimum width and give remaining space to current section
                new_size = old_size + next_section_current_size - self.minimum_section_size
                next_section_new_size = self.minimum_section_size
            if next_section_new_size != next_section_current_size:  # Only resize if necessary
                self.resizeSection(logical_index + 1, next_section_new_size)
        else:
            print("USEFUL!")  # TODO NOT USEFUL?!

        # The max size for the current section is total header width - the sum of all subsequent sections
        max_size = self.width() - sum(self.sectionSize(i) for i in range(logical_index + 1, self.count()))

        # Ensure the current section doesn't grow beyond the available space and doesn't shrink below its own minimum
        clamped_new_size = max(min(new_size, max_size), self.minimum_section_size)
        if clamped_new_size != self.sectionSize(logical_index):  # Only resize if necessary
            self.resizeSection(logical_index, clamped_new_size)
        self.blockSignals(False)

        self.viewport().update()

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        available_space = self.width() - (self.count() - 3) * 100
        col_width = max(available_space // 3, self.minimum_section_size)
        self.blockSignals(True)
        for column in [1, 2]:
            available_space -= col_width
            self.resizeSection(column, col_width)  # TODO KEEP RELATIVE WIDTHS
        self.resizeSection(0, available_space)
        self.blockSignals(False)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        return


class MusicLibraryTable(QTableView):
    song_clicked = Signal(int)

    def __init__(self, shared_signals: SharedSignals, parent: MusicLibraryWidget):
        super().__init__(parent)
        self.shared_signals = shared_signals

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.setShowGrid(False)
        self.setMouseTracking(True)
        self.setWordWrap(False)
        self.setSortingEnabled(True)
        self.setCornerButtonEnabled(False)

        self.setStyleSheet("""
            QTableView {
                background: black;
                border: none;
            }
            QTableView::item {
                background: transparent;
            }""")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalHeader(TableHeader())

        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.verticalHeader().setVisible(False)
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
        self.model_.modelReset.connect(self.adjust_height_to_content)

        QTimer.singleShot(
            0,
            lambda: self.horizontalHeader().setSectionResizeMode(
                self.model().columnCount() - 1, QHeaderView.ResizeMode.Fixed
            ),
        )
        # QTimer.singleShot(0, lambda:self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch) )
        QTimer.singleShot(
            0,
            lambda: self.horizontalHeader().setSectionResizeMode(
                self.model().columnCount() - 2, QHeaderView.ResizeMode.Fixed
            ),
        )

        self.hovered_text_rect = QRect()
        self.hovered_data: Any = None
        self.current_hovered_pos = QPoint()
        self.viewport().installEventFilter(self)
        self.adjust_height_to_content()

    def adjust_height_to_content(self):
        if self.model_.rowCount() == 0:
            self.setMinimumHeight(self.horizontalHeader().height() + 2)
            return
        total_height = (
            2
            + self.horizontalHeader().height()
            + sum(self.verticalHeader().sectionSize(row) for row in range(self.model_.rowCount()))
        )
        self.setMinimumHeight(total_height)

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

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.viewport() and event.type() == QEvent.Type.Wheel:
            event.ignore()  # Pass wheel events up to the parent
            return True  # Event handled
        return super().eventFilter(obj, event)
