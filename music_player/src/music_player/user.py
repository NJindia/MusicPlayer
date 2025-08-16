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


@dataclass
class UserConfig:
    user_id: int
    tree_sort_role: CollectionTreeSortRole
    tree_sort_order: Qt.SortOrder
    library_collection_id: int
    library_sort_column: int
    library_sort_order: Qt.SortOrder

    def upload_to_db(self):
        query = """
        UPDATE user_session_config
        SET (
             playlist_tree_sort_role,
             playlist_tree_sort_order,
             library_collection_id,
             library_sort_column,
             library_sort_order
        ) = (%s, %s, %s, %s, %s) WHERE user_id = %s"""
        get_database_manager().execute_query(
            query,
            (
                self.tree_sort_role.value,
                self.tree_sort_order.value,
                self.library_collection_id,
                self.library_sort_column,
                self.library_sort_order.value,
                self.user_id,
            ),
        )


@cache
def get_user_config(user_id: int = USER_ID) -> UserConfig:
    query = "SELECT * FROM user_session_config WHERE user_id = %s"
    resp = get_database_manager().get_row(query, (user_id,))
    return UserConfig(
        user_id=user_id,
        tree_sort_role=CollectionTreeSortRole(resp["playlist_tree_sort_role"]),
        tree_sort_order=Qt.SortOrder(resp["playlist_tree_sort_order"]),
        library_collection_id=resp["library_collection_id"],
        library_sort_column=resp["library_sort_column"],
        library_sort_order=Qt.SortOrder(resp["library_sort_order"]),
    )
