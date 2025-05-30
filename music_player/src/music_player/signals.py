from PySide6.QtCore import QObject, Signal

from music_player.playlist import Playlist


class SharedSignals(QObject):
    add_to_queue_signal = Signal(int)
    add_to_playlist_signal = Signal(int, Playlist)
    library_load_artist_signal = Signal(str)
    library_load_album_signal = Signal(str)
