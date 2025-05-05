import sys

import numpy as np
import vlc
from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QIcon, QTransform, QPixmap
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
)
from vlc import MediaPlayer, EventType

from music_downloader.album import AlbumButton
from music_downloader.queue_gui import (
    ScrollableLayout,
    QueueEntry,
    GraphicsViewSection,
)
from music_downloader.vlc_core import VLCCore

SKIP_BACK_SECOND_THRESHOLD = 5
"""Number of seconds into a track that pressing the rewind button will skip back to the previous track."""


def expanding_widget() -> QWidget:
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return widget


class MainWindow(QMainWindow):
    def media_player_playing_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        if event.type == EventType.MediaPlayerPlaying:  # pyright: ignore[reportAttributeAccessIssue]
            self.play_button.setIcon(QIcon("icons/pause-button.svg"))
            curr_media_idx = self._current_media_idx
            md = self.core.music_list[curr_media_idx]
            self.song_label.setText(f"{md.title}\n{', '.join(md.artists)}")
            self.album_button.setIcon(md.album_icon)
            self.last_played_idx = curr_media_idx

    def media_player_paused_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        if (
            event.type in [EventType.MediaPlayerPaused, EventType.MediaPlayerStopped]  # pyright: ignore[reportAttributeAccessIssue]
        ):
            self.play_button.setIcon(QIcon("icons/play-button.svg"))

    def media_player_media_changed_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        curr_media_idx = self._current_media_idx
        if curr_media_idx == self.last_played_idx:
            return
        self.queue.update_first_queue_index(curr_media_idx + 1)
        print(self.last_played_idx, curr_media_idx)
        self.history.insert_queue_entry(
            0, QueueEntry(self.core, int(self.last_played_idx))
        )

    @Slot()
    def press_play_button(self):
        """Start audio playback if none is playing, otherwise pause existing."""
        self.core.list_player.pause() if self.core.list_player.is_playing() else self.core.list_player.play()

    @Slot()
    def press_rewind_button(self):
        """Rewind player to the beginning of the track."""
        player: MediaPlayer = self.core.list_player.get_media_player()
        if (
            self._current_media_idx == 0
            or player.get_time() / 1000 > SKIP_BACK_SECOND_THRESHOLD
        ):
            player.set_position(0)
        else:
            self.core.list_player.previous()

    @Slot()
    def press_skip_button(self):
        """Rewind player to the beginning of the track."""
        if self.core.list_player.next() == -1:
            self.core.list_player.stop()

    @Slot()
    def press_shuffle_button(self):
        """Shuffle remaining songs in playlist."""
        if count := self.core.media_list.count():  # If a queue is loaded
            indices = np.arange(start=self._current_media_idx + 1, stop=count)
            np.random.shuffle(indices)
            new_media = [self.core.media_list[i] for i in indices]
            for _ in range(len(indices)):
                self.core.media_list.remove_index(self._current_media_idx + 1)
                self.core.media_list.add_media(new_media.pop(0))

    @property
    def _current_media_idx(self):
        idx = self.core.media_list.index_of_item(self.current_media)
        if idx == -1 and self.core.media_list.count() > 0:
            idx = 0
        return idx

    @property
    def current_media(self):
        return self.core.list_player.get_media_player().get_media()

    def __init__(self, core: VLCCore):
        super().__init__()

        self.core = core

        self.setWindowTitle("Media Player")

        current_media_idx = self._current_media_idx
        current_media_md = self.core.music_list[current_media_idx]
        self.last_played_idx: int = current_media_idx

        main_ui = QHBoxLayout()

        self.history = GraphicsViewSection()
        self.queue = GraphicsViewSection(
            [QueueEntry(self.core, i) for i in range(len(self.core.music_list))]
        )

        queue_tab = QTabWidget()
        queue_tab.addTab(self.queue, "Queue")
        queue_tab.addTab(self.history, "History")

        main_ui.addStretch()  # TODO REMOVE
        main_ui.addWidget(queue_tab)
        w = QWidget()
        w.setLayout(main_ui)
        self.setCentralWidget(w)

        toolbar = QToolBar(
            floatable=False, movable=False, orientation=Qt.Orientation.Horizontal
        )
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, toolbar)

        self.album_button = AlbumButton(current_media_md)
        toolbar.addWidget(self.album_button)

        self.song_label = QLabel(current_media_md.title)
        self.song_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        toolbar.addWidget(self.song_label)

        shuffle_button = QToolButton()
        shuffle_button.setIcon(QIcon("icons/shuffle-button.svg"))
        shuffle_button.setCheckable(True)
        shuffle_button.clicked.connect(self.press_shuffle_button)
        toolbar.addWidget(shuffle_button)

        rewind_button = QToolButton()
        rewind_button.setIcon(QIcon("icons/rewind-button.svg"))
        rewind_button.clicked.connect(self.press_rewind_button)
        toolbar.addWidget(rewind_button)

        self.play_button = QToolButton()
        self.play_button.setIcon(QIcon("icons/play-button.svg"))
        self.play_button.clicked.connect(self.press_play_button)
        toolbar.addWidget(self.play_button)

        skip_button = QToolButton()
        skip_button.setIcon(
            (
                QIcon(
                    QPixmap("icons/rewind-button.svg").transformed(
                        QTransform().scale(-1, 1)
                    )
                )
            )
        )
        skip_button.clicked.connect(self.press_skip_button)
        toolbar.addWidget(skip_button)

        repeat_button = QToolButton()
        repeat_button.setIcon(QIcon("icons/repeat-button.svg"))
        # repeat_button.clicked.connect(self.press_repeat_button)
        toolbar.addWidget(repeat_button)

        toolbar.addWidget(expanding_widget())

        player_manager = self.core.list_player.get_media_player().event_manager()
        player_manager.event_attach(
            EventType.MediaPlayerPlaying,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_playing_callback,
        )
        player_manager.event_attach(
            EventType.MediaPlayerPaused,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_paused_callback,
        )
        player_manager.event_attach(
            EventType.MediaPlayerStopped,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_paused_callback,
        )
        self.core.list_player.event_manager().event_attach(
            EventType.MediaListPlayerPlayed,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_playing_callback,
        )
        self.core.list_player.event_manager().event_attach(
            EventType.MediaListPlayerNextItemSet,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_media_changed_callback,
        )


if __name__ == "__main__":
    core = VLCCore()
    app = QApplication(sys.argv)
    window = MainWindow(core)
    window.show()
    sys.exit(app.exec())
