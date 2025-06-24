from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from functools import cache, cached_property
from itertools import groupby
from pathlib import Path
from typing import Literal, Optional, TypeVar

from line_profiler_pycharm import profile
from psycopg2.extras import RealDictRow
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap, QPixmapCache

from music_player.database import get_database_manager
from music_player.utils import get_colored_pixmap, get_pixmap

CollectionType = Literal["folder", "playlist", "artist", "album"]
INSERT_COLLECTION_SQL = """
INSERT INTO collections
(parent_collection_id, type, name, created, last_updated, last_played, thumbnail, protected)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
RETURNING collection_id;
"""
UPDATE_COLLECTION_SQL = """
UPDATE collections
SET (parent_collection_id, type, name, created, last_updated, last_played, thumbnail, protected)
        = (%s, %s, %s, %s, %s, %s, %s, %s)
WHERE collection_id = %s;
"""


@dataclass
class DbBase(ABC):
    id: int
    name: str
    collection_type: CollectionType
    is_protected: bool

    def __post_init__(self):
        assert self.id != ""
        assert self.name != ""

    @classmethod
    @abstractmethod
    def from_db(cls, db_id: int) -> "DbBase":
        pass

    @abstractmethod
    @cached_property
    def music_ids(self) -> tuple[int, ...]:
        pass


@dataclass  # (frozen=True)
class DbArtist(DbBase):
    img: bytes | None

    @classmethod
    def from_db(cls, db_id: int) -> "DbArtist":
        row = get_database_manager().get_row("SELECT * FROM artists WHERE artist_id = %s", (db_id,))
        return cls(
            id=row["artist_id"],
            name=row["artist_name"],
            img=bytes(row["artist_img"]) if row["artist_img"] else None,
            collection_type="artist",
            is_protected=True,
        )

    @cached_property
    def music_ids(self) -> tuple[int, ...]:
        query = "SELECT music_id FROM music_artists WHERE artist_id = %s ORDER BY sort_order"
        return tuple(row["music_id"] for row in get_database_manager().get_rows(query, (self.id,)))


@dataclass  # (frozen=True)
class DbAlbum(DbBase):
    release_date: str
    cover_bytes: bytes

    @classmethod
    def from_db(cls, db_id: int) -> "DbAlbum":
        row = get_database_manager().get_row("SELECT * FROM albums WHERE album_id = %s", (db_id,))
        return cls(
            id=row["album_id"],
            name=row["album_name"],
            release_date=row["release_date"],
            cover_bytes=bytes(row["cover_bytes"]),
            collection_type="album",
            is_protected=True,
        )

    @property
    def artists(self) -> list[DbArtist]:
        raise NotImplementedError

    @cached_property
    def music_ids(self) -> tuple[int, ...]:
        query = "SELECT music_id FROM music WHERE album_id = %s"
        return tuple(row["music_ids"] for row in get_database_manager().get_rows(query, (self.id,)))


@dataclass(kw_only=True)
class DbCollection(DbBase):
    _parent_id: int
    _created: datetime
    _last_updated: datetime
    _last_played: datetime | None
    _thumbnail: bytes | None

    @cached_property
    def music_ids(self) -> tuple[int, ...]:
        match self.collection_type:
            case "folder":

                def traverse(parent_collection_id: int) -> Iterator[int]:
                    for collection in get_collections_by_parent_id().get(parent_collection_id, []):
                        if collection.is_folder:
                            yield from traverse(collection.id)
                        yield from collection.music_ids

                return tuple(traverse(self.id))
            case "playlist":
                music = get_database_manager().get_rows(
                    "SELECT music_id FROM collection_children WHERE collection_id = %s", (self.id,)
                )
                return tuple(row["music_id"] for row in music)
        raise ValueError

    @classmethod
    def from_db(cls, db_id: int = 1) -> "DbCollection":
        row = get_database_manager().get_row("SELECT * FROM collections WHERE collection_id = %s", (db_id,))
        return cls.from_db_row(row)

    @classmethod
    def from_db_row(cls, db_row: RealDictRow) -> "DbCollection":
        return cls(
            id=db_row["collection_id"],
            name=db_row["name"],
            collection_type=db_row["type"],
            is_protected=db_row["protected"],
            _parent_id=db_row["parent_collection_id"],
            _created=db_row["created"],
            _last_updated=db_row["last_updated"],
            _last_played=db_row["last_played"],
            _thumbnail=db_row["thumbnail"],
        )

    @property
    def parent_id(self) -> int:
        return self._parent_id

    @property
    def created(self) -> datetime:
        return self._created

    @property
    def last_updated(self) -> datetime:
        return self._last_updated

    @property
    def last_played(self) -> datetime | None:
        return self._last_played

    @property
    def thumbnail(self) -> bytes | None:
        return self._thumbnail

    def delete(self):
        assert not self.is_protected
        get_database_manager().execute_query("DELETE FROM collections WHERE collection_id = %s", (self.id,))

    def save(self) -> Optional["DbCollection"]:
        if self.id == -1:
            row = get_database_manager().get_row(
                INSERT_COLLECTION_SQL,
                (
                    self.parent_id,
                    self.collection_type,
                    self.name,
                    self.created,
                    self.last_updated,
                    self.last_played,
                    self.thumbnail,
                    self.is_protected,
                ),
                commit=True,
            )
            self.id = row["collection_id"]
        get_database_manager().execute_query(
            UPDATE_COLLECTION_SQL,
            (
                self.parent_id,
                self.collection_type,
                self.name,
                self.created,
                self.last_updated,
                self.last_played,
                self.thumbnail,
                self.is_protected,
                self.id,
            ),
        )

    def mark_as_played(self):
        self._last_played = datetime.now(tz=UTC)
        update_query = "UPDATE collections SET last_played = %s WHERE collection_id = %s"
        get_database_manager().execute_query(update_query, (self.last_played, self.id))

    def mark_as_updated(self):
        self._last_updated = datetime.now(tz=UTC)
        update_query = "UPDATE collections SET last_updated = %s WHERE collection_id = %s"
        get_database_manager().execute_query(update_query, (self.last_updated, self.id))

    def add_music_ids(self, music_ids: tuple[int, ...]) -> None:
        assert self.collection_type == "playlist"
        add_music_id_sql = "INSERT INTO collection_children (collection_id, music_id, added_on) VALUES %s"
        args = [(self.id, music_id, datetime.now(tz=UTC)) for music_id in music_ids]
        get_database_manager().execute_values(add_music_id_sql, args)
        self.mark_as_updated()
        self.cache_clear()

    def remove_music_ids(self, music_ids: tuple[int, ...]) -> None:
        assert self.collection_type == "playlist"
        delete_music_id_sql = "DELETE FROM collection_children WHERE collection_id = %s AND music_id IN %s"
        get_database_manager().execute_query(delete_music_id_sql, (self.id, music_ids))
        self.mark_as_updated()
        self.cache_clear()

    def cache_clear(self):
        self._get_default_playlist_thumbnail.cache_clear()
        try:
            del self.music_ids
        except AttributeError:
            pass

    @staticmethod
    @cache
    @profile
    def _get_default_playlist_thumbnail(music_ids: list[int], height: int) -> QPixmap:
        print("thumbnail")
        if len(music_ids) == 0:
            return _empty_playlist_pixmap(height)
        a_rows = get_database_manager().get_rows("SELECT album_id FROM music WHERE music_id IN %s", (music_ids,))
        album_ids = [r["album_id"] for r in a_rows]
        if len(album_ids) == 0:
            return _empty_playlist_pixmap(height)
        cover_album_ids = tuple(v[0] for v in Counter(album_ids).most_common(4))
        c_rows = get_database_manager().get_rows(
            "SELECT cover_bytes from albums WHERE album_id IN %s", (cover_album_ids,)
        )
        covers = [r.tobytes() for r in [_r["cover_bytes"] for _r in c_rows] if r]

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

    def get_thumbnail_pixmap(self, height: int) -> QPixmap:
        match self.collection_type:
            case "playlist":
                if self.is_protected:
                    return _get_downloaded_songs_playlist_pixmap(height)
                if self.thumbnail is None:
                    return self._get_default_playlist_thumbnail(self.music_ids, height)
                return get_pixmap(self.thumbnail, height)
            case "folder":
                return _get_folder_pixmap(height)
            case _:
                raise NotImplementedError

    @cached_property  # This shouldn't be able to change so this is fine
    def is_folder(self) -> bool:
        return self.collection_type == "folder"


T = TypeVar("T", bound=DbCollection)


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


@cache
def get_collections_by_parent_id() -> dict[int, list[DbCollection]]:
    collections = get_collections()

    def parent_key(collection: DbCollection) -> int:
        return collection.parent_id

    return {k: list(v) for k, v in groupby(sorted(collections, key=parent_key), key=parent_key)}


def get_collections() -> list[DbCollection]:
    return [DbCollection.from_db_row(row) for row in get_database_manager().get_rows("SELECT * FROM collections")]


@dataclass(frozen=True)
class DbMusic:
    id: int
    name: str
    album_id: int
    album_name: str
    lyrics_by_timestamp: dict[time, str]
    release_date: date
    duration: float
    isrc: str
    file_path: Path
    downloaded_on: datetime
    cover_bytes: bytes | None
    artist_ids: list[int]
    artists: list[str]

    @classmethod
    @cache
    @profile
    def from_db(cls, music_id: int) -> "DbMusic":
        return get_db_music_cache().get(music_id)

    # @cached_property
    # def artist_ids(self) -> list[int]:
    #     artist_id_query = "SELECT artist_id FROM music_artists WHERE music_id = %s ORDER BY sort_order"
    #     return [r["artist_id"] for r in get_database_manager().get_rows(artist_id_query, (self.id,))]
    #
    # @cached_property
    # def artists(self) -> list[str]:
    #     artist_name_query = "SELECT artist_name FROM artists WHERE artist_id IN %s"
    #     return [r["artist_name"] for r in get_database_manager().get_rows(artist_name_query, (tuple(self.artist_ids),))]


class _DbMusicCache:
    def __init__(self):
        self._music_by_id = {
            row["music_id"]: DbMusic(
                id=row["music_id"],
                name=row["music_name"],
                album_id=row["album_id"],
                album_name=row["album_name"],
                lyrics_by_timestamp=row["lyrics_by_timestamp"],
                release_date=row["release_date"],
                duration=row["duration"],
                isrc=row["isrc"],
                file_path=Path(row["file_path"]),
                downloaded_on=row["downloaded_on"],
                cover_bytes=None if row["cover_bytes"] is None else bytes(row["cover_bytes"]),
            )
            for row in get_database_manager().get_rows("SELECT * FROM library_music_view")
        }

    @profile
    def get(self, music_id: int) -> DbMusic:
        if music_id not in self._music_by_id:
            self._music_by_id[music_id] = DbMusic.from_db(music_id)
        return self._music_by_id[music_id]


@cache
@profile
def get_db_music_cache() -> _DbMusicCache:
    return _DbMusicCache()
