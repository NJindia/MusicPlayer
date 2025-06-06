from typing import Callable, Literal

from PySide6.QtCore import QRect, Qt, QModelIndex
from PySide6.QtGui import QPainter, QFont, QFontMetrics, QAction
from PySide6.QtWidgets import (
    QMainWindow,
    QMenu,
    QStyleOptionViewItem,
    QStyleOptionGraphicsItem,
    QDialog,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QHBoxLayout,
    QLabel,
)

from music_player.signals import SharedSignals

BUFFER_CHARS = {",", " ", "…"}
CreateMode = Literal["playlist", "folder"]


def get_artist_text_rect_text_tups(artists: list[str], text_rect: QRect, font_metrics: QFontMetrics):
    v_space = int((text_rect.height() - font_metrics.height() - 2) / 2)
    text_rect.adjust(0, v_space, 0, -v_space)

    text = ", ".join(artists)
    elided_text = font_metrics.elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width())
    unconsumed_start_idx: int = 0
    text_rect_text_tups: list[tuple[QRect, str, str]] = []
    for i, artist in enumerate(artists):
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


def paint_artists(
    artists: list[str],
    painter: QPainter,
    option: QStyleOptionViewItem | QStyleOptionGraphicsItem,
    text_rect: QRect,
    font: QFont,
    hover_condition: Callable[[QRect], bool],
) -> list[QRect]:
    font_metrics: QFontMetrics = option.fontMetrics  # pyright: ignore[reportAttributeAccessIssue]

    text_flag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter  # TODO SINGLE LINE?
    found_hovered: bool = False
    text_rects: list[QRect] = []
    for text_rect, _, text in get_artist_text_rect_text_tups(artists, text_rect, font_metrics):
        text_rects.append(text_rect)
        if not found_hovered and not text_is_buffer(text) and hover_condition(text_rect):
            found_hovered = True
            font.setUnderline(True)
        else:
            font.setUnderline(False)
        painter.save()
        painter.setFont(font)

        painter.drawText(text_rect, text_flag, text)
        painter.restore()

    return text_rects


def text_is_buffer(text: str) -> bool:
    return not bool(len(set(text) - set(BUFFER_CHARS)))


class CreateDialog(QDialog):
    def __init__(self, parent: QMainWindow, root_index: QModelIndex, signals: SharedSignals, mode: CreateMode) -> None:
        super().__init__(parent)
        self.root_index = root_index
        self.signals = signals
        self.mode = mode

        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("QDialog { border-radius: 5px; border: 1px solid white; }")

        header = QLabel(f"New {self.mode.capitalize()}", self)
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        header.setFont(font)

        close_button = QPushButton(self)
        close_button.setText("X")
        close_button.setStyleSheet("QPushButton { border: none; }")
        close_button.clicked.connect(self.close)

        header_layout = QHBoxLayout()
        header_layout.addWidget(header)
        header_layout.addStretch()
        header_layout.addWidget(close_button)

        self.name = QLineEdit(self)
        self.name.setPlaceholderText(f"{self.mode.capitalize()} name")

        confirm_button = QPushButton(self)
        confirm_button.setText("Create")
        confirm_button.setStyleSheet("QPushButton { border-radius: 5px; }")
        confirm_button.released.connect(self.create_clicked)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(confirm_button)

        main_layout = QVBoxLayout()
        main_layout.addLayout(header_layout)
        main_layout.addWidget(self.name)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

    def create_clicked(self):
        match self.mode:
            case "playlist":
                signal = self.signals.create_playlist_signal
            case "folder":
                signal = self.signals.create_folder_signal
            case _:
                raise ValueError(f"Unknown mode: {self.mode}")
        signal.emit(self.name.text(), self.root_index)
        self.close()


class NewPlaylistAction(QAction):
    def __init__(
        self, parent: QMenu, main_window: QMainWindow, root_index: QModelIndex, signals: SharedSignals
    ) -> None:
        super().__init__("New playlist", parent)
        dialog = CreateDialog(main_window, root_index, signals, mode="playlist")
        self.triggered.connect(lambda: dialog.exec())


class NewFolderAction(QAction):
    def __init__(
        self, parent: QMenu, main_window: QMainWindow, root_index: QModelIndex, signals: SharedSignals
    ) -> None:
        super().__init__("New folder", parent)
        dialog = CreateDialog(main_window, root_index, signals, mode="folder")
        self.triggered.connect(lambda: dialog.exec())
