import itertools
from typing import Literal, cast, get_args

from vlc import Event, EventManager, EventType, Instance, Media, MediaList, MediaListPlayer, MediaPlayer

from music_player.db_types import DbCollection, DbMusic, get_db_music_cache

RepeatState = Literal["NO_REPEAT", "REPEAT_QUEUE", "REPEAT_ONE"]


def index_media_list(media_list: MediaList, media: Media) -> int:
    return next(i for i, m in enumerate(media_list) if m.get_mrl() == media.get_mrl())


# TODO REMOVE CLICKING ON SLIDER TO NUDGE
class VLCCore:
    def on_playing(self, _: Event):
        self.media_player.pause()
        self.player_event_manager.event_detach(EventType.MediaPlayerPlaying)

    def load_media_from_music_ids(self, music_ids: tuple[int, ...]):
        paths = [get_db_music_cache().get(i).file_path for i in music_ids]
        self.media_list = self.instance.media_list_new(paths)
        self.list_player.set_media_list(self.media_list)
        self.list_indices = list(range(len(paths)))
        self.db_indices = list(music_ids)

    def __init__(self):
        self.instance = Instance("--no-xlib")

        self.list_player: MediaListPlayer = self.instance.media_list_player_new()

        self.current_collection: DbCollection | None = None
        self.media_list: MediaList = self.instance.media_list_new()
        self.db_indices: list[int] = []
        self.list_indices: list[int] = []
        """The ordered list of indices in BOTH the `db_indices` and `media_list` to play"""
        self.current_media_idx: int = -1

        self.player_event_manager = cast(EventManager, self.media_player.event_manager())  # pyright: ignore[reportUnknownMemberType]
        self.list_player_event_manager = cast(EventManager, self.list_player.event_manager())  # pyright: ignore[reportUnknownMemberType]

        if self.media_list.count():
            self.player_event_manager.event_attach(EventType.MediaPlayerPlaying, self.on_playing)
            self.list_player.next()
        assert not self.media_player.is_playing()

        self.repeat_states = itertools.cycle(get_args(RepeatState))
        self.repeat_state: RepeatState = next(self.repeat_states)
        assert self.repeat_state == "NO_REPEAT"  # Should always start here TODO (for now)

    @property
    def current_music(self) -> DbMusic:
        return get_db_music_cache().get(self.db_indices[self.list_indices[self.current_media_idx]])

    @property
    def current_media(self) -> Media | None:
        """The currently playing media"""
        return self.media_player.get_media()  # TODO: IS LIST REF FASTER?

    @property
    def media_player(self) -> MediaPlayer:
        """The media player instance"""
        return self.list_player.get_media_player()

    def jump_play_index(self, list_index: int):
        self.current_media_idx = list_index
        self.list_player.play_item_at_index(self.list_indices[list_index])

    def previous(self):
        if self.current_media_idx == -1:
            return
        self.current_media_idx -= 1
        self.current_media_idx = max(self.current_media_idx, 0)
        self.list_player.play_item_at_index(self.list_indices[self.current_media_idx])

    def next(self):
        self.current_media_idx += 1
        if self.current_media_idx >= len(self.list_indices):
            self.list_player.stop()
        else:
            self.list_player.play_item_at_index(self.list_indices[self.current_media_idx])
