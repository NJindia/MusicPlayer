from dataclasses import dataclass
from datetime import time, date, datetime
from pathlib import Path
from typing import cast

import soundfile as sf
from PySide6.QtGui import QIcon, QPixmap, QImage
from dacite.cache import cache
from mutagen.flac import FLAC
from tqdm import tqdm
from vlc import Media, Instance


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
    mrl: str
    album_cover_bytes: bytes | None

    @property
    def data_sr(self):
        return sf.read(self.file_path)

    @property
    def album_icon(self) -> QIcon:
        if self.album_cover_bytes is not None:
            return QIcon(QPixmap.fromImage(QImage.fromData(self.album_cover_bytes)))
        return QIcon()


def _parse_lyrics(lyrics: str) -> dict[time | None, str]:
    lyrics_by_timestamp: dict[time | None, str] = {}
    for line in lyrics.split("\n"):
        timestamp_end_idx = line.find("]")
        _time = datetime.strptime(line[1:timestamp_end_idx], "%M:%S.%f").time() if timestamp_end_idx != -1 else None
        lyrics_by_timestamp[_time] = line[timestamp_end_idx + 1 :].strip()
    return lyrics_by_timestamp


@cache
def get_music_media(instance: Instance) -> tuple[list[Music], list[Media]]:
    music_list: list[Music] = []
    media_list: list[Media] = []
    for fp in tqdm(list((Path().resolve().parent / "export/").iterdir())):
        media = cast(Media, instance.media_new(fp))
        media_list.append(media)
        match fp.suffix:
            case ".flac":
                md = FLAC(fp)
                assert md.tags is not None
                music = Music(
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
                    mrl=media.get_mrl(),
                    album_cover_bytes=md.pictures[0].data if md.pictures else None,  # pyright: ignore[reportIndexIssue]
                )
                music_list.append(music)
            case ".m4a":
                continue
                raise NotAcceptedFileTypeError()
    return music_list, media_list


if __name__ == "__main__":
    music_list = list(get_music_media())
