from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from functools import cache, cached_property
from itertools import groupby
from pathlib import Path
from typing import Literal, TypeVar

from line_profiler_pycharm import profile  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from psycopg2.extras import RealDictRow
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap, QPixmapCache

from music_player.database import PATH_TO_IMGS, get_database_manager
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


@dataclass(eq=False)
class DbCollection(ABC):
    _id: int
    _name: str
    _collection_type: CollectionType
    _is_protected: bool
    _img_path: Path | None
    _music_ids: tuple[int, ...]

    def __post_init__(self):
        assert self._id != ""
        assert self._name != ""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DbCollection):
            return self.id == other.id
        return False

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def collection_type(self) -> CollectionType:
        return self._collection_type

    @property
    def is_protected(self) -> bool:
        return self._is_protected

    @property
    def img_path(self) -> Path | None:
        return self._img_path

    @property
    def music_ids(self) -> tuple[int, ...]:
        return self._music_ids

    @classmethod
    @abstractmethod
    def from_db(cls, db_id: int) -> "DbCollection": ...


@dataclass(eq=False)
class DbArtist(DbCollection):
    @classmethod
    def from_db(cls, db_id: int) -> "DbArtist":
        query = """
        SELECT a.*, ARRAY_AGG(ma.music_id) AS music_ids
        FROM artists a
        JOIN music_artists ma USING (artist_id)
        WHERE artist_id = %s
        GROUP BY a.artist_id"""
        row = get_database_manager().get_row(query, (db_id,))
        return cls(
            _id=row["artist_id"],
            _name=row["artist_name"],
            _img_path=PATH_TO_IMGS / Path(row["artist_img"]) if row["artist_img"] else None,
            _collection_type="artist",
            _is_protected=True,
            _music_ids=tuple(row["music_ids"]),
        )


@dataclass(eq=False)
class DbAlbum(DbCollection):
    release_date: str

    @classmethod
    def from_db(cls, db_id: int) -> "DbAlbum":
        query = """
        SELECT a.*, ARRAY_AGG(m.music_id) AS music_ids
        FROM albums a
        JOIN music m USING (album_id)
        WHERE album_id = %s
        GROUP BY a.album_id"""
        row = get_database_manager().get_row(query, (db_id,))
        return cls(
            _id=row["album_id"],
            _name=row["album_name"],
            _img_path=PATH_TO_IMGS / Path(row["img_path"]) if row["img_path"] else None,
            _collection_type="album",
            _is_protected=True,
            release_date=row["release_date"],
            _music_ids=tuple(row["music_ids"]),
        )

    @property
    def artists(self) -> list[DbArtist]:
        raise NotImplementedError


collection_query = """
SELECT
    c.*,
    ARRAY_REMOVE(ARRAY_AGG(cc.music_id ORDER BY cc.sort_order DESC), NULL) as music_ids,
    ARRAY_REMOVE(ARRAY_AGG(cc.added_on ORDER BY cc.sort_order DESC), NULL) as added_on,
    ARRAY_REMOVE(ARRAY_AGG(m.album_id ORDER BY cc.sort_order DESC), NULL) as album_ids,
    ARRAY_REMOVE(ARRAY_AGG(a.img_path ORDER BY cc.sort_order DESC), NULL) as img_paths,
    ARRAY_REMOVE(ARRAY_AGG(-cc.sort_order ORDER BY cc.sort_order DESC), NULL) as sort_order
FROM collections c
LEFT JOIN collection_children cc USING (collection_id)
LEFT JOIN music m USING (music_id)
LEFT JOIN albums a USING (album_id)
WHERE (%(collectionId)s IS NULL) OR (c.collection_id = %(collectionId)s)
GROUP BY c.collection_id
"""


@dataclass(kw_only=True, eq=False)
class DbStoredCollection(DbCollection):
    _parent_id: int
    _created: datetime
    _last_updated: datetime
    _last_played: datetime | None
    _music_ids: tuple[int, ...]
    _music_added_on: list[datetime]
    _album_img_path_counter: Counter[Path]
    _sort_order: list[int]

    # def _music_ids(self) -> tuple[int, ...]:
    #     match self.collection_type:
    #         case "folder":
    #
    #             def traverse(parent_collection_id: int) -> Iterator[int]:
    #                 for collection in get_collections_by_parent_id().get(parent_collection_id, []):
    #                     if collection.is_folder:
    #                         yield from traverse(collection.id)
    #                     yield from collection.music_ids
    #
    #             return tuple(traverse(self.id))
    #     raise ValueError

    @classmethod
    def from_db(cls, db_id: int = 1) -> "DbStoredCollection":
        row = get_database_manager().get_row_k(collection_query, collectionId=db_id)
        return cls.from_db_row(row)

    @classmethod
    def from_db_row(cls, db_row: RealDictRow) -> "DbStoredCollection":
        return cls(
            _id=db_row["collection_id"],
            _name=db_row["name"],
            _collection_type=db_row["type"],
            _is_protected=db_row["protected"],
            _img_path=db_row["thumbnail"],
            _parent_id=db_row["parent_collection_id"],
            _created=db_row["created"],
            _last_updated=db_row["last_updated"],
            _last_played=db_row["last_played"],
            _music_ids=tuple(db_row["music_ids"]),
            _music_added_on=db_row["added_on"],
            _album_img_path_counter=Counter(PATH_TO_IMGS / Path(p) for p in db_row["img_paths"] if p is not None),
            _sort_order=db_row["sort_order"],
        )

    @property
    def music_ids(self) -> tuple[int, ...]:
        return self._music_ids

    @property
    def parent_id(self) -> int:
        return self._parent_id

    @parent_id.setter
    def parent_id(self, parent_id: int) -> None:
        self._parent_id = parent_id
        self.save()

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
    def thumbnail_path(self) -> Path | None:
        return self.img_path

    def rename(self, name: str):
        self._name = name
        self.save()

    def delete(self):
        assert not self.is_protected
        get_database_manager().execute_query("DELETE FROM collections WHERE collection_id = %s", (self.id,))

    def save(self):
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
                    self.thumbnail_path,
                    self.is_protected,
                ),
                commit=True,
            )
            self._id = row["collection_id"]
        else:
            get_database_manager().execute_query(
                UPDATE_COLLECTION_SQL,
                (
                    self.parent_id,
                    self.collection_type,
                    self.name,
                    self.created,
                    self.last_updated,
                    self.last_played,
                    self.thumbnail_path,
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

    @profile
    def add_music_ids(self, music_ids: Sequence[int]) -> None:
        assert self.collection_type == "playlist"
        added_on = datetime.now(tz=UTC)
        self._music_ids = tuple(music_ids) + self._music_ids
        self._music_added_on = [added_on] * len(music_ids) + self._music_added_on
        music = [get_db_music_cache().get(i) for i in music_ids]
        self._album_img_path_counter += Counter(m.img_path for m in music if m.img_path is not None)

        add_music_id_sql = "INSERT INTO collection_children (collection_id, music_id, added_on) VALUES %s"
        args = [(self.id, music_id, added_on) for music_id in reversed(music_ids)]
        get_database_manager().execute_values(add_music_id_sql, args)
        self.mark_as_updated()

    def remove_music_ids(self, music_ids: tuple[int, ...]) -> None:
        assert self.collection_type == "playlist"
        delete_music_id_sql = "DELETE FROM collection_children WHERE collection_id = %s AND music_id IN %s"
        get_database_manager().execute_query(delete_music_id_sql, (self.id, music_ids))
        self.mark_as_updated()

    @profile
    def _get_default_playlist_thumbnail(self, height: int) -> QPixmap:
        if not self._album_img_path_counter:
            return _empty_playlist_pixmap(height)

        most_common_paths = [c[0] for c in self._album_img_path_counter.most_common(4)]

        combined_pixmap = QPixmap()
        key = "_".join((*(str(p) for p in most_common_paths), f"h{height}"))
        if QPixmapCache.find(key, combined_pixmap):
            return combined_pixmap

        # TODO REMOVE OLD KEY
        pixmaps = [get_pixmap(path, None) for path in most_common_paths]
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
        key = f"collection_{self.id}_{height}"
        pixmap = QPixmap()
        if QPixmapCache.find(key, pixmap):
            return pixmap
        match self.collection_type:
            case "playlist":
                if self.is_protected:
                    pixmap = get_colored_pixmap(
                        QPixmap("../icons/playlist/downloaded_songs.svg"), Qt.GlobalColor.black
                    ).scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
                else:
                    pixmap = (
                        self._get_default_playlist_thumbnail(height)
                        if self.thumbnail_path is None
                        else get_pixmap(self.thumbnail_path, height)
                    )
                QPixmapCache.insert(key, pixmap)
                return pixmap
            case "folder":
                return _get_folder_pixmap(height)
            case _:
                raise NotImplementedError

    @cached_property  # This shouldn't be able to change so this is fine
    def is_folder(self) -> bool:
        return self.collection_type == "folder"


T = TypeVar("T", bound=DbStoredCollection)


@cache
def _empty_playlist_pixmap(height: int) -> QPixmap:
    return QPixmap("../icons/playlist/empty-playlist.svg").scaledToHeight(
        height, Qt.TransformationMode.SmoothTransformation
    )


@cache
def _get_folder_pixmap(height: int) -> QPixmap:
    return QPixmap("../icons/playlist/folder.svg").scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)


@cache
def get_collections_by_parent_id() -> dict[int, list[DbStoredCollection]]:
    collections = [
        DbStoredCollection.from_db_row(row)
        for row in get_database_manager().get_rows_k(collection_query, collectionId=None)
    ]

    def parent_key(collection: DbStoredCollection) -> int:
        return collection.parent_id

    return {k: list(v) for k, v in groupby(sorted(collections, key=parent_key), key=parent_key)}


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
    img_path: Path | None
    artist_ids: list[int]
    artists: list[str]

    @classmethod
    def from_db_rows(cls, rows: list[RealDictRow]) -> "DbMusic":
        row = rows[0]
        return DbMusic(
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
            img_path=None if row["img_path"] is None else PATH_TO_IMGS / Path(row["img_path"]),
            artist_ids=[r["artist_id"] for r in rows],
            artists=[r["artist_name"] for r in rows],
        )

    @classmethod
    def from_db(cls, music_id: int) -> "DbMusic":
        query = "SELECT * FROM music_view WHERE music_id = %s ORDER BY (music_id, artist_order)"  # TODO ARRAY_AGG
        rows = get_database_manager().get_rows(query, (music_id,))
        return DbMusic.from_db_rows(rows)


class _DbMusicCache:
    def __init__(self):
        self._music_by_id: dict[int, DbMusic] = {}
        rows = get_database_manager().get_rows("SELECT * FROM music_view ORDER BY (music_id, artist_order)")
        rows_by_music_id = {k: list(v) for k, v in groupby(rows, key=lambda r: r["music_id"])}
        for music_id, rows in rows_by_music_id.items():
            self._music_by_id[music_id] = DbMusic.from_db_rows(rows)

    @profile
    def get(self, music_id: int) -> DbMusic:
        if music_id not in self._music_by_id:
            self._music_by_id[music_id] = DbMusic.from_db(music_id)
        return self._music_by_id[music_id]


@cache
def get_db_music_cache() -> _DbMusicCache:
    return _DbMusicCache()
