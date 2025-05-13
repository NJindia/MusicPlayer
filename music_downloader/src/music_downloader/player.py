import sys
from datetime import datetime
from functools import partial
from typing import cast

import numpy as np
import vlc
from PySide6.QtCore import Slot, Qt, QThread, Signal, QSize, QModelIndex
from PySide6.QtGui import QIcon, QTransform, QPixmap, QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QToolBar,
    QToolButton,
    QMainWindow,
    QWidget,
    QSizePolicy,
    QLabel,
    QHBoxLayout,
    QTabWidget,
    QGraphicsOpacityEffect,
    QVBoxLayout,
)
from vlc import EventType

from music_downloader.album import AlbumButton, get_pixmap
from music_downloader.constants import SKIP_BACK_SECOND_THRESHOLD, QUEUE_ENTRY_WIDTH
from music_downloader.playlist import PlaylistView, TreeModelItem
from music_downloader.queue_gui import (
    QueueGraphicsView,
    QueueEntryGraphicsView,
    QueueEntryGraphicsItem,
)
from music_downloader.toolbar import MediaScrubberSlider, VolumeSlider
from music_downloader.vlc_core import VLCCore

from line_profiler_pycharm import profile


def expanding_widget() -> QWidget:
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return widget


class OpacityButton(QToolButton):
    button_off_opacity = 0.5

    def __init__(self):
        super().__init__()
        self.graphics_effect = QGraphicsOpacityEffect(self)
        self.graphics_effect.setOpacity(self.button_off_opacity)
        self.setGraphicsEffect(self.graphics_effect)
        self.setCheckable(True)

    def button_on(self):
        self.graphics_effect.setOpacity(1)
        self.setChecked(True)

    def button_off(self):
        self.graphics_effect.setOpacity(self.button_off_opacity)
        self.setChecked(False)


class MainWindow(QMainWindow):
    media_changed_signal = Signal()

    def load_media(
        self, media_list: vlc.MediaList, indices: list[int], queue_entries: list[QueueEntryGraphicsItem] | None
    ):
        """Set a new MediaList, and all the other fields that would also need to be set to work properly.

        If queue_entries is None, it will wipe the queue and initialize a new one from self.core.indices"""
        assert media_list.count() == len(indices)
        self.core.media_list = media_list
        self.core.list_player.set_media_list(self.core.media_list)
        self.core.indices = indices
        if queue_entries is None:
            self.queue.initialize_queue()
        else:
            self.queue.queue_entries = queue_entries

    @Slot()
    def play_history_entry(self, queue_entry: QueueEntryGraphicsItem, _: QMouseEvent) -> None:
        new_media_list = self.core.instance.media_list_new([queue_entry.metadata.file_path])
        self.load_media(new_media_list, [queue_entry.music_idx], None)
        self.core.list_player.play_item_at_index(0)
        self.queue.update_first_queue_index()

    @Slot()
    def media_changed_ui(self):
        self.queue.update_first_queue_index()
        hist_entry = QueueEntryGraphicsItem(self.last_played_music_df_idx)
        hist_entry.signal.song_clicked.connect(partial(self.play_history_entry, hist_entry))
        self.history.insert_queue_entry(0, hist_entry)

    def media_player_playing_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        self.play_button.setIcon(QIcon("../icons/pause-button.svg"))
        if self.media_changed:
            self.media_changed = False
            self.media_slider.update_after_label()

    def media_player_paused_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        self.play_button.setIcon(QIcon("../icons/play-button.svg"))

    def media_player_media_changed_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        self.media_changed = True
        current_music_idx, current_music = self.core.get_current_idx_music()
        self.song_label.setText(f"{current_music.title}\n{', '.join(current_music.artists)}")
        if current_music.album_cover_bytes is not None:
            self.album_button.setIcon(QIcon(get_pixmap(current_music.album_cover_bytes)))

        # when VLC emits the MediaPlayerEnded event, it does in a separate thread
        if QThread.currentThread().isMainThread():
            self.media_changed_ui()
        else:
            self.media_changed_signal.emit()

        self.last_played_music_df_idx = current_music_idx

    @Slot()
    def press_rewind_button(self):
        if self.core.current_media_idx == 0 or self.core.media_player.get_time() / 1000 > SKIP_BACK_SECOND_THRESHOLD:
            self.core.media_player.set_position(0)
            self.media_slider.slider.setValue(0)
        else:
            self.core.list_player.previous()

    @Slot()
    def press_play_button(self):
        """Start audio playback if none is playing, otherwise pause existing."""
        self.core.list_player.pause() if self.core.list_player.is_playing() else self.core.list_player.play()

    @Slot()
    def shuffle_button_toggled(self):
        """Shuffle remaining songs in playlist."""
        if self.shuffle_button.isChecked():
            self.shuffle_button.button_on()
            split_idx = self.core.current_media_idx + 1
            assert len(self.core.indices) == len(self.queue.queue_entries) == self.core.media_list.count()
            to_shuffle_indices = self.core.indices[split_idx:]
            to_shuffle_media = [self.core.media_list[i] for i in range(split_idx, self.core.media_list.count())]
            to_shuffle_queue_entries = self.queue.queue_entries[split_idx:]
            assert len(to_shuffle_indices) == len(to_shuffle_media) == len(to_shuffle_queue_entries)
            shuffle_indices = np.arange(len(to_shuffle_indices))
            np.random.shuffle(shuffle_indices)

            shuffled_indices = [to_shuffle_indices[i] for i in shuffle_indices]
            shuffled_media = [to_shuffle_media[i] for i in shuffle_indices]
            shuffled_queue_entries = [to_shuffle_queue_entries[i] for i in shuffle_indices]

            self.load_media(
                self.core.instance.media_list_new(
                    [*[self.core.media_list[i] for i in range(split_idx)], *shuffled_media]
                ),
                [*self.core.indices[:split_idx], *shuffled_indices],
                [*self.queue.queue_entries[:split_idx], *shuffled_queue_entries],
            )
        else:
            self.shuffle_button.button_off()
            self.core.unshuffle()
        self.queue.update_first_queue_index()

    @Slot()
    def press_repeat_button(self):
        """Change repeat state."""
        self.core.repeat_state = next(self.core.repeat_states)
        match self.core.repeat_state:
            case "NO_REPEAT":
                self.repeat_button.setIcon(QIcon("../icons/repeat-button.svg"))
                self.repeat_button.button_off()
                self.core.list_player.set_playback_mode(vlc.PlaybackMode.default)  # pyright: ignore[reportAttributeAccessIssue]
            case "REPEAT_QUEUE":
                self.repeat_button.button_on()
                self.core.list_player.set_playback_mode(vlc.PlaybackMode.loop)  # pyright: ignore[reportAttributeAccessIssue]
            case "REPEAT_ONE":
                self.repeat_button.setIcon(QIcon("../icons/repeat-1-button.svg"))
                self.repeat_button.button_on()
                self.core.list_player.set_playback_mode(vlc.PlaybackMode.repeat)  # pyright: ignore[reportAttributeAccessIssue]

    @Slot()
    @profile
    def double_click_tree_view_item(self, index: QModelIndex) -> None:
        item: TreeModelItem = cast(TreeModelItem, self.playlist_view.model.itemFromIndex(index))
        print(f"Play {item.text()}")
        playlist = item.playlist
        if playlist is None:
            raise NotImplementedError
        playlist.last_played = datetime.now()
        self.load_media(playlist.to_media_list(self.core.instance), playlist.indices, None)
        self.core.list_player.play_item_at_index(0)
        self.queue.update_first_queue_index()

    def __init__(self, core: VLCCore):
        super().__init__()

        self.core = core
        self.media_changed: bool = False
        self.setWindowTitle("Media Player")
        self.media_changed_signal.connect(self.media_changed_ui)
        current_music_idx, current_music = self.core.get_current_idx_music()
        self.last_played_music_df_idx: int = current_music_idx

        main_ui = QHBoxLayout()

        self.playlist_view = PlaylistView(self.core)
        self.playlist_view.tree_view.doubleClicked.connect(self.double_click_tree_view_item)
        main_ui.addWidget(self.playlist_view)

        self.history = QueueEntryGraphicsView()
        self.queue = QueueGraphicsView(self.core)

        queue_tab = QTabWidget()
        queue_tab.setFixedWidth(QUEUE_ENTRY_WIDTH)
        queue_tab.addTab(self.queue, "Queue")
        queue_tab.addTab(self.history, "History")

        main_ui.addStretch()  # TODO REMOVE
        main_ui.addWidget(queue_tab)
        w = QWidget()
        w.setLayout(main_ui)
        self.setCentralWidget(w)

        toolbar = QToolBar(floatable=False, movable=False, orientation=Qt.Orientation.Horizontal)
        toolbar.setFixedHeight(100)
        toolbar.setIconSize(QSize(100, 100))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, toolbar)

        self.album_button = AlbumButton(current_music, toolbar, (100, 0))
        toolbar.addWidget(self.album_button)

        self.song_label = QLabel(current_music.title)
        self.song_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        toolbar.addWidget(self.song_label)

        ### MEDIA PLAYBACK BUTTONS AND SCRUBBER
        media_control_widget = QWidget()
        media_control_vbox = QVBoxLayout(media_control_widget)

        media_control_widget.setStyleSheet("QWidget { background: transparent; }")  # Make the container transparent

        ### MEDIA PLAYBACK BUTTONS
        media_control_button_hbox = QHBoxLayout()
        media_control_vbox.addLayout(media_control_button_hbox)

        self.shuffle_button = OpacityButton()
        self.shuffle_button.setIcon(QIcon("../icons/shuffle-button.svg"))
        self.shuffle_button.toggled.connect(self.shuffle_button_toggled)
        media_control_button_hbox.addWidget(self.shuffle_button)

        rewind_button = QToolButton()
        rewind_button.setIcon(QIcon("../icons/rewind-button.svg"))
        rewind_button.clicked.connect(self.press_rewind_button)
        media_control_button_hbox.addWidget(rewind_button)

        self.play_button = QToolButton()
        self.play_button.setIcon(QIcon("../icons/play-button.svg"))
        self.play_button.clicked.connect(self.press_play_button)
        media_control_button_hbox.addWidget(self.play_button)

        skip_button = QToolButton()
        skip_button.setIcon((QIcon(QPixmap("../icons/rewind-button.svg").transformed(QTransform().scale(-1, 1)))))
        skip_button.clicked.connect(self.core.list_player.next)
        media_control_button_hbox.addWidget(skip_button)

        self.repeat_button = OpacityButton()
        self.repeat_button.setIcon(QIcon("../icons/repeat-button.svg"))
        self.repeat_button.clicked.connect(self.press_repeat_button)
        media_control_button_hbox.addWidget(self.repeat_button)

        ### MEDIA SCRUBBER
        self.media_slider = MediaScrubberSlider(self.core)
        media_control_vbox.addLayout(self.media_slider)

        toolbar.addWidget(expanding_widget())
        toolbar.addWidget(media_control_widget)
        toolbar.addWidget(expanding_widget())

        ### VOLUME BAR
        volume_widget = QWidget()
        VolumeSlider(self.core, volume_widget)
        toolbar.addWidget(volume_widget)

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
            self.media_slider.update_ui_live,
        )
        self.core.list_player_event_manager.event_attach(
            EventType.MediaListPlayerNextItemSet,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_media_changed_callback,
        )


if __name__ == "__main__":
    core = VLCCore()
    app = QApplication(sys.argv)
    window = MainWindow(core)
    window.show()
    sys.exit(app.exec())
