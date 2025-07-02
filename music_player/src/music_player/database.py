import io
import os
from functools import cache
from pathlib import Path
from typing import Any, cast

import psycopg2
from PIL import Image
from psycopg2._json import Json
from psycopg2.extras import RealDictCursor, RealDictRow, execute_values  # pyright: ignore[reportUnknownVariableType]
from PySide6.QtSql import QSqlDatabase

from music_player.music_importer import Music, load_from_sources

INSERT_ALBUM_SQL = "INSERT INTO albums (album_name, release_date) VALUES (%s, %s) RETURNING album_id, img_path;"

INSERT_ARTIST_SQL = "INSERT INTO artists (artist_name, artist_img) VALUES (%s, %s) RETURNING artist_id;"

INSERT_MUSIC_ARTISTS_SQL = "INSERT INTO music_artists (music_id, artist_id, sort_order) VALUES %s;"

INSERT_MUSIC_SQL = """
INSERT INTO music (music_name, album_id, lyrics_by_timestamp, release_date, duration, isrc, file_path, downloaded_on)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
RETURNING music_id;
"""

TRUNCATE_ALL_SQL = """
TRUNCATE TABLE music_artists, albums, music, artists, collections, collection_children RESTART IDENTITY CASCADE;
"""

PATH_TO_IMGS = Path("../images/")


def _insert_music(cursor: RealDictCursor, music: Music):
    cursor.execute("SELECT album_id, img_path FROM albums WHERE album_name=%s LIMIT 1", (music.album,))  # pyright: ignore[reportUnknownMemberType]
    album_row = cursor.fetchone()
    if album_row is None:
        cursor.execute(INSERT_ALBUM_SQL, (music.album, music.release_date))  # pyright: ignore[reportUnknownMemberType]
        album_row = cast(RealDictRow, cursor.fetchone())
        if music.album_cover_bytes:
            Image.open(io.BytesIO(music.album_cover_bytes)).save(PATH_TO_IMGS / album_row["img_path"])

    cursor.execute(  # pyright: ignore[reportUnknownMemberType]
        INSERT_MUSIC_SQL,
        (
            music.title,
            album_row["album_id"],
            Json({ts.isoformat() if ts else ts: lyrics for ts, lyrics in music.lyrics_by_timestamp.items()}),
            music.release_date,
            music.duration_timestamp,
            music.isrc,
            str(music.file_path),
            music.downloaded_datetime,
        ),
    )
    music_id = cast(int, cursor.fetchone()["music_id"])  # pyright: ignore[reportOptionalSubscript]

    artist_ids: list[int] = []
    for artist in music.artists:
        cursor.execute("SELECT artist_id from artists WHERE artist_name=%s LIMIT 1", (artist,))  # pyright: ignore[reportUnknownMemberType]
        artist_row = cursor.fetchone()
        if artist_row is None:
            cursor.execute(INSERT_ARTIST_SQL, (artist, None))  # pyright: ignore[reportUnknownMemberType]
            artist_ids.append(cast(int, cursor.fetchone()["artist_id"]))  # pyright: ignore[reportOptionalSubscript]
        else:
            artist_ids.append(artist_row["artist_id"])
    args = [(music_id, artist_id, i + 1) for i, artist_id in enumerate(artist_ids)]
    execute_values(cursor, INSERT_MUSIC_ARTISTS_SQL, args)


class DatabaseManager:
    def __init__(self):
        self.host = "localhost"
        self.port = 5432
        self.username = "postgres"
        self.password = "nijindia"
        self.database = "music_player"
        self.connection_name = "qt_sql_default_connection"

    def _get_connection(self):
        return psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.username,
            password=self.password,
            database=self.database,
        )

    def execute_values(self, query: str, args: list[tuple[Any, ...]]):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            execute_values(cursor, query, args)
            conn.commit()
        finally:
            conn.close()

    def execute_query(self, query: str, args: tuple[Any, ...] | None = None):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, args)
            conn.commit()
        finally:
            conn.close()

    def get_row_k(self, query: str, *, commit: bool = False, **kwargs: Any):
        return self.get_rows_k(query, commit=commit, **kwargs)[0]

    def get_rows_k(self, query: str, *, commit: bool = False, **kwargs: Any):
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, kwargs)  # pyright: ignore[reportUnknownMemberType]
                if commit:
                    conn.commit()
                return cursor.fetchall()
        finally:
            conn.close()

    def get_row(self, query: str, args: tuple[Any, ...] | None = None, *, commit: bool = False):
        return self.get_rows(query, args, commit=commit)[0]

    def get_rows(self, query: str, args: tuple[Any, ...] | None = None, *, commit: bool = False):
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, args)  # pyright: ignore[reportUnknownMemberType]
                if commit:
                    conn.commit()
                return cursor.fetchall()
        finally:
            conn.close()

    def reset_and_populate_database(self):
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(TRUNCATE_ALL_SQL)  # pyright: ignore[reportUnknownMemberType]
                for music in load_from_sources():
                    _insert_music(cursor, music)
                cursor.execute(  # pyright: ignore[reportUnknownMemberType]
                    "REFRESH MATERIALIZED VIEW CONCURRENTLY library_music_view; REFRESH MATERIALIZED VIEW music_view;"
                )
            conn.commit()
        finally:
            conn.close()

    def create_qt_connection(self):
        os.environ["PATH"] += os.pathsep + r"C:\Users\techn\PycharmProjects\MusicPlayer\dlls"  # TODO
        db = QSqlDatabase.addDatabase("QPSQL", self.connection_name)
        db.setHostName(self.host)
        db.setPort(self.port)
        db.setDatabaseName(self.database)
        db.setUserName(self.username)
        db.setPassword(self.password)
        assert db.open()
        print("Qt Connected")

    def get_qt_connection(self) -> QSqlDatabase:
        return QSqlDatabase.database(self.connection_name)

    def test_connection(self):
        """Test MySQL connection without selecting database"""
        try:
            self._get_connection()
        except Exception as e:
            return False, str(e)
        else:
            return True, "Connection successful"


@cache
def get_database_manager() -> DatabaseManager:
    return DatabaseManager()


if __name__ == "__main__":
    _db = DatabaseManager()
    print(_db.test_connection())
    print(_db.reset_and_populate_database())
