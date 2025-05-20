from datetime import datetime, date, UTC
from typing import cast

from PySide6.QtGui import QPixmap, QPixmapCache, QImage


def length_timestamp_to_seconds(length_timestamp: str) -> int:
    return int(
        (
            datetime.combine(datetime.min, datetime.strptime(length_timestamp, "%H:%M:%S").time()) - datetime.min
        ).total_seconds()
    )


def parse_release_date(release_date: str) -> date:
    match release_date.count("-"):
        case 2:
            return datetime.strptime(release_date, "%Y-%m-%d").date()
        case 1:
            return datetime.strptime(release_date, "%Y-%m").date()
        case 0:
            return datetime.strptime(release_date, "%Y").date()
        case _:
            raise ValueError("Invalid release date")


def timestamp_to_str(timestamp: int | float):
    if isinstance(timestamp, float):
        timestamp = round(timestamp)
    return datetime.fromtimestamp(timestamp).strftime("%M:%S")


def datetime_to_date_str(dt: datetime) -> str:
    return f"{dt:%b} {dt.day}, {dt:%Y}"


def datetime_to_age_string(dt: datetime) -> str:
    td = datetime.now(tz=UTC) - dt
    if td.seconds < 60:
        return f"{td.seconds} second{'s'[: td.seconds ^ 1]} ago"
    elif (mins := round(td.seconds / 60)) < 60:
        return f"{mins} minute{'s'[: mins ^ 1]} ago"
    elif td.days < 1:
        hour = round(td.seconds / 60 / 60)
        return f"{hour} hour{'s'[: hour ^ 1]} ago"
    elif td.days < 7:
        return f"{td.days} day{'s'[: td.days ^ 1]} ago"
    elif td.days <= 28:
        week = td.days // 7
        return f"{week} week{'s'[: week ^ 1]} ago"
    else:
        return datetime_to_date_str(dt)


def get_pixmap(cover_bytes: bytes) -> QPixmap:
    pixmap = cast(QPixmap | None, QPixmapCache.find(str(cover_bytes)))  # pyright: ignore [reportCallIssue]
    if pixmap is None:
        pixmap = QPixmap.fromImage(QImage.fromData(cover_bytes))
        QPixmapCache.insert(str(cover_bytes), pixmap)
    return pixmap
