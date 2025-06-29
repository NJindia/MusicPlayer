from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from enum import Enum
from functools import partial
from typing import cast, override

from line_profiler_pycharm import profile  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QSize,
    QSortFilterProxyModel,
    Qt,
    Slot,
    qCritical,
    qFatal,
)
from PySide6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QIcon,
    QMouseEvent,
    QPainter,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from music_player.common_gui import AddToQueueAction, NewFolderAction, NewPlaylistAction
from music_player.constants import ID_ROLE, MAX_SIDE_BAR_WIDTH
from music_player.db_types import DbCollection, get_collections_by_parent_id
from music_player.signals import SharedSignals
from music_player.utils import get_colored_pixmap
from music_player.view_types import LibraryTableView, PlaylistTreeView

PLAYLIST_ROW_HEIGHT = 50


class SortRole(Enum):
    UPDATED = Qt.ItemDataRole.UserRole + 3
    PLAYED = Qt.ItemDataRole.UserRole + 4
    ALPHABETICAL = Qt.ItemDataRole.UserRole + 5


DEFAULT_SORT_ORDER_BY_SORT_ROLE: dict[SortRole, Qt.SortOrder] = {
    SortRole.UPDATED: Qt.SortOrder.DescendingOrder,
    SortRole.PLAYED: Qt.SortOrder.DescendingOrder,
    SortRole.ALPHABETICAL: Qt.SortOrder.AscendingOrder,
}
INITIAL_SORT_ROLE = SortRole.ALPHABETICAL


class TreeItemDelegate(QStyledItemDelegate):
    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex, /) -> QSize:
        default_size = super().sizeHint(option, index)
        return QSize(default_size.width(), PLAYLIST_ROW_HEIGHT)

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex, /):
        super().paint(painter, option, index)
        if cast(PlaylistTree, self.parent()).drop_index_ == index:
            rect = cast(QRect, option.rect)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 5, 5)


class TreeModelItem(QStandardItem):
    def __init__(self, collection: DbCollection) -> None:
        super().__init__(collection.name)
        self.collection: DbCollection = collection

        font = QFont()
        font.setPointSize(14)
        self.setFont(font)  # pyright: ignore[reportUnknownMemberType]
        self.setEditable(False)
        self.update_icon()

    @override
    def data(self, /, role: int = Qt.ItemDataRole.DisplayRole):
        if role == ID_ROLE:
            data_val = self.collection.id
        elif role == PlaylistTreeView.is_folder_role:
            data_val = self.collection.is_folder
        elif role == PlaylistTreeView.is_protected_role:
            data_val = self.collection.is_protected
        elif role == PlaylistTreeView.collection_role:
            data_val = self.collection
        elif role == SortRole.UPDATED.value:
            data_val = self.collection.last_updated.timestamp()
        elif role == SortRole.PLAYED.value:
            last_played = self.collection.last_played
            data_val = (last_played if last_played else datetime.max.replace(tzinfo=UTC)).timestamp()
        elif role == SortRole.ALPHABETICAL.value:
            data_val = self.text().lower() + self.text()
        else:
            data_val = super().data(role)
        return data_val

    def update_icon(self):
        self.setIcon(QIcon(self.collection.get_thumbnail_pixmap(PLAYLIST_ROW_HEIGHT)))

    def sync_item(self, item: "TreeModelItem"):
        self.setText(self.collection.name)
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


class PlaylistProxyModel(QSortFilterProxyModel):
    def __init__(self, source_model: QStandardItemModel, *, is_main_view: bool, folders_only: bool):
        super().__init__()
        self.main_view = is_main_view
        self.folders_only = folders_only

        self._source_model = source_model

        self.setSourceModel(self._source_model)
        self.setSortRole(INITIAL_SORT_ROLE.value)
        self.sort(0)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    @override
    def sourceModel(self) -> QStandardItemModel:
        return self._source_model

    @override
    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex, /) -> bool:
        if self.folders_only or not self.main_view:
            src_parent_item = (
                self.sourceModel().itemFromIndex(source_parent)
                if source_parent.isValid()
                else self.sourceModel().invisibleRootItem()
            )
            child = src_parent_item.child(source_row)
            assert child is not None
            collection = cast(TreeModelItem, child).collection
            if (self.folders_only and not collection.is_folder) or (not self.main_view and collection.is_protected):
                return False
        return super().filterAcceptsRow(source_row, source_parent)

    def data_(self, index: QModelIndex, role: int):
        data = self.data(index, role)
        assert data is not None, (index, role)
        return data


class PlaylistTree(PlaylistTreeView):
    def __init__(self, model: PlaylistProxyModel, shared_signals: SharedSignals, *, is_main_view: bool):
        super().__init__()
        self._signals = shared_signals
        self.is_main_view = is_main_view
        self.drop_index_: QModelIndex | None = None

        self.setUniformRowHeights(True)
        self.setExpandsOnDoubleClick(True)
        self.setAnimated(True)
        self.setSortingEnabled(False)
        self.setHeaderHidden(True)

        self.setIconSize(QSize(PLAYLIST_ROW_HEIGHT, PLAYLIST_ROW_HEIGHT))
        delegate = TreeItemDelegate(self)
        self.setItemDelegate(delegate)
        if self.is_main_view:
            self.setDragDropMode(QTreeView.DragDropMode.DragDrop)
            self.setDragDropOverwriteMode(True)
            self.setAcceptDrops(True)

            self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setModel(model)

    @override
    def model(self, /) -> PlaylistProxyModel:
        return cast(PlaylistProxyModel, super().model())

    @override
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat("application/x-music-ids"):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    @override
    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._reset_drop_index()
        super().dragLeaveEvent(event)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.RightButton:
            super().mousePressEvent(event)

    @override
    def dropEvent(self, event: QDropEvent) -> None:
        if not self.is_main_view:
            qFatal("dropEvent triggered in non-main view PlaylistTree")

        self._reset_drop_index()
        if event.proposedAction() == Qt.DropAction.IgnoreAction:
            return

        drop_index = self.indexAt(event.pos())
        source = event.source()
        if source == self:
            if event.proposedAction() != Qt.DropAction.MoveAction:
                qCritical("If PlaylistTree.dropEvent source is itself, DropAction should always be MoveAction")
            source_index = self.selectedIndexes()[0]
            if not drop_index.isValid() or self.model().data_(drop_index, self.is_folder_role):
                self._signals.move_collection_signal.emit(
                    self.model().mapToSource(source_index), self.model().mapToSource(drop_index)
                )
            else:
                music_ids = cast(DbCollection, self.model().data_(source_index, self.collection_role)).music_ids
                dest_playlist = cast(DbCollection, self.model().data_(drop_index, self.collection_role))
                self._signals.add_to_playlist_signal.emit(music_ids, dest_playlist)
        else:
            if event.proposedAction() != Qt.DropAction.CopyAction:
                qFatal("If PlaylistTree.dropEvent source is not itself, DropAction should always be CopyAction")
            if not isinstance(source, LibraryTableView):
                qFatal("Bad source")
                return
            lib_indices = source.selectionModel().selectedRows()
            music_ids = [source.model().data(lib_index, ID_ROLE) for lib_index in lib_indices]

            if not drop_index.isValid() or self.model().data_(drop_index, self.is_folder_role):
                source_drop_index = self.model().mapToSource(drop_index)
                self._signals.create_playlist_signal.emit("New Playlist", source_drop_index, music_ids)
            else:
                self._signals.add_to_playlist_signal.emit(
                    music_ids, self.model().data_(drop_index, self.collection_role)
                )

    @override
    def dragMoveEvent(self, event: QDragMoveEvent, /):
        def ignore_event():
            event.setDropAction(Qt.DropAction.IgnoreAction)
            event.ignore()
            self._reset_drop_index()

        if not self.is_main_view:
            qFatal("dragMoveEvent triggered in non-main view PlaylistTree")
        drop_index = self.indexAt(event.pos())
        if event.source() == self:
            selected_indices = self.selectedIndexes()
            assert len(selected_indices) == 1
            src_index = selected_indices[0]
            if (
                drop_index == src_index
                or drop_index == src_index.parent()
                or (
                    drop_index.isValid()
                    and (
                        self.model().data_(drop_index, self.is_protected_role)
                        or (
                            self.model().data_(src_index, self.is_protected_role)
                            and self.model().data_(drop_index, self.is_folder_role)
                        )
                    )
                )
            ):
                ignore_event()
                return
            if Qt.DropAction.MoveAction not in event.possibleActions():
                qCritical("Move action should be possible")
            event.setDropAction(Qt.DropAction.MoveAction)
        else:
            if Qt.DropAction.CopyAction not in event.possibleActions():
                qFatal("Copy action should be possible")
            if drop_index.isValid() and self.model().data_(drop_index, self.is_protected_role):
                ignore_event()
                return
            event.setDropAction(Qt.DropAction.CopyAction)
        if drop_index != self.drop_index_:
            self._reset_drop_index()
            self.drop_index_ = drop_index
            if drop_index.isValid():
                self.setStyleSheet("")
                self.viewport().update(self.visualRect(drop_index))
            else:
                print("SETTING")
                self.setStyleSheet("QTreeView { border: 1px solid white; }")
        event.accept()

    def _reset_drop_index(self):
        if self.drop_index_ is None:
            return
        if self.drop_index_.isValid():
            old_idx = self.drop_index_
            self.drop_index_ = None
            self.viewport().update(self.visualRect(old_idx))
        else:
            self.drop_index_ = None
            self.setStyleSheet("")


class PlaylistTreeWidget(QWidget):
    def __init__(  # noqa: PLR0915
        self,
        parent: QWidget,
        main_window: QMainWindow,
        signals: SharedSignals,
        *,
        is_main_view: bool,
        folders_only: bool = False,
        model: QStandardItemModel | None = None,
        flattened_model: QStandardItemModel | None = None,
    ):
        super().__init__(parent)
        self.is_main_view = is_main_view
        self.signals = signals

        self.setStyleSheet("QWidget { margin: 0px; border: none; }")
        self.setMaximumWidth(MAX_SIDE_BAR_WIDTH)

        if self.is_main_view:
            self.model_: QStandardItemModel = QStandardItemModel()
            self.model_.layoutChanged.connect(self._update_flattened_model)  # TODO NECESSARY?
            self.model_.rowsRemoved.connect(self._update_flattened_model)
            self.model_.dataChanged.connect(self.update_playlist)
            self.flattened_model_: QStandardItemModel = QStandardItemModel()
            self.flattened_model_.dataChanged.connect(self.update_playlist)
            self._initialize_model()
        else:
            assert model
            assert flattened_model
            self.model_ = model
            self.flattened_model_ = flattened_model

        self.proxy_model = PlaylistProxyModel(self.model_, is_main_view=is_main_view, folders_only=folders_only)
        self.tree_view = PlaylistTree(self.proxy_model, self.signals, is_main_view=is_main_view)

        header_widget = QWidget()
        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_widget.setLayout(header_layout)
        if self.is_main_view:
            self.signals.move_collection_signal.connect(self.move_collection)

            label = QLabel("Playlists", self)
            label_font = QFont()
            label_font.setPointSize(20)
            label_font.setBold(True)
            label.setFont(label_font)  # pyright: ignore[reportUnknownMemberType]
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

            create_menu = QMenu(self)
            args = create_menu, main_window, self.model_.invisibleRootItem().index(), self.signals
            create_menu.addActions([NewPlaylistAction(*args), NewFolderAction(*args)])  # pyright: ignore[reportUnknownMemberType]

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
        search_bar.setPlaceholderText(f"Search {'folders' if folders_only else 'playlists'}")

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

    @Slot()
    def move_collection(self, source_idx: QModelIndex, destination_parent_idx: QModelIndex):
        assert source_idx.isValid()
        assert self.source_model() == self.model_, "Should not be able to move in flattened model!"

        src_item = self.item_at_index(source_idx, is_source=True)
        src_parent = src_item.parent() if src_item.parent() else self.model_
        dest_parent = (
            self.item_at_index(destination_parent_idx, is_source=True)
            if destination_parent_idx.isValid()
            else self.model_
        )

        child = src_parent.takeRow(source_idx.row())[0]
        assert child is not None
        dest_parent.appendRow(child)  # pyright: ignore[reportUnknownMemberType]

        src_item.collection.parent_id = dest_parent.collection.id if isinstance(dest_parent, TreeModelItem) else -1

    def update_sort_button(self):
        sort_role = SortRole(self.proxy_model.sortRole())
        order_str = "asc" if self.proxy_model.sortOrder() == Qt.SortOrder.AscendingOrder else "desc"
        pm = get_colored_pixmap(
            QPixmap(f"../icons/sort/sort-{'alpha-' if sort_role == SortRole.ALPHABETICAL else ''}{order_str}.svg"),
            Qt.GlobalColor.white,
        )
        self.sort_button.setIcon(QIcon(pm))
        self.sort_button.setText(sort_role.name.capitalize())

    def filter(self, text: str):
        if text == "":  # Revert back to original nested view
            self.proxy_model.setSourceModel(self.model_)
            self.proxy_model.setFilterRegularExpression("")
            return
        self.proxy_model.setSourceModel(self.flattened_model_)
        self.proxy_model.setFilterRegularExpression(rf"\b{text}\w*")

    @Slot(SortRole)
    def change_sort_role(self, sort_role: SortRole) -> None:
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
        return self.proxy_model.sourceModel()

    def item_at_index(self, index: QModelIndex, *, is_source: bool) -> TreeModelItem:
        if not index.isValid():
            raise ValueError
        assert not isinstance(index.model(), QSortFilterProxyModel if is_source else QStandardItemModel)
        item = self.source_model().itemFromIndex(index if is_source else self.proxy_model.mapToSource(index))
        assert isinstance(item, TreeModelItem)
        return item

    def flattened_proxy_index_to_default_model_item(self, proxy_index: QModelIndex) -> TreeModelItem:
        return self.get_model_item(self.item_at_index(proxy_index, is_source=False).collection)

    @Slot()
    def rename_playlist(self, proxy_index: QModelIndex) -> None:
        item = self.item_at_index(proxy_index, is_source=False)
        self.model_.blockSignals(True)  # noqa: FBT003
        item.setEditable(True)
        self.tree_view.edit(proxy_index)
        item.setEditable(False)
        self.model_.blockSignals(False)  # noqa: FBT003

    @Slot()
    def delete_collection(self, proxy_index: QModelIndex) -> None:
        item = self.flattened_proxy_index_to_default_model_item(proxy_index)
        parent = cast(QStandardItem | None, item.parent())
        parent_index = (parent or self.model_.invisibleRootItem()).index()
        self.model_.beginRemoveRows(parent_index, item.row(), item.row())
        (self.model_ if parent is None else parent).removeRow(item.row())

        if item.collection.is_folder:

            def get_recursive_children(parent_id: int) -> Iterator[DbCollection]:
                for collection in get_collections_by_parent_id().get(parent_id, []):
                    if collection.is_folder:
                        yield from get_recursive_children(collection.id)
                    yield collection

            for child in list(get_recursive_children(item.collection.id)):
                self.signals.delete_collection_signal.emit(child)
            get_collections_by_parent_id.cache_clear()
        self.signals.delete_collection_signal.emit(item.collection)
        print("TODO: PUSH CONFIRMATION")

    @Slot()
    def update_playlist(self, tl_source_index: QModelIndex, _: QModelIndex, roles: list[int]) -> None:
        print("UPDATE")
        if not self.is_main_view:
            raise ValueError
        if Qt.ItemDataRole.DisplayRole in roles:
            item = self.item_at_index(tl_source_index, is_source=True)
            item.collection.rename(item.text())

            if self.proxy_model.filterRegularExpression().pattern():
                self.model_.blockSignals(True)  # noqa: FBT003
                self.get_model_item(item.collection).sync_item(item)
                self.model_.blockSignals(False)  # noqa: FBT003
            else:
                self._update_flattened_model()

    @Slot()
    def playlist_context_menu(self, main_window: QMainWindow, point: QPoint):
        proxy_index = self.tree_view.indexAt(point)
        menu = QMenu(self.tree_view)
        source_root_index = self.source_model().invisibleRootItem().index()
        if proxy_index.isValid():
            item = self.item_at_index(proxy_index, is_source=False)

            menu.addAction(AddToQueueAction(item.collection.music_ids, self.signals, menu))
            menu.addSeparator()

            # Set root for adding playlist/folder
            if item.collection.is_folder:  # Folder is a valid root
                source_root_index = self.proxy_model.mapToSource(proxy_index)
            elif (
                (p := item.parent()) is not None  # pyright: ignore[reportUnnecessaryComparison]
            ):  # If not top-level parent *is* None
                assert self.source_model() != self.flattened_model_, "Should only have top-level for flattened!"
                source_root_index = p.index()

            if not item.collection.is_protected:
                rename_action = QAction("Rename", self.tree_view)
                rename_action.triggered.connect(partial(self.rename_playlist, proxy_index))

                delete_action = QAction("Delete", self.tree_view)
                delete_action.triggered.connect(partial(self.delete_collection, proxy_index))

                move_to_folder_menu = MoveToFolderMenu(item.index(), self.signals, menu, main_window, self)

                menu.addActions([rename_action, delete_action])  # pyright: ignore[reportUnknownMemberType]
                menu.addSeparator()
                menu.addMenu(move_to_folder_menu)
            else:
                menu.addSeparator()

            menu.addMenu(AddToPlaylistMenu(item.collection.music_ids, self.signals, menu, main_window, self))

        args = menu, main_window, source_root_index, self.signals
        menu.addSeparator()
        menu.addActions([NewPlaylistAction(*args), NewFolderAction(*args)])  # pyright: ignore[reportUnknownMemberType]

        menu.popup(self.tree_view.mapToGlobal(point))

    def _update_flattened_model(self):
        if not self.is_main_view:
            raise ValueError
        print("UPDATED FM")
        self.flattened_model_.beginResetModel()
        self.flattened_model_.clear()
        for item in _recursive_traverse(self.model_.invisibleRootItem(), get_non_leaf=self.is_main_view):
            self.flattened_model_.appendRow(TreeModelItem(item.collection))  # pyright: ignore[reportUnknownMemberType]
        self.flattened_model_.endResetModel()

    def _initialize_model(self) -> None:
        assert self.is_main_view

        def _add_children_to_item(root_item_: QStandardItem, root_item_id_: int):
            for collection in get_collections_by_parent_id().get(root_item_id_, []):
                item = TreeModelItem(collection)
                root_item_.appendRow(item)  # pyright: ignore[reportUnknownMemberType]
                if collection.is_folder:
                    _add_children_to_item(item, collection.id)

        _add_children_to_item(self.model_.invisibleRootItem(), -1)
        self._update_flattened_model()  # TODO PASS ROOT ITEM TO MAKE THINGS QUICKER

    def get_model_item(self, collection: DbCollection) -> TreeModelItem:
        return next(
            tree_model_item
            for tree_model_item in _recursive_traverse(self.model_.invisibleRootItem(), get_non_leaf=True)
            if tree_model_item.collection.id == collection.id
        )

    @profile
    def refresh_collection(self, collection: DbCollection, affected_sort_role: SortRole):
        item = self.get_model_item(collection)
        item.collection = collection
        item.update_icon()

        if self.proxy_model.sortRole() == affected_sort_role.value:
            self.proxy_model.invalidate()


class SortRoleAction(QAction):
    def __init__(self, sort_role: SortRole, playlist_widget: PlaylistTreeWidget, parent: QMenu) -> None:
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

        self.sort_updated_action = SortRoleAction(SortRole.UPDATED, parent, self)
        self.sort_played_action = SortRoleAction(SortRole.PLAYED, parent, self)
        self.sort_alphabetical_action = SortRoleAction(SortRole.ALPHABETICAL, parent, self)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)

        self.addActions([self.sort_updated_action, self.sort_played_action, self.sort_alphabetical_action])  # pyright: ignore[reportUnknownMemberType]

        self.update_active_action()

    @override
    def parent(self, /) -> PlaylistTreeWidget:
        return cast(PlaylistTreeWidget, super().parent())

    @override
    def eventFilter(self, watched: QObject, event: QEvent, /) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and isinstance(watched, QMenu)
            and (action := watched.activeAction())
        ):
            action.trigger()
            return True
        return super().eventFilter(watched, event)

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


class MoveToFolderMenu(QMenu):
    def __init__(
        self,
        source_index: QModelIndex,
        shared_signals: SharedSignals,
        parent_menu: QMenu,
        parent: QMainWindow,
        main_playlist_view: PlaylistTreeWidget,
    ):
        super().__init__("Move to folder", parent)
        self.parent_menu = parent_menu
        self.signals = shared_signals

        self.playlist_tree_widget = PlaylistTreeWidget(
            self,
            parent,
            self.signals,
            is_main_view=False,
            folders_only=True,
            model=main_playlist_view.model_,
            flattened_model=main_playlist_view.flattened_model_,
        )
        self.playlist_tree_widget.tree_view.clicked.connect(partial(self.adjust_root_index, source_index))
        widget_action = QWidgetAction(self)
        widget_action.setDefaultWidget(self.playlist_tree_widget)
        self.addAction(widget_action)

        if source_index.parent().isValid():  # If not top-level, allow removing from folders
            remove_from_folders_action = QAction("Remove from folders", self)
            remove_from_folders_action.triggered.connect(partial(self.adjust_root_index, source_index, QModelIndex()))
            self.addAction(remove_from_folders_action)

        new_folder_action = NewFolderAction(
            self,
            parent,
            self.playlist_tree_widget.model_.invisibleRootItem().index(),
            self.signals,
            move_collection_from_index=source_index,
        )
        self.addAction(new_folder_action)

    def adjust_root_index(self, source_index: QModelIndex, proxy_root_index: QModelIndex):
        dest_index = self.playlist_tree_widget.proxy_model.mapToSource(proxy_root_index)
        self.signals.move_collection_signal.emit(source_index, dest_index)
        self.parent_menu.close()


class AddToPlaylistMenu(QMenu):
    def __init__(
        self,
        selected_music_ids: Sequence[int],
        shared_signals: SharedSignals,
        parent_menu: QMenu,
        parent: QMainWindow,
        main_playlist_view: PlaylistTreeWidget,
    ):
        super().__init__("Add to playlist", parent)
        self.parent_menu = parent_menu
        self.signals = shared_signals

        self.playlist_tree_widget = PlaylistTreeWidget(
            self,
            parent,
            self.signals,
            is_main_view=False,
            model=main_playlist_view.model_,
            flattened_model=main_playlist_view.flattened_model_,
        )
        self.playlist_tree_widget.tree_view.clicked.connect(
            partial(self.add_items_to_playlist_at_index, selected_music_ids)
        )
        widget_action = QWidgetAction(self)
        widget_action.setDefaultWidget(self.playlist_tree_widget)

        new_playlist_action = NewPlaylistAction(
            self,
            parent,
            self.playlist_tree_widget.model_.invisibleRootItem().index(),
            self.signals,
            selected_music_ids,
        )

        self.addActions([widget_action, new_playlist_action])  # pyright: ignore[reportUnknownMemberType]

    def add_items_to_playlist_at_index(self, selected_music_ids: Sequence[int], proxy_index: QModelIndex):
        playlist = self.playlist_tree_widget.item_at_index(proxy_index, is_source=False).collection
        self.signals.add_to_playlist_signal.emit(selected_music_ids, playlist)
        self.parent_menu.close()
