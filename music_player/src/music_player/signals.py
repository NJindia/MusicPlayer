from PySide6.QtCore import QObject, Signal, QModelIndex

from music_player.playlist import Playlist


class SharedSignals(QObject):
    add_to_queue_signal = Signal(list)
    add_to_playlist_signal = Signal(list, Playlist)
    create_playlist_signal = Signal(str, QModelIndex)
    library_load_artist_signal = Signal(str)
    library_load_album_signal = Signal(str)
