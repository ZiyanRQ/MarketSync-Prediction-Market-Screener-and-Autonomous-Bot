"""Terminal theme: charcoal surfaces, thin borders, compact dense controls.

One QSS string plus the semantic colours the models use for red/green/amber
meaning. Deliberately flat — no rounded cards, gradients, or shadows.
"""

from __future__ import annotations

# Semantic colours (hex) used by table models / charts.
POS = "#3fb950"     # profit / safe
NEG = "#f85149"     # loss / skip
WARN = "#d29922"    # thin / caution
FAV = "#e3b341"     # star
MUTED = "#8b949e"   # secondary text
ACCENT = "#58a6ff"  # selection / links
GRID = "#1c2128"

BG = "#0d1117"
PANEL = "#161b22"
ROW_ALT = "#12161c"
BORDER = "#30363d"
TEXT = "#c9d1d9"

QSS = f"""
* {{
    font-family: "Consolas", "Cascadia Mono", "DejaVu Sans Mono", monospace;
    font-size: 12px;
}}
QMainWindow, QWidget {{ background: {BG}; color: {TEXT}; }}
QToolBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; spacing: 4px; padding: 2px; }}
QToolBar QToolButton {{ padding: 3px 8px; border: 1px solid transparent; }}
QToolBar QToolButton:hover {{ border: 1px solid {BORDER}; background: {GRID}; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QStatusBar QLabel {{ padding: 0 6px; }}
QDockWidget {{ titlebar-close-icon: none; font-size: 11px; }}
QDockWidget::title {{ background: {PANEL}; padding: 3px 6px; border-bottom: 1px solid {BORDER};
    text-transform: uppercase; letter-spacing: 1px; color: {MUTED}; }}
QTableView, QTreeView, QListView {{ background: {BG}; alternate-background-color: {ROW_ALT};
    gridline-color: {GRID}; border: 1px solid {BORDER}; selection-background-color: #1f2d3d;
    selection-color: #ffffff; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; border: none;
    border-right: 1px solid {GRID}; border-bottom: 1px solid {BORDER};
    padding: 3px 6px; font-weight: bold; }}
QTableView {{ font-variant-numeric: tabular-nums; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; }}
QTabBar::tab {{ background: {PANEL}; padding: 4px 10px; border: 1px solid {BORDER};
    border-bottom: none; color: {MUTED}; }}
QTabBar::tab:selected {{ background: {BG}; color: {TEXT}; }}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{ background: {BG}; border: 1px solid {BORDER};
    padding: 2px 4px; selection-background-color: {ACCENT}; }}
QComboBox::drop-down {{ border-left: 1px solid {BORDER}; width: 16px; }}
QPushButton {{ background: {PANEL}; border: 1px solid {BORDER}; padding: 3px 10px; }}
QPushButton:hover {{ background: {GRID}; }}
QPushButton:pressed {{ background: #22272e; }}
QPushButton:checked {{ background: #1f2d3d; border-color: {ACCENT}; color: #ffffff; }}
QLabel[role="hdr"] {{ color: {MUTED}; text-transform: uppercase; letter-spacing: 1px;
    font-size: 10px; }}
QLabel[role="value"] {{ font-weight: bold; }}
QLabel[role="hint"] {{ color: {MUTED}; font-size: 11px; }}
QGroupBox {{ border: 1px solid {BORDER}; margin-top: 10px; padding: 6px 6px 4px 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px;
    color: {MUTED}; text-transform: uppercase; letter-spacing: 1px; font-size: 10px; }}
QFrame#tile {{ border: 1px solid {BORDER}; background: {PANEL}; }}
QLabel#tileHdr {{ color: {MUTED}; font-size: 9px; letter-spacing: 1px; }}
QLabel#tileVal {{ font-size: 15px; font-weight: bold; }}
QPushButton#botToggle {{ font-size: 13px; font-weight: bold; padding: 5px 16px; }}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: #1f2d3d; }}
QSplitter::handle {{ background: {BORDER}; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; min-height: 20px; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; min-width: 20px; }}
QSlider::groove:horizontal {{ height: 3px; background: {BORDER}; }}
QSlider::handle:horizontal {{ background: {ACCENT}; width: 10px; margin: -5px 0; }}
"""
