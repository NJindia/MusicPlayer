from typing import cast

from PySide6.QtCore import QSize, Slot
from PySide6.QtGui import QPixmap, QImage, QPixmapCache, QIcon
from PySide6.QtWidgets import QToolButton, QWidget

from music_downloader.music_importer import Music


@Slot()
def go_to_album():
    print("TODO Going to album...")


def get_pixmap(cover_bytes: bytes) -> QPixmap:
    pixmap = cast(QPixmap | None, QPixmapCache.find(str(cover_bytes)))  # pyright: ignore [reportCallIssue]
    if pixmap is None:
        pixmap = QPixmap.fromImage(QImage.fromData(cover_bytes))
        QPixmapCache.insert(str(cover_bytes), pixmap)
    return pixmap


class AlbumButton(QToolButton):
    def __init__(self, metadata: Music, parent: QWidget | None = None, height_linewidth: tuple[int, int] | None = None):
        super().__init__(parent)
        self.clicked.connect(go_to_album)
        if metadata.album_cover_bytes is not None:
            self.setIcon(QIcon(get_pixmap(metadata.album_cover_bytes)))
        if height_linewidth is not None:
            height = height_linewidth[0] - height_linewidth[1] * 2
            button_size = QSize(height, height)
            self.setFixedSize(button_size)
            self.setIconSize(button_size)
