from PySide6.QtCore import QModelIndex, QObject, Signal

from music_player.playlist import CollectionBase, Playlist


class SharedSignals(QObject):
    add_to_queue_signal = Signal(list)  # (list[int) (model_df_indices)
    add_to_playlist_signal = Signal(list, Playlist)  # (list[int], Playlist) (model_df_indices, ...)
    create_playlist_signal = Signal(str, QModelIndex, list)  # (name, src_model_root_index, song_df_indices)
    create_folder_signal = Signal(str, QModelIndex, QModelIndex)  # (name, src_model_root_index, move_from_idx)
    library_load_artist_signal = Signal(str)
    library_load_album_signal = Signal(str)
    move_collection_signal = Signal(QModelIndex, QModelIndex)  # (fromIndex, toIndex)
    delete_playlist_signal = Signal(CollectionBase)
