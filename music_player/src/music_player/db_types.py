from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from functools import cache, cached_property
from itertools import groupby
from pathlib import Path
from typing import Literal, TypeVar

from line_profiler_pycharm import profile  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from psycopg2.extras import RealDictRow
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap, QPixmapCache

from music_player.constants import MIN_DATETIME
from music_player.database import PATH_TO_IMGS, get_database_manager
from music_player.utils import get_pixmap
from music_player.view_types import CollectionTreeSortRole

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
            return type(self) is type(other) and self.id == other.id
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

update_field_recursive = """
WITH RECURSIVE hierarchy AS (
    SELECT collection_id
    FROM collections
    WHERE parent_collection_id = :id

    UNION ALL

    SELECT c.collection_id
    FROM collections c
    INNER JOIN hierarchy h ON c.parent_collection_id = h.collection_id
    WHERE c.parent_collection_id != -1
)
UPDATE collections SET last_played = %s
WHERE collection_id = %s OR collection_id IN (SELECT collection_id FROM hierarchy)"""


def get_folder_music_ids(folder_id: int, sort_role: CollectionTreeSortRole | None) -> tuple[int, ...]:
    return tuple(
        m_id
        for collection in get_recursive_children(folder_id, get_folders=False, sort_role=sort_role)
        for m_id in collection.music_ids
    )


@dataclass(kw_only=True, eq=False)
class DbStoredCollection(DbCollection):
    _parent_id: int
    _created: datetime
    _last_updated_actual: datetime
    _last_played: datetime | None
    _music_ids: tuple[int, ...]
    _music_added_on: list[datetime]
    _album_img_path_counter: Counter[Path]
    _last_updated: datetime | None = None
    _pixmap_heights: set[int] = field(default_factory=set[int])

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
            _last_updated=None,
            _last_updated_actual=db_row["last_updated"],
            _last_played=db_row["last_played"],
            _music_ids=tuple(db_row["music_ids"]),
            _music_added_on=db_row["added_on"],
            _album_img_path_counter=Counter(PATH_TO_IMGS / Path(p) for p in db_row["img_paths"] if p is not None),
        )

    @property
    def sort_order(self) -> list[int]:
        return list(range(len(self._music_ids)))

    @property
    def music_ids(self) -> tuple[int, ...]:
        return get_folder_music_ids(self.id, None) if self.collection_type == "folder" else self._music_ids

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
    def last_updated_db(self) -> datetime:
        return self._last_updated_actual

    @property
    @profile
    def last_updated(self) -> datetime:
        if self._last_updated is None:  # During initial setup
            self._last_updated = (
                max((self.last_updated_db, *(e.last_updated_db for e in get_recursive_children(self.id))))
                if self.collection_type == "folder"
                else self.last_updated_db
            )
        return self._last_updated

    @last_updated.setter
    def last_updated(self, last_updated: datetime) -> None:
        self._last_updated = last_updated

    def mark_as_updated(self):
        """Mark this collection as updated in the DB, and update the _last_updated of this collection and its parents"""
        self._last_updated = datetime.now(tz=UTC)

        for parent in get_recursive_parents(self):
            parent.last_updated = self._last_updated  # Current time will always be > old last_played, so no max needed

        update_query = "UPDATE collections SET last_updated = %s WHERE collection_id = %s"
        get_database_manager().execute_query(update_query, (self.last_updated, self.id))

    @property
    @profile
    def last_played(self) -> datetime:
        if self._last_played is None and self.collection_type == "folder":  # During initial setup
            self._last_played = max(  # Folders do not have last_played
                (c.last_played for c in get_recursive_children(self.id, get_folders=False)), default=MIN_DATETIME
            )
        return self._last_played or MIN_DATETIME

    @last_played.setter
    def last_played(self, last_played: datetime) -> None:
        self._last_played = last_played

    def mark_as_played(self):
        """If is playlist, set parents' _last_played, but only update this playlist in the DB.
        If is folder, also set _last_played of children collections and update any playlists' last_played in the DB.

        It should not be possible for a folder to have a last_played value."""
        self._last_played = datetime.now(tz=UTC)

        for parent in get_recursive_parents(self):
            parent.last_played = self._last_played  # Current time will always be > old last_played, so no max needed

        update_ids: list[tuple[int, datetime]]
        if self.is_folder:
            playlist_idx = 0
            update_ids = []
            for child in get_recursive_children(self.id, sort_role=CollectionTreeSortRole.PLAYED):
                child.last_played = self._last_played + timedelta(microseconds=playlist_idx)
                if not child.is_folder:
                    playlist_idx += 1
                    update_ids.append((child.id, child.last_played))
        else:
            update_ids = [(self.id, self._last_played)]

        update_query = (
            "UPDATE collections c SET last_played = t.last_played FROM "
            "(VALUES %s) AS t(id, last_played) WHERE c.collection_id = t.id"
        )
        get_database_manager().execute_values(update_query, update_ids)

    @property
    def thumbnail_path(self) -> Path | None:
        return self.img_path

    def rename(self, name: str):
        self._name = name
        self.save()
        self.mark_as_updated()

    def delete(self):
        assert not self.is_protected
        get_database_manager().execute_query("DELETE FROM collections WHERE collection_id = %s", (self.id,))
        get_db_stored_collection_cache().delete_collection(self.id)

    def save(self):
        if self.id == -1:
            row = get_database_manager().get_row(
                INSERT_COLLECTION_SQL,
                (
                    self.parent_id,
                    self.collection_type,
                    self.name,
                    self.created,
                    self._last_updated_actual,
                    self._last_played,
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
                    self._last_updated_actual,
                    self._last_played,
                    self.thumbnail_path,
                    self.is_protected,
                    self.id,
                ),
            )

    @profile
    def add_music_ids(self, music_ids: Sequence[int]) -> None:
        assert self.collection_type == "playlist"
        self._removed_cached_thumbnails()

        added_on = datetime.now(tz=UTC)
        self._music_ids = tuple(music_ids) + self._music_ids
        self._music_added_on = [added_on] * len(music_ids) + self._music_added_on
        music = [get_db_music_cache().get(i) for i in music_ids]
        self._album_img_path_counter += Counter(m.img_path for m in music if m.img_path is not None)

        add_music_id_sql = "INSERT INTO collection_children (collection_id, music_id, added_on) VALUES %s"
        args = [(self.id, music_id, added_on) for music_id in reversed(music_ids)]
        get_database_manager().execute_values(add_music_id_sql, args)
        self.mark_as_updated()

    def _removed_cached_thumbnails(self):
        for height in self._pixmap_heights:
            QPixmapCache.remove(self._get_thumbnail_pixmap_key(height))

    def remove_music_ids(self, music_ids: tuple[int, ...]) -> None:
        assert self.collection_type == "playlist"
        self._removed_cached_thumbnails()

        _music_ids: list[int] = []
        _music_added_ons: list[datetime] = []
        for idx, music_id in enumerate(self._music_ids):
            if music_id not in music_ids:
                _music_added_ons.append(self._music_added_on[idx])
                _music_ids.append(music_id)
        self._music_ids = tuple(_music_ids)
        self._music_added_on = _music_added_ons
        music = [get_db_music_cache().get(i) for i in music_ids]
        self._album_img_path_counter -= Counter(m.img_path for m in music if m.img_path is not None)

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

    def _get_thumbnail_pixmap_key(self, height: int) -> str:
        return f"collection_{self.id}_{height}"

    def get_thumbnail_pixmap(self, height: int) -> QPixmap:
        key = self._get_thumbnail_pixmap_key(height)
        pixmap = QPixmap()
        if QPixmapCache.find(key, pixmap):
            return pixmap
        self._pixmap_heights.add(height)
        match self.collection_type:
            case "playlist":
                if self.is_protected:
                    pixmap = get_pixmap(
                        Path("../icons/playlist/downloaded_songs.svg"), height, color=Qt.GlobalColor.black
                    )
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

    def get_sort_value(self, sort_role: CollectionTreeSortRole):
        match sort_role:
            case CollectionTreeSortRole.ALPHABETICAL:
                return self.name.lower() + self.name
            case CollectionTreeSortRole.UPDATED:
                return self.last_updated.timestamp()
            case CollectionTreeSortRole.PLAYED:
                return self.last_played.timestamp()
            case _:
                raise ValueError("Unknown sort role")


T = TypeVar("T", bound=DbStoredCollection)


@cache
def _empty_playlist_pixmap(height: int) -> QPixmap:
    return QPixmap("../icons/playlist/empty-playlist.svg").scaledToHeight(
        height, Qt.TransformationMode.SmoothTransformation
    )


@cache
def _get_folder_pixmap(height: int) -> QPixmap:
    return QPixmap("../icons/playlist/folder.svg").scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)


@profile
def get_collections_by_parent_id() -> dict[int, list[DbStoredCollection]]:
    def parent_key(collection: DbStoredCollection) -> int:
        return collection.parent_id

    collections = get_db_stored_collection_cache().collections
    return {k: list(v) for k, v in groupby(sorted(collections, key=parent_key), key=parent_key)}


def get_recursive_parents(collection: DbStoredCollection) -> Iterator[DbStoredCollection]:
    if collection.parent_id != -1:
        parent = get_db_stored_collection_cache().get(collection.parent_id)
        yield parent
        yield from get_recursive_parents(parent)


@profile
def get_recursive_children(
    parent_id: int,
    collections_by_parent_id: dict[int, list[DbStoredCollection]] | None = None,
    *,
    get_folders: bool = True,
    sort_role: CollectionTreeSortRole | None = None,
) -> Iterator[DbStoredCollection]:
    collections_by_parent_id = (
        get_collections_by_parent_id() if collections_by_parent_id is None else collections_by_parent_id
    )
    child_collections = collections_by_parent_id.get(parent_id, [])
    for child_collection in (
        sorted(child_collections, key=lambda c: c.get_sort_value(sort_role)) if sort_role else child_collections
    ):
        if not child_collection.is_folder or get_folders:
            yield child_collection
        if child_collection.is_folder:
            yield from get_recursive_children(child_collection.id, collections_by_parent_id, get_folders=get_folders)


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
        rows = get_database_manager().get_rows("SELECT * FROM music_view ORDER BY (music_id, artist_order)")
        rows_by_music_id = {k: list(v) for k, v in groupby(rows, key=lambda r: r["music_id"])}
        self._music_by_id: dict[int, DbMusic] = {
            music_id: DbMusic.from_db_rows(rows) for music_id, rows in rows_by_music_id.items()
        }

    @profile
    def get(self, music_id: int) -> DbMusic:
        if music_id not in self._music_by_id:
            self._music_by_id[music_id] = DbMusic.from_db(music_id)
        return self._music_by_id[music_id]


@cache
def get_db_music_cache() -> _DbMusicCache:
    return _DbMusicCache()


class _DbStoredCollectionCache:
    def __init__(self):
        self._collection_by_id = {
            row["collection_id"]: DbStoredCollection.from_db_row(row)
            for row in get_database_manager().get_rows_k(collection_query, collectionId=None)
        }

    def get(self, collection_id: int) -> DbStoredCollection:
        if collection_id not in self._collection_by_id:
            self._collection_by_id[collection_id] = DbStoredCollection.from_db(collection_id)
        return self._collection_by_id[collection_id]

    @property
    def collections(self) -> list[DbStoredCollection]:
        return list(self._collection_by_id.values())

    def delete_collection(self, collection_id: int) -> None:
        del self._collection_by_id[collection_id]

    def add_collection(self, collection: DbStoredCollection) -> None:
        self._collection_by_id[collection.id] = collection


@cache
def get_db_stored_collection_cache() -> _DbStoredCollectionCache:
    return _DbStoredCollectionCache()


def get_music_ids(collection: DbCollection, sort_role: CollectionTreeSortRole) -> tuple[int, ...]:
    return (
        get_folder_music_ids(collection.id, sort_role)
        if collection.collection_type == "folder"
        else collection.music_ids
    )
