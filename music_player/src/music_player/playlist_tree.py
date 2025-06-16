from datetime import datetime, UTC
from enum import Enum
from functools import partial
from typing import cast, Iterator

from PySide6.QtCore import (
    Qt,
    QModelIndex,
    QPoint,
    Slot,
    QSize,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    QObject,
    QEvent,
    QAbstractItemModel,
)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon, QAction, QFont, QPixmap, QMouseEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QTreeView,
    QWidget,
    QVBoxLayout,
    QMenu,
    QLabel,
    QLineEdit,
    QHBoxLayout,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QWidgetAction,
)

from music_player.common_gui import NewPlaylistAction, NewFolderAction
from music_player.constants import MAX_SIDE_BAR_WIDTH
from music_player.playlist import Playlist, CollectionBase, get_collections_by_parent_id, Folder
from music_player.signals import SharedSignals
from music_player.utils import get_colored_pixmap

PLAYLIST_ROW_HEIGHT = 50

ID_ROLE = Qt.ItemDataRole.UserRole + 1


class SORT_ROLE(Enum):
    UPDATED = Qt.ItemDataRole.UserRole + 3
    PLAYED = Qt.ItemDataRole.UserRole + 4
    ALPHABETICAL = Qt.ItemDataRole.UserRole + 5


DEFAULT_SORT_ORDER_BY_SORT_ROLE: dict[SORT_ROLE, Qt.SortOrder] = {
    SORT_ROLE.UPDATED: Qt.SortOrder.DescendingOrder,
    SORT_ROLE.PLAYED: Qt.SortOrder.DescendingOrder,
    SORT_ROLE.ALPHABETICAL: Qt.SortOrder.AscendingOrder,
}
INITIAL_SORT_ROLE = SORT_ROLE.ALPHABETICAL


class TreeItemDelegate(QStyledItemDelegate):
    def __init__(self):
        super().__init__()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex, /) -> QSize:
        default_size = super().sizeHint(option, index)
        return QSize(default_size.width(), PLAYLIST_ROW_HEIGHT)


class TreeModelItem(QStandardItem):
    def __init__(self, collection: Playlist | Folder) -> None:
        super().__init__(collection.title)
        self.collection = collection

        font = QFont()
        font.setPointSize(14)
        self.setFont(font)
        self.setEditable(False)
        self.update_icon()

    def data(self, /, role: int = Qt.ItemDataRole.DisplayRole):
        if role == ID_ROLE:
            return self.collection.id
        elif role == SORT_ROLE.UPDATED.value:
            return self.collection.last_updated.timestamp()
        elif role == SORT_ROLE.PLAYED.value:
            last_played = self.collection.last_played
            return (last_played if last_played else datetime.max.replace(tzinfo=UTC)).timestamp()
        elif role == SORT_ROLE.ALPHABETICAL.value:
            return self.text().lower() + self.text()
        return super().data(role)

    def update_icon(self):
        self.setIcon(QIcon(self.collection.get_thumbnail_pixmap(PLAYLIST_ROW_HEIGHT)))

    def sync_item(self, item: "TreeModelItem"):
        self.setText(self.collection.title)
        self.collection = item.collection


def _recursive_traverse(parent_item: QStandardItem, *, get_non_leaf: bool) -> Iterator[TreeModelItem]:
    for row in range(parent_item.rowCount()):
        child_item = cast(TreeModelItem, parent_item.child(row))
        if child_item:
            if child_item.hasChildren():
                if get_non_leaf:
                    yield child_item
                yield from _recursive_traverse(child_item, get_non_leaf=get_non_leaf)
            else:
                yield child_item


class PlaylistTree(QTreeView):
    def __init__(self, model: QAbstractItemModel, *, is_main_view: bool):
        super().__init__()
        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(True)
        self.setAnimated(True)
        self.setSortingEnabled(False)
        self.setHeaderHidden(True)
        self.setIconSize(QSize(PLAYLIST_ROW_HEIGHT, PLAYLIST_ROW_HEIGHT))
        delegate = TreeItemDelegate()
        self.setItemDelegate(delegate)
        if is_main_view:
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setModel(model)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.RightButton:
            super().mousePressEvent(event)


class PlaylistTreeWidget(QWidget):
    def __init__(self, parent: QWidget, main_window: QMainWindow, signals: SharedSignals, *, is_main_view: bool):
        super().__init__(parent)
        self.is_main_view = is_main_view
        self.signals = signals

        self.setStyleSheet("QWidget { margin: 0px; border: none; }")
        self.setMaximumWidth(MAX_SIDE_BAR_WIDTH)

        self.model_: QStandardItemModel = QStandardItemModel()
        self.model_.layoutChanged.connect(self._update_flattened_model)  # TODO NECESSARY?
        self.model_.rowsRemoved.connect(self._update_flattened_model)
        self.model_.dataChanged.connect(self.update_playlist)
        self._flattened_model: QStandardItemModel = QStandardItemModel()
        self._flattened_model.dataChanged.connect(self.update_playlist)
        self._initialize_model()

        self.proxy_model = QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.model_)
        self.proxy_model.setSortRole(INITIAL_SORT_ROLE.value)
        self.proxy_model.sort(0)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.tree_view = PlaylistTree(self.proxy_model, is_main_view=is_main_view)

        header_widget = QWidget()
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_widget.setLayout(header_layout)
        if self.is_main_view:
            label = QLabel("Playlists", self)
            label_font = QFont()
            label_font.setPointSize(20)
            label_font.setBold(True)
            label.setFont(label_font)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

            create_menu = QMenu(self)
            args = create_menu, main_window, self.model_.invisibleRootItem().index(), self.signals
            create_menu.addActions([NewPlaylistAction(*args), NewFolderAction(*args)])

            new_button = QToolButton(self)
            new_button.setText("+ New")
            new_button.setMenu(create_menu)
            new_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            new_button.setStyleSheet("""
                        QToolButton::menu-indicator { image: none; }
                        QToolButton { border-radius: 5px; background: grey}
                    """)

            header_top_layout = QHBoxLayout()
            header_top_layout.setContentsMargins(0, 0, 0, 0)
            header_top_layout.addWidget(label)
            header_top_layout.addWidget(new_button)
            header_layout.addLayout(header_top_layout)

        search_bar = QLineEdit()
        search_bar.textChanged.connect(self.filter)
        search_bar.setClearButtonEnabled(True)
        search_bar.setPlaceholderText("Search playlists")

        self.sort_button = QToolButton(self)  # TODO CUSTOM WIDGET TO GET RID OF SPACING BETWEEN
        self.sort_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.sort_button.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.sort_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.sort_button.setStyleSheet("""
            QToolButton::menu-indicator { image: none; }
            QToolButton { padding: 5px; }
        """)
        self.update_sort_button()

        self.sort_menu = SortMenu(self)
        self.sort_button.setMenu(self.sort_menu)

        search_sort_layout = QHBoxLayout()
        search_sort_layout.setContentsMargins(0, 0, 0, 0)
        search_sort_layout.addWidget(search_bar)
        search_sort_layout.addWidget(self.sort_button)
        header_layout.addLayout(search_sort_layout)

        layout = QVBoxLayout()
        layout.addWidget(header_widget)
        layout.addWidget(self.tree_view)
        self.setLayout(layout)

    def update_sort_button(self):
        sort_role = SORT_ROLE(self.proxy_model.sortRole())
        order_str = "asc" if self.proxy_model.sortOrder() == Qt.SortOrder.AscendingOrder else "desc"
        pm = get_colored_pixmap(
            QPixmap(f"../icons/sort/sort-{'alpha-' if sort_role == SORT_ROLE.ALPHABETICAL else ''}{order_str}.svg"),
            Qt.GlobalColor.white,
        )
        self.sort_button.setIcon(QIcon(pm))
        self.sort_button.setText(sort_role.name.capitalize())

    def filter(self, text: str):
        if text == "":  # Revert back to original nested view
            self.proxy_model.setSourceModel(self.model_)
            self.proxy_model.setFilterRegularExpression("")
            return
        self.proxy_model.setSourceModel(self._flattened_model)
        self.proxy_model.setFilterRegularExpression(rf"\b{text}\w*")

    @Slot(SORT_ROLE)
    def change_sort_role(self, sort_role: SORT_ROLE) -> None:
        sort_type = sort_role.value
        order = (
            (
                Qt.SortOrder.DescendingOrder
                if self.proxy_model.sortOrder() == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
            if self.proxy_model.sortRole() == sort_type
            else DEFAULT_SORT_ORDER_BY_SORT_ROLE[sort_role]
        )
        self.proxy_model.setSortRole(sort_type)
        # TODO THIS IS BASICALLY JUST ALPHA
        self.proxy_model.sort(0, order)

        self.update_sort_button()
        self.sort_menu.update_active_action()

    def source_model(self):
        return cast(QStandardItemModel, self.proxy_model.sourceModel())

    def item_at_index(
        self, index: QModelIndex, *, is_source: bool
    ) -> TreeModelItem:  # , get_default_model_item: bool = False
        assert not isinstance(index.model(), QSortFilterProxyModel if is_source else QStandardItemModel)

        return cast(
            TreeModelItem,
            self.source_model().itemFromIndex(index if is_source else self.proxy_model.mapToSource(index)),
        )

    def flattened_proxy_index_to_default_model_item(self, proxy_index: QModelIndex) -> TreeModelItem:
        return self.get_model_item(self.item_at_index(proxy_index, is_source=False).collection)

    @Slot()
    def rename_playlist(self, proxy_index: QModelIndex) -> None:
        item = self.item_at_index(proxy_index, is_source=False)
        self.model_.blockSignals(True)
        item.setEditable(True)
        self.tree_view.edit(proxy_index)
        item.setEditable(False)
        self.model_.blockSignals(False)

    @Slot()
    def delete_collection(self, proxy_index: QModelIndex) -> None:
        item = self.flattened_proxy_index_to_default_model_item(proxy_index)
        parent = item.parent()
        parent_index = (parent or self.model_.invisibleRootItem()).index()
        self.model_.beginRemoveRows(parent_index, item.row(), item.row())
        (self.model_ if parent is None else parent).removeRow(item.row())

        if item.collection.is_folder:

            def get_recursive_children(parent_id: str) -> Iterator[CollectionBase]:
                for collection in get_collections_by_parent_id().get(parent_id, []):
                    if collection.is_folder:
                        yield from get_recursive_children(collection.id)
                    yield collection

            for child in list(get_recursive_children(item.collection.id)):
                child.delete()
            get_collections_by_parent_id.cache_clear()
        item.collection.delete()
        print("TODO: PUSH CONFIRMATION")

    @Slot()
    def update_playlist(self, tl_source_index: QModelIndex, _: QModelIndex, roles: list[int]) -> None:
        if Qt.ItemDataRole.DisplayRole in roles:
            item = self.item_at_index(tl_source_index, is_source=True)
            if item is None:
                raise ValueError
            playlist = item.collection
            if playlist is None:
                raise NotImplementedError
            playlist.title = item.text()
            playlist.save()

            if self.proxy_model.filterRegularExpression().pattern():
                self.model_.blockSignals(True)
                self.get_model_item(item.collection).sync_item(item)
                self.model_.blockSignals(False)
            else:
                self._update_flattened_model()
            pass

    @Slot()
    def playlist_context_menu(self, main_window: QMainWindow, point: QPoint):
        proxy_index = self.tree_view.indexAt(point)
        menu = QMenu(self.tree_view)
        source_root_index = self.source_model().invisibleRootItem().index()
        if proxy_index.isValid():
            item = self.item_at_index(proxy_index, is_source=False)

            # Set root for adding playlist/folder
            if item.collection.is_folder:  # Folder is a valid root
                source_root_index = self.proxy_model.mapToSource(proxy_index)
            elif (parent := item.parent()) is not None:  # Not top-level
                assert self.source_model() != self._flattened_model, "Should only have top-level for flattened!"
                source_root_index = parent.index()

            if not item.collection.is_protected:
                rename_action = QAction("Rename", self.tree_view)
                rename_action.triggered.connect(partial(self.rename_playlist, proxy_index))

                delete_action = QAction("Delete", self.tree_view)
                delete_action.triggered.connect(partial(self.delete_collection, proxy_index))

                menu.addActions([rename_action, delete_action])

            if not item.collection.is_folder:
                playlist = cast(Playlist, item.collection)
                menu.addMenu(AddToPlaylistMenu(playlist.indices, self.signals, menu, main_window))

        args = menu, main_window, source_root_index, self.signals
        menu.addSeparator()
        menu.addActions([NewPlaylistAction(*args), NewFolderAction(*args)])

        menu.popup(self.tree_view.mapToGlobal(point))

    def _update_flattened_model(self):
        print("UPDATED FM")
        self._flattened_model.clear()
        for item in _recursive_traverse(self.model_.invisibleRootItem(), get_non_leaf=self.is_main_view):
            self._flattened_model.appendRow(TreeModelItem(item.collection))

    def _initialize_model(self) -> None:
        def _add_children_to_item(root_item_: QStandardItem, root_item_id_: str):
            for collection in get_collections_by_parent_id().get(root_item_id_, []):
                if not self.is_main_view and collection.is_protected:
                    continue
                folder_item = TreeModelItem(collection)
                root_item_.appendRow(folder_item)
                if collection.is_folder:
                    _add_children_to_item(folder_item, collection.id)

        _add_children_to_item(self.model_.invisibleRootItem(), "")
        self._update_flattened_model()  # TODO PASS ROOT ITEM TO MAKE THINGS QUICKER

    def get_model_item(self, collection: Playlist | Folder) -> TreeModelItem:
        return next(
            tree_model_item
            for tree_model_item in _recursive_traverse(self.model_.invisibleRootItem(), get_non_leaf=True)
            if tree_model_item.collection.id == collection.id
        )

    def refresh_playlist(self, playlist: Playlist):
        item = self.get_model_item(playlist)
        item.collection = playlist
        item.update_icon()


class SortRoleAction(QAction):
    def __init__(self, sort_role: SORT_ROLE, playlist_widget: PlaylistTreeWidget, parent: QMenu) -> None:
        super().__init__(sort_role.name.capitalize(), parent)
        self.sort_role = sort_role
        self.triggered.connect(partial(playlist_widget.change_sort_role, sort_role))


class SortMenu(QMenu):
    def __init__(self, parent: PlaylistTreeWidget) -> None:
        super().__init__(parent)
        self.installEventFilter(self)
        self.setStyleSheet("""
            QMenu::item {
                padding: 5px;
                spacing: 0px;
            }
        """)

        self.sort_updated_action = SortRoleAction(SORT_ROLE.UPDATED, parent, self)
        self.sort_played_action = SortRoleAction(SORT_ROLE.PLAYED, parent, self)
        self.sort_alphabetical_action = SortRoleAction(SORT_ROLE.ALPHABETICAL, parent, self)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        self.addActions([self.sort_updated_action, self.sort_played_action, self.sort_alphabetical_action])

        self.update_active_action()

    def parent(self, /) -> PlaylistTreeWidget:
        return cast(PlaylistTreeWidget, super().parent())

    def update_active_action(self):
        curr_sort_role = self.parent().proxy_model.sortRole()
        for action in (
            self.sort_updated_action,
            self.sort_played_action,
            self.sort_alphabetical_action,
        ):
            if action.sort_role.value == curr_sort_role:
                order_str = "up" if self.parent().proxy_model.sortOrder() == Qt.SortOrder.AscendingOrder else "down"
                pm = get_colored_pixmap(QPixmap(f"../icons/arrows/arrow-narrow-{order_str}.svg"), Qt.GlobalColor.white)
                action.setIcon(QIcon(pm))
            else:
                action.setIcon(QIcon())

    def eventFilter(self, watched: QObject, event: QEvent, /) -> bool:
        if event.type() == QEvent.Type.MouseButtonRelease:
            if isinstance(watched, QMenu):
                if action := watched.activeAction():
                    action.trigger()
                    return True
        return super().eventFilter(watched, event)


class AddToPlaylistMenu(QMenu):
    def __init__(
        self, selected_song_indices: list[int], shared_signals: SharedSignals, parent_menu: QMenu, parent: QMainWindow
    ):
        super().__init__("Add to playlist", parent)
        self.parent_menu = parent_menu
        self.signals = shared_signals
        self.playlist_tree_widget = PlaylistTreeWidget(self, parent, self.signals, is_main_view=False)
        self.playlist_tree_widget.tree_view.clicked.connect(
            partial(self.add_items_to_playlist_at_index, selected_song_indices)
        )
        widget_action = QWidgetAction(self)
        widget_action.setDefaultWidget(self.playlist_tree_widget)
        self.addActions(
            [
                widget_action,
                NewPlaylistAction(
                    self, parent, self.playlist_tree_widget.model_.invisibleRootItem().index(), self.signals
                ),
            ]
        )

    def add_items_to_playlist_at_index(self, selected_song_indices: list[int], proxy_index: QModelIndex):
        playlist = self.playlist_tree_widget.item_at_index(proxy_index, is_source=False).collection
        self.signals.add_to_playlist_signal.emit(selected_song_indices, playlist)
        self.parent_menu.close()
