from functools import cached_property
from typing import cast, Literal

import numpy as np
from vlc import Instance, MediaPlayer, EventType, Event, MediaList, Media

from music_downloader.music import get_music, Music
from music_downloader.constants import SKIP_BACK_SECOND_THRESHOLD

Success = Literal[-1, 0]


class VLCCore:
    def on_playing(self, _: Event):
        self.list_player.pause()
        self.media_player.event_manager().event_detach(EventType.MediaPlayerPlaying)  # pyright: ignore[reportAttributeAccessIssue]

    def __init__(self):
        self.instance = cast(Instance, Instance())
        self.music_list = list(get_music())
        self.list_player = self.instance.media_list_player_new()
        self.media_list: MediaList = self.instance.media_list_new([m.file_path for m in self.music_list])
        self.list_player.set_media_list(self.media_list)
        self.original_indices: list[int] = list(range(len(self.music_list)))
        if self.media_list.count():
            self.media_player.event_manager().event_attach(
                EventType.MediaPlayerPlaying,  # pyright: ignore[reportAttributeAccessIssue]
                self.on_playing,
            )
            self.list_player.play_item_at_index(0)

        self.current_queue_index = 0
        self.media_list_indices: list[int] = list(range(len(self.music_list)))

        assert not self.list_player.is_playing()
        assert self.media_list.index_of_item(self.media_player.get_media()) != -1

    @cached_property
    def media_player(self) -> MediaPlayer:
        return self.list_player.get_media_player()

    def play_jump_to_index(self, queue_index: int):
        self.current_queue_index = queue_index
        self.list_player.play_item_at_index(self.current_queue_index)

    def _play_current_queue_index(self) -> Success:
        return self.list_player.play_item_at_index(self.media_list_indices[self.current_queue_index])

    def play_next(self) -> Success:
        self.current_queue_index += 1
        if self.current_queue_index >= len(self.media_list):
            return self.list_player.stop()
        return self._play_current_queue_index()

    def play_previous(self) -> Success:
        if (
            self.current_queue_index == 0
            or self.list_player.get_media_player().get_time() / 1000 > SKIP_BACK_SECOND_THRESHOLD
        ):
            self.list_player.get_media_player().set_position(0)
            return 0
        else:
            self.current_queue_index -= 1
            return self._play_current_queue_index()

    def remove_music_at_index(self, media_index: int):
        self.media_list.remove_index(media_index)
        self.music_list.pop(media_index)

    def add_music_at_index(self, index: int, music: Music, media: Media):
        self.music_list.insert(index, music)
        self.media_list.add_media(media)
        self.media_list_indices.insert(index, self.media_list.count() - 1)

    def shuffle_next_indices(self) -> list[int]:
        queue_index = self.current_queue_index + 1
        shuffled = self.media_list_indices[queue_index:]
        np.random.shuffle(shuffled)
        self.media_list_indices[queue_index:] = shuffled
        return shuffled

    def unshuffle_next_indices(self) -> list[int]:
        queue_index = self.current_queue_index
        unshuffled = self.media_list_indices[queue_index:]  # TODO THIS IS WRONG
        self.media_list_indices[queue_index:] = unshuffled
        return unshuffled
