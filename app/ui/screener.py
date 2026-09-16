"""Arbitrage screener — the visual hero.

A dense QTableView over a custom QAbstractTableModel, filtered locally by a
QSortFilterProxyModel that combines the active risk profile's gates with the
filter toolbar. No data is refetched when filters or risk change.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
                            Qt, Signal)
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMenu, QPushButton, QTableView,
                               QVBoxLayout, QWidget)

from ..models.enums import RiskLevel
from ..models.opportunity import Opportunity
from ..services.risk_engine import RiskEngine
from ..utils import formatting as fmt
from . import style


def _start(opp: Opportunity) -> str:
    return "IN-PLAY" if opp.market.in_play else opp.market.start_time.strftime("%H:%M")


class _Col:
    __slots__ = ("title", "width", "right", "disp", "sort", "color")

    def __init__(self, title, width, right, disp, sort, color=None):
        self.title, self.width, self.right = title, width, right
        self.disp, self.sort, self.color = disp, sort, color


def _quality_color(opp):
    q = opp.quality.total
    return style.POS if q >= 80 else style.WARN if q >= 50 else style.NEG


def _edge_color(value):
    return style.POS if value > 0 else style.NEG


def _status_color(opp):
    return {"LIVE": style.POS, "THIN": style.WARN}.get(opp.status.value, style.MUTED)


def _risk_color(opp):
    return {RiskLevel.SAFE: style.POS, RiskLevel.THIN: style.WARN}.get(opp.risk, style.NEG)


# Column table — display, sort key and optional colour per field.
COLUMNS: List[_Col] = [
    _Col("★", 24, False, lambda o: "★" if o.favourite else "", lambda o: o.favourite,
         lambda o: style.FAV if o.favourite else None),
    _Col("STATUS", 58, False, lambda o: o.status.value, lambda o: o.status.value, _status_color),
    _Col("SPORT", 78, False, lambda o: o.market.sport.value, lambda o: o.market.sport.value),
    _Col("LEAGUE", 96, False, lambda o: o.market.league, lambda o: o.market.league),
    _Col("EVENT", 168, False, lambda o: o.market.event, lambda o: o.market.event),
    _Col("START", 60, False, _start, lambda o: o.market.start_time.timestamp()),
    _Col("MARKET", 90, False, lambda o: o.market.market_name, lambda o: o.market.market_name),
    _Col("SELECTION", 110, False, lambda o: o.market.selection, lambda o: o.market.selection),
    _Col("BF BACK", 62, True, lambda o: fmt.odds(o.market.betfair.best_back),
         lambda o: o.market.betfair.best_back or 0),
    _Col("BF LAY", 62, True, lambda o: fmt.odds(o.market.betfair.best_lay),
         lambda o: o.market.betfair.best_lay or 0),
    _Col("MB BACK", 62, True, lambda o: fmt.odds(o.market.matchbook.best_back),
         lambda o: o.market.matchbook.best_back or 0),
    _Col("MB LAY", 62, True, lambda o: fmt.odds(o.market.matchbook.best_lay),
         lambda o: o.market.matchbook.best_lay or 0),
    _Col("DIRECTION", 108, False, lambda o: o.direction.value, lambda o: o.direction.value),
    _Col("LIQ", 62, True, lambda o: fmt.money_short(o.liquidity), lambda o: o.liquidity),
    _Col("GROSS%", 62, True, lambda o: fmt.pct(o.gross_edge), lambda o: o.gross_edge,
         lambda o: _edge_color(o.gross_edge)),
    _Col("NET%", 62, True, lambda o: fmt.pct(o.net_edge), lambda o: o.net_edge,
         lambda o: _edge_color(o.net_edge)),
    _Col("BUF", 54, True, lambda o: fmt.pct(-o.safety_buffer), lambda o: o.safety_buffer),
    _Col("BUF.EDGE%", 70, True, lambda o: fmt.pct(o.buffered_edge), lambda o: o.buffered_edge,
         lambda o: _edge_color(o.buffered_edge)),
    _Col("EST £", 60, True, lambda o: fmt.money(max(0.0, o.net_edge)), lambda o: o.net_edge),
    _Col("AGE", 48, True, lambda o: fmt.age(o.age_seconds), lambda o: o.age_seconds),
    _Col("QUAL", 46, True, lambda o: f"{o.quality.total:.0f}", lambda o: o.quality.total,
         _quality_color),
    _Col("P.AGE", 50, True, lambda o: fmt.age(o.price_age), lambda o: o.price_age,
         lambda o: style.WARN if o.price_age > 30 else None),
    _Col("VOL%", 52, True, lambda o: fmt.pct(o.volatility, 1), lambda o: o.volatility,
         lambda o: style.WARN if o.volatility > 8 else None),
    _Col("RISK", 56, False, lambda o: o.risk.value, lambda o: o.risk.value, _risk_color),
]


class OpportunityModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: List[Opportunity] = []
        self._ids: List[str] = []

    def set_opportunities(self, opps: List[Opportunity]) -> None:
        ids = [o.key for o in opps]
        if ids == self._ids and self._rows:
            self._rows = opps
            top = self.index(0, 0)
            bottom = self.index(self.rowCount() - 1, self.columnCount() - 1)
            self.dataChanged.emit(top, bottom)
        else:
            self.beginResetModel()
            self._rows, self._ids = opps, ids
            self.endResetModel()

    def opportunity_at(self, row: int) -> Optional[Opportunity]:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        opp = self._rows[index.row()]
        col = COLUMNS[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return col.disp(opp)
        if role == Qt.ItemDataRole.UserRole:
            return col.sort(opp)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            flag = Qt.AlignmentFlag.AlignRight if col.right else Qt.AlignmentFlag.AlignLeft
            return int(flag | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ForegroundRole and col.color:
            hexcol = col.color(opp)
            return QColor(hexcol) if hexcol else None
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section].title
        return None

    def flags(self, index):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class OpportunityProxy(QSortFilterProxyModel):
    """Local filter combining the active risk profile with the filter toolbar."""

    def __init__(self, risk: RiskEngine) -> None:
        super().__init__()
        self.risk = risk
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.criteria: Dict[str, object] = {
            "sport": "ALL", "league": "ALL", "market": "ALL", "min_net": 0.0,
            "min_buffered": -100.0, "min_liq": 0.0, "min_quality": 0.0,
            "max_price_age": 999.0, "play": "ALL", "direction": "ALL",
            "search": "", "watch_only": False, "favourites": False,
        }
        self.watchlist: set[str] = set()

    def set_criteria(self, **kwargs) -> None:
        self.criteria.update(kwargs)
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        model: OpportunityModel = self.sourceModel()
        opp = model.opportunity_at(row)
        if opp is None:
            return False
        c = self.criteria
        if not self.risk.passes(opp):
            return False
        if c["sport"] != "ALL" and opp.market.sport.value != c["sport"]:
            return False
        if c["league"] != "ALL" and opp.market.league != c["league"]:
            return False
        if c["market"] != "ALL" and opp.market.market_name != c["market"]:
            return False
        if opp.net_edge < c["min_net"] or opp.buffered_edge < c["min_buffered"]:
            return False
        if opp.liquidity < c["min_liq"] or opp.quality.total < c["min_quality"]:
            return False
        if opp.price_age > c["max_price_age"]:
            return False
        if c["play"] == "PRE" and opp.market.in_play:
            return False
        if c["play"] == "INPLAY" and not opp.market.in_play:
            return False
        if c["direction"] != "ALL" and opp.direction.value != c["direction"]:
            return False
        if c["favourites"] and not opp.favourite:
            return False
        if c["watch_only"] and opp.key not in self.watchlist:
            return False
        text = str(c["search"]).strip().lower()
        if text and text not in (opp.market.event + opp.market.selection).lower():
            return False
        return True


class ScreenerWidget(QWidget):
    selection_changed = Signal(object)   # Opportunity or None
    open_requested = Signal(object)      # Opportunity
    context_action = Signal(str, object)  # (action, Opportunity)

    def __init__(self, risk: RiskEngine) -> None:
        super().__init__()
        self.risk = risk
        self.model = OpportunityModel()
        self.proxy = OpportunityProxy(risk)
        self.proxy.setSourceModel(self.model)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_filters())

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(15, Qt.SortOrder.DescendingOrder)  # NET%
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.doubleClicked.connect(
            lambda idx: self.open_requested.emit(self._opp_at_proxy(idx.row())))
        for i, col in enumerate(COLUMNS):
            self.table.setColumnWidth(i, col.width)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_menu)
        self.table.selectionModel().selectionChanged.connect(self._emit_selection)
        layout.addWidget(self.table, 1)

    # -- filter toolbar ----------------------------------------------------
    def _build_filters(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 3, 4, 3)
        row.setSpacing(4)

        self.sport_box = QComboBox()
        self.sport_box.addItems(["ALL", "Football", "Tennis", "Basketball", "Horse Racing"])
        self.sport_box.currentTextChanged.connect(lambda v: self.proxy.set_criteria(sport=v))

        self.min_net = QDoubleSpinBox()
        self.min_net.setRange(0, 20); self.min_net.setSingleStep(0.25)
        self.min_net.setPrefix("net≥ "); self.min_net.setSuffix("%")
        self.min_net.valueChanged.connect(lambda v: self.proxy.set_criteria(min_net=v))

        self.min_liq = QDoubleSpinBox()
        self.min_liq.setRange(0, 100000); self.min_liq.setSingleStep(100)
        self.min_liq.setPrefix("liq≥ £")
        self.min_liq.valueChanged.connect(lambda v: self.proxy.set_criteria(min_liq=v))

        self.search = QLineEdit()
        self.search.setPlaceholderText("search event / selection…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda v: self.proxy.set_criteria(search=v))

        row.addWidget(QLabel("FILTERS"))
        row.addWidget(self.sport_box)
        row.addWidget(self.min_net)
        row.addWidget(self.min_liq)
        row.addWidget(self.search, 1)

        for label, fn in [
            ("ALL", self._quick_all), ("FOOTBALL", lambda: self._quick_sport("Football")),
            ("TENNIS", lambda: self._quick_sport("Tennis")), ("IN-PLAY", self._quick_inplay),
            ("1%", lambda: self._quick_net(1.0)), ("2%", lambda: self._quick_net(2.0)),
            ("HIGH LIQ", lambda: self._quick_liq(1000)), ("WATCH", self._quick_watch),
        ]:
            btn = QPushButton(label)
            btn.setMaximumWidth(72)
            btn.clicked.connect(fn)
            row.addWidget(btn)
        return bar

    def _quick_all(self):
        self.sport_box.setCurrentText("ALL"); self.min_net.setValue(0); self.min_liq.setValue(0)
        self.search.clear()
        self.proxy.set_criteria(sport="ALL", min_net=0, min_liq=0, play="ALL", watch_only=False)

    def _quick_sport(self, sport): self.sport_box.setCurrentText(sport)
    def _quick_inplay(self): self.proxy.set_criteria(play="INPLAY")
    def _quick_net(self, v): self.min_net.setValue(v)
    def _quick_liq(self, v): self.min_liq.setValue(v)
    def _quick_watch(self): self.proxy.set_criteria(watch_only=True)

    # -- data / selection --------------------------------------------------
    def set_opportunities(self, opps: List[Opportunity]) -> None:
        self.model.set_opportunities(opps)

    def refilter(self) -> None:
        self.proxy.invalidateFilter()

    def set_watchlist(self, ids: set) -> None:
        self.proxy.watchlist = set(ids)
        self.proxy.invalidateFilter()

    def _opp_at_proxy(self, proxy_row: int) -> Optional[Opportunity]:
        src = self.proxy.mapToSource(self.proxy.index(proxy_row, 0))
        return self.model.opportunity_at(src.row())

    def current_opportunity(self) -> Optional[Opportunity]:
        idx = self.table.currentIndex()
        return self._opp_at_proxy(idx.row()) if idx.isValid() else None

    def _emit_selection(self, *_):
        self.selection_changed.emit(self.current_opportunity())

    def select_row(self, delta: int) -> None:
        rows = self.proxy.rowCount()
        if not rows:
            return
        cur = self.table.currentIndex().row()
        nxt = max(0, min(rows - 1, (cur if cur >= 0 else -1) + delta))
        self.table.selectRow(nxt)

    # -- menus -------------------------------------------------------------
    def _menu(self, pos):
        opp = self.current_opportunity()
        if opp is None:
            return
        menu = QMenu(self)
        menu.addAction("Open in inspector", lambda: self.open_requested.emit(opp))
        menu.addAction("Toggle favourite", lambda: self.context_action.emit("favourite", opp))
        menu.addAction("Add to watchlist", lambda: self.context_action.emit("watch", opp))
        menu.addSeparator()
        menu.addAction("Simulate trade", lambda: self.context_action.emit("simulate", opp))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _header_menu(self, pos):
        menu = QMenu(self)
        for i, col in enumerate(COLUMNS):
            act = QAction(col.title, menu, checkable=True)
            act.setChecked(not self.table.isColumnHidden(i))
            act.toggled.connect(lambda vis, c=i: self.table.setColumnHidden(c, not vis))
            menu.addAction(act)
        menu.exec(self.table.horizontalHeader().mapToGlobal(pos))
