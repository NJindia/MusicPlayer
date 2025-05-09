from PySide6.QtCore import QSize, Slot
from PySide6.QtWidgets import QToolButton, QWidget

from music_downloader.music import Music


@Slot()
def go_to_album():
    print("TODO Going to album...")


class AlbumButton(QToolButton):
    def __init__(self, metadata: Music, parent: QWidget | None = None, height_linewidth: tuple[int, int] | None = None):
        super().__init__(parent)
        self.clicked.connect(go_to_album)
        self.setIcon(metadata.album_icon)
        if height_linewidth is not None:
            height = height_linewidth[0] - height_linewidth[1] * 2
            button_size = QSize(height, height)
            self.setFixedSize(button_size)
            self.setIconSize(button_size)
