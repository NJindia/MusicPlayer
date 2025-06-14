import sys
from dataclasses import asdict
from datetime import datetime, UTC
from functools import partial
from itertools import count
from typing import cast

import qdarktheme
import numpy as np
import pandas as pd
import vlc
from PySide6.QtCore import Slot, Qt, QThread, Signal, QModelIndex, QPoint
from PySide6.QtGui import QIcon, QMouseEvent, QAction
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QTabWidget,
    QMenu,
    QWidgetAction,
)
from vlc import EventType

from music_player.common_gui import NewPlaylistAction
from music_player.constants import MAX_SIDE_BAR_WIDTH
from music_player.playlist import Playlist, Folder, CollectionBase, DEFAULT_PLAYLIST_PATH, get_collections_by_parent_id
from music_player.signals import SharedSignals
from music_player.utils import get_pixmap
from music_player.library import MusicLibraryWidget, MusicLibraryScrollArea
from music_player.playlist_tree import (
    PlaylistTreeWidget,
    TreeModelItem,
    SORT_ROLE,
)
from music_player.queue_gui import (
    QueueGraphicsView,
    QueueEntryGraphicsView,
    QueueEntryGraphicsItem,
)
from music_player.music_importer import get_music_df
from music_player.toolbar import MediaToolbar
from music_player.vlc_core import VLCCore

from music_player.common_gui import CreateMode


class AddToQueueAction(QAction):
    def __init__(self, selected_song_df_indices: list[int], signals: SharedSignals, parent: QWidget):
        super().__init__("Add to queue", parent)
        self.triggered.connect(partial(signals.add_to_queue_signal.emit, selected_song_df_indices))


class AddToPlaylistMenu(QMenu):
    def __init__(
        self, selected_song_indices: list[int], shared_signals: SharedSignals, parent_menu: QMenu, parent: QMainWindow
    ):
        super().__init__("Add to playlist", parent)
        self.parent_menu = parent_menu
        self.signals = shared_signals
        self.playlist_tree_widget = PlaylistTreeWidget(self, parent, self.signals, is_main_view=False)
        self.playlist_tree_widget.tree_view.clicked.connect(
            partial(self.add_items_to_playlist_at_index, selected_song_indices)
        )
        widget_action = QWidgetAction(self)
        widget_action.setDefaultWidget(self.playlist_tree_widget)
        self.addActions(
            [
                widget_action,
                NewPlaylistAction(
                    self, parent, self.playlist_tree_widget.model_.invisibleRootItem().index(), self.signals
                ),
            ]
        )

    def add_items_to_playlist_at_index(self, selected_song_indices: list[int], proxy_index: QModelIndex):
        playlist = self.playlist_tree_widget.item_at_index(proxy_index, is_source=False).collection
        self.signals.add_to_playlist_signal.emit(selected_song_indices, playlist)
        self.parent_menu.close()


class MainWindow(QMainWindow):
    media_changed_signal = Signal()
    collection_id = count(len(list(DEFAULT_PLAYLIST_PATH.iterdir())))

    @Slot()
    def media_changed_ui(self):
        self.queue.update_first_queue_index()
        hist_entry = QueueEntryGraphicsItem(
            self.last_played_music, self.shared_signals, start_width=self.history.viewport().width()
        )
        hist_entry.signal.song_clicked.connect(partial(self.play_history_entry, hist_entry))
        self.history.insert_queue_entry(0, hist_entry)

    def media_player_playing_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        self.toolbar.play_button.setIcon(QIcon("../icons/pause-button.svg"))
        if self.media_changed:
            self.media_changed = False
            self.toolbar.media_slider.update_after_label()

    def media_player_paused_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        self.toolbar.play_button.setIcon(QIcon("../icons/play-button.svg"))

    def media_player_media_changed_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        self.media_changed = True
        current_music = self.core.current_music
        self.toolbar.song_label.setText(f"{current_music.title}\n{', '.join(current_music.artists)}")
        if current_music.album_cover_bytes is not None:
            self.toolbar.album_button.setIcon(QIcon(get_pixmap(current_music.album_cover_bytes, None)))

        # when VLC emits the MediaPlayerEnded event, it does in a separate thread
        if QThread.currentThread().isMainThread():
            self.media_changed_ui()
        else:
            self.media_changed_signal.emit()

        self.last_played_music = current_music

    def media_player_ended_callback(self, event):
        print(f"Event: {event.type}")
        self.toolbar.skip_button.clicked.emit()

    def shuffle_indices(self, split_index: int):
        shuffled_indices = self.core.list_indices[split_index:]
        np.random.shuffle(shuffled_indices)
        self.core.list_indices = [*self.core.list_indices[:split_index], *shuffled_indices]
        self.queue.queue_entries = [
            *self.queue.queue_entries[:split_index],
            *[self.queue.queue_entries[i] for i in shuffled_indices],
        ]

    @Slot()
    def shuffle_button_toggled(self):
        """Shuffle remaining songs in playlist."""
        if self.toolbar.shuffle_button.isChecked():
            self.toolbar.shuffle_button.button_on()
            self.shuffle_indices(self.core.current_media_idx + 1)
        else:
            self.toolbar.shuffle_button.button_off()
            self.core.list_indices = list(range(len(self.core.current_music_df)))

            # Get index of original playlist music that was most recently played, and start queue from there
            last_playlist_music_played = next(
                qe for qe in self.queue.queue_entries[self.core.current_media_idx :: -1] if not qe.manually_added
            ).music
            self.core.current_media_idx = self.core.current_music_df[
                (self.core.current_music_df == last_playlist_music_played).all(axis=1)
            ].index[0]

            # Replace any music/media that was added manually with the original lists
            self.load_media(self.core.current_playlist.dataframe)
        self.queue.update_first_queue_index()

    @Slot()
    def add_to_queue(self, music_df_indices: list[int]):
        for music_df_index in music_df_indices:
            music = get_music_df().iloc[music_df_index]
            try:
                list_index = np.where((self.core.current_music_df == music).all(axis=1))[0][0]
            except IndexError:
                self.core.current_music_df.iloc[len(self.core.current_music_df) - 1] = music
                self.core.media_list.add_media(music.file_path)
                self.core.list_player.set_media_list(self.core.media_list)
                print(len(self.core.current_music_df), len(self.core.current_music_df) - 1, music.file_path)
                self.core.current_music_df = pd.concat(
                    [self.core.current_music_df, music.to_frame().T], ignore_index=True
                )
                list_index = len(self.core.current_music_df) - 1
            self.core.list_indices.insert(self.core.current_media_idx + 1, list_index)
            self.queue.insert_queue_entry(
                self.core.current_media_idx + 1,
                QueueEntryGraphicsItem(
                    music, self.shared_signals, manually_added=True, start_width=self.queue.viewport().width()
                ),
            )

    @Slot()
    def remove_from_queue(self, item: QueueEntryGraphicsItem):
        queue_index = self.queue.queue_entries.index(item)
        self.queue.scene().removeItem(self.queue.queue_entries.pop(queue_index))
        del self.core.list_indices[queue_index]
        self.queue.update_first_queue_index()

    @Slot()
    def play_history_entry(self, queue_entry: QueueEntryGraphicsItem, _: QMouseEvent) -> None:
        self.core.current_media_idx = 0
        self.load_media(queue_entry.music.to_frame())
        self.core.list_player.play_item_at_index(0)
        self.queue.update_first_queue_index()

    @Slot()
    def play_song_from_library(self, lib_index: int):
        if self.library.playlist is not None:
            self.play_playlist(self.library.playlist, lib_index)
        else:
            self.play_music(self.library.table_view.model_.music_data["file_path"].to_list(), lib_index)

    def play_playlist(self, playlist: Playlist, playlist_index: int):
        if not playlist.playlist_items:
            return
        playlist.last_played = datetime.now(tz=UTC)
        playlist.save()

        if self.playlist_view.proxy_model.sortRole() == SORT_ROLE.PLAYED.value:
            self.playlist_view.proxy_model.invalidate()

        self.play_music(playlist.dataframe, playlist_index)
        self.core.current_playlist = playlist

    @Slot()
    def play_music(self, music_df: pd.DataFrame, list_index: int):
        self.load_media(music_df)
        jump_index = list_index
        if self.toolbar.shuffle_button.isChecked():
            jump_index = 0
            self.shuffle_indices(jump_index)  # Shuffle all
            # Find index of song we want to play now in the shuffled list, then swap that with the shuffled 1st song
            _list_index = self.core.list_indices.index(list_index)
            self.core.list_indices[_list_index] = self.core.list_indices[jump_index]
            self.core.list_indices[jump_index] = list_index

            temp = self.queue.queue_entries[_list_index]
            self.queue.queue_entries[_list_index] = self.queue.queue_entries[jump_index]
            self.queue.queue_entries[jump_index] = temp
        self.core.jump_play_index(jump_index)

    def load_media(self, music_df: pd.DataFrame):
        """Set a new MediaList, and all the other fields that would also need to be set to work properly.

        If queue_entries is None, it will wipe the queue and initialize a new one from self.core.indices"""
        file_paths = music_df["file_path"].to_list()
        self.core.media_list = self.core.instance.media_list_new(file_paths)
        self.core.list_player.set_media_list(self.core.media_list)
        self.core.current_music_df = music_df
        self.core.list_indices = list(range(len(self.core.current_music_df)))
        self.queue.initialize_queue()

    @Slot()
    def select_tree_view_item(self, proxy_index: QModelIndex):
        playlist = self.playlist_view.item_at_index(proxy_index, is_source=False).collection
        if not isinstance(playlist, Playlist):
            raise NotImplementedError(proxy_index)
        self.library.load_playlist(playlist)

    @Slot()
    def double_click_tree_view_item(self, proxy_index: QModelIndex) -> None:
        playlist = cast(TreeModelItem, self.playlist_view.item_at_index(proxy_index, is_source=False)).collection
        if not isinstance(playlist, Playlist):
            raise NotImplementedError
        self.play_playlist(playlist, 0)

    @Slot()
    def create(self, mode: CreateMode, name: str, source_model_root_index: QModelIndex) -> None:
        invis_root = self.playlist_view.model_.invisibleRootItem()
        root_collection = self.playlist_view.item_at_index(source_model_root_index, is_source=True).collection
        default_model_root_item = self.playlist_view.get_model_item(root_collection) or invis_root
        collection_base = CollectionBase(
            id=str(next(self.collection_id)),
            parent_id="" if default_model_root_item == invis_root else default_model_root_item.collection.id,
            title=name,
            created=datetime.now(tz=UTC),
            last_updated=datetime.now(tz=UTC),
            last_played=None,
            thumbnail=None,
        )
        match mode:
            case "playlist":
                collection_base.id = "p" + collection_base.id
                collection = Playlist(playlist_items=[], **asdict(collection_base))
                self.library.load_playlist(collection)
            case "folder":
                collection_base.id = "f" + collection_base.id
                collection = Folder(**asdict(collection_base))
            case _:
                raise ValueError(f"Unknown mode: {mode}")
        collection.save()
        get_collections_by_parent_id.cache_clear()
        default_model_root_item.appendRow(TreeModelItem(collection))
        default_model_root_item.sortChildren(0)

    def _update_playlist_last_updated(self, playlist: Playlist):
        playlist.last_updated = datetime.now(tz=UTC)
        playlist.save()
        if self.playlist_view.proxy_model.sortRole() == SORT_ROLE.PLAYED.value:
            self.playlist_view.proxy_model.invalidate()

    @Slot()
    def add_items_to_playlist(self, music_df_indices: list[int], playlist: Playlist | None):
        if playlist is None:
            raise NotImplementedError
        for i in music_df_indices:
            playlist.add_item(i)
        self._update_playlist_last_updated(playlist)
        if self.library.playlist and playlist.id == self.library.playlist.id:
            self.library.load_playlist(playlist)
        self.playlist_view.refresh_playlist(playlist)

    @Slot()
    def remove_items_from_playlist(self, item_indices: list[int]):
        assert self.library.playlist is not None
        self.library.playlist.remove_items(item_indices)
        self._update_playlist_last_updated(self.library.playlist)
        self.library.load_playlist(self.library.playlist)
        self.playlist_view.refresh_playlist(self.library.playlist)

    @Slot()
    def library_context_menu(self, point: QPoint):
        indices = self.library.table_view.selectionModel().selectedRows()
        if not indices:
            index = self.library.table_view.indexAt(point)
            if not index.isValid():
                return
            rows = [index.row()]
        else:
            rows = [i.row() for i in indices]
        selected_song_indices = [int(self.library.table_view.model_.music_data.index[row]) for row in rows[::-1]]
        menu = QMenu(self)

        # Add to queue
        add_to_queue_action = AddToQueueAction(selected_song_indices, self.shared_signals, self)
        menu.addAction(add_to_queue_action)

        # Add to playlist
        playlist_menu = AddToPlaylistMenu(selected_song_indices, self.shared_signals, menu, self)
        menu.addMenu(playlist_menu)

        if self.library.playlist:
            # Remove from current playlist
            remove_from_curr_playlist_action = QAction("Remove from this playlist", self)
            remove_from_curr_playlist_action.triggered.connect(partial(self.remove_items_from_playlist, rows))
            menu.addAction(remove_from_curr_playlist_action)

        menu.exec(self.library.table_view.mapToGlobal(point))

    def queue_context_menu(self, point: QPoint):
        item = cast(QueueEntryGraphicsItem, self.queue.itemAt(point))
        if item is None:
            return
        menu = QMenu(self)

        remove_from_queue_action = QAction("Remove from queue", self)
        remove_from_queue_action.triggered.connect(partial(self.remove_from_queue, item))
        menu.addAction(remove_from_queue_action)

        music_df_idx = get_music_df()[get_music_df()["file_path"] == item.music.file_path].index[0]
        add_to_playlist_menu = AddToPlaylistMenu(music_df_idx, self.shared_signals, menu, self)
        menu.addMenu(add_to_playlist_menu)

        menu.exec(self.queue.mapToGlobal(point))

    def __init__(self, core: VLCCore):
        super().__init__()

        self.core = core
        self.media_changed: bool = False
        self.setWindowTitle("Media Player")
        self.media_changed_signal.connect(self.media_changed_ui)
        self.last_played_music: pd.Series = self.core.current_music  # TODO -> VLCCore?

        main_ui = QHBoxLayout()
        self.shared_signals = SharedSignals()

        self.playlist_view = PlaylistTreeWidget(self, self, self.shared_signals, is_main_view=True)
        self.playlist_view.tree_view.clicked.connect(self.select_tree_view_item)
        self.playlist_view.tree_view.doubleClicked.connect(self.double_click_tree_view_item)
        self.playlist_view.tree_view.customContextMenuRequested.connect(
            partial(self.playlist_view.playlist_context_menu, self)
        )
        main_ui.addWidget(self.playlist_view, 1)

        self.library = MusicLibraryWidget(self.core.current_playlist, self.shared_signals)
        self.shared_signals.add_to_playlist_signal.connect(self.add_items_to_playlist)
        self.shared_signals.create_playlist_signal.connect(partial(self.create, "playlist"))
        self.shared_signals.create_folder_signal.connect(partial(self.create, "folder"))
        self.library.table_view.song_clicked.connect(self.play_song_from_library)
        self.library.table_view.customContextMenuRequested.connect(self.library_context_menu)
        scroll_area = MusicLibraryScrollArea(self.library)

        main_ui.addWidget(scroll_area, 2)

        self.history = QueueEntryGraphicsView()
        self.queue = QueueGraphicsView(self.core, self.shared_signals)
        self.shared_signals.add_to_queue_signal.connect(self.add_to_queue)
        self.queue.customContextMenuRequested.connect(self.queue_context_menu)

        queue_tab = QTabWidget()
        queue_tab.setMaximumWidth(MAX_SIDE_BAR_WIDTH)
        queue_tab.addTab(self.queue, "Queue")
        queue_tab.addTab(self.history, "History")
        main_ui.addWidget(queue_tab, 1)

        self.toolbar = MediaToolbar(self.core, self.shared_signals)
        self.toolbar.shuffle_button.toggled.connect(self.shuffle_button_toggled)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, self.toolbar)

        w = QWidget()
        main_ui.setSpacing(0)
        main_ui.setContentsMargins(0, 0, 0, 0)
        w.setLayout(main_ui)
        self.setCentralWidget(w)

        self.core.player_event_manager.event_attach(
            EventType.MediaPlayerPlaying,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_playing_callback,
        )
        self.core.player_event_manager.event_attach(
            EventType.MediaPlayerPaused,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_paused_callback,
        )
        self.core.player_event_manager.event_attach(
            EventType.MediaPlayerStopped,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_paused_callback,
        )
        self.core.player_event_manager.event_attach(
            EventType.MediaPlayerTimeChanged,  # pyright: ignore[reportAttributeAccessIssue]
            self.toolbar.media_slider.update_ui_live,
        )
        self.core.player_event_manager.event_attach(
            EventType.MediaPlayerEndReached,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_ended_callback,
        )
        self.core.list_player_event_manager.event_attach(
            EventType.MediaListPlayerNextItemSet,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_media_changed_callback,
        )


if __name__ == "__main__":
    core = VLCCore()
    app = QApplication(sys.argv)
    qdarktheme.setup_theme()
    window = MainWindow(core)
    window.show()
    sys.exit(app.exec())
