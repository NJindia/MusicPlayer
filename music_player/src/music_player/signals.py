from collections.abc import Sequence

from PySide6.QtCore import QModelIndex, QObject, Signal

from music_player.db_types import DbCollection, DbStoredCollection


class SharedSignals(QObject):
    add_to_queue_signal = Signal(Sequence)  # (Sequence[int) (music_ids)
    add_to_playlist_signal = Signal(
        Sequence, DbStoredCollection
    )  # (Sequence[int], DbStoredCollection) (music_ids, ...)
    create_playlist_signal = Signal(str, QModelIndex, list)  # (name, src_model_root_index, music_ids)
    create_folder_signal = Signal(str, QModelIndex, QModelIndex)  # (name, src_model_root_index, move_from_idx)
    library_load_artist_signal = Signal(int)  # (artist_id)
    library_load_album_signal = Signal(int)  # (album_id)
    move_collection_signal = Signal(QModelIndex, QModelIndex)  # (fromIndex, toIndex)
    delete_collection_signal = Signal(DbStoredCollection)
    play_collection_signal = Signal(DbCollection, int)  # (DbStoredCollection, collection_idx_to_play_from)
    toggle_shuffle_signal = Signal(bool)  # (shuffle)
    play_history_song_signal = Signal(int)  # (music_id)
