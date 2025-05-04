from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QWidget, QHBoxLayout, QVBoxLayout, QScrollArea

from music_downloader.album import AlbumButton
from music_downloader.common import HoverableUnderlineLabel
from music_downloader.constants import (
    QUEUE_ENTRY_HEIGHT,
    QUEUE_ENTRY_WIDTH,
    QUEUE_ENTRY_SPACING,
)
from music_downloader.vlc_core import VLCCore


class ScrollableLayout(QScrollArea):
    def __init__(self, layout: QVBoxLayout) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_widget.setLayout(layout)
        self.setWidget(scroll_widget)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)


class QueueEntry(QFrame):
    def __init__(self, core: VLCCore, media_list_index: int):
        super().__init__()
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation, False)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Plain)
        self.setFixedSize(QUEUE_ENTRY_WIDTH, QUEUE_ENTRY_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setLineWidth(QUEUE_ENTRY_SPACING)
        self.setStyleSheet("""
                    QFrame {
                        background-color: #1b4af5;
                        border-radius: 4px;
                    }
                    QFrame:hover {
                        background-color: #e6e6f0;
                    }
                """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            QUEUE_ENTRY_SPACING,
            QUEUE_ENTRY_SPACING,
            QUEUE_ENTRY_SPACING,
            QUEUE_ENTRY_SPACING,
        )
        metadata = core.music_list[media_list_index]

        song_album_layout = QVBoxLayout(self)
        song_label = HoverableUnderlineLabel(metadata.title, self)
        song_label.clicked.connect(
            lambda _: core.list_player.play_item_at_index(media_list_index)
        )

        artists_text_browser = HoverableUnderlineLabel(",".join(metadata.artists), self)
        artists_text_browser.clicked.connect(lambda _: print("TODO Go to artist"))

        song_album_layout.addWidget(song_label)
        song_album_layout.addWidget(artists_text_browser)

        layout.addWidget(AlbumButton(metadata, self))
        layout.addLayout(song_album_layout)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            print("clicked!")
        super().mouseDoubleClickEvent(event)


class Queue(QVBoxLayout):
    def update_first_queue_index(self, index: int) -> QWidget | None:
        for widget in (w for w in self.queue_entries[:index] if w.parent()):
            widget.setParent(None)
        first_widget = (
            self.queue_entries[index] if index < len(self.queue_entries) else None
        )
        if (
            first_widget and first_widget.parent() is None
        ):  # If going to previous track, parent() will be None
            self.insertWidget(0, first_widget)
        return first_widget

    def __init__(self, queue_widgets: list[QueueEntry] | None = None) -> None:
        super().__init__()
        self.queue_entries = queue_widgets if queue_widgets else []
        for widget in self.queue_entries:
            self.addWidget(widget)
        self.addStretch()
