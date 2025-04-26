from dataclasses import dataclass
from datetime import date

import polars

from music_downloader.utils import length_timestamp_to_seconds, parse_release_date
import subprocess

@dataclass(kw_only=True)
class SpotifyImportMetadata:
    artists: list[str]
    track_name: str
    album_name: str
    length_seconds: int
    spotify_id: str
    isrc: str
    release_date: date
    popularity: int


# df = polars.read_csv("spotlistr-exported-playlist.csv", separator="|")
# import_metadata = [
#     SpotifyImportMetadata(
#         artists=[n.strip() for n in row_dict["Arist(s) Name"].strip().split(";")],
#         track_name=row_dict["Track Name"].strip(),
#         album_name=row_dict["Album Name"].strip(),
#         length_seconds=length_timestamp_to_seconds(row_dict["Length"].strip()),
#         spotify_id=row_dict["SpotifyID"].strip(),
#         isrc=row_dict["ISRC"].strip(),
#         release_date=parse_release_date(row_dict["Release Date"].strip()),
#         popularity=int(row_dict["Popularity"].strip()),
#     )
#     for row_dict in df.rows(named=True)
# ]

rip_process = subprocess.run(
    ["rip", "url", "https://tidal.com/album/36039902/track/36039911", ""], capture_output=True, shell=True
)
print(rip_process.stdout.decode())
print(rip_process.stderr.decode())
assert rip_process.returncode == 0
