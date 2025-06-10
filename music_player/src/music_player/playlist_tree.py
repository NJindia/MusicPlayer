import json
import math
import shutil
from datetime import datetime, UTC
from enum import Enum
from functools import partial, cache
from pathlib import Path
from typing import cast, Iterator

from PySide6.QtCore import (
    Qt,
    QModelIndex,
    QPoint,
    Slot,
    QSize,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    QObject,
    QEvent,
)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon, QAction, QFont, QPixmap
from PySide6.QtWidgets import (
    QMainWindow,
    QTreeView,
    QWidget,
    QVBoxLayout,
    QMenu,
    QLabel,
    QLineEdit,
    QHBoxLayout,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
)

from music_player.common_gui import NewPlaylistAction, NewFolderAction
from music_player.constants import MAX_SIDE_BAR_WIDTH
from music_player.playlist import Playlist, get_playlist
from music_player.signals import SharedSignals
from music_player.utils import get_colored_pixmap

PLAYLIST_ROW_HEIGHT = 50
DEFAULT_PLAYLIST_PATH = Path("../playlists")
PLAYLIST_CUSTOM_INDEX_JSON_PATH = Path("../custom_playlist_indices.json")


class SORT_ROLE(Enum):
    CUSTOM = Qt.ItemDataRole.UserRole + 1
    UPDATED = Qt.ItemDataRole.UserRole + 2
    PLAYED = Qt.ItemDataRole.UserRole + 3
    ALPHABETICAL = Qt.ItemDataRole.UserRole + 4


DEFAULT_SORT_ORDER_BY_SORT_ROLE: dict[SORT_ROLE, Qt.SortOrder] = {
    SORT_ROLE.CUSTOM: Qt.SortOrder.AscendingOrder,
    SORT_ROLE.UPDATED: Qt.SortOrder.DescendingOrder,
    SORT_ROLE.PLAYED: Qt.SortOrder.DescendingOrder,
    SORT_ROLE.ALPHABETICAL: Qt.SortOrder.AscendingOrder,
}
INITIAL_SORT_ROLE = SORT_ROLE.PLAYED  # TODO: CUSTOM


class TreeItemDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex, /) -> QSize:
        default_size = super().sizeHint(option, index)
        return QSize(default_size.width(), PLAYLIST_ROW_HEIGHT)


@cache
def get_folder_pixmap(height: int) -> QPixmap:
    return QPixmap("../icons/folder.svg").scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)


class TreeModelItem(QStandardItem):
    def __init__(self, path: Path, playlist: Playlist | None) -> None:
        super().__init__(path.stem)
        font = QFont()
        font.setPointSize(14)
        self.setFont(font)
        self.setEditable(False)
        self.playlist = playlist
        self.path = path
        self.update_icon()

    def data(self, /, role: int = Qt.ItemDataRole.DisplayRole):
        if role == SORT_ROLE.CUSTOM.value:
            return _get_custom_ordered_playlists().index(self.path)
        elif role == SORT_ROLE.UPDATED.value:
            if self.playlist:
                return self.playlist.last_updated.timestamp()
            elif self.hasChildren():  # Get most recent child playlist value
                return max(
                    cast(Playlist, p.playlist).last_updated for p in _recursive_traverse(self, get_non_leaf=False)
                ).timestamp()
            else:  # Get folder modified time
                return self.path.stat().st_mtime
        elif role == SORT_ROLE.PLAYED.value:
            if self.playlist and self.playlist.last_played:
                return self.playlist.last_played.timestamp()
            elif not self.playlist and self.hasChildren():  # Get most last played child playlist value
                return max(
                    [
                        t
                        for t in [
                            cast(Playlist, p.playlist).last_played
                            for p in _recursive_traverse(self, get_non_leaf=False)
                        ]
                        if t is not None
                    ],
                    default=datetime.max.replace(tzinfo=UTC),
                ).timestamp()
            else:  # Hasn't been played yet, put at bottom
                return datetime.max.replace(tzinfo=UTC).timestamp()
        elif role == SORT_ROLE.ALPHABETICAL.value:
            return self.text()
        return super().data(role)

    def update_icon(self):
        self.setIcon(
            QIcon(
                get_folder_pixmap(PLAYLIST_ROW_HEIGHT)
                if self.playlist is None
                else self.playlist.get_thumbnail_pixmap(PLAYLIST_ROW_HEIGHT)
            )
        )


def _recursive_traverse(parent_item: QStandardItem, *, get_non_leaf: bool) -> Iterator[TreeModelItem]:
    for row in range(parent_item.rowCount()):
        child_item = cast(TreeModelItem, parent_item.child(row))
        if child_item:
            if child_item.hasChildren():
                if get_non_leaf:
                    yield child_item
                yield from _recursive_traverse(child_item, get_non_leaf=get_non_leaf)
            else:
                yield child_item


class PlaylistTreeWidget(QWidget):
    def __init__(self, parent: QWidget, main_window: QMainWindow, signals: SharedSignals, *, is_main_view: bool):
        super().__init__(parent)
        self.is_main_view = is_main_view
        self.signals = signals

        self.setStyleSheet("QWidget { margin: 0px; border: none; }")
        self.setMaximumWidth(MAX_SIDE_BAR_WIDTH)
        self.tree_view = QTreeView()
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setExpandsOnDoubleClick(True)
        self.tree_view.setAnimated(True)
        self.tree_view.setSortingEnabled(False)
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setIconSize(QSize(PLAYLIST_ROW_HEIGHT, PLAYLIST_ROW_HEIGHT))
        delegate = TreeItemDelegate()
        self.tree_view.setItemDelegate(delegate)

        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        self.model_: QStandardItemModel = QStandardItemModel()
        self.model_.dataChanged.connect(self.update_playlist)
        self._initialize_model()

        self.proxy_model = QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.model_)
        self.proxy_model.setSortRole(INITIAL_SORT_ROLE.value)
        self.tree_view.setModel(self.proxy_model)

        header_widget = QWidget()
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_widget.setLayout(header_layout)
        if self.is_main_view:
            label = QLabel("Playlists", self)
            label_font = QFont()
            label_font.setPointSize(20)
            label_font.setBold(True)
            label.setFont(label_font)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

            create_menu = QMenu(self)
            args = create_menu, main_window, self.model_.invisibleRootItem().index(), self.signals
            create_menu.addActions([NewPlaylistAction(*args), NewFolderAction(*args)])

            new_button = QToolButton(self)
            new_button.setText("+ New")
            new_button.setMenu(create_menu)
            new_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            new_button.setStyleSheet("""
                        QToolButton::menu-indicator { image: none; }
                        QToolButton { border-radius: 5px; background: grey}
                    """)

            header_top_layout = QHBoxLayout()
            header_top_layout.setContentsMargins(0, 0, 0, 0)
            header_top_layout.addWidget(label)
            header_top_layout.addWidget(new_button)
            header_layout.addLayout(header_top_layout)

        search_bar = QLineEdit()
        search_bar.textChanged.connect(self.filter)
        search_bar.setClearButtonEnabled(True)
        search_bar.setPlaceholderText("Search playlists")

        self.sort_button = QToolButton(self)  # TODO CUSTOM WIDGET TO GET RID OF SPACING BETWEEN
        self.sort_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.sort_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.sort_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.sort_button.setStyleSheet("""
            QToolButton::menu-indicator { image: none; }
            QToolButton { padding: 5px; }
        """)
        self.update_sort_button()

        self.sort_menu = SortMenu(self)
        self.sort_button.setMenu(self.sort_menu)

        search_sort_layout = QHBoxLayout()
        search_sort_layout.setContentsMargins(0, 0, 0, 0)
        search_sort_layout.addWidget(search_bar)
        search_sort_layout.addWidget(self.sort_button)
        header_layout.addLayout(search_sort_layout)

        layout = QVBoxLayout()
        layout.addWidget(header_widget)
        layout.addWidget(self.tree_view)
        self.setLayout(layout)

    def update_sort_button(self):
        sort_role = SORT_ROLE(self.proxy_model.sortRole())
        order_str = "asc" if self.proxy_model.sortOrder() == Qt.SortOrder.AscendingOrder else "desc"
        pm = get_colored_pixmap(
            QPixmap(f"../icons/sort/sort-{'alpha-' if sort_role == SORT_ROLE.ALPHABETICAL else ''}{order_str}.svg"),
            Qt.GlobalColor.white,
        )
        self.sort_button.setIcon(QIcon(pm))
        self.sort_button.setText(sort_role.name.capitalize())

    def save_model_as_custom_indices(self):
        indices_json = [i.path for i in _recursive_traverse(self.item_at_index(QModelIndex), get_non_leaf=True)]
        print(indices_json)

    def filter(self, text: str):
        if text == "":  # Revert back to original nested view
            self.proxy_model.setSourceModel(self.model_)
            return
        # Flatten and list each item in single column
        traversed_tups = _recursive_traverse(self.model_.invisibleRootItem(), get_non_leaf=self.is_main_view)
        filtered_tups = [t for t in traversed_tups if text.lower() in t.text().lower()]

        search_model = QStandardItemModel()
        search_model.dataChanged.connect(self.update_playlist)
        for item in filtered_tups:
            search_model.appendRow(TreeModelItem(item.path, item.playlist))
        self.proxy_model.setSourceModel(search_model)

    @Slot(SORT_ROLE)
    def change_sort_role(self, sort_role: SORT_ROLE) -> None:
        sort_type = sort_role.value
        order = (
            (
                Qt.SortOrder.DescendingOrder
                if self.proxy_model.sortOrder() == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
            if self.proxy_model.sortRole() == sort_type
            else DEFAULT_SORT_ORDER_BY_SORT_ROLE[sort_role]
        )
        if sort_type == SORT_ROLE.CUSTOM:
            self.save_model_as_custom_indices()
        else:
            self.proxy_model.setSortRole(sort_type)
        # TODO THIS IS BASICALLY JUST ALPHA
        self.proxy_model.sort(-1 if sort_type == SORT_ROLE.CUSTOM else 0, order)

        self.update_sort_button()
        self.sort_menu.update_active_action()

    def source_model(self):
        return cast(QStandardItemModel, self.proxy_model.sourceModel())

    def item_at_index(self, index: QModelIndex, *, is_source: bool = False) -> TreeModelItem:
        assert not isinstance(index.model(), QSortFilterProxyModel if is_source else QStandardItemModel)
        return cast(
            TreeModelItem,
            self.source_model().itemFromIndex(index if is_source else self.proxy_model.mapToSource(index)),
        )

    @Slot()
    def rename_playlist(self, index: QModelIndex) -> None:
        item = self.item_at_index(index)
        self.model_.blockSignals(True)
        item.setEditable(True)
        self.tree_view.edit(index)
        item.setEditable(False)
        self.model_.blockSignals(False)

    @Slot()
    def delete_playlist(self, index: QModelIndex) -> None:
        item = self.item_at_index(index)
        parent = item.parent()
        self.model_.beginRemoveRows(index, index.row(), index.row())
        (self.model_ if parent is None else parent).removeRow(item.row())
        if item.path.is_dir():
            shutil.rmtree(item.path)
        else:
            item.path.unlink()
        print("TODO: PUSH CONFIRMATION")

    @Slot()
    def update_playlist(self, tl: QModelIndex, br: QModelIndex, roles) -> None:
        print(tl, br, roles)  # TODO: REFRESH PERSISTENT SOURCE MODEL
        if Qt.ItemDataRole.DisplayRole in roles:
            item = self.item_at_index(tl, is_source=True)
            playlist = item.playlist
            if playlist is None:
                raise NotImplementedError
            playlist.title = item.text()
            playlist.playlist_path = playlist.playlist_path.parent / f"{item.text()}.json"
            playlist.save()

    @Slot()
    def playlist_context_menu(self, main_window: QMainWindow, point: QPoint):
        tree_index = self.tree_view.indexAt(point)
        menu = QMenu(self.tree_view)
        root_index = self.model_.invisibleRootItem().index()
        if tree_index.isValid():
            rename_action = QAction("Rename", self.tree_view)
            rename_action.triggered.connect(partial(self.rename_playlist, tree_index))

            delete_action = QAction("Delete", self.tree_view)
            delete_action.triggered.connect(partial(self.delete_playlist, tree_index))

            menu.addActions([rename_action, delete_action])

            if (item := self.item_at_index(tree_index)).playlist is None:  # Clicked on folder
                root_index = self.proxy_model.mapToSource(tree_index)
            elif (parent := item.parent()) is not None:  # Not top-level
                root_index = parent.index()
        args = menu, main_window, root_index, self.signals
        menu.addActions([NewPlaylistAction(*args), NewFolderAction(*args)])

        menu.exec_(self.tree_view.mapToGlobal(point))

    def _initialize_model(self, path: Path | None = None, root_item: QStandardItem | None = None) -> None:
        path = DEFAULT_PLAYLIST_PATH if path is None else path
        root_item = self.model_.invisibleRootItem() if root_item is None else root_item
        for fp in path.iterdir():
            if fp.is_dir():
                item = TreeModelItem(fp, None)
                root_item.appendRow(item)
                self._initialize_model(fp, item)
            else:
                playlist = get_playlist(fp)
                item = TreeModelItem(playlist.playlist_path, playlist)
                root_item.appendRow(item)

    def refresh_playlist(self, playlist: Playlist):
        item = next(
            tree_model_item
            for tree_model_item in _recursive_traverse(self.model_.invisibleRootItem(), get_non_leaf=False)
            if cast(Playlist, tree_model_item.playlist).playlist_path == playlist.playlist_path
        )
        item.playlist = playlist
        item.update_icon()


@cache
def _get_custom_ordered_playlists() -> list[Path]:
    with PLAYLIST_CUSTOM_INDEX_JSON_PATH.open("rb") as f:
        return json.load(f)


class SortRoleAction(QAction):
    def __init__(self, sort_role: SORT_ROLE, playlist_widget: PlaylistTreeWidget, parent: QMenu) -> None:
        super().__init__(sort_role.name.capitalize(), parent)
        self.sort_role = sort_role
        self.triggered.connect(partial(playlist_widget.change_sort_role, sort_role))


class SortMenu(QMenu):
    def __init__(self, parent: PlaylistTreeWidget) -> None:
        super().__init__(parent)
        self.installEventFilter(self)
        self.setStyleSheet("""
            QMenu::item {
                padding: 5px;
                spacing: 0px;
            }
        """)

        self.sort_custom_action = SortRoleAction(SORT_ROLE.CUSTOM, parent, self)
        self.sort_updated_action = SortRoleAction(SORT_ROLE.UPDATED, parent, self)
        self.sort_played_action = SortRoleAction(SORT_ROLE.PLAYED, parent, self)
        self.sort_alphabetical_action = SortRoleAction(SORT_ROLE.ALPHABETICAL, parent, self)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        self.addActions(
            [self.sort_custom_action, self.sort_updated_action, self.sort_played_action, self.sort_alphabetical_action]
        )

        self.update_active_action()

    def parent(self, /) -> PlaylistTreeWidget:
        return cast(PlaylistTreeWidget, super().parent())

    def update_active_action(self):
        curr_sort_role = self.parent().proxy_model.sortRole()
        for action in (
            self.sort_custom_action,
            self.sort_updated_action,
            self.sort_played_action,
            self.sort_alphabetical_action,
        ):
            if action.sort_role.value == curr_sort_role:
                order_str = "up" if self.parent().proxy_model.sortOrder() == Qt.SortOrder.AscendingOrder else "down"
                pm = get_colored_pixmap(QPixmap(f"../icons/arrows/arrow-narrow-{order_str}.svg"), Qt.GlobalColor.white)
                action.setIcon(QIcon(pm))
            else:
                action.setIcon(QIcon())

    def eventFilter(self, watched: QObject, event: QEvent, /) -> bool:
        if event.type() == QEvent.Type.MouseButtonRelease:
            if isinstance(watched, QMenu):
                if action := watched.activeAction():
                    action.trigger()
                    return True
        return super().eventFilter(watched, event)
