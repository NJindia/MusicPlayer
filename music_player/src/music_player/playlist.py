from functools import partial
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, QModelIndex, QPoint, Slot
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon, QAction
from PySide6.QtWidgets import QTreeView, QSizePolicy, QWidget, QVBoxLayout, QMenu

from music_player.common import Playlist, get_playlist
from music_player.vlc_core import VLCCore


class TreeModelItem(QStandardItem):
    def __init__(self, text: str, playlist: Playlist | None) -> None:
        super().__init__(text)
        self.setEditable(False)
        self.playlist = playlist
        if self.playlist is None:
            self.setIcon(QIcon("../icons/folder.svg"))
        else:
            self.setIcon(QIcon("../icons/music-playlist2.svg"))


class PlaylistView(QWidget):
    @Slot()
    def rename_playlist(self, index: QModelIndex) -> None:
        item: TreeModelItem = cast(TreeModelItem, self.model.itemFromIndex(index))
        self.model.blockSignals(True)
        item.setEditable(True)
        self.tree_view.edit(index)
        item.setEditable(False)
        self.model.blockSignals(False)

    @Slot()
    def delete_playlist(self, index: QModelIndex) -> None:
        item: TreeModelItem = cast(TreeModelItem, self.model.itemFromIndex(index))
        parent = item.parent()
        (self.model if parent is None else parent).removeRow(item.row())
        print("TODO: PUSH CONFIRMATION + ACTUALLY DELETE")

    @Slot()
    def update_playlist(self, item: TreeModelItem) -> None:
        print(f"Playlist Update {item.text()}")
        if item.playlist is None:
            raise NotImplementedError
        item.playlist.title = item.text()
        print("TODO: ACTUALLY UPDATE")

    @Slot()
    def playlist_context_menu(self, point: QPoint):
        playlist_index = self.tree_view.indexAt(point)
        menu = QMenu(self.tree_view)

        rename_action = QAction("Rename", self.tree_view)
        rename_action.triggered.connect(partial(self.rename_playlist, playlist_index))

        delete_action = QAction("Delete", self.tree_view)
        delete_action.triggered.connect(partial(self.delete_playlist, playlist_index))

        menu.addActions([rename_action, delete_action])
        chosen_action = menu.exec_(self.tree_view.mapToGlobal(point))

    def __init__(self, vlc_core: VLCCore):
        super().__init__()
        self.core = vlc_core

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self.tree_view = QTreeView()
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setExpandsOnDoubleClick(True)
        self.tree_view.setAnimated(True)
        self.tree_view.setSortingEnabled(False)
        self.tree_view.setHeaderHidden(True)

        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.playlist_context_menu)

        self.model: QStandardItemModel = QStandardItemModel()
        self.model.itemChanged.connect(self.update_playlist)
        self.initialize_model(Path("../playlists"), self.model)

        layout = QVBoxLayout()
        layout.addWidget(self.tree_view)
        self.setLayout(layout)

        self.tree_view.setModel(self.model)

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
