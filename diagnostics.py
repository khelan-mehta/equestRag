"""
Diagnostics & Anomaly Detection Engine
Detects: simultaneous heating & cooling, winter cooling dominance,
flat load curves, abnormal EUI, impossible peak timing, and more.
"""

import logging
from typing import Dict, Any, List
from dataclasses import dataclass, field

logger = logging.getLogger("equestrag.diagnostics")

# EUI benchmarks by building type (kBTU/sqft/yr)
EUI_BENCHMARKS = {
    "office": {"excellent": 40, "good": 65, "average": 90, "poor": 120},
    "retail": {"excellent": 35, "good": 55, "average": 80, "poor": 110},
    "school": {"excellent": 30, "good": 50, "average": 75, "poor": 100},
    "hospital": {"excellent": 100, "good": 160, "average": 220, "poor": 300},
    "hotel": {"excellent": 50, "good": 80, "average": 110, "poor": 150},
    "warehouse": {"excellent": 15, "good": 25, "average": 40, "poor": 60},
    "restaurant": {"excellent": 100, "good": 200, "average": 350, "poor": 500},
    "multifamily": {"excellent": 25, "good": 45, "average": 65, "poor": 90},
    "default": {"excellent": 40, "good": 65, "average": 100, "poor": 140},
}


@dataclass
class Diagnostic:
    severity: str  # "critical", "warning", "info"
    category: str
    title: str
    description: str
    recommendation: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticsReport:
    diagnostics: List[Diagnostic] = field(default_factory=list)
    health_score: float = 1.0
    summary: str = ""
    critical_count: int = 0
    warning_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "health_score": round(self.health_score, 2),
            "summary": self.summary,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "total_diagnostics": len(self.diagnostics),
            "diagnostics": [
                {
                    "severity": d.severity,
                    "category": d.category,
                    "title": d.title,
                    "description": d.description,
                    "recommendation": d.recommendation,
                    "data": d.data,
                }
                for d in self.diagnostics
            ],
        }


class DiagnosticsEngine:
    """Analyzes building energy data for anomalies and issues."""

    def analyze(self, building_data: Dict[str, Any],
                metrics: Dict[str, Any] = None,
                building_type: str = "default") -> DiagnosticsReport:
        report = DiagnosticsReport()

        m = metrics or {}

        self._check_simultaneous_heating_cooling(building_data, report)
        self._check_winter_cooling(building_data, report)
        self._check_flat_load_curve(building_data, report)
        self._check_abnormal_eui(building_data, m, building_type, report)
        self._check_peak_timing(building_data, report)
        self._check_baseload_ratio(building_data, report)
        self._check_cooling_efficiency(building_data, m, report)
        self._check_ventilation_ratio(building_data, report)
        self._check_monthly_anomalies(building_data, report)

        # Score
        report.critical_count = sum(1 for d in report.diagnostics if d.severity == "critical")
        report.warning_count = sum(1 for d in report.diagnostics if d.severity == "warning")
        report.health_score = max(0, 1.0 - report.critical_count * 0.15 - report.warning_count * 0.05)

        report.summary = (
            f"Building health score: {report.health_score:.0%}. "
            f"Found {report.critical_count} critical issues and {report.warning_count} warnings."
        )

        return report

    def _check_simultaneous_heating_cooling(self, data: Dict, report: DiagnosticsReport):
        """Detect months with significant simultaneous heating and cooling."""
        ps_e = data.get("ps_e", [])
        if not isinstance(ps_e, list):
            return

        monthly = [r for r in ps_e if r.get("Month") not in ("ANNUAL", None)]
        simultaneous_months = []

        for row in monthly:
            cooling = row.get("Cooling", 0)
            heating = row.get("Heating", 0)
            total = row.get("Total", 1)
            if total <= 0:
                continue

            if cooling > 0 and heating > 0:
                min_val = min(cooling, heating)
                # Flag if the smaller value is > 20% of total
                if min_val / total > 0.20:
                    simultaneous_months.append(row.get("Month", ""))

        if simultaneous_months:
            report.diagnostics.append(Diagnostic(
                severity="warning",
                category="HVAC",
                title="Simultaneous Heating & Cooling Detected",
                description=(
                    f"Months with significant simultaneous heating and cooling: "
                    f"{', '.join(simultaneous_months)}. This may indicate reheat, "
                    f"poor thermostat deadband, or zone interactions."
                ),
                recommendation=(
                    "Review HVAC system type and thermostat settings. "
                    "Consider widening deadband or switching to a system that avoids reheat."
                ),
                data={"months": simultaneous_months},
            ))

    def _check_winter_cooling(self, data: Dict, report: DiagnosticsReport):
        """Detect cooling dominance in winter months."""
        ps_e = data.get("ps_e", [])
        if not isinstance(ps_e, list):
            return

        winter_months = {"DEC", "JAN", "FEB"}
        monthly = [r for r in ps_e if r.get("Month") in winter_months]

        for row in monthly:
            cooling = row.get("Cooling", 0)
            heating = row.get("Heating", 0)
            if cooling > heating and cooling > 0:
                report.diagnostics.append(Diagnostic(
                    severity="warning",
                    category="HVAC",
                    title=f"Winter Cooling Dominance in {row.get('Month', '')}",
                    description=(
                        f"Cooling ({cooling:,.0f}) exceeds heating ({heating:,.0f}) in "
                        f"{row.get('Month', '')}. This may indicate internal load issues "
                        f"or incorrect modeling of HVAC system."
                    ),
                    recommendation="Review internal loads, occupancy schedules, and HVAC system type.",
                    data={"month": row.get("Month"), "cooling": cooling, "heating": heating},
                ))
                break  # One warning is enough

    def _check_flat_load_curve(self, data: Dict, report: DiagnosticsReport):
        """Detect unnaturally flat monthly load profiles."""
        ps_e = data.get("ps_e", [])
        if not isinstance(ps_e, list):
            return

        monthly = [r for r in ps_e if r.get("Month") not in ("ANNUAL", None)]
        if len(monthly) < 6:
            return

        totals = [r.get("Total", 0) for r in monthly]
        if not totals or max(totals) == 0:
            return

        cv = (max(totals) - min(totals)) / max(totals)
        if cv < 0.05:
            report.diagnostics.append(Diagnostic(
                severity="warning",
                category="Load Profile",
                title="Flat Monthly Load Profile",
                description=(
                    f"Monthly energy consumption variation is only {cv:.1%}. "
                    f"Real buildings typically show 15-50% seasonal variation. "
                    f"This may indicate incorrect schedules or default loads."
                ),
                recommendation="Review occupancy schedules, HVAC schedules, and weather file assignment.",
                data={"coefficient_of_variation": round(cv, 3)},
            ))

    def _check_abnormal_eui(self, data: Dict, metrics: Dict,
                            building_type: str, report: DiagnosticsReport):
        """Check EUI against benchmarks."""
        bepu = data.get("bepu", {})
        if not isinstance(bepu, dict):
            return

        eui_kwh = bepu.get("eui_kwh_sqft_yr", 0)
        if eui_kwh <= 0:
            return

        eui_kbtu = eui_kwh * 3.412
        benchmarks = EUI_BENCHMARKS.get(building_type.lower(), EUI_BENCHMARKS["default"])

        if eui_kbtu < benchmarks["excellent"] * 0.3:
            report.diagnostics.append(Diagnostic(
                severity="critical",
                category="Energy Performance",
                title="Impossibly Low EUI",
                description=(
                    f"EUI of {eui_kbtu:.1f} kBTU/sqft/yr is unrealistically low "
                    f"(below 30% of 'excellent' benchmark of {benchmarks['excellent']}). "
                    f"This strongly suggests a modeling error."
                ),
                recommendation="Check floor area, unmet hours, schedules, and internal loads.",
                data={"eui_kbtu": round(eui_kbtu, 1), "benchmark_excellent": benchmarks["excellent"]},
            ))
        elif eui_kbtu > benchmarks["poor"] * 1.5:
            report.diagnostics.append(Diagnostic(
                severity="warning",
                category="Energy Performance",
                title="Very High EUI",
                description=(
                    f"EUI of {eui_kbtu:.1f} kBTU/sqft/yr significantly exceeds "
                    f"the 'poor' benchmark of {benchmarks['poor']}. This may indicate "
                    f"energy efficiency issues or incorrect model inputs."
                ),
                recommendation="Review HVAC efficiency, envelope properties, and internal loads.",
                data={"eui_kbtu": round(eui_kbtu, 1), "benchmark_poor": benchmarks["poor"]},
            ))

    def _check_peak_timing(self, data: Dict, report: DiagnosticsReport):
        """Check for impossible peak timing."""
        ls_c = data.get("ls_c", {})
        if not isinstance(ls_c, dict):
            return

        # Check if cooling peak is in winter
        cool_time = ls_c.get("cooling_peak_time", "")
        if cool_time and any(m in cool_time.upper() for m in ["JAN", "FEB", "DEC"]):
            report.diagnostics.append(Diagnostic(
                severity="warning",
                category="Peak Loads",
                title="Cooling Peak in Winter",
                description=f"Cooling peak occurs at {cool_time}, which is unusual.",
                recommendation="Verify weather file and cooling load calculations.",
            ))

        # Check if heating peak is in summer
        heat_time = ls_c.get("heating_peak_time", "")
        if heat_time and any(m in heat_time.upper() for m in ["JUN", "JUL", "AUG"]):
            report.diagnostics.append(Diagnostic(
                severity="warning",
                category="Peak Loads",
                title="Heating Peak in Summer",
                description=f"Heating peak occurs at {heat_time}, which is unusual.",
                recommendation="Verify weather file and heating load calculations.",
            ))

    def _check_baseload_ratio(self, data: Dict, report: DiagnosticsReport):
        """Check if baseload is abnormally high."""
        ps_e = data.get("ps_e", [])
        if not isinstance(ps_e, list):
            return

        monthly = [r for r in ps_e if r.get("Month") not in ("ANNUAL", None)]
        annual = [r for r in ps_e if r.get("Month") == "ANNUAL"]

        if len(monthly) < 12 or not annual:
            return

        min_month_total = min(r.get("Total", 0) for r in monthly)
        annual_total = annual[0].get("Total", 0)

        if annual_total > 0:
            baseload_ratio = (min_month_total * 12) / annual_total
            if baseload_ratio > 0.95:
                report.diagnostics.append(Diagnostic(
                    severity="info",
                    category="Load Profile",
                    title="Very High Baseload Ratio",
                    description=(
                        f"Baseload accounts for {baseload_ratio:.0%} of total energy. "
                        f"Weather-dependent loads are minimal."
                    ),
                    recommendation="Consider if HVAC and weather-dependent loads are properly modeled.",
                    data={"baseload_ratio": round(baseload_ratio, 2)},
                ))

    def _check_cooling_efficiency(self, data: Dict, metrics: Dict, report: DiagnosticsReport):
        """Check cooling system efficiency indicators."""
        kwh_per_ton = metrics.get("kwh_per_ton", 0)
        if kwh_per_ton > 0:
            if kwh_per_ton > 2000:
                report.diagnostics.append(Diagnostic(
                    severity="warning",
                    category="HVAC Efficiency",
                    title="High kWh/Ton Ratio",
                    description=(
                        f"kWh/ton ratio of {kwh_per_ton:.0f} is high, suggesting "
                        f"inefficient cooling or oversized equipment."
                    ),
                    recommendation="Review chiller efficiency, cooling tower performance, and sizing.",
                ))

    def _check_ventilation_ratio(self, data: Dict, report: DiagnosticsReport):
        """Check if ventilation energy is abnormally high."""
        ps_e = data.get("ps_e", [])
        if not isinstance(ps_e, list):
            return

        annual = [r for r in ps_e if r.get("Month") == "ANNUAL"]
        if not annual:
            return

        row = annual[0]
        vent = row.get("Vent_Fans", 0)
        total = row.get("Total", 0)

        if total > 0 and vent / total > 0.30:
            report.diagnostics.append(Diagnostic(
                severity="warning",
                category="Ventilation",
                title="High Ventilation Energy",
                description=(
                    f"Ventilation fans consume {vent/total:.0%} of total energy, "
                    f"which exceeds typical 15-25% range."
                ),
                recommendation="Review fan power, duct static pressure, and VAV box settings.",
                data={"vent_percentage": round(vent / total * 100, 1)},
            ))

    def _check_monthly_anomalies(self, data: Dict, report: DiagnosticsReport):
        """Detect months with anomalous energy consumption."""
        ps_e = data.get("ps_e", [])
        if not isinstance(ps_e, list):
            return

        monthly = [r for r in ps_e if r.get("Month") not in ("ANNUAL", None)]
        if len(monthly) < 6:
            return

        totals = [r.get("Total", 0) for r in monthly]
        if not totals:
            return

        import statistics
        mean_val = statistics.mean(totals)
        if mean_val == 0:
            return
        try:
            stdev = statistics.stdev(totals)
        except statistics.StatisticsError:
            return

        if stdev == 0:
            return

        for i, (total, row) in enumerate(zip(totals, monthly)):
            z_score = (total - mean_val) / stdev
            if abs(z_score) > 2.5:
                month = row.get("Month", f"Month {i+1}")
                direction = "high" if z_score > 0 else "low"
                report.diagnostics.append(Diagnostic(
                    severity="info",
                    category="Monthly Anomaly",
                    title=f"Anomalous Energy in {month}",
                    description=(
                        f"{month} consumption ({total:,.0f}) is anomalously {direction} "
                        f"(z-score: {z_score:.1f})."
                    ),
                    recommendation=f"Investigate unusual conditions in {month}.",
                    data={"month": month, "value": total, "z_score": round(z_score, 1)},
                ))
