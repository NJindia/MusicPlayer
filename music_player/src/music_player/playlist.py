import json
from dataclasses import dataclass
from datetime import datetime, UTC
from functools import cache
from pathlib import Path

import dacite
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QPixmapCache
from dacite import Config

from music_player.music_importer import get_music_df
from music_player.utils import get_pixmap


@dataclass
class PlaylistItem:
    song_index: int
    added_on: datetime

    def to_json(self):
        return {"song_index": self.song_index, "added_on": self.added_on.isoformat()}


@cache
def empty_playlist_pixmap(height: int) -> QPixmap:
    return QPixmap("../icons/empty-playlist.svg").scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)


@dataclass(kw_only=True)
class Playlist:
    title: str
    created: datetime
    last_updated: datetime
    last_played: datetime | None
    playlist_items: list[PlaylistItem]
    playlist_path: Path
    thumbnail: bytes | None

    def get_thumbnail_pixmap(self, height: int) -> QPixmap:
        if self.thumbnail is None:
            return self.get_default_thumbnail(height)
        return get_pixmap(self.thumbnail, height)

    def get_default_thumbnail(self, height: int) -> QPixmap:
        album_covers = self.dataframe["album_cover_bytes"]
        covers = album_covers.value_counts().index[:4]
        if len(covers) == 0:
            return empty_playlist_pixmap(height)

        combined_pixmap = QPixmap()
        key = f"{b''.join(covers)}_{height}"
        if QPixmapCache.find(key, combined_pixmap):
            return combined_pixmap

        # TODO REMOVE OLD KEY
        pixmaps = [get_pixmap(cover, None) for cover in covers]
        if len(pixmaps) != 4:
            combined_pixmap = pixmaps[0]
        else:
            assert len({pm.size() for pm in pixmaps}) == 1, {pm.size() for pm in pixmaps}
            pm_size = pixmaps[0].size()
            combined_pixmap = QPixmap(pm_size * 2)

            painter = QPainter(combined_pixmap)
            for i, (w, h) in enumerate(
                [(0, 0), (pm_size.width(), 0), (0, pm_size.height()), (pm_size.width(), pm_size.height())]
            ):
                painter.drawPixmap(w, h, pixmaps[i])
            painter.end()

        combined_pixmap = combined_pixmap.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
        QPixmapCache.insert(key, combined_pixmap)
        return combined_pixmap

    @property
    def indices(self) -> list[int]:
        return [i.song_index for i in self.playlist_items]

    @property
    def dataframe(self) -> pd.DataFrame:
        return get_music_df().iloc[self.indices]

    def to_json(self):
        return {
            "title": self.title,
            "created": self.created.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "last_played": self.last_played.isoformat() if self.last_played else None,
            "playlist_items": [i.to_json() for i in self.playlist_items],
            "thumbnail": self.thumbnail,
        }

    def save(self):
        print(f"SPLAYLIST: {self}")
        with self.playlist_path.open("w") as file:
            json.dump(self.to_json(), file)

    def remove_items(self, item_indices: list[int]):
        self.playlist_items = [item for i, item in enumerate(self.playlist_items) if i not in item_indices]
        self.save()

    def add_item(self, music_df_idx: int):
        self.playlist_items.insert(0, PlaylistItem(music_df_idx, datetime.now(tz=UTC)))
        print(f"PLAYLIST: {self}")
        self.save()


@cache
def get_playlist(playlist_path: Path) -> Playlist:
    with playlist_path.open("r") as f:
        return dacite.from_dict(
            Playlist,
            {"playlist_path": playlist_path, **json.load(f)},
            config=Config(type_hooks={datetime: lambda d: datetime.fromisoformat(d)}),
        )
