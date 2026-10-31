"""Sayso's look: dark Ink surfaces, Ember accent, Tide for "thinking". Original palette and shapes."""

from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

INK = "#14162B"
INK_2 = "#1E2140"
EMBER = "#FF7A59"
TIDE = "#5CC8B8"
MIST = "#E9EBF5"
DANGER = "#FF5C7A"
SUCCESS = "#5CD68A"
MUTED = "#9094B5"
BORDER = "#2C3057"

FONT_FAMILY = "Segoe UI Variable Text"
FONT_FALLBACK = "Segoe UI"
SPACING = (4, 8, 12, 16, 24)
RADIUS = 10
OVERLAY_RADIUS = 18


def qcolor(hex_color: str, alpha: float = 1.0) -> QColor:
    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


def stylesheet() -> str:
    return f"""
* {{ font-family: "{FONT_FAMILY}", "{FONT_FALLBACK}", sans-serif; font-size: 13px; }}
QDialog, QWidget#surface, QMainWindow {{ background: {INK}; color: {MIST}; }}
QLabel {{ color: {MIST}; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[heading="true"] {{ font-size: 18px; font-weight: 600; }}
QToolTip {{ background: {INK_2}; color: {MIST}; border: 1px solid {BORDER}; padding: 4px 8px; border-radius: 6px; }}
QPushButton {{ background: {INK_2}; color: {MIST}; border: 1px solid {BORDER}; border-radius: {RADIUS}px;
  padding: 7px 16px; }}
QPushButton:hover {{ border-color: {EMBER}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {INK_2}; }}
QPushButton[primary="true"] {{ background: {EMBER}; color: {INK}; border: none; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: #FF8E72; }}
QPushButton[danger="true"] {{ color: {DANGER}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{ background: {INK_2}; color: {MIST};
  border: 1px solid {BORDER}; border-radius: {RADIUS}px; padding: 6px 10px; selection-background-color: {EMBER};
  selection-color: {INK}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {EMBER}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {MUTED}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {INK_2}; color: {MIST}; selection-background-color: {EMBER};
  selection-color: {INK}; border: 1px solid {BORDER}; }}
QCheckBox {{ spacing: 8px; color: {MIST}; }}
QCheckBox:disabled {{ color: {MUTED}; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER}; background: {INK_2}; }}
QCheckBox::indicator:checked {{ background: {EMBER}; border-color: {EMBER}; }}
QListView, QListWidget, QTableWidget, QTreeWidget {{ background: {INK_2}; color: {MIST}; border: 1px solid {BORDER};
  border-radius: {RADIUS}px; outline: none; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {BORDER}; color: {MIST}; }}
QHeaderView::section {{ background: {INK}; color: {MUTED}; border: none; padding: 6px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: {RADIUS}px; }}
QTabBar::tab {{ padding: 8px 14px; color: {MUTED}; }}
QTabBar::tab:selected {{ color: {MIST}; border-bottom: 2px solid {EMBER}; }}
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {EMBER}; width: 16px; margin: -6px 0; border-radius: 8px; }}
QProgressBar {{ background: {INK_2}; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {TIDE}; border-radius: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 24px; }}
QMenu {{ background: {INK_2}; color: {MIST}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {BORDER}; }}
QMenu::item:disabled {{ color: {MUTED}; }}
"""


def dark_palette() -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: INK,
        QPalette.ColorRole.WindowText: MIST,
        QPalette.ColorRole.Base: INK_2,
        QPalette.ColorRole.AlternateBase: INK,
        QPalette.ColorRole.Text: MIST,
        QPalette.ColorRole.Button: INK_2,
        QPalette.ColorRole.ButtonText: MIST,
        QPalette.ColorRole.Highlight: EMBER,
        QPalette.ColorRole.HighlightedText: INK,
        QPalette.ColorRole.ToolTipBase: INK_2,
        QPalette.ColorRole.ToolTipText: MIST,
        QPalette.ColorRole.PlaceholderText: MUTED,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    return p


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setFont(QFont(FONT_FAMILY if sys.platform == "win32" else FONT_FALLBACK, 10))
    app.setStyleSheet(stylesheet())


def style_title_bar(widget: QWidget) -> None:
    """Dark title bar and Mica backdrop on Windows 11; silently skipped elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        from sayso.winsys import win32

        hwnd = int(widget.winId())
        one, mica = ctypes.c_int(1), ctypes.c_int(2)
        win32.dwmapi().DwmSetWindowAttribute(hwnd, 20, ctypes.byref(one), 4)
        win32.dwmapi().DwmSetWindowAttribute(hwnd, 38, ctypes.byref(mica), 4)
    except Exception:
        pass


def set_prop(widget: QWidget, name: str, value: object = True) -> QWidget:
    widget.setProperty(name, value)
    return widget
