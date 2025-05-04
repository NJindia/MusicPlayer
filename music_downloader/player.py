import sys
from functools import partial
from typing import cast

import numpy as np
import vlc
from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QIcon, QTransform, QPixmap, QImage
from PySide6.QtWidgets import (
    QApplication,
    QToolBar,
    QToolButton,
    QMainWindow,
    QWidget,
    QSizePolicy,
    QLabel,
)
from vlc import MediaPlayer, MediaListPlayer, Instance, EventType

from music_downloader.music import get_music, Music

SKIP_BACK_SECOND_THRESHOLD = 5
"""Number of seconds into a track that pressing the rewind button will skip back to the previous track."""


def expanding_widget() -> QWidget:
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return widget


def get_song_label(metadata: Music) -> str:
    return f"{metadata.title} - {', '.join(metadata.artists)}"


# Subclass QMainWindow to customize your application's main window
class MainWindow(QMainWindow):
    def test(self, event):
        print(f"{event.type}")

    def media_player_playing_callback(
        self,
        play_button: QToolButton,
        song_label: QLabel,
        album_button: QToolButton,
        event: vlc.Event,
    ):
        print(f"Event: {event.type}")
        if event.type == EventType.MediaPlayerPlaying:  # pyright: ignore[reportAttributeAccessIssue]
            play_button.setIcon(QIcon("icons/pause-button.svg"))
            md = self.get_media_metadata(self.current_media)
            song_label.setText(get_song_label(md))
            if md.album_cover_bytes is not None:
                album_button.setIcon(
                    QIcon(QPixmap.fromImage(QImage.fromData(md.album_cover_bytes)))
                )

    def media_player_paused_callback(self, button: QToolButton, event: vlc.Event):
        print(f"Event: {event.type}")
        if (
            event.type == EventType.MediaPlayerPaused  # pyright: ignore[reportAttributeAccessIssue]
            or event.type == EventType.MediaPlayerStopped  # pyright: ignore[reportAttributeAccessIssue]
        ):
            button.setIcon(QIcon("icons/play-button.svg"))

    @Slot()
    def press_play_button(self):
        """Start audio playback if none is playing, otherwise pause existing."""
        self.list_player.pause() if self.list_player.is_playing() else self.list_player.play()

    @Slot()
    def press_rewind_button(self):
        """Rewind player to the beginning of the track."""
        if self.list_player.is_playing():
            player: MediaPlayer = self.list_player.get_media_player()
            if (
                self._current_media_idx == 0
                or player.get_time() / 1000 > SKIP_BACK_SECOND_THRESHOLD
            ):
                player.set_position(0)
            else:
                self.list_player.previous()

    @Slot()
    def press_skip_button(self):
        """Rewind player to the beginning of the track."""
        if self.list_player.next() == -1:
            self.list_player.stop()

    @Slot()
    def press_shuffle_button(self):
        """Shuffle remaining songs in playlist."""
        if count := self.media_list.count():  # If a queue is loaded
            indices = np.arange(start=self._current_media_idx + 1, stop=count)
            np.random.shuffle(indices)
            new_media = [self.media_list[i] for i in indices]
            for _ in range(len(indices)):
                self.media_list.remove_index(self._current_media_idx + 1)
                self.media_list.add_media(new_media.pop(0))

    @property
    def _current_media_idx(self):
        idx = self.media_list.index_of_item(self.current_media)
        if idx == -1 and self.media_list.count() > 0:
            idx = 0
        return idx

    @property
    def current_media(self):
        return self.list_player.get_media_player().get_media()

    def get_media_metadata(self, media: vlc.Media):
        idx = self.media_list.index_of_item(media)
        return self.metadata[idx if idx != -1 else 0]

    def __init__(
        self,
        media_list: vlc.MediaList,
        vlc_list_player: vlc.MediaListPlayer,
        metadata: list[Music],
    ):
        super().__init__()

        self.list_player = vlc_list_player
        self.media_list = media_list
        self.metadata = metadata

        self.setWindowTitle("Media Player")

        toolbar = QToolBar(
            floatable=False, movable=False, orientation=Qt.Orientation.Horizontal
        )
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, toolbar)

        album_button = QToolButton()
        toolbar.addWidget(album_button)
        # album_button.setIcon()

        song_label = QLabel(get_song_label(self.get_media_metadata(self.current_media)))
        song_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        toolbar.addWidget(song_label)

        shuffle_button = QToolButton()
        shuffle_button.setIcon(QIcon("icons/shuffle-button.svg"))
        shuffle_button.setCheckable(True)
        shuffle_button.clicked.connect(self.press_shuffle_button)
        toolbar.addWidget(shuffle_button)

        rewind_button = QToolButton()
        rewind_button.setIcon(QIcon("icons/rewind-button.svg"))
        rewind_button.clicked.connect(self.press_rewind_button)
        toolbar.addWidget(rewind_button)

        play_button = QToolButton()
        play_button.setIcon(QIcon("icons/play-button.svg"))
        play_button.clicked.connect(self.press_play_button)
        toolbar.addWidget(play_button)

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

        em = self.list_player.get_media_player().event_manager()
        em.event_attach(
            EventType.MediaPlayerPlaying,  # pyright: ignore[reportAttributeAccessIssue]
            partial(
                self.media_player_playing_callback,
                play_button,
                song_label,
                album_button,
            ),
        )
        em.event_attach(
            EventType.MediaPlayerPaused,  # pyright: ignore[reportAttributeAccessIssue]
            partial(self.media_player_paused_callback, play_button),
        )
        em.event_attach(
            EventType.MediaPlayerStopped,  # pyright: ignore[reportAttributeAccessIssue]
            partial(self.media_player_paused_callback, play_button),
        )


if __name__ == "__main__":
    music = list(get_music())

    instance = cast(Instance, Instance())

    player_: MediaListPlayer = instance.media_list_player_new()
    media_list_ = instance.media_list_new([m.file_path for m in music])
    player_.set_media_list(media_list_)

    app = QApplication(sys.argv)
    window = MainWindow(media_list_, player_, music)
    window.show()
    sys.exit(app.exec())
