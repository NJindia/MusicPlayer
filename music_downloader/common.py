from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget


class HoverableUnderlineLabel(QLabel):
    clicked = Signal(QEvent)

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setMouseTracking(True)
        self.setText(text)

    def leaveEvent(self, event: QEvent | None) -> None:
        f = self.font()
        f.setUnderline(False)
        self.setFont(f)

    def enterEvent(self, event: QEvent | None) -> None:
        f = self.font()
        f.setUnderline(True)
        self.setFont(f)

    def mousePressEvent(self, event: QEvent | None) -> None:
        self.clicked.emit(event)
