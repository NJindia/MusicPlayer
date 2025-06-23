from dataclasses import dataclass

from music_player.database import get_database_manager


@dataclass
class Artist:
    id: str
    name: str
    img: bytes | None

    @classmethod
    def from_db(cls, artist_id: int) -> "Artist":
        row = get_database_manager().get_row("SELECT * FROM artists WHERE artist_id = %s", (artist_id,))
        return cls(
            id=row["artist_id"],
            name=row["artist_name"],
            img=bytes(row["artist_img"]) if row["artist_img"] else None,
        )


@dataclass(frozen=True)
class Album:
    id: str
    name: str
    release_date: str
    cover_bytes: bytes

    @classmethod
    def from_db(cls, album_id: int) -> "Album":
        row = get_database_manager().get_row("SELECT * FROM albums WHERE album_id = %s", (album_id,))
        return cls(
            id=row["album_id"],
            name=row["album_name"],
            release_date=row["release_date"],
            cover_bytes=bytes(row["cover_bytes"]),
        )

    @property
    def artists(self) -> list[Artist]:
        raise NotImplementedError
