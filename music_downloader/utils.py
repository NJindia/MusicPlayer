from datetime import datetime, timedelta, date


def length_timestamp_to_seconds(length_timestamp: str) -> int:
    return int(
        (datetime.combine(datetime.min, datetime.strptime(length_timestamp, "%H:%M:%S").time()) - datetime.min).total_seconds()
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