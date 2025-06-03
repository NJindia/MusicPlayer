import re
from typing import Any, cast

import numpy as np
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
    QStyle,
    QPushButton,
    QLineEdit,
)
from qdarktheme.qtpy.QtWidgets import QApplication

from music_player.common import paint_artists, get_artist_text_rect_text_tups, text_is_buffer
from music_player.playlist import Playlist
from music_player.music_importer import get_music_df
from music_player.signals import SharedSignals
from music_player.utils import datetime_to_age_string, datetime_to_date_str, get_pixmap

PADDING = 5
ROW_HEIGHT = 50
ICON_SIZE = ROW_HEIGHT - PADDING * 2
ALBUM_COL_IDX = 2
DATE_ADDED_COL_IDX = 3
DURATION_COL_IDX = 4


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
        view: MusicLibraryTable = option.widget  # pyright: ignore[reportAttributeAccessIssue]
        text_rect, _, album_text = view.get_text_rect_tups_for_index(index)[0]

        painter.save()
        if view.hovered_text_rect == text_rect:
            font = QFont(option.font)  # pyright: ignore[reportAttributeAccessIssue]
            font.setUnderline(True)
            painter.setFont(font)
        painter.drawText(text_rect, option.displayAlignment | Qt.TextFlag.TextSingleLine, album_text)  # pyright: ignore[reportAttributeAccessIssue]
        painter.restore()


class ArtistsItemDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex):
        index_rect: QRect = option.rect  # pyright: ignore[reportAttributeAccessIssue]
        view: MusicLibraryTable = option.widget  # pyright: ignore[reportAttributeAccessIssue]
        text_rect = index_rect.adjusted(PADDING, PADDING, -PADDING, -PADDING)

        paint_artists(
            index.data(Qt.ItemDataRole.DisplayRole),
            painter,
            option,
            text_rect,
            option.font,  # pyright: ignore[reportAttributeAccessIssue]
            lambda r: r == view.hovered_text_rect,
        )


class SongItemDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        painter.save()

        pixmap = index.data(Qt.ItemDataRole.DecorationRole)

        view: MusicLibraryTable = option.widget  # pyright: ignore[reportAttributeAccessIssue]

        index_rect: QRect = option.rect  # pyright: ignore[reportAttributeAccessIssue]
        icon_rect = QRect(index_rect.topLeft() + QPoint(0, PADDING), pixmap.size())
        painter.drawPixmap(icon_rect, pixmap)
        text_rect, _, elided_text = view.get_text_rect_tups_for_index(index)[0]

        if view.hovered_text_rect == text_rect:
            font = QFont(option.font)  # pyright: ignore[reportAttributeAccessIssue]
            font.setUnderline(True)
            painter.setFont(font)
        painter.drawText(text_rect, option.displayAlignment | Qt.TextFlag.TextSingleLine, elided_text)  # pyright: ignore[reportAttributeAccessIssue]

        painter.restore()


class MusicTableModel(QAbstractTableModel):
    re_pattern = re.compile(r"[\W_]+")

    def __init__(self, parent: "MusicLibraryTable"):
        super(MusicTableModel, self).__init__(parent)
        self.music_data: pd.DataFrame = pd.DataFrame()
        self.display_df: pd.DataFrame = pd.DataFrame()
        self.search_df: pd.DataFrame = pd.DataFrame()
        self.view = parent
        self.modelReset.connect(self.update_dfs)

    def update_dfs(self):
        self.display_df = pd.DataFrame()
        cols = self.music_data.columns
        for col in ["title", "artists", "album", "date added", "duration"]:
            self.display_df[col] = self.music_data[col] if col in cols else None

        self.search_df = self.music_data[["title", "artists", "album"]].apply(
            lambda col: col.astype(str).str.lower().replace(self.re_pattern, "", regex=True)
        )

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
            return self.display_df.iloc[index.row(), index.column()]
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
            return get_pixmap(self.music_data["album_cover_bytes"].iloc[index.row()], ICON_SIZE)
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
        self.setContentsMargins(0, 0, 0, 0)
        self.setMargin(0)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        type_font = QFont()
        type_font.setBold(True)
        type_font.setPointSize(font_size)
        self.original_text = ""
        self.setFont(type_font)
        self.setStyleSheet("QLabel { padding: 0px; margin: 0px; } ")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide_text()

    def _elide_text(self):
        current_width = self.contentsRect().width()
        if current_width > 0:
            elided_text = self.fontMetrics().elidedText(self.original_text, Qt.TextElideMode.ElideRight, current_width)
            assert self.fontMetrics().horizontalAdvance(elided_text) <= current_width
            if self.text() != elided_text:
                super().setText(elided_text)

    def setText(self, text: str):
        self.original_text = text
        self._elide_text()


class MusicLibraryScrollArea(QScrollArea):
    def __init__(self, library: "MusicLibraryWidget"):
        super().__init__()
        self.library = library
        self.setStyleSheet("QScrollArea { padding: 0px; margin: 0px; border: none; }")
        self.setWidgetResizable(True)
        self.setWidget(self.library)

        self.setMinimumWidth(500 + QApplication.style().pixelMetric(QStyle.PM_ScrollBarExtent))  # pyright: ignore[reportAttributeAccessIssue]
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

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

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.library.setMaximumWidth(event.size().width())


class LibraryHeaderWidget(QWidget):
    header_img_size = 140
    header_padding = 5

    def __init__(self, library: "MusicLibraryWidget"):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.header_img_size + self.header_padding * 2)

        self.header_img = QLabel()

        header_text_layout = QVBoxLayout()
        header_text_layout.setContentsMargins(0, 0, 0, 0)
        header_text_layout.addStretch()

        self.header_label_type = TextLabel(10)
        self.header_label_title = TextLabel(20)
        self.header_label_subtitle = TextLabel(12)
        self.header_label_meta = TextLabel(12)

        header_text_layout.addWidget(self.header_label_type)
        header_text_layout.addWidget(self.header_label_title)
        header_text_layout.addWidget(self.header_label_subtitle)
        header_text_layout.addWidget(self.header_label_meta)

        header_meta_layout = QHBoxLayout()
        header_meta_layout.addWidget(self.header_img)
        header_meta_layout.addLayout(header_text_layout)

        play_button = QPushButton("Play")
        play_shuffled_button = QPushButton("Shuffle")

        search_bar = QLineEdit()
        search_bar.textChanged.connect(library.filter)
        search_bar.setClearButtonEnabled(True)

        header_interactive_layout = QHBoxLayout()
        header_interactive_layout.addWidget(play_button)
        header_interactive_layout.addWidget(play_shuffled_button)
        header_interactive_layout.addStretch()
        header_interactive_layout.addWidget(search_bar)

        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(
            self.header_padding, self.header_padding, self.header_padding, self.header_padding
        )
        header_layout.addLayout(header_meta_layout)
        header_layout.addLayout(header_interactive_layout)
        self.setLayout(header_layout)


class MusicLibraryWidget(QWidget):
    def __init__(self, playlist: Playlist, shared_signals: SharedSignals):
        super().__init__()
        self.setStyleSheet("QWidget { margin: 0px; border: none; }")
        self.playlist: Playlist | None = playlist

        shared_signals.library_load_artist_signal.connect(self.load_artist)
        shared_signals.library_load_album_signal.connect(self.load_album)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Expanding)

        self.header_widget = LibraryHeaderWidget(self)
        self.table_view = MusicLibraryTable(shared_signals, self)
        self.load_playlist(self.playlist)

        layout = QVBoxLayout()
        layout.addWidget(self.header_widget)
        layout.addWidget(self.table_view)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    @Slot()
    def filter(self, text: str):
        cleaned_text = re.sub(self.table_view.model_.re_pattern, "", text).lower()
        good_series = self.table_view.model_.search_df.apply(lambda col: col.str.contains(cleaned_text)).any(axis=1)
        good_rows = np.where(good_series)[0]
        bad_rows = np.where(~good_series)[0]
        for row in bad_rows:
            if not self.table_view.isRowHidden(row):
                self.table_view.hideRow(row)
        for row in good_rows:
            if self.table_view.isRowHidden(row):
                self.table_view.showRow(row)
        self.table_view.adjust_height_to_content()

    @Slot()
    def remove_items_from_playlist(self, item_indices: list[int]):
        assert self.playlist is not None
        self.playlist.remove_items(item_indices)
        self.load_playlist(self.playlist)

    def load_playlist(self, playlist: Playlist):
        playlist_df = get_music_df().iloc[playlist.indices].copy()
        dates = [i.added_on for i in playlist.playlist_items]
        playlist_df["_date_added"] = [datetime_to_date_str(d) for d in dates]
        playlist_df["date added"] = [datetime_to_age_string(d) for d in dates]
        self.header_widget.header_img.setPixmap(
            playlist.thumbnail_pixmap.scaled(
                self.header_widget.header_img_size,
                self.header_widget.header_img_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.header_widget.header_label_type.setText("Playlist")
        self.header_widget.header_label_title.setText(playlist.title)
        self.header_widget.header_label_subtitle.setVisible(False)
        self.header_widget.header_label_meta.setText(_get_meta_text(playlist_df))
        self.table_view.show_date_added()

        self.playlist = playlist
        model = self.table_view.model_
        model.beginResetModel()
        model.music_data = playlist_df
        model.endResetModel()

    @Slot()
    def load_artist(self, artist: str):
        # TODO LOAD IMG
        artist_df = get_music_df().loc[get_music_df()["artists"].apply(lambda x: artist in x)]
        self.header_widget.header_label_type.setText("Artist")
        self.header_widget.header_label_title.setText(artist)
        self.header_widget.header_label_subtitle.setVisible(False)
        self.header_widget.header_label_meta.setText(_get_meta_text(artist_df))
        self.table_view.hide_date_added()

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
        self.header_widget.header_img.setPixmap(
            get_pixmap(album_df.iloc[0]["album_cover_bytes"], self.header_widget.header_img_size)
        )
        self.header_widget.header_label_type.setText("Album")
        self.header_widget.header_label_title.setText(album)
        self.header_widget.header_label_subtitle.setVisible(True)
        self.header_widget.header_label_subtitle.setText(album_df.iloc[0]["album_artist"])
        self.header_widget.header_label_meta.setText(_get_meta_text(album_df))
        self.table_view.hide_date_added()

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
            QHeaderView::section { background: grey; }
            QHeaderView { background: transparent; }
        """)
        self.setSortIndicatorClearable(True)
        self.setSortIndicatorShown(True)
        self.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumSectionSize(self.minimum_section_size)
        self.sectionResized.connect(self._resize)

    def _resize(self, logical_index: int, old_size: int, new_size: int):
        self.blockSignals(True)
        # Check if there's a next section to resize
        next_section_idx = next(
            (i for i in range(logical_index + 1, self.count()) if not self.isSectionHidden(i)), None
        )
        if next_section_idx is not None:
            next_section_current_size = self.sectionSize(next_section_idx)
            next_section_new_size = next_section_current_size - (new_size - old_size)
            # Prevent the next section from shrinking below minimum
            if next_section_new_size < self.minimum_section_size:
                # Set next section size to minimum width and give remaining space to current section
                new_size = old_size + next_section_current_size - self.minimum_section_size
                next_section_new_size = self.minimum_section_size
            self._resize_section_if_needed(next_section_idx, next_section_new_size, next_section_current_size)
        else:
            print("USEFUL!")  # TODO NOT USEFUL?!

        # The max size for the current section is total header width - the sum of all subsequent sections
        max_size = self.width() - (
            0
            if next_section_idx is None
            else sum(self.sectionSize(i) for i in range(next_section_idx, self.count()) if not self.isSectionHidden(i))
        )

        # Ensure the current section doesn't grow beyond the available space and doesn't shrink below its own minimum
        self._resize_section_if_needed(logical_index, max(min(new_size, max_size), self.minimum_section_size))
        self.blockSignals(False)

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.resize_sections()

    def resize_sections(self):
        available_space = self.width() - (self.count() - self.hiddenSectionCount() - 3) * self.minimum_section_size
        sizes = np.asarray([self.sectionSize(i) for i in range(3)])
        col12_widths = [max(int(available_space * sizes[i] / sum(sizes)), self.minimum_section_size) for i in (1, 2)]
        col_widths = [available_space - sum(col12_widths), *col12_widths]
        self.blockSignals(True)
        for column in range(3):
            self._resize_section_if_needed(column, col_widths[column])
        self._resize_section_if_needed(DATE_ADDED_COL_IDX, self.minimum_section_size)
        self._resize_section_if_needed(DURATION_COL_IDX, self.minimum_section_size)
        self.blockSignals(False)

    def _resize_section_if_needed(self, logical_index: int, new_size: int, old_size: int | None = None):
        if (self.sectionSize(logical_index) if old_size is None else old_size) != new_size:
            self.resizeSection(logical_index, new_size)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        logical_index = self.logicalIndexAt(event.pos())
        if logical_index == -1:
            return
        target_order = (
            Qt.SortOrder.AscendingOrder
            if self.sortIndicatorSection() != logical_index
            else (Qt.SortOrder.DescendingOrder if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder else None)
        )
        args = (-1, Qt.SortOrder.AscendingOrder) if target_order is None else (logical_index, target_order)
        self.setSortIndicator(*args)


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
            QTableView { background: black; border: none; }
            QTableView::item { background: transparent; }
        """)
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

        self.horizontalHeader().setSectionResizeMode(DATE_ADDED_COL_IDX, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setSectionResizeMode(DURATION_COL_IDX, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setSectionResizeMode(ALBUM_COL_IDX, QHeaderView.ResizeMode.Fixed)

        self.hovered_text_rect = QRect()
        self.hovered_data: Any = None

        self.viewport().installEventFilter(self)
        self.adjust_height_to_content()

    def get_text_rect_tups_for_index(self, index: QModelIndex | QPersistentModelIndex) -> list[tuple[QRect, str, str]]:
        column = index.column()
        index_rect = self.visualRect(index)
        font_metrics = self.fontMetrics()
        match column:
            case 0:  # SongItem
                text_rect = index_rect.adjusted(ICON_SIZE + PADDING, PADDING, -PADDING, -PADDING)

            case 1:  # ArtistsItem
                artists = index.data(Qt.ItemDataRole.DisplayRole)
                text_rect = index_rect.adjusted(PADDING, PADDING, -PADDING, -PADDING)
                return get_artist_text_rect_text_tups(artists, text_rect, font_metrics)

            case 2:  # AlbumItem
                text_rect = index_rect.adjusted(PADDING, PADDING, -PADDING, -PADDING)

            case _:
                return [(QRect(), "", "")]

        font_metrics = self.fontMetrics()
        original_text = index.data(Qt.ItemDataRole.DisplayRole)
        text = font_metrics.elidedText(original_text, Qt.TextElideMode.ElideRight, text_rect.width())
        text_size = font_metrics.boundingRect(text).size()
        h_space = (text_rect.width() - text_size.width()) - 2
        v_space = (text_rect.height() - text_size.height()) - 2
        text_rect.adjust(0, v_space // 2, -h_space, -v_space // 2)
        return [(text_rect, original_text, text)]

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
        for rect, data, shown_text in self.get_text_rect_tups_for_index(index):
            if not text_is_buffer(shown_text) and rect.contains(pos):
                self.hovered_text_rect, self.hovered_data = rect, data
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                break
        else:
            self.hovered_text_rect = QRect()
            self.hovered_data = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
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
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().update()
        super().leaveEvent(event)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.viewport() and event.type() == QEvent.Type.Wheel:
            event.ignore()  # Pass wheel events up to the parent
            return True  # Event handled
        return super().eventFilter(obj, event)

    def hide_date_added(self):
        header = cast(TableHeader, self.horizontalHeader())
        if not header.isSectionHidden(DATE_ADDED_COL_IDX):
            header.hideSection(DATE_ADDED_COL_IDX)
            header.resize_sections()
        if self.horizontalHeader().visualIndex(DATE_ADDED_COL_IDX) == DATE_ADDED_COL_IDX:  # It's in it's right spot
            self.horizontalHeader().moveSection(DATE_ADDED_COL_IDX, DURATION_COL_IDX)

    def show_date_added(self):
        header = cast(TableHeader, self.horizontalHeader())
        if header.isSectionHidden(DATE_ADDED_COL_IDX):
            header.showSection(DATE_ADDED_COL_IDX)
            header.resize_sections()
        if (date_index := header.visualIndex(DATE_ADDED_COL_IDX)) != DATE_ADDED_COL_IDX:
            header.moveSection(date_index, DATE_ADDED_COL_IDX)
