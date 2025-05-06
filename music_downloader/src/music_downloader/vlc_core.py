from functools import cached_property
from typing import cast

from vlc import Instance, MediaListPlayer, MediaPlayer, EventType, Event

from music_downloader.music import get_music


class VLCCore:
    def on_playing(self, _: Event):
        self.list_player.pause()
        self.media_player.event_manager().event_detach(EventType.MediaPlayerPlaying)  # pyright: ignore[reportAttributeAccessIssue]

    def __init__(self):
        self.instance = cast(Instance, Instance())
        self.music_list = list(get_music())
        self.list_player: MediaListPlayer = self.instance.media_list_player_new()
        self.media_list = self.instance.media_list_new([m.file_path for m in self.music_list])
        self.list_player.set_media_list(self.media_list)
        self.original_indices: list[int] = list(range(len(self.music_list)))
        if self.media_list.count():
            self.media_player.event_manager().event_attach(
                EventType.MediaPlayerPlaying,  # pyright: ignore[reportAttributeAccessIssue]
                self.on_playing,
            )
            self.list_player.play_item_at_index(0)

        assert not self.list_player.is_playing()
        assert self.media_list.index_of_item(self.media_player.get_media()) != -1

    @cached_property
    def media_player(self) -> MediaPlayer:
        return self.list_player.get_media_player()
