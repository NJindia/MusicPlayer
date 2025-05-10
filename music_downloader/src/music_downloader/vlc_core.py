import itertools
from typing import cast, Literal, get_args

import numpy as np
from vlc import Instance, MediaPlayer, EventType, Event, MediaList, MediaListPlayer, MediaLibrary, Media

from music_downloader.music import get_music_media, Music

Success = Literal[-1, 0]

RepeatState = Literal["NO_REPEAT", "REPEAT_QUEUE", "REPEAT_ONE"]


def index_media_list(media_list: MediaList, media: Media) -> int:
    return next(i for i, m in enumerate(media_list) if m.get_mrl() == media.get_mrl())


class VLCCore:
    def on_playing(self, _: Event):
        self.media_player.pause()
        self.player_event_manager.event_detach(EventType.MediaPlayerPlaying)  # pyright: ignore[reportAttributeAccessIssue]

    def __init__(self):
        self.instance = cast(Instance, Instance("--no-xlib"))
        self.music_list, media_list = list(get_music_media(self.instance))
        self.list_player: MediaListPlayer = self.instance.media_list_player_new()

        self.media_list: MediaList = self.instance.media_list_new(media_list)
        self.list_player.set_media_list(self.media_list)
        self.player_event_manager = self.media_player.event_manager()
        self.list_player_event_manager = self.list_player.event_manager()

        self.library: MediaLibrary = self.instance.media_library_new()
        self.library.load()
        lib_media: MediaList = self.library.media_list()
        for _ in range(lib_media.count()):
            lib_media.remove_index(0)
        for m in self.music_list:
            lib_media.add_media(self.instance.media_new(m.file_path))
        self.list_player.set_media_list(lib_media)
        self.indices: list[int] = list(range(lib_media.count()))

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
    def current_music(self) -> Music:
        """The Music that is currently playing"""
        return next(m for m in self.music_list if m.mrl == self.current_media.get_mrl())

    @property
    def current_media_idx(self) -> int:
        """The index of the current media. Corresponds to appropriate index of `self.indices`"""
        return index_media_list(self.media_list, self.current_media)

    @property
    def current_media(self) -> Media:
        """The currently playing media"""
        return self.media_player.get_media()

    @property
    def media_player(self) -> MediaPlayer:
        """The media player instance"""
        return self.list_player.get_media_player()

    def shuffle_next(self):
        shuffle_indices = self.indices[self.current_media_idx + 1 :]
        np.random.shuffle(shuffle_indices)
        self.indices = self.indices[: self.current_media_idx + 1] + shuffle_indices
        self.media_list = self.instance.media_list_new([self.library.media_list()[i] for i in self.indices])
        self.list_player.set_media_list(self.media_list)

    def unshuffle(self):
        played_media = self.media_list[: self.current_media_idx + 1]
        index_of_current_media_in_library = index_media_list(self.library.media_list(), self.current_media)
        next_media = self.library.media_list()[index_of_current_media_in_library + 1 :]
        self.media_list = self.instance.media_list_new([*played_media, *next_media])
        self.list_player.set_media_list(self.media_list)
        self.indices = self.indices[: self.current_media_idx + 1] + list(
            range(index_of_current_media_in_library, index_of_current_media_in_library + len(next_media))
        )
