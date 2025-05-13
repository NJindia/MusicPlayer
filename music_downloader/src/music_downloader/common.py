import json
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from pathlib import Path

import dacite
import vlc
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget
from dacite import Config
from line_profiler_pycharm import profile

from music_downloader.music_importer import get_music_df


class HoverableUnderlineLabel(QLabel):
    clicked = Signal(QEvent)

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setMouseTracking(True)
        self.setText(text)

    def leaveEvent(self, event: QEvent | None) -> None:
        f = self.font()
        f.setUnderline(False)
        self.setFont(f)

    def enterEvent(self, event: QEvent | None) -> None:
        f = self.font()
        f.setUnderline(True)
        self.setFont(f)

    def mousePressEvent(self, event: QEvent | None) -> None:
        self.clicked.emit(event)


@dataclass
class PlaylistItem:
    song_index: int
    added_on: datetime

    def to_json(self):
        return {"song_index": self.song_index, "added_on": self.added_on.isoformat()}


@dataclass
class Playlist:
    title: str
    last_played: datetime | None
    playlist_items: list[PlaylistItem]
    # thumbnail: QPixmap | None = None

    @property
    def indices(self) -> list[int]:
        return [i.song_index for i in self.playlist_items]

    @profile
    def to_media_list(self, instance: vlc.Instance) -> vlc.MediaList:
        music_df = get_music_df().iloc[self.indices]
        return instance.media_list_new(music_df["file_path"].to_list())

    def to_json(self):
        return {
            "title": self.title,
            "last_played": self.last_played.isoformat() if self.last_played else None,
            "playlist_items": [i.to_json() for i in self.playlist_items],
        }


@cache
def get_playlist(playlist_path: Path) -> Playlist:
    with playlist_path.open("r") as f:
        return dacite.from_dict(
            Playlist,
            json.load(f),
            config=Config(type_hooks={datetime: lambda d: datetime.fromisoformat(d)}),
        )
