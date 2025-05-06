import sys

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
from vlc import EventType

from music_downloader.album import AlbumButton
from music_downloader.queue_gui import (
    QueueEntry,
    GraphicsViewSection,
)
from music_downloader.vlc_core import VLCCore


def expanding_widget() -> QWidget:
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return widget


class MainWindow(QMainWindow):
    def media_player_paused_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        self.play_button.setIcon(QIcon("../icons/play-button.svg"))

    def media_player_media_changed_callback(self, event: vlc.Event):
        print(f"Event: {event.type}")
        # TODO FIX THIS
        # curr_media_idx = self._current_media_idx
        # if curr_media_idx == self.last_played_idx:
        #     return

        curr_media_idx = self.core.media_list_indices[self.core.current_queue_index]
        md = self.core.music_list[curr_media_idx]
        self.song_label.setText(f"{md.title}\n{', '.join(md.artists)}")
        self.album_button.setIcon(md.album_icon)

        self.queue.update_first_queue_index(self.core.current_queue_index + 1)
        self.history.insert_queue_entry(0, QueueEntry(self.core, int(self.last_played_idx)))
        self.last_played_idx = curr_media_idx

    @Slot()
    def press_play_button(self):
        """Start audio playback if none is playing, otherwise pause existing."""
        self.core.list_player.pause() if self.core.list_player.is_playing() else self.core.list_player.play()

    @Slot()
    def shuffle_button_toggled(self):
        """Shuffle remaining songs in playlist."""
        if count := self.core.media_list.count():  # If a queue is loaded
            if self.shuffle_button.isChecked():
                new_queue_indices = self.core.shuffle_next_indices()
                self.queue.queue_indices = self.queue.queue_indices[: -len(new_queue_indices)] + new_queue_indices
                self.queue.update_first_queue_index(self.queue.current_queue_index)
            else:
                print("TODO")
                # new_media = [self.core.media_list[i] for i in self.core.original_indices[self._current_media_idx + 1 :]]
                # for _ in range(len(new_media)):
                #     self.core.media_list.remove_index(self._current_media_idx + 1)
                #     self.core.media_list.add_media(new_media.pop(0))
                #
                # original_next_indices = self.core.original_indices[-self.queue.current_queue_index :]
                # self.queue.queue_indices = (
                #     self.queue.queue_indices[: -len(original_next_indices)] + original_next_indices
                # )
                # self.queue.update_first_queue_index(self.queue.current_queue_index)  # TODO?

    def __init__(self, core: VLCCore):
        super().__init__()

        self.core = core

        self.setWindowTitle("Media Player")

        curr_media_idx = self.core.media_list.index_of_item(self.core.list_player.get_media_player().get_media())
        if curr_media_idx == -1 and self.core.media_list.count() > 0:
            curr_media_idx = 0
        current_media_md = self.core.music_list[curr_media_idx]
        self.last_played_idx: int = curr_media_idx

        main_ui = QHBoxLayout()

        self.history = GraphicsViewSection(self.core, empty=True)
        self.queue = GraphicsViewSection(self.core)

        queue_tab = QTabWidget()
        queue_tab.addTab(self.queue, "Queue")
        queue_tab.addTab(self.history, "History")

        main_ui.addStretch()  # TODO REMOVE
        main_ui.addWidget(queue_tab)
        w = QWidget()
        w.setLayout(main_ui)
        self.setCentralWidget(w)

        toolbar = QToolBar(floatable=False, movable=False, orientation=Qt.Orientation.Horizontal)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, toolbar)

        self.album_button = AlbumButton(current_media_md)
        toolbar.addWidget(self.album_button)

        self.song_label = QLabel(current_media_md.title)
        self.song_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        toolbar.addWidget(self.song_label)

        self.shuffle_button = QToolButton()
        self.shuffle_button.setIcon(QIcon("../icons/shuffle-button.svg"))
        self.shuffle_button.setCheckable(True)
        self.shuffle_button.toggled.connect(self.shuffle_button_toggled)
        toolbar.addWidget(self.shuffle_button)

        rewind_button = QToolButton()
        rewind_button.setIcon(QIcon("../icons/rewind-button.svg"))
        rewind_button.clicked.connect(self.core.play_previous)
        toolbar.addWidget(rewind_button)

        self.play_button = QToolButton()
        self.play_button.setIcon(QIcon("../icons/play-button.svg"))
        self.play_button.clicked.connect(self.press_play_button)
        toolbar.addWidget(self.play_button)

        skip_button = QToolButton()
        skip_button.setIcon((QIcon(QPixmap("../icons/rewind-button.svg").transformed(QTransform().scale(-1, 1)))))
        skip_button.clicked.connect(self.core.play_next)
        toolbar.addWidget(skip_button)

        repeat_button = QToolButton()
        repeat_button.setIcon(QIcon("../icons/repeat-button.svg"))
        # repeat_button.clicked.connect(self.press_repeat_button)
        toolbar.addWidget(repeat_button)

        toolbar.addWidget(expanding_widget())

        player_manager = self.core.list_player.get_media_player().event_manager()
        player_manager.event_attach(
            EventType.MediaPlayerPlaying,  # pyright: ignore[reportAttributeAccessIssue]
            lambda _: self.play_button.setIcon(QIcon("../icons/pause-button.svg")),
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
            EventType.MediaListPlayerNextItemSet,  # pyright: ignore[reportAttributeAccessIssue]
            self.media_player_media_changed_callback,
        )


if __name__ == "__main__":
    core = VLCCore()
    app = QApplication(sys.argv)
    window = MainWindow(core)
    window.show()
    sys.exit(app.exec())
