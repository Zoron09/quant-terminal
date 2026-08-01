"""Data models for the Code 33 revenue-acceleration screener."""
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


@dataclass
class QuarterPoint:
    """One company-native fiscal quarter's discrete ("three months ended") revenue figure."""

    period_end: date  # ddate of the discrete period (quarter end)
    filed: date  # date the source report was filed
    adsh: str  # SEC accession number of the source filing
    form: str  # 10-Q or 10-K
    fy: Optional[int]
    fp: Optional[str]  # Q1/Q2/Q3/Q4/FY as reported by SEC
    value: Optional[float]  # discrete quarter revenue, USD; None if unavailable
    tag: Optional[str]  # which XBRL tag supplied the value; None if unavailable
    source: str = "missing"  # "reported" | "derived_fy_minus_quarters" | "missing"
    derived_from_adsh: Optional[str] = None  # comma-joined Q1/Q2/Q3 adshs subtracted from, when source is derived
    plausible: Optional[bool] = None  # None for reported/missing; True/False for derived only
    restated: bool = False  # True if a later filing reports a different value for this same
    # (ddate, qtrs, tag) than the filing this point's own value came from
    restated_value: Optional[float] = None  # the later figure, when restated is True; value is never changed


@dataclass
class QuarterlyRevenueSeries:
    """A company's own sequential discrete-quarter revenue figures, most recent first."""

    cik: int
    points: List[QuarterPoint] = field(default_factory=list)
    series_flag: Optional[str] = None  # set when the series can't be built at all (e.g. no filings)

    @property
    def is_usable(self) -> bool:
        return self.series_flag is None and len(self.points) > 0


@dataclass
class MarginPoint:
    """One quarter's net margin, carrying the underlying net-income and revenue points'
    own source/plausible/restated flags through for transparency — same principle as
    QuarterPoint, just at the paired-metric level."""

    period_end: date
    fiscal_quarter: str  # e.g. "2025 Q3", from whichever leg (NI or revenue) has it
    net_income: Optional[float]
    ni_source: str
    ni_plausible: Optional[bool]
    ni_restated: bool
    ni_restated_value: Optional[float]
    revenue: Optional[float]
    revenue_source: str
    revenue_plausible: Optional[bool]
    revenue_restated: bool
    revenue_restated_value: Optional[float]
    net_margin_pct: Optional[float]  # None if revenue is missing or zero


@dataclass
class QuarterlyNetMarginSeries:
    """A company's own sequential discrete-quarter net margins, most recent first."""

    cik: int
    points: List[MarginPoint] = field(default_factory=list)
    series_flag: Optional[str] = None  # set when the series can't be built at all (e.g. no filings)

    @property
    def is_usable(self) -> bool:
        return self.series_flag is None and len(self.points) > 0


@dataclass
class Code33RevenueResult:
    """Result of the revenue-acceleration (Code 33) check for one company."""

    cik: int
    passed: bool
    growth_rates: List[float]  # 4 YoY growth rates, most recent first [g(Q0), g(Q-1), g(Q-2), g(Q-3)]
    quarters_used: List[QuarterPoint]  # the 8 QuarterPoints (Q0..Q-7) underpinning growth_rates
    flag: Optional[str] = None  # set (and passed=False) when data was insufficient to evaluate
