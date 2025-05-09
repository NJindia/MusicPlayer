from functools import cache

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QSlider, QLabel, QHBoxLayout, QToolButton
from typing_extensions import Literal

from music_downloader.vlc_core import VLCCore


class LabeledSlider(QHBoxLayout):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.slider = QSlider(Qt.Orientation.Horizontal)  # TODO TICK POS
        self.before_label = QLabel()
        self.after_label = QLabel()

        self.addWidget(self.before_label)
        self.addWidget(self.slider)
        self.addWidget(self.after_label)


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
        self.volume_slider.setValue(current_volume)
        self.volume_slider.setMaximum(100)
        self.volume_slider.valueChanged.connect(self.update_volume)

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
