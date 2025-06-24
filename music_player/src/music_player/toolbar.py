from functools import cache, partial
from typing import Literal

import pandas as pd
import vlc
from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtGui import QIcon, QPixmap, QTransform
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from music_player.common_gui import get_play_button_icon, get_shuffle_button_icon
from music_player.constants import SKIP_BACK_SECOND_THRESHOLD
from music_player.signals import SharedSignals
from music_player.utils import get_empty_pixmap, get_pixmap, timestamp_to_str
from music_player.vlc_core import VLCCore


def expanding_widget() -> QWidget:
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    return widget


class AlbumButton(QToolButton):
    def __init__(self, music: pd.Series | None, shared_signals: SharedSignals, height_linewidth: tuple[int, int]):
        super().__init__()
        self.music = music
        self.signals = shared_signals

        height = height_linewidth[0] - height_linewidth[1] * 2
        button_size = QSize(height, height)
        self.setFixedSize(button_size)
        self.setIconSize(button_size)

        self.clicked.connect(self.button_clicked)

    def button_clicked(self):
        if self.music is None:
            return
        partial(self.signals.library_load_album_signal.emit, self.music["album"])

    def set_music(self, music: pd.Series | None):
        """Set the music for this button, updating the icon."""
        self.music = music
        if self.music is not None:
            if self.music["album_cover_bytes"] is None:
                raise NotImplementedError("NEED PLACEHOLDER FOR NO ALBUM COVER")
            self.setIcon(QIcon(get_pixmap(self.music["album_cover_bytes"], self.iconSize().height())))
        else:
            self.setIcon(QIcon(get_empty_pixmap(self.iconSize().height())))


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

    def update_ui_live(self, event: vlc.Event):
        if self.slider.isSliderDown():
            return  # Don't update if scrubbing
        new_time = round(event.u.new_time / 1000)
        self.slider.setSliderPosition(new_time)
        self.before_label.setText(timestamp_to_str(new_time))
        # TODO CONSIDER round(self.core.music_player.get_time() / 1000) for time choppiness

    @Slot()
    def set_media_position(self):
        self.core.media_player.set_position(self.slider.value() / self.get_current_media_duration())


VOLUME_ICONS = Literal["VOLUME_MUTED", "VOLUME_OFF", "VOLUME_MAX", "VOLUME_MIN"]


@cache
def get_volume_icons() -> dict[VOLUME_ICONS, QIcon]:
    return {
        "VOLUME_MUTED": QIcon("../icons/volume/volume-mute.svg"),
        "VOLUME_OFF": QIcon("../icons/volume/volume-off.svg"),
        "VOLUME_MAX": QIcon("../icons/volume/volume-max.svg"),
        "VOLUME_MIN": QIcon("../icons/volume/volume-min.svg"),
    }


class VolumeSlider(QHBoxLayout):
    def __init__(self, core: VLCCore, parent: QWidget):
        super().__init__(parent)
        self.core = core
        current_volume = self.core.media_player.audio_get_volume()
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.volume_slider.setMaximumWidth(200)
        self.volume_slider.setTracking(True)
        self.volume_slider.setValue(current_volume)
        self.volume_slider.setMaximum(100)
        self.volume_slider.valueChanged.connect(self.update_volume)
        self.volume_slider.setStyleSheet("QSlider { background: transparent; }")

        self.volume_button: QToolButton = QToolButton()
        self.volume_button.setCheckable(True)
        self.volume_button.toggled.connect(self.toggle_volume_button)
        self.update_volume(current_volume)

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


class MediaToolbar(QToolBar):
    @Slot()
    def press_play_button(self):
        """Start audio playback if none is playing, otherwise pause existing."""
        print(self.core.current_media)
        self.core.list_player.pause() if self.core.list_player.is_playing() else self.core.list_player.play()

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
                self.core.list_player.set_playback_mode(vlc.PlaybackMode.default)  # pyright: ignore[reportAttributeAccessIssue]
            case "REPEAT_QUEUE":
                self.repeat_button.button_on()
                self.core.list_player.set_playback_mode(vlc.PlaybackMode.loop)  # pyright: ignore[reportAttributeAccessIssue]
            case "REPEAT_ONE":
                self.repeat_button.setIcon(QIcon("../icons/repeat-1-button.svg"))
                self.repeat_button.button_on()
                self.core.list_player.set_playback_mode(vlc.PlaybackMode.repeat)  # pyright: ignore[reportAttributeAccessIssue]

    def __init__(self, core: VLCCore, shared_signals: SharedSignals):
        super().__init__(floatable=False, movable=False, orientation=Qt.Orientation.Horizontal)
        self.core = core

        self.setFixedHeight(100)
        self.setIconSize(QSize(100, 100))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        current_music = None  # TODO REMEMBER LAST SESSION self.core.current_music
        self.album_button = AlbumButton(current_music, shared_signals, (100, 0))
        self.addWidget(self.album_button)

        self.song_label = QLabel()  # current_music.title)
        self.song_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.addWidget(self.song_label)

        ### MEDIA PLAYBACK BUTTONS AND SCRUBBER
        media_control_widget = QWidget()
        media_control_vbox = QVBoxLayout(media_control_widget)

        media_control_widget.setStyleSheet("QWidget { background: transparent; }")

        ### MEDIA PLAYBACK BUTTONS
        media_control_button_hbox = QHBoxLayout()
        media_control_vbox.addLayout(media_control_button_hbox)

        self.shuffle_button = OpacityButton()
        self.shuffle_button.setIcon(get_shuffle_button_icon())
        media_control_button_hbox.addWidget(self.shuffle_button)

        rewind_button = QToolButton()
        rewind_button.setIcon(QIcon("../icons/rewind-button.svg"))
        rewind_button.clicked.connect(self.press_rewind_button)
        media_control_button_hbox.addWidget(rewind_button)

        self.play_pause_button = QToolButton()
        self.play_pause_button.setIcon(get_play_button_icon())
        self.play_pause_button.clicked.connect(self.press_play_button)
        media_control_button_hbox.addWidget(self.play_pause_button)

        self.skip_button = QToolButton()
        self.skip_button.setIcon(QIcon(QPixmap("../icons/rewind-button.svg").transformed(QTransform().scale(-1, 1))))
        self.skip_button.clicked.connect(self.core.next)
        media_control_button_hbox.addWidget(self.skip_button)

        self.repeat_button = OpacityButton()
        self.repeat_button.setIcon(QIcon("../icons/repeat-button.svg"))
        self.repeat_button.clicked.connect(self.press_repeat_button)
        media_control_button_hbox.addWidget(self.repeat_button)

        ### MEDIA SCRUBBER
        self.media_slider = MediaScrubberSlider(self.core)
        media_control_vbox.addLayout(self.media_slider)

        self.addWidget(expanding_widget())
        self.addWidget(media_control_widget)
        self.addWidget(expanding_widget())

        ### VOLUME BAR
        volume_widget = QWidget()
        VolumeSlider(self.core, volume_widget)
        self.addWidget(volume_widget)
