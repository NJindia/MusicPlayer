from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, cast

from mutagen.flac import FLAC, Picture, VCFLACDict
from tqdm import tqdm


class NotAcceptedFileTypeError(ValueError):
    pass


@dataclass
class Music:
    title: str
    artists: list[str]
    album: str
    album_artist: str
    lyrics_by_timestamp: dict[time | None, str]
    release_date: date
    duration_timestamp: float
    isrc: str
    file_path: Path
    album_cover_bytes: bytes | None
    downloaded_datetime: datetime


SOURCES: list[Path] = [Path("../export/")]


def _parse_lyrics(lyrics: str) -> dict[time | None, str]:
    lyrics_by_timestamp: dict[time | None, str] = {}
    for line in lyrics.split("\n"):
        timestamp_end_idx = line.find("]")
        _time = (
            datetime.strptime(line[1:timestamp_end_idx], "%M:%S.%f").replace(tzinfo=UTC).time()
            if timestamp_end_idx != -1
            else None
        )
        lyrics_by_timestamp[_time] = line[timestamp_end_idx + 1 :].strip()
    return lyrics_by_timestamp


def load_music(path: Path) -> Music:
    match path.suffix:
        case ".flac":
            md = FLAC(path)
            assert isinstance(md.tags, VCFLACDict)  # pyright: ignore[reportUnknownMemberType]
            tags = cast(dict[str, list[Any]], md.tags)
            pictures = cast(list[Picture], md.pictures)  # pyright: ignore[reportUnknownMemberType]
            return Music(
                title=tags["TITLE"][0],
                artists=[s.strip() for s in tags["ARTIST"][0].split(",")],
                album=tags["ALBUM"][0],
                album_artist=tags["ALBUMARTIST"][0],
                duration_timestamp=cast(float, md.info.length),  # pyright: ignore[reportUnknownMemberType]
                isrc=tags["ISRC"][0],
                release_date=datetime.strptime(
                    tags["DATE"][0],
                    "%Y-%m-%dT%H:%M:%S.%f%z",
                ).date(),
                lyrics_by_timestamp=_parse_lyrics(tags["LYRICS"][0]) if "LYRICS" in tags else {},
                file_path=path,
                album_cover_bytes=cast(bytes, pictures[0].data) if pictures else None,  # pyright: ignore[reportUnknownMemberType]
                downloaded_datetime=datetime.fromtimestamp(path.stat().st_birthtime, tz=UTC),
            )
        case ".m4a":
            raise NotAcceptedFileTypeError
        case _:
            raise NotAcceptedFileTypeError


def load_from_sources():
    for source in SOURCES:
        assert source.is_dir()
        for fp in tqdm(list(source.iterdir())):
            yield load_music(fp)
