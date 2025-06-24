import os
from functools import cache
from typing import Any

import psycopg2
from psycopg2._json import Json
from psycopg2.extras import RealDictCursor, execute_values
from PySide6.QtSql import QSqlDatabase

from music_player.music_importer import Music, load_from_sources

CREATE_SQL = """
DROP TABLE IF EXISTS albums, artists, music, music_artists, collections, collection_children CASCADE;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE albums (
	album_id SERIAL PRIMARY KEY ,
    album_name VARCHAR(255) NOT NULL,
	release_date DATE NOT NULL,
	cover_bytes BYTEA
);

CREATE TABLE artists (
	artist_id SERIAL PRIMARY KEY,
    artist_name VARCHAR(255) NOT NULL,
    artist_img BYTEA
);


CREATE TABLE music (
	music_id SERIAL PRIMARY KEY,
    music_name VARCHAR(255) NOT NULL,
    album_id INT NOT NULL,
    lyrics_by_timestamp JSONB,
    release_date DATE NOT NULL,
    duration REAL NOT NULL,
    isrc VARCHAR(255) NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    downloaded_on TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (album_id) REFERENCES albums(album_id)
);

CREATE MATERIALIZED VIEW library_music_view AS
SELECT
    m.*,
    a.album_name,
    a.cover_bytes,
    (
        COALESCE(music_name)    || CHR(31) ||
        COALESCE(album_name)
    ) as search_vector
FROM music as m JOIN albums as a USING (album_id);
CREATE UNIQUE INDEX index ON library_music_view (music_id);
REFRESH MATERIALIZED VIEW CONCURRENTLY library_music_view;

CREATE INDEX idx_library_search_gin ON library_music_view
USING GIN (search_vector gin_trgm_ops);

CREATE TABLE music_artists (
	music_id INT NOT NULL,
    artist_id INT NOT NULL,
    sort_order INT NOT NULL,
    PRIMARY KEY (music_id, artist_id),
    FOREIGN KEY (music_id) REFERENCES music(music_id),
	FOREIGN KEY (artist_id) REFERENCES artists(artist_id)
);
CREATE TABLE collections (
    collection_id SERIAL PRIMARY KEY,
    type VARCHAR(25) NOT NULL,
    parent_collection_id INT,
    name VARCHAR(255) NOT NULL,
    created TIMESTAMPTZ NOT NULL,
    last_updated TIMESTAMPTZ NOT NULL,
    last_played TIMESTAMPTZ,
    thumbnail BYTEA,
    protected BOOLEAN
);

CREATE TABLE collection_children (
    collection_id INT NOT NULL,
    music_id INT NOT NULL,
    added_on TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (collection_id, music_id),
    FOREIGN KEY (collection_id) REFERENCES collections(collection_id),
    FOREIGN KEY (music_id) REFERENCES music(music_id)
);

CREATE MATERIALIZED VIEW music_view AS
SELECT lmv.*, ma.artist_id, ma.sort_order AS artist_order FROM library_music_view AS lmv
JOIN music_artists ma USING (music_id)
JOIN artists AS a USING (artist_id);
"""

INSERT_ALBUM_SQL = "INSERT INTO albums (album_name, release_date, cover_bytes) VALUES (%s, %s, %s) RETURNING album_id;"

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


def _insert_music(cursor: RealDictCursor, music: Music):
    cursor.execute("SELECT album_id FROM albums WHERE album_name=%s LIMIT 1", (music.album,))
    album_row = cursor.fetchone()
    if album_row is None:
        cursor.execute(INSERT_ALBUM_SQL, (music.album, music.release_date, music.album_cover_bytes))
        album_id = cursor.fetchone()["album_id"]  # pyright: ignore[reportOptionalSubscript]
    else:
        album_id = album_row["album_id"]

    cursor.execute(
        INSERT_MUSIC_SQL,
        (
            music.title,
            album_id,
            Json({ts.isoformat() if ts else ts: lyrics for ts, lyrics in music.lyrics_by_timestamp.items()}),
            music.release_date,
            music.duration_timestamp,
            music.isrc,
            str(music.file_path),
            music.downloaded_datetime,
        ),
    )
    music_id = cursor.fetchone()["music_id"]  # pyright: ignore[reportOptionalSubscript]

    artist_ids: list[int] = []
    for artist in music.artists:
        cursor.execute("SELECT artist_id from artists WHERE artist_name=%s LIMIT 1", (artist,))
        artist_row = cursor.fetchone()
        if artist_row is None:
            cursor.execute(INSERT_ARTIST_SQL, (artist, None))
            artist_ids.append(cursor.fetchone()["artist_id"])  # pyright: ignore[reportOptionalSubscript]
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

    def execute_query(self, query, args: tuple[Any, ...] | None = None):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, args)
            conn.commit()
        finally:
            conn.close()

    def get_row(self, query: str, args: tuple[Any, ...] | None = None, *, commit: bool = False):
        return self.get_rows(query, args, commit=commit)[0]

    def get_rows(self, query: str, args: tuple[Any, ...] | None = None, *, commit: bool = False):
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, args)
                if commit:
                    conn.commit()
                return cursor.fetchall()
        finally:
            conn.close()

    def reset_and_populate_database(self):
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(TRUNCATE_ALL_SQL)
                for music in load_from_sources():
                    _insert_music(cursor, music)
                cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY library_music_view;")
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
