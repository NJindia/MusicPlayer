# pyright: strict
import sys
from collections import Counter
from datetime import UTC, datetime
from functools import partial
from typing import cast

import numpy as np
import qdarktheme  # pyright: ignore[reportMissingTypeStubs]
import vlc  # pyright: ignore[reportMissingTypeStubs]
from line_profiler_pycharm import profile  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from PySide6.QtCore import QModelIndex, QPoint, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QIcon, QMouseEvent, QPixmapCache
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QMenu, QTabWidget, QWidget
from tqdm import tqdm

from music_player.common_gui import CreateMode, get_pause_button_icon, get_play_button_icon
from music_player.constants import MAX_SIDE_BAR_WIDTH
from music_player.database import get_database_manager
from music_player.db_types import DbCollection, DbMusic, get_collections_by_parent_id, get_db_music_cache
from music_player.library import MusicLibraryScrollArea, MusicLibraryWidget
from music_player.playlist_tree import AddToPlaylistMenu, PlaylistTreeWidget, SortRole, TreeModelItem
from music_player.queue_gui import QueueEntryGraphicsItem, QueueEntryGraphicsView, QueueGraphicsView
from music_player.signals import SharedSignals
from music_player.toolbar import MediaToolbar
from music_player.utils import get_pixmap
from music_player.vlc_core import VLCCore


class AddToQueueAction(QAction):
    def __init__(self, selected_song_db_indices: list[int], signals: SharedSignals, parent: QWidget):
        super().__init__("Add to queue", parent)
        self.triggered.connect(partial(signals.add_to_queue_signal.emit, selected_song_db_indices))


class MainWindow(QMainWindow):
    media_changed_signal = Signal()

    def __init__(self, core: VLCCore):
        super().__init__()
        get_database_manager().create_qt_connection()

        self.core = core
        self.media_changed: bool = False
        self.setWindowTitle("Media Player")
        self.media_changed_signal.connect(self.media_changed_ui)
        self.last_played_music: DbMusic | None = None  # TODO -> VLCCore?

        main_ui = QHBoxLayout()
        self.shared_signals = SharedSignals()
        self.shared_signals.play_playlist_signal.connect(self.play_playlist)

        self.playlist_view = PlaylistTreeWidget(self, self, self.shared_signals, is_main_view=True)
        self.playlist_view.tree_view.clicked.connect(self.select_tree_view_item)
        self.playlist_view.tree_view.doubleClicked.connect(self.double_click_tree_view_item)
        self.playlist_view.tree_view.customContextMenuRequested.connect(
            partial(self.playlist_view.playlist_context_menu, self)
        )
        main_ui.addWidget(self.playlist_view, 1)

        self.library = MusicLibraryWidget(self.core.current_collection, self.shared_signals, self.core)
        self.shared_signals.add_to_playlist_signal.connect(self.add_items_to_collection)
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

        self.core.player_event_manager.event_attach(  # pyright: ignore[reportUnknownMemberType]
            vlc.EventType.MediaPlayerPlaying,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
            self.media_player_playing_callback,
        )
        self.core.player_event_manager.event_attach(  # pyright: ignore[reportUnknownMemberType]
            vlc.EventType.MediaPlayerPaused,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
            self.media_player_paused_callback,
        )
        self.core.player_event_manager.event_attach(  # pyright: ignore[reportUnknownMemberType]
            vlc.EventType.MediaPlayerStopped,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
            self.media_player_paused_callback,
        )
        self.core.player_event_manager.event_attach(  # pyright: ignore[reportUnknownMemberType]
            vlc.EventType.MediaPlayerTimeChanged,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
            self.toolbar.media_slider.update_ui_live,
        )
        self.core.player_event_manager.event_attach(  # pyright: ignore[reportUnknownMemberType]
            vlc.EventType.MediaPlayerEndReached,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
            self.media_player_ended_callback,
        )
        self.core.list_player_event_manager.event_attach(  # pyright: ignore[reportUnknownMemberType]
            vlc.EventType.MediaListPlayerNextItemSet,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
            self.media_player_media_changed_callback,
        )

    @Slot()
    def media_changed_ui(self):
        self.queue.update_first_queue_index()
        if self.last_played_music is not None:  # None when nothing has been played yet
            hist_entry = QueueEntryGraphicsItem(
                self.last_played_music, self.shared_signals, start_width=self.history.viewport().width()
            )
            hist_entry.signal.song_clicked.connect(partial(self.play_history_entry, hist_entry))
            self.history.insert_queue_entries(0, [hist_entry])

    def media_player_playing_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        self.toolbar.play_pause_button.setIcon(get_pause_button_icon())
        if self.media_changed:
            self.media_changed = False
            self.toolbar.media_slider.update_after_label()
        if self.library.collection == self.core.current_collection:
            self.library.header_widget.play_pause_button.setIcon(get_pause_button_icon())

    def media_player_paused_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        self.toolbar.play_pause_button.setIcon(get_play_button_icon())
        self.library.header_widget.play_pause_button.setIcon(get_play_button_icon())

    def media_player_media_changed_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        self.media_changed = True
        if self.core.current_media_idx == -1:
            self.core.current_media_idx = 0
        current_music = self.core.current_music
        self.toolbar.song_label.setText(f"{current_music.name}\n{', '.join(current_music.artists)}")
        if current_music.img_path is not None:
            self.toolbar.album_button.setIcon(QIcon(get_pixmap(current_music.img_path, None)))

        # when VLC emits the MediaPlayerEnded event, it does in a separate thread
        if QThread.currentThread().isMainThread():
            self.media_changed_ui()
        else:
            self.media_changed_signal.emit()

        self.last_played_music = current_music

    def media_player_ended_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        self.toolbar.skip_button.clicked.emit()

    def shuffle_indices(self, split_index: int):
        shuffled_indices = self.core.list_indices[split_index:]
        rng = np.random.default_rng()
        rng.shuffle(shuffled_indices)
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
            self.core.list_indices = list(range(len(self.core.list_indices)))

            # Get index of original playlist music that was most recently played, and start queue from there
            last_music_played = next(
                qe for qe in self.queue.queue_entries[self.core.current_media_idx :: -1] if not qe.manually_added
            ).music
            self.core.current_media_idx = self.core.db_indices.index(last_music_played.id)

            # Replace any music/media that was added manually with the original lists
            self.load_media(tuple(self.core.current_collection.music_ids))
        self.queue.update_first_queue_index()

    @Slot()
    @profile
    def add_to_queue(self, music_db_indices: list[int]):
        print("CONNECT START")
        items: list[QueueEntryGraphicsItem] = []
        list_indices: list[int] = []
        for music_db_index in tqdm(music_db_indices):
            music = get_db_music_cache().get(music_db_index)
            if music_db_index in self.core.db_indices:
                list_index = self.core.db_indices.index(music_db_index)
            else:  # Music not in media list, needs to be added
                self.core.media_list.add_media(music.file_path)  # pyright: ignore[reportUnknownMemberType]
                self.core.list_player.set_media_list(self.core.media_list)  # pyright: ignore[reportUnknownMemberType]
                self.core.db_indices.append(music_db_index)
                list_index = len(self.core.db_indices) - 1
            list_indices.append(list_index)

            item = QueueEntryGraphicsItem(
                music, self.shared_signals, manually_added=True, start_width=self.queue.viewport().width()
            )
            items.append(item)

        insert_idx = self.core.current_media_idx + 1
        self.core.list_indices = (
            self.core.list_indices[:insert_idx] + list_indices + self.core.list_indices[insert_idx:]
        )
        self.queue.insert_queue_entries(insert_idx, items)
        print("CONNECT END")

    @Slot()
    def remove_from_queue(self, item: QueueEntryGraphicsItem):
        queue_index = self.queue.queue_entries.index(item)
        self.queue.scene().removeItem(self.queue.queue_entries.pop(queue_index))
        del self.core.list_indices[queue_index]
        self.queue.update_first_queue_index()

    @Slot()
    def play_history_entry(self, queue_entry: QueueEntryGraphicsItem, _: QMouseEvent) -> None:
        self.core.current_media_idx = 0
        self.load_media((queue_entry.music.id,))
        self.core.list_player.play_item_at_index(0)  # pyright: ignore[reportUnknownMemberType]
        self.queue.update_first_queue_index()

    @Slot()
    def play_song_from_library(self, lib_index: int):
        if self.library.collection is not None:
            self.shared_signals.play_playlist_signal.emit(self.library.collection, lib_index)
        else:
            self.play_music(self.library.table_view.model_.get_visible_music_ids(), lib_index)

    @Slot()
    def play_playlist(self, playlist: DbCollection, playlist_index: int):
        if not playlist.music_ids:
            return
        playlist.mark_as_played()

        if self.playlist_view.proxy_model.sortRole() == SortRole.PLAYED.value:
            self.playlist_view.proxy_model.invalidate()

        self.core.current_collection = playlist
        self.play_music(tuple(playlist.music_ids), playlist_index)

    @Slot()
    def play_music(self, music_indices: tuple[int, ...], list_index: int):
        self.load_media(music_indices)
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

    def load_media(self, music_ids: tuple[int, ...]):
        """Set a new MediaList, and all the other fields that would also need to be set to work properly.

        If queue_entries is None, it will wipe the queue and initialize a new one from self.core.indices"""
        self.core.load_media_from_music_ids(music_ids)
        self.queue.initialize_queue()

    @Slot()
    def select_tree_view_item(self, proxy_index: QModelIndex):
        playlist = self.playlist_view.item_at_index(proxy_index, is_source=False).collection
        if playlist.is_folder:
            return
        self.library.load_playlist(playlist)

    @Slot()
    def double_click_tree_view_item(self, proxy_index: QModelIndex) -> None:
        playlist = self.playlist_view.item_at_index(proxy_index, is_source=False).collection
        if playlist.is_folder:
            raise NotImplementedError
        self.shared_signals.play_playlist_signal.emit(playlist, 0)

    @Slot()
    def create(
        self,
        mode: CreateMode,
        name: str,
        source_model_root_index: QModelIndex,
        callback_value: QModelIndex | list[int],
    ) -> None:
        invis_root = self.playlist_view.model_.invisibleRootItem()
        if source_model_root_index.isValid():
            root_collection = self.playlist_view.item_at_index(source_model_root_index, is_source=True).collection
            default_model_root_item = self.playlist_view.get_model_item(root_collection)
            parent_id = default_model_root_item.collection.id
        else:
            default_model_root_item = invis_root
            parent_id = -1
        collection = DbCollection(
            id=-1,
            collection_type=mode,
            _parent_id=parent_id,
            name=name,
            _created=datetime.now(tz=UTC),
            _last_updated=datetime.now(tz=UTC),
            _last_played=None,
            _thumbnail_path=None,
            is_protected=False,
            music_ids=[],
            music_added_on=[],
            album_ids=[],
            album_img_path_counter=Counter(),
        )
        collection.save()
        get_collections_by_parent_id.cache_clear()
        item = TreeModelItem(collection)
        default_model_root_item.appendRow(item)  # pyright: ignore[reportUnknownMemberType]

        if callback_value:
            match mode:
                case "folder":
                    assert isinstance(callback_value, QModelIndex)
                    if callback_value.isValid():
                        self.shared_signals.move_collection_signal.emit(callback_value, item.index())
                case "playlist":
                    assert isinstance(callback_value, list)
                    if len(callback_value):
                        self.shared_signals.add_to_playlist_signal.emit(callback_value, collection)

    @Slot()
    @profile
    def add_items_to_collection(self, music_db_indices: tuple[int, ...], playlist: DbCollection):
        playlist.add_music_ids(music_db_indices)

        print("adds")
        if self.library.collection and playlist.id == self.library.collection.id:
            self.library.load_playlist(playlist)
        self.playlist_view.refresh_collection(playlist, SortRole.UPDATED)

    @Slot()
    def remove_items_from_playlist(self, item_indices: tuple[int, ...]):
        playlist = self.library.collection
        assert isinstance(playlist, DbCollection)
        playlist.remove_music_ids(item_indices)
        self.library.load_playlist(playlist)
        self.playlist_view.refresh_collection(playlist, SortRole.UPDATED)

    @Slot()
    @profile
    def library_context_menu(self, point: QPoint):
        table_view = self.library.table_view
        row_indices = table_view.selectionModel().selectedRows()
        if not row_indices:
            index = table_view.indexAt(point)
            if not index.isValid():
                return
            rows = [index.row()]
        else:
            rows = [i.row() for i in row_indices]
        selected_song_indices = sorted(table_view.model_.get_music_id(row) for row in rows)
        menu = QMenu(self)

        # Add to queue
        add_to_queue_action = AddToQueueAction(selected_song_indices, self.shared_signals, self)
        menu.addAction(add_to_queue_action)

        # Add to playlist
        playlist_menu = AddToPlaylistMenu(selected_song_indices, self.shared_signals, menu, self, self.playlist_view)
        menu.addMenu(playlist_menu)

        if self.library.collection:
            # Remove from current playlist
            remove_from_curr_playlist_action = QAction("Remove from this playlist", self)
            remove_from_curr_playlist_action.triggered.connect(partial(self.remove_items_from_playlist, rows))
            menu.addAction(remove_from_curr_playlist_action)

        menu.exec(table_view.mapToGlobal(point))  # pyright: ignore[reportUnknownMemberType]

    def queue_context_menu(self, point: QPoint):
        item = self.queue.itemAt(point)
        if item is None:  # Can be None... # pyright: ignore[reportUnnecessaryComparison]
            return
        item = cast(QueueEntryGraphicsItem, item)
        menu = QMenu(self)

        remove_from_queue_action = QAction("Remove from queue", self)
        remove_from_queue_action.triggered.connect(partial(self.remove_from_queue, item))
        menu.addAction(remove_from_queue_action)

        add_to_playlist_menu = AddToPlaylistMenu([item.music.id], self.shared_signals, menu, self, self.playlist_view)
        menu.addMenu(add_to_playlist_menu)

        menu.exec(self.queue.mapToGlobal(point))  # pyright: ignore[reportUnknownMemberType]


if __name__ == "__main__":
    core = VLCCore()
    app = QApplication(sys.argv)
    QPixmapCache.setCacheLimit(102400)  # 100MB
    get_db_music_cache()  # TODO THIS COULD BE BETTER THAN FRONTLOADING
    qdarktheme.setup_theme()
    window = MainWindow(core)
    window.show()
    sys.exit(app.exec())
