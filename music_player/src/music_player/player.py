import sys

import qdarktheme  # pyright: ignore[reportMissingTypeStubs]
from PySide6.QtGui import QPixmapCache
from PySide6.QtWidgets import QApplication

from music_player.constants import SKIP_BACK_SECOND_THRESHOLD
from music_player.db_types import DbMusic, get_db_music_cache
from music_player.main_window import MainWindow
from music_player.signals import SharedSignals
from music_player.stylesheet import stylesheet
from music_player.vlc_core import VLCCore


class Player:
    def __init__(self):
        self.vlc_core = VLCCore()
        self.shared_signals = SharedSignals()

        self.app = QApplication(sys.argv)
        self.app.setStyleSheet(stylesheet)
        self.main_window = MainWindow(self.vlc_core, self.shared_signals)

        self.shared_signals.play_song_signal.connect(self.vlc_core.play_item)
        self.shared_signals.next_song_signal.connect(self.next)
        self.shared_signals.rewind_signal.connect(self.rewind)

    @property
    def manual_music_ids(self) -> list[int]:
        return self.main_window.queue.manual_music_ids

    @property
    def queue_music_ids(self) -> list[int]:
        return self.main_window.queue.queue_music_ids

    @property
    def current_queue_idx(self) -> int:
        return self.main_window.queue.current_queue_idx

    @current_queue_idx.setter
    def current_queue_idx(self, value: int):
        self.main_window.queue.current_queue_idx = value

    def play(self):
        if self.current_queue_idx == -1:
            self.next()
        else:
            self.vlc_core.media_player.play()

    def next(self, *, manually_triggered: bool = False):
        repeat_state = self.main_window.toolbar.repeat_button.repeat_state
        if repeat_state == "REPEAT_ONE" and not manually_triggered:
            self.vlc_core.play_item(self.queue_music_ids[self.current_queue_idx])
            return

        if len(self.manual_music_ids):
            self.main_window.play_manual_list_item(0)
            return

        self.current_queue_idx += 1
        if self.current_queue_idx >= len(self.queue_music_ids):
            if repeat_state == "NO_REPEAT":
                self.vlc_core.stop()
            else:
                self.current_queue_idx = 0
                self.vlc_core.play_item(self.queue_music_ids[self.current_queue_idx])
        else:
            self.vlc_core.play_item(self.queue_music_ids[self.current_queue_idx])

    def rewind(self):
        if self.current_queue_idx == -1:
            return
        if self.current_queue_idx == 0 or self.vlc_core.media_player.get_time() / 1000 > SKIP_BACK_SECOND_THRESHOLD:
            self.vlc_core.media_player.set_position(0)
            self.main_window.toolbar.media_slider.slider.setValue(0)
        self.current_queue_idx = max(self.current_queue_idx - 1, 0)
        self.vlc_core.play_item(self.queue_music_ids[self.current_queue_idx])

    def run(self):
        QPixmapCache.setCacheLimit(102400)  # 100MB
        get_db_music_cache()  # TODO THIS COULD BE BETTER THAN FRONTLOADING
        qdarktheme.setup_theme()
        self.main_window.show()
        sys.exit(self.app.exec())


if __name__ == "__main__":
    Player().run()
