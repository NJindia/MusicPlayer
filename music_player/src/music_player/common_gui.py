from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast, override

from line_profiler_pycharm import profile  # pyright: ignore[reportMissingTypeStubs, reportUnknownVariableType]
from PySide6.QtCore import (
    QAbstractAnimation,
    QByteArray,
    QEasingCurve,
    QEvent,
    QModelIndex,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    SignalInstance,
)
from PySide6.QtGui import QAction, QDrag, QEnterEvent, QFont, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyleOptionGraphicsItem,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from music_player.constants import TOOLBAR_HEIGHT
from music_player.signals import SharedSignals
from music_player.utils import get_pixmap

BUFFER_CHARS = {",", " ", "…"}
CreateMode = Literal["playlist", "folder"]


def get_artist_text_rect_text_tups(artists: list[str], text_rect: QRect, font_metrics: QFontMetrics):
    v_space = int((text_rect.height() - font_metrics.height() - 2) / 2)
    text_rect.adjust(0, v_space, 0, -v_space)

    text = ", ".join(artists)
    elided_text = font_metrics.elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width())
    unconsumed_start_idx: int = 0
    text_rect_text_tups: list[tuple[QRect, str, str]] = []
    for artist in artists:
        if unconsumed_start_idx == len(elided_text):
            break
        elided_artist_text = (
            artist
            if artist in elided_text[unconsumed_start_idx:]
            else elided_text[unconsumed_start_idx : len(elided_text) - 1]
        )
        unconsumed_start_idx += len(elided_artist_text)
        text_size = font_metrics.boundingRect(elided_artist_text).size()
        h_space = (text_rect.width() - text_size.width()) - 2
        artist_rect = text_rect.adjusted(0, 0, -h_space, 0)
        text_rect_text_tups.append((artist_rect, artist, elided_artist_text))
        text_rect.setLeft(artist_rect.right() + 1)

        if unconsumed_start_idx == len(elided_text):
            break
        if elided_text[unconsumed_start_idx] in [",", "…"]:  # Elide can cut off comma
            buffer_text_idx = next(
                (
                    i
                    for i, c in enumerate(elided_text[unconsumed_start_idx:], start=unconsumed_start_idx)
                    if c not in BUFFER_CHARS
                ),
                len(elided_text),
            )
            buffer_text = elided_text[unconsumed_start_idx:buffer_text_idx]
            comma_text_width = font_metrics.horizontalAdvance(buffer_text)
            comma_rect = text_rect.adjusted(0, 0, -(text_rect.width() - comma_text_width - 2), 0)
            unconsumed_start_idx += len(buffer_text)
            text_rect.setLeft(comma_rect.right())
            text_rect_text_tups.append((comma_rect, "", buffer_text))
    return text_rect_text_tups


@profile
def paint_artists(
    artists: list[str],
    painter: QPainter,
    option: QStyleOptionViewItem | QStyleOptionGraphicsItem,
    text_rect: QRect,
    font: QFont,
    hover_condition: Callable[[QRect], bool],
) -> list[QRect]:
    font_metrics = cast(QFontMetrics, option.fontMetrics)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]

    text_flag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter  # TODO SINGLE LINE?
    found_hovered: bool = False
    text_rects: list[QRect] = []
    for artist_text_rect, _, text in get_artist_text_rect_text_tups(artists, text_rect, font_metrics):
        text_rects.append(artist_text_rect)
        if not found_hovered and not text_is_buffer(text) and hover_condition(artist_text_rect):
            found_hovered = True
            font.setUnderline(True)
        else:
            font.setUnderline(False)
        painter.save()
        painter.setFont(font)  # pyright: ignore[reportUnknownMemberType]

        painter.drawText(artist_text_rect, text_flag, text)
        painter.restore()

    return text_rects


def text_is_buffer(text: str) -> bool:
    return not bool(len(set(text) - set(BUFFER_CHARS)))


class NewPlaylistAction(QAction):
    def __init__(
        self,
        parent: QMenu,
        main_window: QMainWindow,
        source_root_index: QModelIndex,
        signals: SharedSignals,
        music_ids_to_add: Sequence[int] | None = None,
    ) -> None:
        super().__init__("New playlist", parent)
        self.triggered.connect(
            lambda: _CreateDialog(
                main_window, source_root_index, signals, mode="playlist", music_ids_to_add=music_ids_to_add
            ).exec()
        )


class NewFolderAction(QAction):
    def __init__(
        self,
        parent: QMenu,
        main_window: QMainWindow,
        source_root_index: QModelIndex,
        signals: SharedSignals,
        move_collection_from_index: QModelIndex | None = None,
    ) -> None:
        super().__init__("New folder", parent)
        self.triggered.connect(
            lambda: _CreateDialog(
                main_window, source_root_index, signals, mode="folder", move_from_index=move_collection_from_index
            ).exec()
        )


def get_play_button_icon(height: int | None = None) -> QIcon:
    return QIcon(get_pixmap(Path("../icons/play-button.svg"), height, color=Qt.GlobalColor.white))


def get_pause_button_icon(height: int | None = None) -> QIcon:
    return QIcon(get_pixmap(Path("../icons/pause-button.svg"), height, color=Qt.GlobalColor.white))


class AddToQueueAction(QAction):
    def __init__(self, selected_song_db_indices: Sequence[int], signals: SharedSignals, parent: QMenu):
        super().__init__("Add to queue", parent)
        self.triggered.connect(partial(signals.add_to_queue_signal.emit, selected_song_db_indices, 0, True))  # noqa: FBT003


class OpacityButton(QToolButton):
    button_off_opacity = 0.5

    def __init__(self):
        super().__init__()
        self.setObjectName("OpacityButton")
        self.graphics_effect = QGraphicsOpacityEffect(self)
        self.graphics_effect.setOpacity(self.button_off_opacity)
        self.setGraphicsEffect(self.graphics_effect)
        self.setCheckable(True)

    def button_on(self):
        self.graphics_effect.setOpacity(1)
        self.setChecked(True)

    def button_off(self):
        self.graphics_effect.setOpacity(self.button_off_opacity)
        self.setChecked(False)


class ShuffleButton(OpacityButton):
    def __init__(self, signals: SharedSignals, height: int | None = None):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setIcon(QIcon(get_pixmap(Path("../icons/shuffle-button.svg"), height, color=Qt.GlobalColor.white)))
        self.clicked.connect(partial(self._clicked, signals.toggle_shuffle_signal))

    def _clicked(self, shuffle_signal: SignalInstance):
        shuffle_signal.emit(self.isChecked())


class SongDrag(QDrag):
    def __init__(self, source: QObject, drag_text: str):
        super().__init__(source)
        self.setHotSpot(QPoint(-20, 0))

        font_metrics = QFontMetrics(QFont())
        size = QSize(font_metrics.horizontalAdvance(drag_text) + 2, font_metrics.height() + 2)

        pixmap = QPixmap(size)
        painter = QPainter(pixmap)
        painter.setPen(Qt.GlobalColor.black)
        painter.setBrush(Qt.GlobalColor.white)

        rect = QRect(0, 0, size.width(), size.height())
        painter.drawRect(rect)
        painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, drag_text)
        painter.end()

        self.setPixmap(pixmap)


class _TempMainDialog(QDialog):
    def __init__(self, parent: QMainWindow):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, on=True)


class _CreateDialog(_TempMainDialog):
    def __init__(
        self,
        parent: QMainWindow,
        source_root_index: QModelIndex,
        signals: SharedSignals,
        mode: CreateMode,
        move_from_index: QModelIndex | None = None,
        music_ids_to_add: Sequence[int] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("InteractiveDialogue")
        self.source_root_index = source_root_index
        self.signals = signals
        self.mode = mode

        header = QLabel(f"New {self.mode.capitalize()}", self)
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        header.setFont(font)  # pyright: ignore[reportUnknownMemberType]

        header_layout = QHBoxLayout()
        header_layout.addWidget(header)
        header_layout.addStretch()
        header_layout.addWidget(CloseButton(self, self.close))

        self.name = QLineEdit(self)
        self.name.setPlaceholderText(f"{self.mode.capitalize()} name")
        self.name.textChanged.connect(self.update_confirm_button)

        self.confirm_button = QPushButton(self)
        self.confirm_button.setEnabled(False)
        self.confirm_button.setText("Create")
        self.confirm_button.released.connect(partial(self.create_clicked, move_from_index, music_ids_to_add))

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.confirm_button)

        main_layout = QVBoxLayout()
        main_layout.addLayout(header_layout)
        main_layout.addWidget(self.name)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

    def update_confirm_button(self, text: str) -> None:
        self.confirm_button.setEnabled(bool(text))

    def create_clicked(self, move_from_index: QModelIndex | None, music_ids_to_add: Sequence[int] | None) -> None:
        base_args = self.name.text(), self.source_root_index
        match self.mode:
            case "playlist":
                assert move_from_index is None
                self.signals.create_playlist_signal.emit(*base_args, music_ids_to_add or [])
            case "folder":
                assert music_ids_to_add is None
                self.signals.create_folder_signal.emit(*base_args, move_from_index or QModelIndex())
            case _:
                raise ValueError(f"Unknown mode: {self.mode}")
        self.close()


class CloseButton(QPushButton):
    def __init__(self, parent: QWidget, clicked_connect: Callable[[], Any]):
        super().__init__(parent)
        self.setObjectName("CloseButton")
        self.setText("X")
        self.clicked.connect(clicked_connect)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class ConfirmationDialog(_TempMainDialog):
    def __init__(
        self,
        parent: QMainWindow,
        header: str,
        confirmation_text: str,
        confirm_button_text: str,
        confirm_action: Callable[[], None],
    ):
        super().__init__(parent)
        self.setObjectName("InteractiveDialogue")

        header_label = QLabel(header, self)
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        header_label.setFont(font)  # pyright: ignore[reportUnknownMemberType]

        confirm_label = QLabel(confirmation_text, self, textFormat=Qt.TextFormat.RichText)

        cancel_button = QPushButton(self)
        cancel_button.setText("Cancel")
        cancel_button.clicked.connect(self.close)

        confirm_button = QPushButton(self)
        confirm_button.setText(confirm_button_text)
        confirm_button.clicked.connect(partial(self.confirm_clicked, confirm_action))
        confirm_button.setFocus()

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(confirm_button)

        main_layout = QVBoxLayout()
        main_layout.addWidget(header_label)
        main_layout.addWidget(confirm_label)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

    def confirm_clicked(self, confirm_action: Callable[[], None]) -> None:
        confirm_action()
        self.close()


class WarningPopup(QWidget):
    def __init__(self, parent: QMainWindow, warning_text: str):
        super().__init__(parent)
        self.setMouseTracking(True)

        self.label = QLabel(warning_text, self)
        self.label.setObjectName("WarningLabel")

        self.graphics_effect = QGraphicsOpacityEffect(self.label)
        self.label.setGraphicsEffect(self.graphics_effect)
        self.label.setAutoFillBackground(True)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label, alignment=Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        self.setLayout(layout)

        self.animation = QPropertyAnimation(self.graphics_effect, QByteArray.fromStdString("opacity"), self)
        self.animation.setDuration(3000)
        self.animation.setStartValue(1)
        self.animation.setEndValue(0)
        self.animation.setEasingCurve(QEasingCurve.Type.InCirc)
        self.animation.finished.connect(self.close)

    @override
    def parent(self) -> QMainWindow:
        return cast(QMainWindow, super().parent())

    @override
    def show(self, /):
        rect = self.parent().rect()
        label_size = self.label.sizeHint()
        w_adj = (rect.width() - label_size.width()) // 2
        h_adj = rect.height() - label_size.height() - TOOLBAR_HEIGHT
        self.setGeometry(rect.adjusted(w_adj, h_adj, -w_adj, -TOOLBAR_HEIGHT))
        self.animation.start(QAbstractAnimation.DeletionPolicy.KeepWhenStopped)
        super().show()

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        self.animation.stop()
        self.graphics_effect.setOpacity(1)
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent, /):
        self.animation.start()
        super().leaveEvent(event)


class TextScrollArea(QScrollArea):
    scroll_rate = 100

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.label = QLabel(self)
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self.setWidget(self.label)
        self.animation = QPropertyAnimation(self.horizontalScrollBar(), QByteArray.fromStdString("value"), self)
        self.animation.finished.connect(self.reverse_animation)

        self.horizontalScrollBar().rangeChanged.connect(self.update_animation)

    @override
    def enterEvent(self, event: QEnterEvent) -> None:
        if self.animation.state() == QAbstractAnimation.State.Running:
            self.animation.pause()
        super().enterEvent(event)

    @override
    def leaveEvent(self, event: QEvent, /):
        if self.animation.state() == QAbstractAnimation.State.Paused:
            self.animation.resume()
        super().leaveEvent(event)

    def update_animation(self, new_start: int, new_end: int) -> None:
        if new_start == new_end == 0:
            self.animation.stop()
        else:
            self.animation.setStartValue(new_start)
            self.animation.setEndValue(new_end)
            self.animation.setDuration((new_end - new_start) * self.scroll_rate)
            self.animation.start()

    def reverse_animation(self) -> None:
        direction = (
            QAbstractAnimation.Direction.Backward
            if self.animation.direction() == QAbstractAnimation.Direction.Forward
            else QAbstractAnimation.Direction.Forward
        )
        self.animation.setDirection(direction)
        self.animation.start()

    def set_text(self, text: str):
        self.animation.stop()
        self.label.setText(text)
