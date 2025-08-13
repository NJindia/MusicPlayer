import re
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import Enum
from functools import cache
from pathlib import Path
from typing import Any, cast, override

import numpy as np
from line_profiler_pycharm import profile  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSortFilterProxyModel,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QIcon,
    QMouseEvent,
    QPainter,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtSql import QSqlQueryModel
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from music_player.common_gui import (
    ShuffleButton,
    SongDrag,
    get_artist_text_rect_text_tups,
    get_pause_button_icon,
    get_play_button_icon,
    paint_artists,
    text_is_buffer,
)
from music_player.constants import MUSIC_IDS_MIMETYPE
from music_player.database import PATH_TO_IMGS, get_database_manager
from music_player.db_types import DbAlbum, DbArtist, DbCollection, DbStoredCollection
from music_player.signals import SharedSignals
from music_player.utils import (
    datetime_to_age_string,
    datetime_to_date_str,
    get_pixmap,
    get_single_song_drag_text,
    music_ids_to_qbytearray,
    qbytearray_to_music_ids,
    timestamp_to_str,
)
from music_player.view_types import LibraryTableView, PlaylistTreeView, StackGraphicsView
from music_player.vlc_core import VLCCore

PADDING = 5
ROW_HEIGHT = 50
ICON_SIZE = ROW_HEIGHT - PADDING * 2


class ColIndex(Enum):
    MUSIC_NAME = 0
    ARTISTS = 1
    ALBUM_NAME = 2
    DATE_ADDED = 3
    DURATION = 4


COLUMN_MAP_BY_IDX = {
    0: ("Title", "music_name"),
    1: ("Artists", "artist_names"),  # This is a custom-handled column
    2: ("Album", "album_name"),  # This is a relational column
    3: ("Date Added", "downloaded_on"),  # TODO
    4: ("Duration", "duration"),
}


def _get_total_length_string(total_timestamp: float) -> str:
    total_timestamp = round(total_timestamp / 60)
    components: list[str] = []
    for item in ["minute", "hour", "day"]:
        num = total_timestamp % 60
        if not num:
            break
        components.insert(0, f"{num} {item}{'s'[: num ^ 1]}")
        total_timestamp = total_timestamp // 60
    return " ".join(components)


def pg_array_agg_to_list(agg: str) -> list[str]:
    return [r.strip('"') for r in agg[1:-1].split(",")]  # TODO


def _paint_hoverable_elided_text(
    painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
) -> None:
    widget = cast(MusicLibraryTable, option.widget)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    text_rect, _, elided_text = widget.get_text_rect_tups_for_index(index)[0]
    if widget.hovered_text_rect == text_rect:
        font = QFont(option.font)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType]
        font.setUnderline(True)
        painter.setFont(font)  # pyright: ignore[reportUnknownMemberType]
    painter.drawText(text_rect, option.displayAlignment | Qt.TextFlag.TextSingleLine, elided_text)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType]


class AlbumItemDelegate(QStyledItemDelegate):
    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex):
        painter.save()
        _paint_hoverable_elided_text(painter, option, index)
        painter.restore()


class ArtistsItemDelegate(QStyledItemDelegate):
    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex):
        index_rect = cast(QRect, option.rect)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        view = cast(MusicLibraryTable, option.widget)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        text_rect = index_rect.adjusted(PADDING, PADDING, -PADDING, -PADDING)

        paint_artists(
            index.data(Qt.ItemDataRole.DisplayRole),
            painter,
            option,
            text_rect,
            cast(QFont, option.font),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
            lambda r: r == view.hovered_text_rect,
        )


class SongItemDelegate(QStyledItemDelegate):
    @override
    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        pixmap = index.data(Qt.ItemDataRole.DecorationRole)

        painter.save()
        if pixmap is not None:
            icon_rect = QRect(cast(QRect, option.rect).topLeft() + QPoint(0, PADDING), pixmap.size())  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
            painter.drawPixmap(icon_rect, pixmap)
        _paint_hoverable_elided_text(painter, option, index)
        painter.restore()


class MusicTableModel(QSqlQueryModel):
    re_pattern = re.compile(r"[\W_]+")

    def __init__(self, parent: "MusicLibraryTable"):
        super().__init__(parent)
        get_database_manager().get_qt_connection()
        self.setQuery("SELECT *, row_number() over () AS sort_order FROM library_music_view")

        self.music_id_field_idx = self.record().indexOf("music_id")
        self.music_name_field_idx = self.record().indexOf("music_name")
        self.artist_ids_field_idx = self.record().indexOf("artist_ids")
        self.artist_names_field_idx = self.record().indexOf("artist_names")
        self.album_name_field_idx = self.record().indexOf("album_name")
        self.album_id_field_idx = self.record().indexOf("album_id")
        self.duration_field_idx = self.record().indexOf("duration")
        self.album_img_path_field_idx = self.record().indexOf("img_path")
        self.sort_order_field_idx = self.record().indexOf("sort_order")

        self.sort_order_by_music_id = {
            super().data(self.index(i, self.music_id_field_idx)): super().data(self.index(i, self.sort_order_field_idx))
            for i in range(self.rowCount())
        }

        self.view = parent

    @override
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Returns header data for given role."""
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMN_MAP_BY_IDX.get(section, ("", ""))[0]
        return None

    @override
    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # noqa: PLR0911, PLR0912, C901
        """Returns data for given index."""
        if not index.isValid():
            return None

        column_name, db_field = COLUMN_MAP_BY_IDX.get(index.column(), (None, None))
        if not column_name or not db_field:
            return None

        if role == LibraryTableView.music_id_role:
            return super().data(self.index(index.row(), self.music_id_field_idx))

        if role == LibraryTableView.sort_order_role:
            return self.sort_order_by_music_id[super().data(self.index(index.row(), self.music_id_field_idx))]

        if role in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole}:
            res = super().data(self.index(index.row(), self.record().indexOf(db_field)), role)
            if column_name == "Artists":
                return pg_array_agg_to_list(res)
            if column_name == "Date Added":
                return datetime_to_age_string(datetime.fromtimestamp(res.toSecsSinceEpoch(), tz=UTC))
            if column_name == "Duration":
                return timestamp_to_str(res)
            return str(res)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        if role == Qt.ItemDataRole.ToolTipRole:
            data = super().data(self.index(index.row(), self.record().indexOf(db_field)), Qt.ItemDataRole.DisplayRole)
            if column_name == "Date Added":
                return datetime_to_date_str(datetime.fromtimestamp(data.toSecsSinceEpoch(), tz=UTC))
            text = ", ".join(pg_array_agg_to_list(data)) if column_name == "Artists" else data
            column_width = self.view.columnWidth(index.column()) - (ROW_HEIGHT if index.column() == 0 else PADDING * 2)
            if self.view.fontMetrics().horizontalAdvance(text) > column_width:
                return text
        if role == Qt.ItemDataRole.DecorationRole and column_name == "Title":
            img_path = super().data(self.index(index.row(), self.album_img_path_field_idx))
            if img_path:
                return get_pixmap(PATH_TO_IMGS / img_path, ICON_SIZE)
            return None  # Return None if no cover
        return None

    @override
    def mimeData(self, indexes: Sequence[QModelIndex], /):
        music_ids: list[int] = []
        last_row = -1
        for index in indexes:
            row = index.row()
            if last_row != row:
                music_ids.append(self.get_music_id(row))
            last_row = row

        data = QMimeData()
        data.setData(MUSIC_IDS_MIMETYPE, music_ids_to_qbytearray(music_ids))
        return data

    @override
    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        """Returns flags for given index."""
        return super().flags(index) | Qt.ItemFlag.ItemIsDragEnabled | ~Qt.ItemFlag.ItemIsEditable

    @cache
    def get_music_id(self, row: int) -> int:
        return super().data(self.index(row, self.music_id_field_idx))

    def get_visible_music_ids(self):
        return [
            self.get_music_id(row)
            for row in range(self.rowCount())  # TODO IF HIDDEN?
        ]

    def get_foreign_key(self, original_text: str, index: QModelIndex | QPersistentModelIndex) -> int | None:
        col = index.column()
        match col:
            case 1:  # Artists
                artist_names = self.data(self.index(index.row(), ColIndex.ARTISTS.value))
                artist_idx: int = artist_names.index(original_text)
                artist_ids = pg_array_agg_to_list(super().data(self.index(index.row(), self.artist_ids_field_idx)))
                return int(artist_ids[artist_idx])
            case 2:  # Album
                return super().data(self.index(index.row(), self.album_id_field_idx))
            case _:
                return None

    def get_total_timestamp(self):
        return sum([super().data(self.index(row, self.duration_field_idx)) for row in range(self.rowCount())])


class ProxyModel(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self._music_ids: tuple[int, ...] = ()
        self.setSortRole(LibraryTableView.sort_order_role)
        self.sort(0)

    @override
    def columnCount(self, /, parent: QModelIndex | QPersistentModelIndex = QModelIndex()):  # pyright: ignore[reportCallInDefaultInitializer]  # noqa: B008
        return 5

    @override
    def rowCount(self, /, parent: QModelIndex | QPersistentModelIndex = QModelIndex()):  # pyright: ignore[reportCallInDefaultInitializer]  # noqa: B008
        return len(self._music_ids)

    @override
    def sourceModel(self, /) -> MusicTableModel:
        return cast(MusicTableModel, super().sourceModel())

    @override
    def invalidateFilter(self, /):
        self.layoutAboutToBeChanged.emit()
        super().invalidateFilter()
        self.layoutChanged.emit()

    @override
    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex, /):
        if not self._music_ids:
            return False
        data = self.sourceModel().index(source_row, 0, source_parent).data(LibraryTableView.music_id_role)
        assert data
        return data in self._music_ids

    def set_music_ids(self, music_ids: tuple[int, ...]):
        if music_ids != self._music_ids:
            self._music_ids = music_ids
            self.invalidateFilter()

    def get_music_id(self, row: int):
        source_model_index = self.mapToSource(self.index(row, 0))
        return self.sourceModel().get_music_id(source_model_index.row())


class ElidedTextLabel(QLabel):
    def __init__(self, font_size: int):
        super().__init__()
        self.setObjectName("ElidedTextLabel")
        self.setContentsMargins(0, 0, 0, 0)
        self.setMargin(0)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        type_font = QFont()
        type_font.setBold(True)
        type_font.setPointSize(font_size)
        self.original_text = ""
        self.setFont(type_font)  # pyright: ignore[reportUnknownMemberType]

    @override
    def setText(self, text: str):
        self.original_text = text
        self._elide_text()

    @override
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


class MusicLibraryScrollArea(QScrollArea):
    def __init__(self, library: "MusicLibraryWidget"):
        super().__init__()
        self.library = library
        self.setWidgetResizable(True)
        self.setWidget(self.library)

        self.setMinimumWidth(500 + QApplication.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.header = self.library.table_view.horizontalHeader()
        self.original_header_rect = self.header.rect()
        self.verticalScrollBar().valueChanged.connect(self.update_header)

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.library.setMaximumWidth(event.size().width())

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


class LibraryHeaderWidget(QWidget):
    header_img_size = 140
    header_padding = 5

    def __init__(self, shared_signals: SharedSignals, library: "MusicLibraryWidget"):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.header_img = QLabel()

        header_text_layout = QVBoxLayout()
        header_text_layout.setContentsMargins(0, 0, 0, 0)
        header_text_layout.addStretch()

        self.header_label_type = ElidedTextLabel(10)
        self.header_label_title = ElidedTextLabel(20)
        self.header_label_subtitle = ElidedTextLabel(12)
        self.header_label_meta = ElidedTextLabel(12)

        header_text_layout.addWidget(self.header_label_type)
        header_text_layout.addWidget(self.header_label_title)
        header_text_layout.addWidget(self.header_label_subtitle)
        header_text_layout.addWidget(self.header_label_meta)

        header_meta_layout = QHBoxLayout()
        header_meta_layout.addWidget(self.header_img)
        header_meta_layout.addLayout(header_text_layout)

        self.play_pause_button = QToolButton()
        self.set_play_pause_button_state(is_play_button=True)

        self.shuffle_button = ShuffleButton(shared_signals)

        self.save_button = QToolButton()
        self.save_button.setIcon(QIcon(get_pixmap(Path("../icons/add-to.svg"), None, color=Qt.GlobalColor.white)))

        self.menu_button = QToolButton()
        self.menu_button.setIcon(QIcon(get_pixmap(Path("../icons/more-button.svg"), None, color=Qt.GlobalColor.white)))

        search_bar = QLineEdit()
        search_bar.textChanged.connect(library.filter)
        search_bar.setClearButtonEnabled(True)
        search_bar.setPlaceholderText("Search")

        header_interactive_layout = QHBoxLayout()
        header_interactive_layout.addWidget(self.play_pause_button)
        header_interactive_layout.addWidget(self.shuffle_button)
        header_interactive_layout.addWidget(self.save_button)
        header_interactive_layout.addWidget(self.menu_button)
        header_interactive_layout.addStretch()
        header_interactive_layout.addWidget(search_bar)

        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(
            self.header_padding, self.header_padding, self.header_padding, self.header_padding
        )
        header_layout.addLayout(header_meta_layout)
        header_layout.addLayout(header_interactive_layout)
        self.setLayout(header_layout)

    def set_play_pause_button_state(self, *, is_play_button: bool):
        self.play_pause_button.setProperty("is_play_button", is_play_button)
        self.play_pause_button.setIcon(get_play_button_icon() if is_play_button else get_pause_button_icon())


class MusicLibraryWidget(QWidget):
    def __init__(self, shared_signals: SharedSignals, core: VLCCore):
        super().__init__()
        self.setObjectName("MusicLibrary")
        self.library_id: str = ""
        self.core = core

        shared_signals.library_load_artist_signal.connect(self.load_artist)
        shared_signals.library_load_album_signal.connect(self.load_album)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Expanding)

        self.header_widget = LibraryHeaderWidget(shared_signals, self)
        self.table_view = MusicLibraryTable(shared_signals, self)
        self.header_widget.play_pause_button.clicked.connect(self.play_button_clicked)

        self.collection: DbCollection | None = None
        self.load_playlist(DbStoredCollection.from_db())

        layout = QVBoxLayout()
        layout.addWidget(self.header_widget)
        layout.addWidget(self.table_view)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

    def play_button_clicked(self):
        if self.header_widget.play_pause_button.property("is_play_button"):
            if self.core.current_collection == self.collection:
                self.core.media_player.play()
            else:
                self.table_view.song_clicked.emit(0)
        else:
            self.core.media_player.pause()

    @Slot()
    def play_library(self) -> None:
        self.table_view.song_clicked.emit(0)

    @Slot()
    def filter(self, text: str):
        model = self.table_view.model_

        def clean_text(_text: str):
            return re.sub(model.re_pattern, "", _text).lower()

        cleaned_text = clean_text(text)
        good_rows: list[int] = []
        bad_rows: list[int] = []
        for row in range(model.rowCount()):
            if (
                cleaned_text in clean_text(model.data(model.index(row, ColIndex.MUSIC_NAME.value)))  # Title
                or cleaned_text in clean_text(model.data(model.index(row, ColIndex.ALBUM_NAME.value)))  # Album
            ):
                good_rows.append(row)
                continue
            bad_rows.append(row)
        for row in bad_rows:
            if not self.table_view.isRowHidden(row):
                self.table_view.hideRow(row)
        for row in good_rows:
            if self.table_view.isRowHidden(row):
                self.table_view.showRow(row)
        self.table_view.adjust_height_to_content()

    @profile
    def _load(
        self,
        *,
        new_collection: DbCollection | None,
        img_pixmap: QPixmap,
        header_label_type: str,
        header_label_title: str,
        header_label_subtitle: str | None,
        show_date_added_col: bool | None,
        no_meta: bool = False,
        sort_orders: list[int] | None = None,
    ):
        self.header_widget.header_img.setPixmap(img_pixmap)
        self.header_widget.header_label_type.setText(header_label_type)
        self.header_widget.header_label_title.setText(header_label_title)

        if header_label_subtitle is None:
            self.header_widget.header_label_subtitle.setVisible(False)
        else:
            self.header_widget.header_label_subtitle.setText(header_label_subtitle)
            self.header_widget.header_label_subtitle.setVisible(True)

        if show_date_added_col is not None:
            if show_date_added_col:
                self.table_view.show_date_added()
            else:
                self.table_view.hide_date_added()

        if self.collection != new_collection:
            self.table_view.selectionModel().clearSelection()
            self.collection = new_collection
        if self.collection is None:
            print("NOT IMPLEMENTED")
        is_play_button = self.collection != self.core.current_collection or not self.core.media_player.is_playing()
        self.header_widget.set_play_pause_button_state(is_play_button=is_play_button)

        model = self.table_view.model()
        music_ids = () if new_collection is None else new_collection.music_ids
        model.set_music_ids(music_ids)
        if sort_orders is not None:
            self.table_view.model_.sort_order_by_music_id = dict(zip(music_ids, sort_orders, strict=True))
            assert len(sort_orders) == self.table_view.model().rowCount()
            print("LOAD")
            model.invalidate()
        if not no_meta:
            num_tracks = model.rowCount()
            total_timestamp = self.table_view.model_.get_total_timestamp()  # TODO FIX THIS TO MODEL()
            meta_text = f"{num_tracks} Track{'s'[: num_tracks ^ 1]}, {_get_total_length_string(total_timestamp)}"
        else:
            meta_text = ""
        self.header_widget.header_label_meta.setText(meta_text)

    def load_nothing(self):
        self._load(
            new_collection=None,
            img_pixmap=get_pixmap(None, self.header_widget.header_img_size),
            header_label_type="",
            header_label_title="",
            header_label_subtitle=None,
            show_date_added_col=None,
            no_meta=True,
        )

    @profile
    def load_playlist(self, playlist: DbStoredCollection):
        t = datetime.now(tz=UTC)
        self.library_id = str(playlist.id)

        self._load(
            new_collection=playlist,
            img_pixmap=playlist.get_thumbnail_pixmap(self.header_widget.header_img_size),
            header_label_type="Playlist",
            header_label_title=playlist.name,
            header_label_subtitle=None,
            show_date_added_col=True,
            sort_orders=playlist.sort_order,
        )
        print("LOAD END", (datetime.now(tz=UTC) - t).microseconds / 1000)

    @Slot(int)
    def load_artist(self, artist_id: int):
        artist = DbArtist.from_db(artist_id)
        img_size = self.header_widget.header_img_size
        self._load(
            new_collection=artist,  # TODO
            img_pixmap=get_pixmap(artist.img_path, img_size),
            header_label_type="Artist",
            header_label_title=artist.name,
            header_label_subtitle=None,
            show_date_added_col=False,
        )

    @Slot()
    def load_album(self, album_id: int, *, is_db_collection: bool = False):  # TODO ENABLE LATER
        self.library_id = f"album-{album_id}"

        # assert len(set(album_df["album_artist"])) == 1  # TODO HANDLE THIS
        album = DbAlbum.from_db(album_id)
        self._load(
            new_collection=album,  # TODO
            img_pixmap=get_pixmap(album.img_path, self.header_widget.header_img_size),
            header_label_type="Album",
            header_label_title=album.name,
            header_label_subtitle="",  # album_df.iloc[0]["album_artist"],
            show_date_added_col=False,
        )


class TableHeader(QHeaderView):
    minimum_section_size = 100

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setSectionsClickable(True)
        self.setObjectName("LibraryTableHeader")
        self.setSortIndicatorClearable(True)
        self.setSortIndicatorShown(True)
        self.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setMinimumSectionSize(self.minimum_section_size)
        self.sectionResized.connect(self._resize)

    @override
    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.resize_sections()

    @override
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

    def _resize(self, logical_index: int, old_size: int, new_size: int):
        self.blockSignals(True)  # noqa: FBT003
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
        self.blockSignals(False)  # noqa: FBT003

    def resize_sections(self):
        available_space = self.width() - (self.count() - self.hiddenSectionCount() - 3) * self.minimum_section_size
        sizes = np.asarray([self.sectionSize(i) for i in range(3)])
        col12_widths = [max(int(available_space * sizes[i] / sum(sizes)), self.minimum_section_size) for i in (1, 2)]
        col_widths = [available_space - sum(col12_widths), *col12_widths]
        self.blockSignals(True)  # noqa: FBT003
        for column in range(3):
            self._resize_section_if_needed(column, col_widths[column])
        self._resize_section_if_needed(ColIndex.DATE_ADDED.value, self.minimum_section_size)
        self._resize_section_if_needed(ColIndex.DURATION.value, self.minimum_section_size)
        self.blockSignals(False)  # noqa: FBT003

    def _resize_section_if_needed(self, logical_index: int, new_size: int, old_size: int | None = None):
        if (self.sectionSize(logical_index) if old_size is None else old_size) != new_size:
            self.resizeSection(logical_index, new_size)


class MusicLibraryTable(LibraryTableView):
    song_clicked = Signal(int)

    def __init__(self, shared_signals: SharedSignals, parent: MusicLibraryWidget):
        super().__init__(parent)
        self.setObjectName("LibraryTableView")
        self._signals = shared_signals

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.setShowGrid(False)
        self.setMouseTracking(True)
        self.setWordWrap(False)
        self.setSortingEnabled(True)
        self.setCornerButtonEnabled(False)

        self.setDragEnabled(True)
        self.setDragDropMode(QTableView.DragDropMode.DragDrop)
        self.setDragDropOverwriteMode(False)
        self.setAcceptDrops(True)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalHeader(TableHeader())

        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.setFont(QFont())  # pyright: ignore[reportUnknownMemberType]

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.song_delegate = SongItemDelegate(self)
        self.setItemDelegateForColumn(0, self.song_delegate)
        self.artists_delegate = ArtistsItemDelegate(self)
        self.setItemDelegateForColumn(1, self.artists_delegate)
        self.album_delegate = AlbumItemDelegate(self)
        self.setItemDelegateForColumn(2, self.album_delegate)

        self.model_ = MusicTableModel(self)
        proxy_model = ProxyModel()
        proxy_model.setSourceModel(self.model_)
        self.setModel(proxy_model)
        self.model().layoutChanged.connect(self.adjust_height_to_content)

        self.horizontalHeader().setSectionResizeMode(ColIndex.DATE_ADDED.value, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setSectionResizeMode(ColIndex.DURATION.value, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setSectionResizeMode(ColIndex.ALBUM_NAME.value, QHeaderView.ResizeMode.Fixed)

        self.hovered_text_rect: QRect = QRect()
        self.hovered_data: int | None = None

        self.viewport().installEventFilter(self)

    @override
    def startDrag(self, supportedActions: Qt.DropAction, /):
        indices = self.selectedIndexes()
        row_count = len({i.row() for i in indices})
        if not row_count:
            raise ValueError
        if row_count == 1:
            model = self.model()
            title = model.data(model.index(indices[0].row(), ColIndex.MUSIC_NAME.value))
            artists = model.data(model.index(indices[0].row(), ColIndex.ARTISTS.value))
            text = get_single_song_drag_text(title, artists)
        else:
            text = f"{row_count} items"

        drag = SongDrag(self, text)
        drag.setMimeData(self.model().mimeData(indices))  # pyright: ignore[reportUnknownMemberType]
        drag.exec(supportedActions)

    @override
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasFormat(MUSIC_IDS_MIMETYPE):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()

    @override
    def dragMoveEvent(self, event: QDragMoveEvent, /):
        source = event.source()
        playlist = cast(MusicLibraryWidget, self.parent()).collection
        if playlist is None or playlist.is_protected or not isinstance(source, (PlaylistTreeView, StackGraphicsView)):
            event.ignore()
        else:
            event.accept()

    @override
    def dropEvent(self, event: QDropEvent, /):
        music_ids = qbytearray_to_music_ids(event.mimeData().data(MUSIC_IDS_MIMETYPE))
        dest_playlist = cast(MusicLibraryWidget, self.parent()).collection
        assert dest_playlist is not None
        self._signals.add_to_playlist_signal.emit(music_ids, dest_playlist)

    @override
    def mouseMoveEvent(self, event: QMouseEvent):
        pos = event.pos()
        proxy_index = self.indexAt(pos)
        if not proxy_index.isValid():
            return
        for rect, original_text, shown_text in self.get_text_rect_tups_for_index(proxy_index):
            if not text_is_buffer(shown_text) and rect.contains(pos):
                self.hovered_text_rect = rect
                self.hovered_data = self.model_.get_foreign_key(original_text, self.model().mapToSource(proxy_index))
                self.setCursor(Qt.CursorShape.PointingHandCursor)
                break
        else:
            self.hovered_text_rect = QRect()
            self.hovered_data = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().update(self.visualRect(proxy_index))
        super().mouseMoveEvent(event)

    @override
    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            if self.hovered_text_rect.contains(pos):
                index = self.indexAt(pos)
                match index.column():
                    case 0:
                        self.song_clicked.emit(index.row())
                    case 1:
                        self._signals.library_load_artist_signal.emit(self.hovered_data)
                    case 2:
                        self._signals.library_load_album_signal.emit(self.hovered_data)
                    case _:
                        raise NotImplementedError
        super().mouseReleaseEvent(event)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.RightButton:
            super().mousePressEvent(event)

    @override
    def mouseDoubleClickEvent(self, event: QMouseEvent, /):
        index = self.indexAt(event.pos())
        if not index.isValid():
            return
        self.song_clicked.emit(index.row())

    @override
    def leaveEvent(self, event: QEvent) -> None:
        self.hovered_text_rect = QRect()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport().update()
        super().leaveEvent(event)

    @override
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self.viewport() and event.type() == QEvent.Type.Wheel:
            event.ignore()  # Pass wheel events up to the parent
            return True  # Event handled
        return super().eventFilter(obj, event)

    @override
    def model(self, /) -> ProxyModel:
        return cast(ProxyModel, super().model())

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
        if self.model().rowCount() == 0:
            self.setMinimumHeight(self.horizontalHeader().height() + 2)
            return
        total_height = (
            2
            + self.horizontalHeader().height()
            + sum(self.verticalHeader().sectionSize(row) for row in range(self.model().rowCount()))
        )
        self.setMinimumHeight(total_height)

    def hide_date_added(self):
        date_added_idx = ColIndex.DATE_ADDED.value
        header = cast(TableHeader, self.horizontalHeader())
        if not header.isSectionHidden(date_added_idx):
            header.hideSection(date_added_idx)
            header.resize_sections()
        if self.horizontalHeader().visualIndex(date_added_idx) == date_added_idx:  # It's in it's right spot
            self.horizontalHeader().moveSection(date_added_idx, ColIndex.DURATION.value)

    def show_date_added(self):
        date_added_idx = ColIndex.DATE_ADDED.value
        header = cast(TableHeader, self.horizontalHeader())
        if header.isSectionHidden(date_added_idx):
            header.showSection(date_added_idx)
            header.resize_sections()
        if (date_index := header.visualIndex(date_added_idx)) != date_added_idx:
            header.moveSection(date_index, date_added_idx)
