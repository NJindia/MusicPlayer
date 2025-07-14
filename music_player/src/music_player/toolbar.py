from functools import cache, partial
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtGui import QIcon, QTransform
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QSlider, QToolButton, QVBoxLayout, QWidget

from music_player.common_gui import OpacityButton, ShuffleButton, TextScrollArea, get_play_button_icon
from music_player.constants import (
    SKIP_BACK_SECOND_THRESHOLD,
    TOOLBAR_HEIGHT,
    TOOLBAR_MEDIA_CONTROL_WIDTH,
    TOOLBAR_PADDING,
    VOLUME_SLIDER_MAX_WIDTH,
)
from music_player.db_types import DbMusic
from music_player.signals import SharedSignals
from music_player.utils import get_pixmap, timestamp_to_str
from music_player.vlc_core import VLCCore


def expanding_widget() -> QWidget:
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return widget


class AlbumButton(QToolButton):
    def __init__(self, album_id: int, shared_signals: SharedSignals, height_linewidth: tuple[int, int]):
        super().__init__()
        self.setObjectName("AlbumButton")
        self._album_id = album_id
        self._signals = shared_signals

        height = height_linewidth[0] - height_linewidth[1] * 2
        button_size = QSize(height, height)
        self.setFixedSize(button_size)
        self.setIconSize(button_size)

        self.clicked.connect(self.button_clicked)

    def change_music(self, new_music: DbMusic):
        self._album_id = new_music.album_id
        self.setIcon(QIcon(get_pixmap(new_music.img_path, self.height())))

    def button_clicked(self):
        if not self._album_id:
            return
        partial(self._signals.library_load_album_signal.emit, self._album_id)


class MediaScrubberSlider(QHBoxLayout):
    def __init__(self, core: VLCCore):
        super().__init__()
        self.core = core

        self.before_label = QLabel(timestamp_to_str(0))
        self.after_label = QLabel()

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.sliderMoved.connect(self.scrub_media)
        self.slider.sliderReleased.connect(self.set_media_position)
        self.slider.setValue(0)

        self.addWidget(self.before_label)
        self.addWidget(self.slider)
        self.addWidget(self.after_label)

        self.update_after_label()

    def get_current_media_duration(self) -> float:
        curr_media = self.core.current_media
        if curr_media is None:
            return 0.0
        return curr_media.get_duration() / 1000

    @Slot()
    def scrub_media(self):
        self.before_label.setText(timestamp_to_str(self.slider.sliderPosition()))

    def update_after_label(self):
        self.slider.setMaximum(round(self.get_current_media_duration()))
        self.after_label.setText(timestamp_to_str(self.get_current_media_duration()))

    def update_ui_live(self, new_time: int):
        if self.slider.isSliderDown():
            return  # Don't update if scrubbing
        new_time = round(new_time / 1000)
        self.slider.setSliderPosition(new_time)
        self.before_label.setText(timestamp_to_str(new_time))
        # TODO CONSIDER round(self.core.music_player.get_time() / 1000) for time choppiness

    @Slot()
    def set_media_position(self):
        if self.slider.value() == self.slider.maximum():
            self.core.next()
        else:
            self.core.media_player.set_position(self.slider.value() / self.get_current_media_duration())


VOLUME_ICONS = Literal["VOLUME_MUTED", "VOLUME_OFF", "VOLUME_MAX", "VOLUME_MIN"]


@cache
def get_volume_icons() -> dict[VOLUME_ICONS, QIcon]:
    return {
        "VOLUME_MUTED": QIcon(
            get_pixmap(Path("../icons/volume/volume-mute.svg"), None, color=Qt.GlobalColor.white, cache=False)
        ),
        "VOLUME_OFF": QIcon(
            get_pixmap(Path("../icons/volume/volume-off.svg"), None, color=Qt.GlobalColor.white, cache=False)
        ),
        "VOLUME_MAX": QIcon(
            get_pixmap(Path("../icons/volume/volume-max.svg"), None, color=Qt.GlobalColor.white, cache=False)
        ),
        "VOLUME_MIN": QIcon(
            get_pixmap(Path("../icons/volume/volume-min.svg"), None, color=Qt.GlobalColor.white, cache=False)
        ),
    }


class VolumeSlider(QHBoxLayout):
    def __init__(self, core: VLCCore):
        super().__init__()
        self.core = core

        current_volume = self.core.media_player.audio_get_volume()

        self.volume_button: QToolButton = QToolButton()
        self.volume_button.setCheckable(True)
        self.volume_button.toggled.connect(self.toggle_volume_button)
        self.update_volume(current_volume)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.volume_slider.setMaximumWidth(VOLUME_SLIDER_MAX_WIDTH - self.volume_button.sizeHint().width())
        self.volume_slider.setTracking(True)
        self.volume_slider.setValue(current_volume)
        self.volume_slider.setMaximum(100)
        self.volume_slider.valueChanged.connect(self.update_volume)

        self.addWidget(self.volume_button)
        self.addWidget(self.volume_slider)

    @Slot()
    def update_volume(self, new_volume: int):
        assert self.core.media_player.audio_set_volume(new_volume) != -1
        if self.volume_button.isChecked():
            self.volume_button.setIcon(get_volume_icons()["VOLUME_MUTED"])
        elif new_volume == 0:
            self.volume_button.setIcon(get_volume_icons()["VOLUME_OFF"])
        elif new_volume == 100:
            self.volume_button.setIcon(get_volume_icons()["VOLUME_MAX"])
        else:
            self.volume_button.setIcon(get_volume_icons()["VOLUME_MIN"])

    @Slot()
    def toggle_volume_button(self):
        if self.volume_button.isChecked():
            self.update_volume(0)
            self.volume_slider.setEnabled(False)
        else:
            self.update_volume(self.volume_slider.value())
            self.volume_slider.setEnabled(True)


class MediaToolbar(QWidget):
    @Slot()
    def press_play_button(self):
        """Start audio playback if none is playing, otherwise pause existing."""
        if self.core.media_player.is_playing():
            self.core.media_player.pause()
        elif self.core.current_media_idx == -1:
            self.core.next()
        else:
            self.core.media_player.play()

    @Slot()
    def press_rewind_button(self):
        if self.core.current_media_idx == 0 or self.core.media_player.get_time() / 1000 > SKIP_BACK_SECOND_THRESHOLD:
            self.core.media_player.set_position(0)
            self.media_slider.slider.setValue(0)
        else:
            self.core.previous()

    @Slot()
    def press_repeat_button(self):
        """Change repeat state."""
        self.core.repeat_state = next(self.core.repeat_states)
        match self.core.repeat_state:
            case "NO_REPEAT":
                self.repeat_button.setIcon(QIcon("../icons/repeat-button.svg"))
                self.repeat_button.button_off()
                # self.core.media_player.set_playback_mode(vlc.PlaybackMode.default)
            case "REPEAT_QUEUE":
                self.repeat_button.button_on()
                # self.core.media_player.set_playback_mode(vlc.PlaybackMode.loop)
            case "REPEAT_ONE":
                self.repeat_button.setIcon(QIcon("../icons/repeat-1-button.svg"))
                self.repeat_button.button_on()
                # self.core.media_player.set_playback_mode(vlc.PlaybackMode.repeat)

    def __init__(self, core: VLCCore, shared_signals: SharedSignals):
        super().__init__()
        self.setObjectName("MediaToolbar")
        self.core = core
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, on=True)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(TOOLBAR_HEIGHT)

        self.album_button = AlbumButton(0, shared_signals, (TOOLBAR_HEIGHT, TOOLBAR_PADDING))

        self.song_label = TextScrollArea()
        self.artists_label = TextScrollArea()

        self.shuffle_button = ShuffleButton(shared_signals)

        rewind_pixmap = get_pixmap(Path("../icons/rewind-button.svg"), None, color=Qt.GlobalColor.white)
        rewind_button = QToolButton()
        rewind_button.setIcon(QIcon(rewind_pixmap))
        rewind_button.clicked.connect(self.press_rewind_button)

        self.play_pause_button = QToolButton()
        self.play_pause_button.setIcon(get_play_button_icon())
        self.play_pause_button.clicked.connect(self.press_play_button)

        skip_button = QToolButton()
        skip_button.setIcon(QIcon(rewind_pixmap.transformed(QTransform().scale(-1, 1))))
        skip_button.clicked.connect(self.core.next)

        self.repeat_button = OpacityButton()
        self.repeat_button.setIcon(
            QIcon(get_pixmap(Path("../icons/repeat-button.svg"), None, color=Qt.GlobalColor.white))
        )
        self.repeat_button.clicked.connect(self.press_repeat_button)

        self.media_slider = MediaScrubberSlider(self.core)

        media_control_button_hbox = QHBoxLayout()
        media_control_button_hbox.addStretch()
        media_control_button_hbox.addWidget(self.shuffle_button)
        media_control_button_hbox.addWidget(rewind_button)
        media_control_button_hbox.addWidget(self.play_pause_button)
        media_control_button_hbox.addWidget(skip_button)
        media_control_button_hbox.addWidget(self.repeat_button)
        media_control_button_hbox.addStretch()

        media_control_widget = QWidget()
        media_control_widget.setMaximumWidth(TOOLBAR_MEDIA_CONTROL_WIDTH)

        media_control_vbox = QVBoxLayout(media_control_widget)
        media_control_vbox.addLayout(media_control_button_hbox)
        media_control_vbox.addLayout(self.media_slider)

        song_meta_layout = QVBoxLayout()
        song_meta_layout.addWidget(self.song_label)
        song_meta_layout.addWidget(self.artists_label)

        left_layout = QHBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.album_button)
        left_layout.addLayout(song_meta_layout)

        right_layout = QHBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addStretch()
        right_layout.addLayout(VolumeSlider(self.core))

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(TOOLBAR_PADDING, TOOLBAR_PADDING, TOOLBAR_PADDING, TOOLBAR_PADDING)
        main_layout.setSpacing(0)
        main_layout.addLayout(left_layout)
        main_layout.addWidget(media_control_widget)
        main_layout.addLayout(right_layout)
        self.setLayout(main_layout)
