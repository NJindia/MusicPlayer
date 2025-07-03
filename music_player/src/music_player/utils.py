import struct
from collections.abc import Sequence
from datetime import UTC, date, datetime
from functools import cache
from pathlib import Path

from line_profiler_pycharm import profile  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from PySide6.QtCore import QByteArray, QSize, QThread
from PySide6.QtGui import QPixmap, QPixmapCache, Qt


def length_timestamp_to_seconds(length_timestamp: str) -> int:
    min_datetime_utc = datetime.min.replace(tzinfo=UTC)
    length_time_utc = datetime.strptime(length_timestamp, "%H:%M:%S").replace(tzinfo=UTC).time()
    return int((datetime.combine(min_datetime_utc, length_time_utc) - min_datetime_utc).total_seconds())


def parse_release_date(release_date: str) -> date:
    match release_date.count("-"):
        case 2:
            return datetime.strptime(release_date, "%Y-%m-%d").replace(tzinfo=UTC).date()
        case 1:
            return datetime.strptime(release_date, "%Y-%m").replace(tzinfo=UTC).date()
        case 0:
            return datetime.strptime(release_date, "%Y").replace(tzinfo=UTC).date()
        case _:
            raise ValueError("Invalid release date")


def timestamp_to_str(timestamp: float):
    if isinstance(timestamp, float):
        timestamp = round(timestamp)
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%M:%S")


def datetime_to_date_str(dt: datetime) -> str:
    return f"{dt:%b} {dt.day}, {dt:%Y}"


def datetime_to_age_string(dt: datetime) -> str:
    td = datetime.now(tz=UTC) - dt
    if td.seconds < 60:
        return f"{td.seconds} second{'s'[: td.seconds ^ 1]} ago"
    if (mins := round(td.seconds / 60)) < 60:
        return f"{mins} minute{'s'[: mins ^ 1]} ago"
    if td.days < 1:
        hour = round(td.seconds / 60 / 60)
        return f"{hour} hour{'s'[: hour ^ 1]} ago"
    if td.days < 7:
        return f"{td.days} day{'s'[: td.days ^ 1]} ago"
    if td.days <= 28:
        week = td.days // 7
        return f"{week} week{'s'[: week ^ 1]} ago"
    return datetime_to_date_str(dt)


@profile
def get_pixmap(source: Path | None, height: int | None) -> QPixmap:
    assert QThread.currentThread().isMainThread()
    if source is None:
        return get_empty_pixmap(height)
    pixmap = QPixmap()
    key = f"{source!s}_{height}"
    if not QPixmapCache.find(key, pixmap):
        # print(f"key: {key}, {QPixmapCache.cacheLimit()}")
        pixmap = QPixmap(source)
        if height is not None:
            pixmap = pixmap.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
        QPixmapCache.insert(key, pixmap)
    return pixmap


def get_colored_pixmap(pixmap: QPixmap, color: Qt.GlobalColor) -> QPixmap:
    colored_pm = QPixmap(pixmap)
    colored_pm.fill(color)
    colored_pm.setMask(pixmap.createMaskFromColor(Qt.GlobalColor.transparent))
    return colored_pm


@cache
def get_empty_pixmap(height: int | None) -> QPixmap:
    pm = QPixmap(QSize(height, height)) if height is not None else QPixmap()
    pm.fill(Qt.GlobalColor.transparent)  # Fill with transparent pixmap
    return pm


def get_single_song_drag_text(title: str, artists: list[str]) -> str:
    return f"{title} - {', '.join(artists)}"


def music_ids_to_qbytearray(music_ids: Sequence[int]) -> QByteArray:
    packed_data = struct.pack(f">{len(music_ids)}i", *music_ids)
    return QByteArray(packed_data)


def qbytearray_to_music_ids(data: QByteArray) -> list[int]:
    byte_data = data.data()
    num_ints = len(byte_data) // 4
    return list(struct.unpack(f">{num_ints}i", byte_data))
