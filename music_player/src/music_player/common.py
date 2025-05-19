import json
from dataclasses import dataclass
from datetime import datetime, UTC
from functools import cache
from pathlib import Path

import dacite
import pandas as pd
from dacite import Config

from music_player.music_importer import get_music_df


@dataclass
class PlaylistItem:
    song_index: int
    added_on: datetime

    def to_json(self):
        return {"song_index": self.song_index, "added_on": self.added_on.isoformat()}


@dataclass
class Playlist:
    title: str
    created: datetime | None
    last_played: datetime | None
    playlist_items: list[PlaylistItem]
    playlist_path: Path
    # thumbnail: QPixmap | None = None

    @property
    def indices(self) -> list[int]:
        return [i.song_index for i in self.playlist_items]

    @property
    def dataframe(self) -> pd.DataFrame:
        return get_music_df().iloc[self.indices]

    def to_json(self):
        return {
            "title": self.title,
            "last_played": self.last_played.isoformat() if self.last_played else None,
            "playlist_items": [i.to_json() for i in self.playlist_items],
        }

    def save(self):
        with self.playlist_path.open("w") as file:
            json.dump(self.to_json(), file)

    def remove_item(self, item_index: int):
        del self.playlist_items[item_index]
        self.save()

    def add_item(self, music_df_idx: int):
        self.playlist_items.insert(0, PlaylistItem(music_df_idx, datetime.now(tz=UTC)))
        self.save()


@cache
def get_playlist(playlist_path: Path) -> Playlist:
    with playlist_path.open("r") as f:
        return dacite.from_dict(
            Playlist,
            {"playlist_path": playlist_path, **json.load(f)},
            config=Config(type_hooks={datetime: lambda d: datetime.fromisoformat(d)}),
        )
