from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsView, QTableView, QTreeView


class PlaylistTreeView(QTreeView):
    collection_id_role = Qt.ItemDataRole.UserRole + 1
    is_folder_role = Qt.ItemDataRole.UserRole + 2
    is_protected_role = Qt.ItemDataRole.UserRole + 3
    collection_role = Qt.ItemDataRole.UserRole + 4


class LibraryTableView(QTableView):
    music_id_role = Qt.ItemDataRole.UserRole + 1
    sort_order_role = Qt.ItemDataRole.UserRole + 2


class StackGraphicsView(QGraphicsView):
    pass


class CollectionTreeSortRole(Enum):
    UPDATED = Qt.ItemDataRole.UserRole + 5
    PLAYED = Qt.ItemDataRole.UserRole + 6
    ALPHABETICAL = Qt.ItemDataRole.UserRole + 7
