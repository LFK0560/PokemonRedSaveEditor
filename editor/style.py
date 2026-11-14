from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QMessageBox


INK = "#192b2a"
SUBTLE = "#526860"
ACCENT = "#236657"
RED = "#ad3129"
GOLD = "#886323"

STYLES = """
QWidget {
    color: #192b2a;
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
}
QWidget#window, QMainWindow, QDialog { background: #f3f5ef; }
QWidget#masthead, QWidget#context, QWidget#surface {
    background: #ffffff;
}
QWidget#context { border-top: 1px solid #dde5dc; border-bottom: 1px solid #dde5dc; }
QWidget#surface { border: 1px solid #dbe3d9; border-radius: 13px; }
QLabel#appTitle { font-size: 23px; font-weight: 800; color: #193931; }
QLabel#heading { font-size: 23px; font-weight: 800; color: #193931; }
QLabel#section { font-size: 15px; font-weight: 750; color: #234a3d; }
QLabel#muted { color: #526860; }
QLabel#warning { color: #ad3129; }
QLabel#hint { color: #526860; padding: 8px 10px; background: #eaf1ea; border-radius: 7px; }
QLabel#pill { padding: 5px 10px; border-radius: 7px; background: #e4efea; color: #22624d; font-weight: 650; }
QPushButton {
    background: #ffffff; border: 1px solid #bccfc5; border-radius: 8px;
    padding: 7px 13px; min-height: 20px; font-weight: 600;
}
QPushButton:hover { border-color: #236657; background: #eaf4ee; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #397b68; }
QPushButton:disabled { color: #7b8882; background: #eff1ed; border-color: #dbe1d9; }
QPushButton[primary="true"] { color: #fff; background: #225e50; border-color: #225e50; }
QPushButton[primary="true"]:hover { background: #174b3d; }
QPushButton[primary="true"]:disabled { color: #778780; background: #e3eae3; border-color: #d8e0d8; }
QPushButton[link="true"] { color: #236657; border: 0; background: transparent; padding: 4px; }
QPushButton[link="true"]:hover { color: #173f35; text-decoration: underline; }
QPushButton[link="true"]:disabled { color: #7c8880; }
QTabWidget::pane { border: 0; }
QTabBar::tab {
    color: #526860; padding: 10px 17px; border-bottom: 3px solid transparent; font-weight: 650;
}
QTabBar::tab:hover { background: #eaf1e9; }
QTabBar::tab:selected { color: #215e4f; border-bottom-color: #236657; }
QLineEdit, QComboBox, QSpinBox {
    background: #fff; border: 1px solid #bfcfc5; border-radius: 6px;
    padding: 5px 8px; min-height: 19px; selection-background-color: #236657;
}
QComboBox::drop-down { width: 18px; border: 0; }
QComboBox { padding-right: 20px; combobox-popup: 0; }
QComboBox::down-arrow { image: none; width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid #526860; }
QComboBox QAbstractItemView { background: #fff; border: 1px solid #bfcfc5; padding: 3px;
    selection-background-color: #d7ebe0; selection-color: #192b2a; }
QSpinBox:disabled, QLineEdit:disabled { background: #eef2ed; color: #61736a; }
QRadioButton { spacing: 6px; }
QRadioButton::indicator {
    width: 12px; height: 12px; border: 1px solid #789987; border-radius: 7px; background: #fff;
}
QRadioButton::indicator:checked { background: #236657; border-color: #236657; }
QTableWidget, QListWidget {
    border: 1px solid #dce5db; border-radius: 8px; background: #ffffff;
    alternate-background-color: #f6f8f3; outline: 0;
    selection-background-color: #d8ebe1; selection-color: #192b2a;
}
QTableWidget::item, QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #edf1eb; }
QHeaderView::section { padding: 8px; background: #ebf0e9; border: 0; color: #436155; font-weight: 750; }
QGraphicsView { border: 0; border-radius: 9px; background: #dde7dd; }
QProgressBar { border: 0; border-radius: 3px; background: #e5ede5; }
QProgressBar::chunk { border-radius: 3px; background: #4f896b; }
QToolTip { background-color: #fff; color: #192b2a; border: 1px solid #bdd0c5; padding: 5px; }
"""


def label(text: str = "", kind: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if kind:
        widget.setObjectName(kind)
    widget.setWordWrap(wrap)
    return widget


def app_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(QColor("#225e50"))
    painter = QPainter(pix)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#f0f6ef"), 4))
        painter.drawRoundedRect(16, 11, 32, 42, 6, 6)
        painter.drawLine(23, 41, 41, 41)
        painter.drawLine(32, 24, 32, 33)
        painter.drawLine(27, 28, 37, 28)
    finally:
        painter.end()
    return QIcon(pix)


def message(parent, title, text, icon=QMessageBox.Icon.Warning):
    box = QMessageBox(icon, title, str(text), parent=parent)
    ok = box.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(ok)
    box.exec()
