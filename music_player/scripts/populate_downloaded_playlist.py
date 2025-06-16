import datetime

from music_player.music_importer import get_music_df
from music_player.playlist import Playlist, PlaylistItem

downloaded = get_music_df()["downloaded_datetime"]
downloaded_playlist = Playlist(
    parent_id="",
    id="_",
    title="Downloaded Songs",
    created=datetime.datetime.now(tz=datetime.UTC),
    last_updated=datetime.datetime.now(tz=datetime.UTC),
    last_played=None,
    thumbnail=None,
    playlist_items=[PlaylistItem(index, row) for index, row in zip(downloaded.index, downloaded, strict=True)],
)
downloaded_playlist.save()
