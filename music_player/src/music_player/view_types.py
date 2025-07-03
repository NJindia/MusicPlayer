from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsView, QTableView, QTreeView


class PlaylistTreeView(QTreeView):
    is_folder_role = Qt.ItemDataRole.UserRole + 2
    is_protected_role = Qt.ItemDataRole.UserRole + 3
    collection_role = Qt.ItemDataRole.UserRole + 4


class LibraryTableView(QTableView):
    pass


class StackGraphicsView(QGraphicsView):
    pass
