from dataclasses import dataclass
from datetime import time, date, datetime
from pathlib import Path
from typing import Iterator

import soundfile as sf
from dacite.cache import cache
from mutagen.flac import FLAC
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
    isrc: str
    file_path: Path
    album_cover_bytes: bytes | None

    @property
    def data_sr(self):
        return sf.read(self.file_path)


def _parse_lyrics(lyrics: str) -> dict[time | None, str]:
    lyrics_by_timestamp: dict[time | None, str] = {}
    for line in lyrics.split("\n"):
        timestamp_end_idx = line.find("]")
        _time = (
            datetime.strptime(line[1:timestamp_end_idx], "%M:%S.%f").time()
            if timestamp_end_idx != -1
            else None
        )
        lyrics_by_timestamp[_time] = line[timestamp_end_idx + 1 :].strip()
    return lyrics_by_timestamp


@cache
def get_music() -> Iterator[Music]:
    for fp in tqdm(list((Path().resolve() / "export/").iterdir())):
        match fp.suffix:
            case ".flac":
                md = FLAC(fp)
                assert md.tags is not None
                yield Music(
                    title=md.tags["TITLE"][0],  # pyright: ignore[reportIndexIssue]
                    artists=[s.strip() for s in md.tags["ARTIST"][0].split(",")],  # pyright: ignore[reportIndexIssue]
                    album=md.tags["ALBUM"][0],  # pyright: ignore[reportIndexIssue]
                    album_artist=md.tags["ALBUMARTIST"][0],  # pyright: ignore[reportIndexIssue]
                    isrc=md.tags["ISRC"][0],  # pyright: ignore[reportIndexIssue]
                    release_date=datetime.strptime(
                        md.tags["DATE"][0],  # pyright: ignore[reportIndexIssue]
                        "%Y-%m-%dT%H:%M:%S.%f%z",
                    ).date(),
                    lyrics_by_timestamp=_parse_lyrics(md.tags["LYRICS"][0])  # pyright: ignore[reportIndexIssue]
                    if "LYRICS" in md.tags  # pyright: ignore[reportOperatorIssue]
                    else {},
                    file_path=fp,
                    album_cover_bytes=md.pictures[0].data if md.pictures else None,  # pyright: ignore[reportIndexIssue]
                )
            case ".m4a":
                continue
                raise NotAcceptedFileTypeError()


if __name__ == "__main__":
    music_list = list(get_music())
