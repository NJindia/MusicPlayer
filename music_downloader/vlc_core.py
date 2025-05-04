from typing import cast

from vlc import Instance, MediaListPlayer

from music_downloader.music import get_music


class VLCCore:
    def __init__(self):
        self.instance = cast(Instance, Instance())
        self.music_list = list(get_music())
        self.list_player: MediaListPlayer = self.instance.media_list_player_new()
        self.media_list = self.instance.media_list_new(
            [m.file_path for m in self.music_list]
        )
        self.list_player.set_media_list(self.media_list)
