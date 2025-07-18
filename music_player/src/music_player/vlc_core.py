import itertools
from typing import Literal, cast, get_args

from vlc import EventManager, EventType, Instance, Media, MediaList

from music_player.db_types import DbCollection, get_db_music_cache
from music_player.signals import VLCSignals

RepeatState = Literal["NO_REPEAT", "REPEAT_QUEUE", "REPEAT_ONE"]


def index_media_list(media_list: MediaList, media: Media) -> int:
    return next(i for i, m in enumerate(media_list) if m.get_mrl() == media.get_mrl())


# TODO REMOVE CLICKING ON SLIDER TO NUDGE
class VLCCore:
    def __init__(self):
        self.instance = Instance("--no-xlib")
        self.vlc_signals = VLCSignals()

        self.current_collection: DbCollection | None = None
        self.media_player = self.instance.media_player_new()

        self.event_manager = cast(EventManager, self.media_player.event_manager())  # pyright: ignore[reportUnknownMemberType]
        connect = self.event_manager.event_attach

        assert not self.media_player.is_playing()

        self.repeat_states = itertools.cycle(get_args(RepeatState))
        self.repeat_state: RepeatState = next(self.repeat_states)
        assert self.repeat_state == "NO_REPEAT"  # Should always start here TODO (for now)

        connect(EventType.MediaPlayerPlaying, lambda _: self.vlc_signals.media_playing_signal.emit())
        connect(EventType.MediaPlayerPaused, lambda _: self.vlc_signals.media_paused_signal.emit())
        connect(EventType.MediaPlayerStopped, lambda _: self.vlc_signals.media_paused_signal.emit())
        connect(EventType.MediaPlayerTimeChanged, lambda e: self.vlc_signals.time_changed_signal.emit(e.u.new_time))
        connect(EventType.MediaPlayerEndReached, lambda _: self.vlc_signals.media_end_reached_signal.emit())
        connect(EventType.MediaPlayerMediaChanged, lambda _: self.vlc_signals.media_changed_signal.emit())

    @property
    def current_media(self) -> Media | None:
        """The currently playing media"""
        return self.media_player.get_media()  # TODO: IS LIST REF FASTER?

    def stop(self):
        self.media_player.stop()

    def play_item(self, music_id: int):
        media = self.instance.media_new_path(get_db_music_cache().get(music_id).file_path)
        assert media is not None
        self.media_player.set_media(media)
        self.media_player.play()
        self.vlc_signals.time_changed_signal.emit(0)
