from dataclasses import dataclass
from functools import cache

from PySide6.QtCore import Qt

from music_player.constants import USER_ID
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


def update_user_session_library_collection_id(user_id: int, collection_id: int):
    query = "UPDATE user_session_config SET library_collection_id = %s WHERE user_id = %s"
    get_database_manager().execute_query(query, (collection_id, user_id))


def update_user_session_library_sort_column_order(user_id: int, sort_column: int, sort_order: Qt.SortOrder):
    query = "UPDATE user_session_config SET (library_sort_column, library_sort_order) = (%s, %s) WHERE user_id = %s"
    get_database_manager().execute_query(query, (sort_column, sort_order.value, user_id))


@dataclass(frozen=True)
class UserStartupConfig:
    sort_role: CollectionTreeSortRole
    sort_order: Qt.SortOrder
    library_collection_id: int
    library_sort_column: int
    library_sort_order: Qt.SortOrder


@cache
def get_user_startup_config(user_id: int = USER_ID) -> UserStartupConfig:
    query = "SELECT * FROM user_session_config WHERE user_id = %s"
    resp = get_database_manager().get_row(query, (user_id,))
    return UserStartupConfig(
        sort_role=CollectionTreeSortRole(resp["playlist_tree_sort_role"]),
        sort_order=Qt.SortOrder(resp["playlist_tree_sort_order"]),
        library_collection_id=resp["library_collection_id"],
        library_sort_column=resp["library_sort_column"],
        library_sort_order=Qt.SortOrder(resp["library_sort_order"]),
    )
