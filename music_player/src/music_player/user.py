from dataclasses import dataclass
from functools import cache

from PySide6.QtCore import Qt

from music_player.database import get_database_manager
from music_player.view_types import CollectionTreeSortRole


def create_user(name: str):
    query = """
    WITH u_ids AS (INSERT INTO users (name) VALUES (%s) RETURNING user_id)
    INSERT INTO user_session_config (user_id) SELECT (u_ids.user_id) FROM u_ids"""
    get_database_manager().execute_query(query, (name,))


def update_user_session_tree_sort_role_order(user_id: int, sort_role: CollectionTreeSortRole, sort_order: Qt.SortOrder):
    query = """
    UPDATE user_session_config
    SET (playlist_tree_sort_role, playlist_tree_sort_order) = (%s, %s)
    WHERE user_id = %s"""
    get_database_manager().execute_query(query, (sort_role.value, sort_order.value, user_id))


def get_user_session_tree_sort_role_order_tup(user_id: int) -> tuple[CollectionTreeSortRole, Qt.SortOrder]:
    query = "SELECT playlist_tree_sort_role FROM user_session_config WHERE user_id = %s"
    resp = get_database_manager().get_row(query, (user_id,))
    sort_role_val = resp["playlist_tree_sort_role"]
    sort_role_order = resp["playlist_tree_sort_order"]
    sort_order = Qt.SortOrder.AscendingOrder if sort_role_order is None else Qt.SortOrder(sort_role_order)
    sort_role = CollectionTreeSortRole.ALPHABETICAL if sort_role_val is None else CollectionTreeSortRole(val)
    return sort_role, sort_order


def update_user_session_library_collection(user_id: int, collection_id: int):
    query = "UPDATE user_session_config SET library_collection_id = %s WHERE user_id = %s"
    get_database_manager().execute_query(query, (collection_id, user_id))


def get_user_session_library_collection(user_id: int) -> int:
    query = "SELECT library_collection_id FROM user_session_config WHERE user_id = %s"
    return get_database_manager().get_row(query, (user_id,))["library_collection_id"]


@dataclass(frozen=True)
class UserStartupConfig:
    sort_role: CollectionTreeSortRole
    sort_order: Qt.SortOrder
    library_collection_id: int


@cache
def get_user_startup_config(user_id: int) -> UserStartupConfig:
    query = "SELECT * FROM user_session_config WHERE user_id = %s"
    resp = get_database_manager().get_row(query, (user_id,))
    sort_role_val = resp["playlist_tree_sort_role"]
    sort_role_order = resp["playlist_tree_sort_order"]
    library_collection_id = resp["library_collection_id"]
    return UserStartupConfig(
        sort_role=CollectionTreeSortRole.ALPHABETICAL
        if sort_role_val is None
        else CollectionTreeSortRole(sort_role_val),
        sort_order=Qt.SortOrder.AscendingOrder if sort_role_order is None else Qt.SortOrder(sort_role_order),
        library_collection_id=-1 if library_collection_id is None else library_collection_id,
    )
