import itertools
from pathlib import Path
from typing import cast, Literal, get_args

import numpy as np
from vlc import Instance, MediaPlayer, EventType, Event, MediaList, MediaListPlayer, Media

from music_downloader.music_importer import Music, get_music_df
from music_downloader.common import get_playlist
from dacite import from_dict

RepeatState = Literal["NO_REPEAT", "REPEAT_QUEUE", "REPEAT_ONE"]


def index_media_list(media_list: MediaList, media: Media) -> int:
    return next(i for i, m in enumerate(media_list) if m.get_mrl() == media.get_mrl())


# TODO REMOVE CLICKING ON SLIDER TO NUDGE
class VLCCore:
    def on_playing(self, _: Event):
        self.media_player.pause()
        self.player_event_manager.event_detach(EventType.MediaPlayerPlaying)  # pyright: ignore[reportAttributeAccessIssue]

    def __init__(self):
        self.instance = cast(Instance, Instance("--no-xlib"))

        self.list_player: MediaListPlayer = self.instance.media_list_player_new()

        init_playlist = get_playlist(Path("../playlists/playlist4.json"))
        self.media_list = init_playlist.to_media_list(self.instance)
        self.indices = init_playlist.indices
        self.list_player.set_media_list(self.media_list)

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

    def initialize_list_player(self, media_list: MediaList, music_list: list[Music]):
        assert media_list.count() == len(music_list)
        self.media_list = media_list
        self.list_player.set_media_list(self.media_list)
        self.indices = list(range(self.media_list.count()))  # TODO

    @property
    def current_music(self) -> Music:
        return from_dict(Music, get_music_df().iloc[self.indices[self.current_media_idx]].to_dict())

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
        self.media_list = self.instance.media_list_new([self.media_list[i] for i in self.indices])
        self.list_player.set_media_list(self.media_list)

    def unshuffle(self):
        current_media_idx = self.current_media_idx
        played_media = self.media_list[: current_media_idx + 1]
        next_media = self.media_list[current_media_idx + 1 :]
        self.media_list = self.instance.media_list_new([*played_media, *next_media])
        self.list_player.set_media_list(self.media_list)
        self.indices = self.indices[: self.current_media_idx + 1] + list(
            range(current_media_idx, current_media_idx + len(next_media))
        )
