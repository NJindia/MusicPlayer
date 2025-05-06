from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QScrollArea,
    QGraphicsView,
    QGraphicsScene,
    QSizePolicy,
    QGraphicsProxyWidget,
)

from music_downloader.album import AlbumButton
from music_downloader.common import HoverableUnderlineLabel
from music_downloader.constants import (
    QUEUE_ENTRY_HEIGHT,
    QUEUE_ENTRY_WIDTH,
    QUEUE_ENTRY_SPACING,
    QUEUE_WIDTH,
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
        self.core = core
        self.media_list_index = media_list_index
        metadata = self.core.music_list[self.media_list_index]

        song_album_layout = QVBoxLayout()
        song_label = HoverableUnderlineLabel(metadata.title, self)
        song_label.clicked.connect(lambda _: self.core.play_jump_to_index(self.media_list_index))

        artists_text_browser = HoverableUnderlineLabel(",".join(metadata.artists), self)
        artists_text_browser.clicked.connect(lambda _: print("TODO Go to artist"))

        song_album_layout.addWidget(song_label)
        song_album_layout.addWidget(artists_text_browser)

        layout.addWidget(AlbumButton(metadata, self))
        layout.addLayout(song_album_layout)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.core.play_jump_to_index(self.media_list_index)
        super().mouseDoubleClickEvent(event)


class GraphicsViewSection(QGraphicsView):
    @property
    def current_entries(self):
        return [self.queue_entries[i] for i in self.queue_indices[self.current_queue_index :]]

    @property
    def past_entries(self):
        return [self.queue_entries[i] for i in self.queue_indices[: self.current_queue_index]]

    def update_scene(self, from_index: int = 0):
        for i, proxy in enumerate(
            self.current_entries[from_index:],
            start=from_index,
        ):
            proxy.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))
        assert all(e in self.scene().items() for e in self.current_entries)
        self.setSceneRect(0, 0, self.width(), self.get_y_pos(len(self.scene().items())))  # Update scene size

    def update_first_queue_index(self, queue_index: int) -> None:
        self.current_queue_index = queue_index
        scene_items = self.scene().items()
        for proxy in self.past_entries:
            if proxy.scene():
                self.scene().removeItem(proxy)
        first_proxy = (
            self.queue_entries[self.queue_indices[self.current_queue_index]]
            if self.current_queue_index < len(self.queue_indices)
            else None
        )
        if first_proxy and first_proxy not in scene_items:
            self.scene().addItem(first_proxy)
        self.update_scene()

    def insert_queue_entry(self, queue_index: int, entry: QueueEntry) -> None:
        assert queue_index > self.current_queue_index, "Can't insert queue entry before current queue index"
        self.queue_entries.append(self.scene().addWidget(entry))
        for i, idx in enumerate(self.queue_indices):
            if idx >= queue_index:
                self.queue_indices[i] = idx + 1
        self.queue_indices.insert(queue_index, len(self.queue_entries) - 1)
        assert len(self.queue_indices) == len(self.queue_entries)

        self.update_scene(queue_index)

    @staticmethod
    def get_y_pos(index: int) -> float:
        return QUEUE_ENTRY_SPACING + index * (QUEUE_ENTRY_SPACING + QUEUE_ENTRY_HEIGHT)

    def __init__(self, vlc_core: VLCCore, *, empty: bool = False):
        super().__init__()
        self.setScene(QGraphicsScene())
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFixedWidth(QUEUE_WIDTH)
        self.queue_entries: list[QGraphicsProxyWidget] = []
        self.current_queue_index = 0
        self.core = vlc_core

        if not empty:
            for i in range(len(self.core.music_list)):
                proxy = self.scene().addWidget(QueueEntry(self.core, i))
                proxy.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))
                self.queue_entries.append(proxy)

        self.queue_indices: list[int] = list(range(len(self.queue_entries)))
