import itertools
from typing import Literal, cast, get_args

from PySide6.QtCore import SignalInstance
from vlc import Event, EventManager, EventType, Instance, Media, MediaList

from music_player.db_types import DbCollection, DbMusic, get_db_music_cache
from music_player.signals import VLCSignals

RepeatState = Literal["NO_REPEAT", "REPEAT_QUEUE", "REPEAT_ONE"]


def index_media_list(media_list: MediaList, media: Media) -> int:
    return next(i for i, m in enumerate(media_list) if m.get_mrl() == media.get_mrl())


# TODO REMOVE CLICKING ON SLIDER TO NUDGE
class VLCCore:
    def on_playing(self, _: Event):
        self.media_player.pause()
        self.emanager.event_detach(EventType.MediaPlayerPlaying)

    def load_media_from_music_ids(self, music_ids: tuple[int, ...]):
        paths = [get_db_music_cache().get(i).file_path for i in music_ids]
        self.media_list = self.instance.media_list_new(paths)
        self.list_indices = list(range(len(paths)))
        self.music_ids = list(music_ids)

    def __init__(self):
        self.instance = Instance("--no-xlib")
        self.vlc_signals = VLCSignals()

        self.current_collection: DbCollection | None = None
        self.media_player = self.instance.media_player_new()
        self.media_list: MediaList = self.instance.media_list_new()
        self.music_ids: list[int] = []
        self.list_indices: list[int] = []
        """The ordered list of indices in BOTH the `db_indices` and `media_list` to play"""
        self.current_media_idx: int = -1
        self.emanager = cast(EventManager, self.media_player.event_manager())  # pyright: ignore[reportUnknownMemberType]

        if self.media_list.count():
            self.emanager.event_attach(EventType.MediaPlayerPlaying, self.on_playing)
            self.media_player.play()
        assert not self.media_player.is_playing()

        self.repeat_states = itertools.cycle(get_args(RepeatState))
        self.repeat_state: RepeatState = next(self.repeat_states)
        assert self.repeat_state == "NO_REPEAT"  # Should always start here TODO (for now)

        self.emanager.event_attach(EventType.MediaPlayerPlaying, lambda _: self.vlc_signals.media_playing_signal.emit())
        self.emanager.event_attach(EventType.MediaPlayerPaused, lambda _: self.vlc_signals.media_paused_signal.emit())
        self.emanager.event_attach(EventType.MediaPlayerStopped, lambda _: self.vlc_signals.media_paused_signal.emit())
        self.emanager.event_attach(
            EventType.MediaPlayerTimeChanged, lambda e: self.vlc_signals.time_changed_signal.emit(e.u.new_time)
        )
        self.emanager.event_attach(
            EventType.MediaPlayerEndReached, lambda _: self.vlc_signals.media_end_reached_signal.emit()
        )
        self.emanager.event_attach(
            EventType.MediaPlayerMediaChanged, lambda _: self.vlc_signals.media_changed_signal.emit()
        )

    @property
    def current_music(self) -> DbMusic:
        return get_db_music_cache().get(self.music_ids[self.list_indices[self.current_media_idx]])

    @property
    def current_media(self) -> Media | None:
        """The currently playing media"""
        return self.media_player.get_media()  # TODO: IS LIST REF FASTER?

    def jump_play_index(self, list_index: int):
        self.current_media_idx = list_index
        self.play_item_at_index(self.list_indices[list_index])

    def previous(self):
        if self.current_media_idx == -1:
            return
        self.current_media_idx -= 1
        self.current_media_idx = max(self.current_media_idx, 0)
        self.play_item_at_index(self.list_indices[self.current_media_idx])

    def next(self):
        self.current_media_idx += 1
        if self.current_media_idx >= len(self.list_indices):
            self.media_player.stop()
        else:
            self.play_item_at_index(self.list_indices[self.current_media_idx])

    def play_item_at_index(self, list_index: int):
        media = self.media_list.item_at_index(list_index)
        assert media is not None
        self.media_player.set_media(media)
        self.media_player.play()
