from PySide6.QtCore import QModelIndex, QObject, Signal

from music_player.playlist import DbCollection


class SharedSignals(QObject):
    clear_queue_signal = Signal()
    add_to_queue_signal = Signal(list)  # (list[int) (model_df_indices)
    add_to_playlist_signal = Signal(list, DbCollection)  # (list[int], DbCollection) (model_df_indices, ...)
    create_playlist_signal = Signal(str, QModelIndex, list)  # (name, src_model_root_index, song_df_indices)
    create_folder_signal = Signal(str, QModelIndex, QModelIndex)  # (name, src_model_root_index, move_from_idx)
    library_load_artist_signal = Signal(int)  # (artist_id)
    library_load_album_signal = Signal(int)  # (album_id)
    move_collection_signal = Signal(QModelIndex, QModelIndex)  # (fromIndex, toIndex)
    delete_collection_signal = Signal(DbCollection)
    play_playlist_signal = Signal(DbCollection, int)  # (DbCollection, playlist_idx_to_play_from)
