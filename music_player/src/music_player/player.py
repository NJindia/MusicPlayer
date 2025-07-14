import sys
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from functools import partial
from typing import cast

import numpy as np
import qdarktheme  # pyright: ignore[reportMissingTypeStubs]
from line_profiler_pycharm import profile  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from PySide6.QtCore import QModelIndex, QPoint, Qt, QThread, Slot
from PySide6.QtGui import QAction, QPixmapCache, QStandardItem
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QMenu, QTabWidget, QVBoxLayout, QWidget
from tqdm import tqdm

from music_player.common_gui import (
    AddToQueueAction,
    ConfirmationDialog,
    CreateMode,
    NewFolderAction,
    NewPlaylistAction,
    WarningPopup,
    get_pause_button_icon,
    get_play_button_icon,
)
from music_player.constants import MAIN_PADDING, MAIN_SPACING, MAX_SIDE_BAR_WIDTH
from music_player.database import get_database_manager
from music_player.db_types import (
    DbCollection,
    DbMusic,
    DbStoredCollection,
    get_collection_children,
    get_collections_by_parent_id,
    get_db_music_cache,
)
from music_player.library import MusicLibraryScrollArea, MusicLibraryWidget
from music_player.playlist_tree import AddToPlaylistMenu, MoveToFolderMenu, PlaylistTreeWidget, SortRole, TreeModelItem
from music_player.queue_gui import HistoryGraphicsView, QueueEntryGraphicsItem, QueueGraphicsView
from music_player.signals import SharedSignals
from music_player.stylesheet import stylesheet
from music_player.toolbar import MediaToolbar
from music_player.vlc_core import VLCCore


class MainWindow(QMainWindow):
    def __init__(self, core: VLCCore):
        super().__init__()
        get_database_manager().create_qt_connection()
        self.setStyleSheet(stylesheet)

        self.core = core
        self.media_changed: bool = False
        self.setWindowTitle("Media Player")
        self.last_played_music: DbMusic | None = None  # TODO -> VLCCore?

        main_ui = QHBoxLayout()
        main_ui.setSpacing(MAIN_SPACING)
        main_ui.setContentsMargins(MAIN_PADDING, MAIN_PADDING, MAIN_PADDING, MAIN_PADDING)
        self.shared_signals = SharedSignals()

        self.playlist_view = PlaylistTreeWidget(self, self, self.shared_signals, is_main_view=True)
        self.playlist_view.tree_view.clicked.connect(self.select_tree_view_item)
        self.playlist_view.tree_view.doubleClicked.connect(self.double_click_tree_view_item)
        self.playlist_view.tree_view.customContextMenuRequested.connect(self.playlist_context_menu)
        main_ui.addWidget(self.playlist_view, 1)

        self.library = MusicLibraryWidget(self.shared_signals, self.core)
        self.library.header_widget.customContextMenuRequested.connect(self.library_header_context_menu)
        self.library.header_widget.menu_button.clicked.connect(partial(self.library_header_context_menu, None))
        self.library.table_view.song_clicked.connect(self.play_song_from_library)
        self.library.table_view.customContextMenuRequested.connect(self.library_context_menu)
        scroll_area = MusicLibraryScrollArea(self.library)

        main_ui.addWidget(scroll_area, 2)

        self.history = HistoryGraphicsView()
        self.queue = QueueGraphicsView(self.core, self.shared_signals)
        self.queue.customContextMenuRequested.connect(self.queue_context_menu)

        queue_tab = QTabWidget()
        queue_tab.setMaximumWidth(MAX_SIDE_BAR_WIDTH)
        queue_tab.addTab(self.queue, "Queue")
        queue_tab.addTab(self.history, "History")
        main_ui.addWidget(queue_tab, 1)

        self.toolbar = MediaToolbar(self.core, self.shared_signals)
        main_win = QVBoxLayout()
        main_win.setSpacing(0)
        main_win.setContentsMargins(0, 0, 0, 0)
        main_win.addLayout(main_ui)
        main_win.addWidget(self.toolbar)

        w = QWidget()
        w.setObjectName("MainWindow")
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, on=True)
        w.setLayout(main_win)
        self.setCentralWidget(w)

        self.core.vlc_signals.media_playing_signal.connect(self._media_player_playing_ui)
        self.core.vlc_signals.media_paused_signal.connect(self._media_player_paused_ui)
        self.core.vlc_signals.time_changed_signal.connect(self.toolbar.media_slider.update_ui_live)
        self.core.vlc_signals.media_changed_signal.connect(self._media_changed_ui)
        self.core.vlc_signals.media_end_reached_signal.connect(self.shared_signals.next_song_signal.emit)

        self.shared_signals.play_collection_signal.connect(self.play_collection)
        self.shared_signals.add_to_playlist_signal.connect(self.add_items_to_collection)
        self.shared_signals.create_playlist_signal.connect(partial(self.create_collection, "playlist"))
        self.shared_signals.create_folder_signal.connect(partial(self.create_collection, "folder"))
        self.shared_signals.add_to_queue_signal.connect(self.add_to_queue)
        self.shared_signals.toggle_shuffle_signal.connect(self.shuffle_button_clicked)
        self.shared_signals.play_from_queue_signal.connect(self.play_from_queue)
        self.shared_signals.delete_collection_signal.connect(self.delete_collection)
        self.shared_signals.next_song_signal.connect(self.core.next)

    def _media_player_playing_ui(self):
        self.toolbar.play_pause_button.setIcon(get_pause_button_icon())
        if self.media_changed:
            self.media_changed = False
            self.toolbar.media_slider.update_after_label()
        if self.library.collection == self.core.current_collection:
            self.library.header_widget.set_play_pause_button_state(is_play_button=False)

    def _media_player_paused_ui(self):
        self.toolbar.play_pause_button.setIcon(get_play_button_icon())
        self.library.header_widget.set_play_pause_button_state(is_play_button=True)

    def _media_changed_ui(self):
        self.media_changed = True
        if self.core.current_media_idx == -1:
            self.core.current_media_idx = 0
        current_music = self.core.current_music

        # when VLC emits the MediaPlayerEnded event, it does in a separate thread
        assert QThread.currentThread().isMainThread()
        self.queue.update_first_queue_index()
        if self.last_played_music is not None:  # None when nothing has been played yet
            hist_entry = QueueEntryGraphicsItem(
                self.last_played_music,
                self.shared_signals,
                start_width=self.history.viewport().width(),
                is_history=True,
            )
            self.history.insert_queue_entries(0, [hist_entry])
        self.toolbar.song_label.set_text(current_music.name)
        self.toolbar.artists_label.set_text(", ".join(current_music.artists))
        self.toolbar.album_button.change_music(current_music)

        self.last_played_music = current_music

    def shuffle_indices(self, split_index: int):
        shuffled_indices = self.core.list_indices[split_index:]
        rng = np.random.default_rng()
        rng.shuffle(shuffled_indices)
        self.core.list_indices = [*self.core.list_indices[:split_index], *shuffled_indices]
        self.queue.queue_entries = [self.queue.queue_entries[i] for i in self.core.list_indices]

    @Slot(bool)
    def shuffle_button_clicked(self, shuffle: bool):
        """Shuffle remaining songs in playlist."""
        if shuffle:
            self.toolbar.shuffle_button.button_on()
            self.library.header_widget.shuffle_button.button_on()
            self.shuffle_indices(self.core.current_media_idx + 1)
        else:
            self.toolbar.shuffle_button.button_off()
            self.library.header_widget.shuffle_button.button_off()

            if self.core.current_collection:
                self.core.list_indices = list(range(len(self.core.list_indices)))

                # Get index of original playlist music that was most recently played, and start queue from there
                last_music_played = next(
                    qe for qe in self.queue.queue_entries[self.core.current_media_idx :: -1] if not qe.manually_added
                ).music
                self.core.current_media_idx = self.core.music_ids.index(last_music_played.id)

                # Replace any music/media that was added manually with the original lists
                self.load_media(self.core.current_collection.music_ids)
        self.queue.update_first_queue_index()

    @Slot()
    @profile
    def add_to_queue(self, music_ids: Sequence[int], insert_index: int):
        t = datetime.now(tz=UTC)
        items: list[QueueEntryGraphicsItem] = []
        list_indices: list[int] = []
        for music_db_index in tqdm(music_ids):
            music = get_db_music_cache().get(music_db_index)
            if music_db_index in self.core.music_ids:
                list_index = self.core.music_ids.index(music_db_index)
            else:  # Music not in media list, needs to be added
                self.core.media_list.add_media(music.file_path)
                self.core.music_ids.append(music_db_index)
                list_index = len(self.core.music_ids) - 1
            list_indices.append(list_index)

            item = QueueEntryGraphicsItem(
                music, self.shared_signals, manually_added=True, start_width=self.queue.viewport().width()
            )
            items.append(item)

        insert_idx = self.core.current_media_idx + 1 if insert_index == -1 else insert_index
        self.core.list_indices = (
            self.core.list_indices[:insert_idx] + list_indices + self.core.list_indices[insert_idx:]
        )
        self.queue.insert_queue_entries(insert_idx, items)
        print("add_to_queue", (datetime.now(tz=UTC) - t).microseconds / 1000)

    @Slot()
    def remove_from_queue(self, item: QueueEntryGraphicsItem):
        queue_index = self.queue.queue_entries.index(item)
        self.queue.scene().removeItem(self.queue.queue_entries.pop(queue_index))
        del self.core.list_indices[queue_index]
        self.queue.update_first_queue_index()

    @Slot()
    def play_from_queue(self, queue_entry: QueueEntryGraphicsItem) -> None:
        if queue_entry.is_history:
            self.core.current_media_idx = 0
            self.load_media((queue_entry.music.id,))
            self.core.play_item_at_index(0)
            self.queue.update_first_queue_index()
        else:
            self.core.jump_play_index(self.queue.queue_entries.index(queue_entry))

    @Slot()
    def play_song_from_library(self, lib_index: int):
        assert self.library.collection is not None
        self.shared_signals.play_collection_signal.emit(self.library.collection, lib_index)

    @Slot()
    def play_collection(self, collection: DbCollection, collection_index: int):
        self.core.current_collection = collection
        if not collection.music_ids:
            return
        if isinstance(collection, DbStoredCollection):
            collection.mark_as_played()

        if self.playlist_view.proxy_model.sortRole() == SortRole.PLAYED.value:
            self.playlist_view.proxy_model.invalidate()

        self.load_media(collection.music_ids)
        jump_index = collection_index
        if self.toolbar.shuffle_button.isChecked():
            jump_index = 0
            self.shuffle_indices(jump_index)  # Shuffle all
            # Find index of song we want to play now in the shuffled list, then swap that with the shuffled 1st song
            _list_index = self.core.list_indices.index(collection_index)
            self.core.list_indices[_list_index] = self.core.list_indices[jump_index]
            self.core.list_indices[jump_index] = collection_index

            temp = self.queue.queue_entries[_list_index]
            self.queue.queue_entries[_list_index] = self.queue.queue_entries[jump_index]
            self.queue.queue_entries[jump_index] = temp
        self.core.jump_play_index(jump_index)

    def load_media(self, music_ids: tuple[int, ...]):
        """Set a new MediaList, and all the other fields that would also need to be set to work properly."""
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
        self.shared_signals.play_collection_signal.emit(playlist, 0)

    @Slot()
    def create_collection(
        self,
        mode: CreateMode,
        name: str,
        source_model_root_index: QModelIndex,
        callback_value: QModelIndex | Sequence[int],
    ) -> None:
        invis_root = self.playlist_view.model_.invisibleRootItem()
        if source_model_root_index.isValid():
            root_collection = self.playlist_view.item_at_index(source_model_root_index, is_source=True).collection
            default_model_root_item = self.playlist_view.get_model_item(root_collection)
            parent_id = default_model_root_item.collection.id
        else:
            default_model_root_item = invis_root
            parent_id = -1
        collection = DbStoredCollection(
            _id=-1,
            _name=name,
            _collection_type=mode,
            _img_path=None,
            _is_protected=False,
            _parent_id=parent_id,
            _created=datetime.now(tz=UTC),
            _last_updated=datetime.now(tz=UTC),
            _last_played=None,
            _music_ids=(),
            _music_added_on=[],
            _album_img_path_counter=Counter(),
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
                    assert isinstance(callback_value, Sequence)
                    if len(callback_value):
                        self.shared_signals.add_to_playlist_signal.emit(callback_value, collection)

    def __delete_single_collection(self, collection: DbStoredCollection):
        if collection == self.library.collection:
            self.library.load_nothing()
        collection.delete()

    def _delete_collection(self, collection: DbStoredCollection):
        playlist_tree_item = self.playlist_view.get_model_item(collection)
        item_parent = cast(QStandardItem | None, playlist_tree_item.parent())
        (self.playlist_view.model_ if item_parent is None else item_parent).removeRow(playlist_tree_item.row())

        if collection.is_folder:
            for child in list(get_collection_children(collection.id)):
                self.__delete_single_collection(child)
        self.__delete_single_collection(collection)
        get_collections_by_parent_id.cache_clear()

    @Slot()
    def delete_collection(self, collection: DbStoredCollection):
        ConfirmationDialog(
            self,
            f"Delete {collection.collection_type.capitalize()}",
            f"Are you sure you want to delete <b>{collection.name}</b>"
            f"{' and all its children' if collection.is_folder else ''}?",
            "Delete",
            partial(self._delete_collection, collection),
        ).exec()

    @Slot()
    @profile
    def add_items_to_collection(self, music_db_indices: Sequence[int], playlist: DbStoredCollection):
        valid_music_ids = [m_id for m_id in music_db_indices if m_id not in playlist.music_ids]
        if bad_num := len(music_db_indices) - len(valid_music_ids):
            warning = f"Could not add {bad_num} song{'s'[: bad_num ^ 1]} to '{playlist.name}': Already added."
            warning_popup = WarningPopup(self, warning)
            window_bottom_mid = cast(QPoint, (self.rect().bottomLeft() + self.rect().bottomRight()) / 2)  # pyright: ignore[reportOperatorIssue]
            warning_size = warning_popup.sizeHint()
            popup_y = round(window_bottom_mid.y() - self.toolbar.height() - warning_size.height())
            popup_top_left = QPoint(round(window_bottom_mid.x() - warning_size.width() / 2), popup_y)
            warning_popup.move(self.mapToGlobal(popup_top_left))
            warning_popup.show()
        playlist.add_music_ids(valid_music_ids)

        if self.library.collection and playlist.id == self.library.collection.id:
            self.library.load_playlist(playlist)
        self.playlist_view.refresh_collection(playlist, SortRole.UPDATED)

    @Slot()
    def remove_items_from_playlist(self, item_indices: tuple[int, ...]):
        playlist = self.library.collection
        assert isinstance(playlist, DbStoredCollection)
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
            rows = sorted(i.row() for i in row_indices)
        selected_song_indices = [table_view.model().get_music_id(row) for row in rows]
        menu = QMenu(self)

        # Add to queue
        menu.addAction(AddToQueueAction(selected_song_indices, self.shared_signals, menu))

        # Add to playlist
        menu.addMenu(AddToPlaylistMenu(selected_song_indices, self.shared_signals, menu, self, self.playlist_view))

        if self.library.collection:
            # Remove from current playlist
            remove_from_curr_playlist_action = QAction("Remove from this playlist", menu)
            remove_from_curr_playlist_action.triggered.connect(
                partial(self.remove_items_from_playlist, tuple(selected_song_indices))
            )
            menu.addSeparator()
            menu.addAction(remove_from_curr_playlist_action)

        if len(selected_song_indices) == 1:
            selected_music = get_db_music_cache().get(selected_song_indices[0])
            menu.addSeparator()

            def get_go_to_artist_action(_artist_id: int, _name: str = "Go to artist") -> QAction:
                go_to_artist_action = QAction(_name, menu)
                go_to_artist_action.triggered.connect(
                    partial(self.shared_signals.library_load_artist_signal.emit, _artist_id)
                )
                return go_to_artist_action

            if len(selected_music.artist_ids) == 1:
                menu.addAction(get_go_to_artist_action(selected_music.artist_ids[0]))
            else:
                go_to_artist_menu = QMenu("Go to artist", menu)
                for artist_id, artist_name in zip(selected_music.artist_ids, selected_music.artists, strict=True):
                    go_to_artist_menu.addAction(get_go_to_artist_action(artist_id, artist_name))
                menu.addMenu(go_to_artist_menu)

            go_to_album_action = QAction("Go to album", menu)
            go_to_album_action.triggered.connect(
                partial(self.shared_signals.library_load_album_signal.emit, selected_music.album_id)
            )
            menu.addAction(go_to_album_action)

        menu.exec(table_view.mapToGlobal(point))  # pyright: ignore[reportUnknownMemberType]

    def queue_context_menu(self, point: QPoint):
        item = self.queue.item_at(point)
        if item is None:
            return
        menu = QMenu(self)

        remove_from_queue_action = QAction("Remove from queue", menu)
        remove_from_queue_action.triggered.connect(partial(self.remove_from_queue, item))
        menu.addAction(remove_from_queue_action)

        add_to_playlist_menu = AddToPlaylistMenu([item.music.id], self.shared_signals, menu, self, self.playlist_view)
        menu.addMenu(add_to_playlist_menu)

        menu.exec(self.queue.mapToGlobal(point))  # pyright: ignore[reportUnknownMemberType]

    @Slot()
    def playlist_context_menu(self, point: QPoint):
        pview = self.playlist_view
        proxy_index = pview.tree_view.indexAt(point)
        menu = QMenu(self)
        source_root_index = pview.source_model().invisibleRootItem().index()
        if proxy_index.isValid():
            item = pview.item_at_index(proxy_index, is_source=False)

            # Set root for adding playlist/folder
            if item.collection.is_folder:  # Folder is a valid root
                source_root_index = pview.proxy_model.mapToSource(proxy_index)
            elif (
                (p := item.parent()) is not None  # pyright: ignore[reportUnnecessaryComparison]
            ):  # If not top-level parent *is* None
                assert pview.source_model() != pview.flattened_model_, "Should only have top-level for flattened!"
                source_root_index = p.index()

            self._add_playlist_base_context_menu_actions(
                menu, item.collection, partial(pview.rename_playlist, proxy_index), item.index()
            )

        args = menu, self, source_root_index, self.shared_signals
        menu.addSeparator()
        menu.addActions([NewPlaylistAction(*args), NewFolderAction(*args)])  # pyright: ignore[reportUnknownMemberType]

        menu.popup(pview.tree_view.mapToGlobal(point))

    @Slot()
    def library_header_context_menu(self, header_point: QPoint | None):
        menu = QMenu(self)
        collection = self.library.collection
        if collection is None:
            return
        self._add_playlist_base_context_menu_actions(menu, collection, lambda: print("TODO"))
        if header_point is None:
            menu_button = self.library.header_widget.menu_button
            point = menu_button.mapToGlobal(menu_button.rect().bottomLeft())
        else:
            point = self.library.header_widget.mapToGlobal(header_point)
        menu.popup(point)

    def _add_playlist_base_context_menu_actions(
        self,
        menu: QMenu,
        collection: DbStoredCollection,
        rename_callable: Callable[[], None],
        playlist_tree_source_index: QModelIndex | None = None,
    ):
        """Add the base context menu actions for a playlist."""
        if collection.music_ids:
            menu.addAction(AddToQueueAction(collection.music_ids, self.shared_signals, menu))
            menu.addSeparator()
        if not collection.is_protected:
            rename_action = QAction("Rename", menu)
            rename_action.triggered.connect(rename_callable)

            delete_action = QAction("Delete", menu)
            delete_action.triggered.connect(partial(self.shared_signals.delete_collection_signal.emit, collection))

            source_index = (
                self.playlist_view.get_model_item(collection).index()
                if playlist_tree_source_index is None
                else playlist_tree_source_index
            )
            move_to_folder_menu = MoveToFolderMenu(source_index, self.shared_signals, menu, self, self.playlist_view)

            menu.addActions([rename_action, delete_action])  # pyright: ignore[reportUnknownMemberType]
            menu.addSeparator()
            menu.addMenu(move_to_folder_menu)
        else:
            menu.addSeparator()

        menu.addMenu(AddToPlaylistMenu(collection.music_ids, self.shared_signals, menu, self, self.playlist_view))


if __name__ == "__main__":
    core = VLCCore()
    app = QApplication(sys.argv)
    app.setStyleSheet(stylesheet)
    QPixmapCache.setCacheLimit(102400)  # 100MB
    get_db_music_cache()  # TODO THIS COULD BE BETTER THAN FRONTLOADING
    qdarktheme.setup_theme()
    window = MainWindow(core)
    window.show()
    sys.exit(app.exec())
