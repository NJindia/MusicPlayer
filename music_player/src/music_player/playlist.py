import json
from abc import abstractmethod
from dataclasses import dataclass
from datetime import datetime, UTC
from functools import cache
from itertools import groupby
from pathlib import Path
from typing import TypeVar, Type, Iterator

import dacite
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QPixmapCache
from dacite import Config
from typing_extensions import override

from music_player.music_importer import get_music_df
from music_player.utils import get_pixmap, get_colored_pixmap

DEFAULT_PLAYLIST_PATH = Path("../playlists")
DOWNLOADED_SONGS_PLAYLIST_PATH = Path("../playlists/_.json")


@dataclass
class PlaylistItem:
    song_index: int
    added_on: datetime

    def to_json(self):
        return {"song_index": self.song_index, "added_on": self.added_on.isoformat()}


@cache
def _empty_playlist_pixmap(height: int) -> QPixmap:
    return QPixmap("../icons/playlist/empty-playlist.svg").scaledToHeight(
        height, Qt.TransformationMode.SmoothTransformation
    )


@cache
def _get_folder_pixmap(height: int) -> QPixmap:
    return QPixmap("../icons/playlist/folder.svg").scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)


@cache
def _get_downloaded_songs_playlist_pixmap(height: int) -> QPixmap:
    return get_colored_pixmap(QPixmap("../icons/playlist/downloaded_songs.svg"), Qt.GlobalColor.black).scaledToHeight(
        height, Qt.TransformationMode.SmoothTransformation
    )


@dataclass(kw_only=True)
class CollectionBase:
    id: str
    parent_id: str
    title: str
    created: datetime
    last_updated: datetime
    last_played: datetime | None
    thumbnail: bytes | None

    def __post_init__(self):
        assert self.id != ""
        assert self.title != ""

    @property
    def _playlist_path(self) -> Path:
        return DEFAULT_PLAYLIST_PATH / f"{self.id}.json"

    def to_json(self):
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "title": self.title,
            "created": self.created.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "last_played": self.last_played.isoformat() if self.last_played else None,
            "thumbnail": self.thumbnail,
        }

    def save(self):
        print(f"SPLAYLIST: {self}")
        with self._playlist_path.open("w") as file:
            json.dump(self.to_json(), file)

    def delete(self):
        self._playlist_path.unlink()

    @abstractmethod
    def get_thumbnail_pixmap(self, height: int) -> QPixmap:
        pass

    @property
    @abstractmethod
    def indices(self) -> list[int]:
        pass

    @property
    def is_folder(self) -> bool:
        return self.id[0] == "f"

    @property
    def is_protected(self) -> bool:
        return self.id == "_"


@dataclass(kw_only=True)
class Playlist(CollectionBase):
    playlist_items: list[PlaylistItem]

    @override
    def to_json(self):
        return {"playlist_items": [i.to_json() for i in self.playlist_items], **super().to_json()}

    @override
    def get_thumbnail_pixmap(self, height: int) -> QPixmap:
        if self.is_protected:
            return _get_downloaded_songs_playlist_pixmap(height)
        if self.thumbnail is None:
            return self.get_default_thumbnail(height)
        return get_pixmap(self.thumbnail, height)

    def remove_items(self, item_indices: list[int]):
        self.playlist_items = [item for i, item in enumerate(self.playlist_items) if i not in item_indices]
        self.save()

    def add_items(self, music_df_indices: list[int]):
        self.playlist_items = [
            PlaylistItem(df_idx, datetime.now(tz=UTC)) for df_idx in music_df_indices
        ] + self.playlist_items
        print(f"PLAYLIST: {self}")
        self.save()

    @property
    def indices(self) -> list[int]:
        return [i.song_index for i in self.playlist_items]

    @property
    def dataframe(self) -> pd.DataFrame:
        return get_music_df().iloc[self.indices]

    def get_default_thumbnail(self, height: int) -> QPixmap:
        album_covers = self.dataframe["album_cover_bytes"]
        covers = album_covers.value_counts().index[:4]
        if len(covers) == 0:
            return _empty_playlist_pixmap(height)

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


@dataclass(kw_only=True)
class Folder(CollectionBase):
    @override
    def get_thumbnail_pixmap(self, height: int) -> QPixmap:
        return _get_folder_pixmap(height)

    @property
    @override
    def indices(self) -> list[int]:
        def traverse(parent_collection_id: str) -> Iterator[int]:
            for collection in get_collections_by_parent_id().get(parent_collection_id, []):
                if collection.is_folder:
                    yield from traverse(collection.id)
                yield from collection.indices

        return list(traverse(self.id))


T = TypeVar("T", bound=CollectionBase)


# TODO CACHE THIS OR SOMETHING IDK
def _get_collection(path: Path, collection_type: Type[T]) -> T:
    with path.open("r") as f:
        return dacite.from_dict(
            collection_type,
            json.load(f),
            config=Config(type_hooks={datetime: lambda d: datetime.fromisoformat(d)}),
        )


def get_folder(folder_path: Path) -> Folder:
    return _get_collection(folder_path, Folder)


def get_playlist(playlist_path: Path) -> Playlist:
    return _get_collection(playlist_path, Playlist)


@cache
def get_collections_by_parent_id() -> dict[str, list[Folder | Playlist]]:
    collections: list[Folder | Playlist] = []
    for file in DEFAULT_PLAYLIST_PATH.iterdir():
        if file.stem[0] == "f":
            collections.append(get_folder(file))
        elif file.stem[0] in ["p", "_"]:
            collections.append(get_playlist(file))
        else:
            raise ValueError

    def parent_key(collection: CollectionBase) -> str:
        return collection.parent_id

    return {k: list(v) for k, v in groupby(sorted(collections, key=parent_key), key=parent_key)}
