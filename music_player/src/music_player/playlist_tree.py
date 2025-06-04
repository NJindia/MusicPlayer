from functools import partial, cache
from pathlib import Path
from typing import cast, Iterator

from PySide6.QtCore import Qt, QModelIndex, QPoint, Slot, QSize, QPersistentModelIndex
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon, QAction, QFont, QPixmap
from PySide6.QtWidgets import (
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

from music_player.common import NewPlaylistAction, NewFolderAction
from music_player.constants import MAX_SIDE_BAR_WIDTH
from music_player.playlist import Playlist, get_playlist

PLAYLIST_ROW_HEIGHT = 50


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
    def __init__(self, text: str, playlist: Playlist | None) -> None:
        super().__init__(text)
        font = QFont()
        font.setPointSize(14)
        self.setFont(font)
        self.setEditable(False)
        self.playlist = playlist
        self.update_icon()

    def update_icon(self):
        self.setIcon(
            QIcon(
                get_folder_pixmap(PLAYLIST_ROW_HEIGHT)
                if self.playlist is None
                else self.playlist.get_thumbnail_pixmap(PLAYLIST_ROW_HEIGHT)
            )
        )


class PlaylistTreeWidget(QWidget):
    def __init__(self, parent: QWidget, *, is_main_view: bool):
        super().__init__(parent)
        self.is_main_view = is_main_view

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
        self.model_.itemChanged.connect(self.update_playlist)
        self.initialize_model(Path("../playlists"), self.model_)

        layout = QVBoxLayout()
        for widget in self.header_widgets():
            layout.addWidget(widget)
        layout.addWidget(self.tree_view)
        self.setLayout(layout)

        self.tree_view.setModel(self.model_)

    def _recursive_traverse(
        self, parent_item: QStandardItem, *, get_non_leaf: bool
    ) -> Iterator[tuple[TreeModelItem, bool]]:
        for row in range(parent_item.rowCount()):
            child_item = cast(TreeModelItem, parent_item.child(row))
            if child_item:
                if child_item.hasChildren():
                    if get_non_leaf:
                        yield child_item, True
                    yield from self._recursive_traverse(child_item, get_non_leaf=get_non_leaf)
                else:
                    yield child_item, False

    def filter(self, text: str):
        if text == "":  # Revert back to original nested view
            self.tree_view.setModel(self.model_)
            return
        # Flatten and list each item in single column
        traversed_tups = self._recursive_traverse(self.model_.invisibleRootItem(), get_non_leaf=self.is_main_view)
        filtered_tups = [t for t in traversed_tups if text.lower() in t[0].text().lower()]

        search_model = QStandardItemModel()
        search_model.itemChanged.connect(self.update_playlist)
        for item, _ in filtered_tups:
            search_model.appendRow(TreeModelItem(item.text(), item.playlist))
        self.tree_view.setModel(search_model)

    def header_widgets(self) -> list[QWidget]:
        widgets: list[QWidget] = []
        if self.is_main_view:
            label = QLabel("Playlists", self)
            label_font = QFont()
            label_font.setPointSize(20)
            label_font.setBold(True)
            label.setFont(label_font)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

            new_button = QToolButton(self)
            new_button.setText("+ New")
            new_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            new_button.setStyleSheet("QToolButton::menu-indicator { image: none; }")

            menu = QMenu(self)
            menu.addActions([NewPlaylistAction(self), NewFolderAction(self)])
            new_button.setMenu(menu)

            header_layout = QHBoxLayout()
            header_layout.addWidget(label)
            header_layout.addWidget(new_button)

            header_widget = QWidget()
            header_widget.setLayout(header_layout)
            widgets.append(header_widget)
        search_bar = QLineEdit()
        search_bar.textChanged.connect(self.filter)
        search_bar.setClearButtonEnabled(True)
        search_bar.setPlaceholderText("Search playlists")
        widgets.append(search_bar)
        return widgets

    def item_at_index(self, index: QModelIndex) -> TreeModelItem:
        return cast(TreeModelItem, cast(QStandardItemModel, self.tree_view.model()).itemFromIndex(index))

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
        print("TODO: PUSH CONFIRMATION + ACTUALLY DELETE")

    @Slot()
    def update_playlist(self, item: TreeModelItem) -> None:
        print(f"UPDATING {item.text()}")
        playlist = item.playlist
        if playlist is None:
            raise NotImplementedError
        playlist.title = item.text()
        playlist.save()

    @Slot()
    def playlist_context_menu(self, point: QPoint):
        playlist_index = self.tree_view.indexAt(point)
        menu = QMenu(self.tree_view)
        if playlist_index.isValid():
            rename_action = QAction("Rename", self.tree_view)
            rename_action.triggered.connect(partial(self.rename_playlist, playlist_index))

            delete_action = QAction("Delete", self.tree_view)
            delete_action.triggered.connect(partial(self.delete_playlist, playlist_index))

            menu.addActions([rename_action, delete_action])

        new_playlist_action = NewPlaylistAction(self)
        new_folder_action = NewFolderAction(self)
        menu.addActions([new_playlist_action, new_folder_action])

        chosen_action = menu.exec_(self.tree_view.mapToGlobal(point))

    def initialize_model(self, path: Path, root_item: QStandardItem | QStandardItemModel) -> None:
        for fp in path.iterdir():
            if fp.is_dir():
                item = TreeModelItem(fp.stem, None)
                root_item.appendRow(item)
                self.initialize_model(fp, item)
            else:
                playlist = get_playlist(fp)
                item = TreeModelItem(playlist.title, playlist)
                root_item.appendRow(item)

    def refresh_playlist_thumbnail(self, playlist: Playlist):
        next(
            tree_model_item
            for tree_model_item, _ in self._recursive_traverse(self.model_.invisibleRootItem(), get_non_leaf=False)
            if tree_model_item.playlist == playlist
        ).update_icon()
