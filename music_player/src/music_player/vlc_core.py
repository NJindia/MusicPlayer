import itertools
from typing import Literal, cast, get_args

from vlc import Event, EventType, Instance, Media, MediaList, MediaListPlayer, MediaPlayer

from music_player.database import get_database_manager
from music_player.playlist import DbCollection, DbMusic

RepeatState = Literal["NO_REPEAT", "REPEAT_QUEUE", "REPEAT_ONE"]


def index_media_list(media_list: MediaList, media: Media) -> int:
    return next(i for i, m in enumerate(media_list) if m.get_mrl() == media.get_mrl())


# TODO REMOVE CLICKING ON SLIDER TO NUDGE
class VLCCore:
    def on_playing(self, _: Event):
        self.media_player.pause()
        self.player_event_manager.event_detach(EventType.MediaPlayerPlaying)  # pyright: ignore[reportAttributeAccessIssue]

    def load_media_from_music_ids(self, music_ids: tuple[int, ...]):
        rows = (
            get_database_manager().get_rows("SELECT file_path FROM music WHERE music_id IN %s", (music_ids,))
            if music_ids
            else []
        )
        paths = [r["file_path"] for r in rows]
        self.media_list = self.instance.media_list_new(paths)
        self.list_player.set_media_list(self.media_list)
        self.list_indices = list(range(len(paths)))
        self.db_indices = list(music_ids)

    def __init__(self):
        self.instance = cast(Instance, Instance("--no-xlib"))

        self.list_player: MediaListPlayer = self.instance.media_list_player_new()

        self.current_collection: DbCollection = DbCollection.from_db()
        self.media_list: MediaList = self.instance.media_list_new()
        self.db_indices: list[int] = []
        self.list_indices: list[int] = []
        """The ordered list of indices in BOTH the `db_indices` and `media_list` to play"""
        self.current_media_idx: int = 0
        self.load_media_from_music_ids(self.current_collection.get_music_ids())

        self.player_event_manager = self.media_player.event_manager()
        self.list_player_event_manager = self.list_player.event_manager()

        if self.media_list.count():
            self.player_event_manager.event_attach(
                EventType.MediaPlayerPlaying,  # pyright: ignore[reportAttributeAccessIssue]
                self.on_playing,
            )
            self.list_player.next()
        assert not self.media_player.is_playing()

        self.repeat_states = itertools.cycle(get_args(RepeatState))
        self.repeat_state: RepeatState = next(self.repeat_states)
        assert self.repeat_state == "NO_REPEAT"  # Should always start here TODO (for now)

    @property
    def current_music(self) -> DbMusic:
        return DbMusic.from_db(self.db_indices[self.list_indices[self.current_media_idx]])

    @property
    def current_media(self) -> Media:
        """The currently playing media"""
        return self.media_player.get_media()  # TODO: IS LIST REF FASTER?

    @property
    def media_player(self) -> MediaPlayer:
        """The media player instance"""
        return self.list_player.get_media_player()

    def jump_play_index(self, list_index: int):
        print(list_index)
        self.current_media_idx = list_index
        self.list_player.play_item_at_index(self.list_indices[list_index])

    def previous(self):
        self.current_media_idx -= 1
        self.current_media_idx = max(self.current_media_idx, 0)
        self.list_player.play_item_at_index(self.list_indices[self.current_media_idx])

    def next(self):
        self.current_media_idx += 1
        if self.current_media_idx >= len(self.list_indices):
            self.list_player.stop()
        self.list_player.play_item_at_index(self.list_indices[self.current_media_idx])
