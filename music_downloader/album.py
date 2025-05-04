from PySide6.QtCore import QSize
from PySide6.QtWidgets import QToolButton, QFrame

from music_downloader.music import Music


def go_to_album():
    print("TODO Going to album...")


class AlbumButton(QToolButton):
    def __init__(self, metadata: Music, parent: QFrame | None = None):
        super().__init__(parent)
        self.clicked.connect(go_to_album)
        self.setIcon(metadata.album_icon)
        if parent is not None:
            height = parent.height() - parent.lineWidth() * 2
            button_size = QSize(height, height)
            self.setFixedSize(button_size)
            self.setIconSize(button_size)

    def heightForWidth(self, width: int):
        return width
