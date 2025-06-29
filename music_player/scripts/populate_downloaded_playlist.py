import datetime
from collections import Counter

from music_player.database import get_database_manager
from music_player.db_types import DbStoredCollection
from music_player.music_importer import load_from_sources

downloaded = list(load_from_sources())
downloaded_playlist = DbStoredCollection(
    _id=-1,
    _collection_type="playlist",
    _parent_id=-1,
    _name="Downloaded Songs",
    _created=datetime.datetime.now(tz=datetime.UTC),
    _last_updated=datetime.datetime.now(tz=datetime.UTC),
    _last_played=None,
    _img_path=None,
    _is_protected=True,
    _music_ids=(),
    _music_added_on=[],
    _album_img_path_counter=Counter(),
)
get_database_manager().reset_and_populate_database()
downloaded_playlist.save()
downloaded_playlist.add_music_ids(tuple(1 + i for i in range(len(downloaded))))
