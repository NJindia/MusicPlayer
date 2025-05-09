from functools import partial

from PySide6.QtCore import Qt, Slot
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
from typing_extensions import override

from music_downloader.album import AlbumButton
from music_downloader.common import HoverableUnderlineLabel
from music_downloader.constants import (
    QUEUE_ENTRY_HEIGHT,
    QUEUE_ENTRY_WIDTH,
    QUEUE_ENTRY_SPACING,
    QUEUE_WIDTH,
)
from music_downloader.music import Music
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
    def __init__(self, metadata: Music):
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

        song_album_layout = QVBoxLayout()
        self.song_label = HoverableUnderlineLabel(metadata.title, self)

        artists_text_browser = HoverableUnderlineLabel(",".join(metadata.artists), self)
        artists_text_browser.clicked.connect(lambda _: print("TODO Go to artist"))

        song_album_layout.addWidget(self.song_label)
        song_album_layout.addWidget(artists_text_browser)

        layout.addWidget(AlbumButton(metadata, self, (self.height(), self.lineWidth())))
        layout.addLayout(song_album_layout)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.song_label.clicked.emit(event)
        super().mouseDoubleClickEvent(event)


class QueueEntryGraphicsView(QGraphicsView):
    @property
    def current_entries(self):
        return self.queue_entries

    def update_scene(self, from_index: int = 0):
        for i, proxy in enumerate(self.current_entries[from_index:], start=from_index):
            proxy.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))

        # TODO REMOVE BAD ENTRIES

        assert all(e in self.scene().items() for e in self.current_entries)
        self.setSceneRect(0, 0, self.width(), self.get_y_pos(len(self.scene().items())))  # Update scene size

    def insert_queue_entry(self, queue_index: int, entry: QueueEntry) -> None:
        self.queue_entries.insert(queue_index, self.scene().addWidget(entry))
        self.update_scene(queue_index)

    @staticmethod
    def get_y_pos(index: int) -> float:
        return QUEUE_ENTRY_SPACING + index * (QUEUE_ENTRY_SPACING + QUEUE_ENTRY_HEIGHT)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene())
        self.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFixedWidth(QUEUE_WIDTH)
        self.queue_entries: list[QGraphicsProxyWidget] = []


class QueueGraphicsView(QueueEntryGraphicsView):
    def __init__(self, vlc_core: VLCCore):
        super().__init__()
        self.core = vlc_core
        for i, music_idx in enumerate(self.core.indices):
            qe = QueueEntry(self.core.music_list[music_idx])
            qe.song_label.clicked.connect(partial(self.play_song, qe))
            proxy = self.scene().addWidget(qe)

            proxy.setPos(QUEUE_ENTRY_SPACING, self.get_y_pos(i))
            self.queue_entries.append(proxy)

    @Slot(QueueEntry)
    def play_song(self, queue_entry: QueueEntry, _: QMouseEvent):
        queue_index = [p.widget() for p in self.ordered_entries].index(queue_entry)
        self.core.list_player.play_item_at_index(queue_index)
        # if self.queue_index is not None:
        #     self.core.play_jump_to_index(self.queue_index)
        # else:
        #     print("TODO: WIPE Q AND PLAY THIS SONG")

    @property
    def current_entries(self):
        return self.ordered_entries[self.core.current_media_idx + 1 :]

    @property
    def past_entries(self):
        return self.ordered_entries[: self.core.current_media_idx + 1]

    @property
    def ordered_entries(self):
        return [self.queue_entries[i] for i in self.core.indices]

    def update_first_queue_index(self) -> None:
        for proxy in self.past_entries:
            if proxy.scene():
                self.scene().removeItem(proxy)
        for proxy in self.current_entries:
            if not proxy.scene():
                self.scene().addItem(proxy)
        self.update_scene()

    @override
    def insert_queue_entry(self, queue_index: int, entry: QueueEntry) -> None:
        assert queue_index > self.core.current_media_idx, "Can't insert queue entry before current queue index"
        super().insert_queue_entry(queue_index, entry)
