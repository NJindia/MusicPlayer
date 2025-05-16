import itertools
from pathlib import Path
from typing import cast, Literal, get_args

from vlc import Instance, MediaPlayer, EventType, Event, MediaList, MediaListPlayer, Media

from music_player.music_importer import Music
from music_player.common import get_playlist, Playlist

RepeatState = Literal["NO_REPEAT", "REPEAT_QUEUE", "REPEAT_ONE"]


def index_media_list(media_list: MediaList, media: Media) -> int:
    return next(i for i, m in enumerate(media_list) if m.get_mrl() == media.get_mrl())


def get_init_playlist():
    return get_playlist(Path("../playlists/playlist4.json"))


# TODO REMOVE CLICKING ON SLIDER TO NUDGE
class VLCCore:
    def on_playing(self, _: Event):
        self.media_player.pause()
        self.player_event_manager.event_detach(EventType.MediaPlayerPlaying)  # pyright: ignore[reportAttributeAccessIssue]

    def __init__(self):
        self.instance = cast(Instance, Instance("--no-xlib"))

        self.list_player: MediaListPlayer = self.instance.media_list_player_new()

        init_playlist: Playlist = get_init_playlist()
        paths = init_playlist.file_paths
        self.media_list: MediaList = self.instance.media_list_new(paths)
        self.list_indices = list(range(len(paths)))
        self.music_list: list[Music] = init_playlist.music_list
        self.current_media_idx: int = 0
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

    @property
    def current_music(self) -> Music:
        return self.music_list[self.list_indices[self.current_media_idx]]

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
        if self.current_media_idx < 0:
            self.current_media_idx = 0
        self.list_player.play_item_at_index(self.list_indices[self.current_media_idx])

    def next(self):
        self.current_media_idx += 1
        self.list_player.play_item_at_index(self.list_indices[self.current_media_idx])
