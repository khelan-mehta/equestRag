"""
Data Quality & Confidence Engine
Completeness scoring, consistency checks, unrealistic value detection,
modeling error flags, and output confidence scoring.
"""

import logging
from typing import Dict, Any, List
from dataclasses import dataclass, field

logger = logging.getLogger("equestrag.data_quality")


# ---------------------------------------------------------------------------
# Reasonable value ranges for building energy metrics
# ---------------------------------------------------------------------------
REASONABLE_RANGES = {
    "eui_kwh_sqft_yr": (2, 150),
    "eui_kbtu_sqft_yr": (10, 500),
    "floor_area_sqft": (500, 10_000_000),
    "total_electricity_kwh": (1000, 500_000_000),
    "total_gas_therm": (0, 50_000_000),
    "cooling_load_kbtu_h": (1, 500_000),
    "heating_load_kbtu_h": (1, 500_000),
    "cooling_tons": (0.1, 50_000),
    "cost_per_sqft": (0.10, 50.0),
    "total_cost": (100, 100_000_000),
    "cop": (1.0, 10.0),
    "eer": (5.0, 30.0),
    "u_value": (0.01, 2.0),
    "r_value": (0.5, 100.0),
    "shgc": (0.01, 1.0),
    "window_wall_ratio": (0.01, 0.95),
}

# Expected sections by project type
EXPECTED_SECTIONS = {
    "minimal": ["bepu"],
    "standard": ["ps_e", "bepu", "ls_c", "es_d"],
    "comprehensive": ["ps_e", "bepu", "ls_c", "es_d", "lv_d", "metadata"],
    "full": ["ps_e", "bepu", "ls_c", "es_d", "lv_d", "ss_p", "sv_a", "metadata"],
}


@dataclass
class QualityIssue:
    severity: str  # "error", "warning", "info"
    category: str  # "completeness", "consistency", "range", "modeling"
    field: str
    message: str
    value: Any = None
    expected_range: Any = None


@dataclass
class QualityReport:
    overall_score: float = 0.0
    completeness_score: float = 0.0
    consistency_score: float = 0.0
    plausibility_score: float = 0.0
    confidence_grade: str = "F"
    issues: List[QualityIssue] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 2),
            "completeness_score": round(self.completeness_score, 2),
            "consistency_score": round(self.consistency_score, 2),
            "plausibility_score": round(self.plausibility_score, 2),
            "confidence_grade": self.confidence_grade,
            "issues": [
                {
                    "severity": i.severity,
                    "category": i.category,
                    "field": i.field,
                    "message": i.message,
                    "value": i.value,
                }
                for i in self.issues
            ],
            "summary": self.summary,
            "error_count": sum(1 for i in self.issues if i.severity == "error"),
            "warning_count": sum(1 for i in self.issues if i.severity == "warning"),
            "info_count": sum(1 for i in self.issues if i.severity == "info"),
        }


class DataQualityEngine:
    """Analyzes building data quality and produces confidence scores."""

    def analyze(self, building_data: Dict[str, Any], metrics: Dict[str, Any] = None) -> QualityReport:
        report = QualityReport()

        # Run all checks
        self._check_completeness(building_data, report)
        self._check_consistency(building_data, metrics or {}, report)
        self._check_plausibility(building_data, metrics or {}, report)
        self._check_modeling_errors(building_data, report)

        # Calculate overall score
        weights = {
            "completeness": 0.30,
            "consistency": 0.30,
            "plausibility": 0.25,
            "modeling": 0.15,
        }

        error_penalty = sum(0.05 for i in report.issues if i.severity == "error")
        warning_penalty = sum(0.02 for i in report.issues if i.severity == "warning")

        modeling_score = max(0, 1.0 - sum(
            0.1 for i in report.issues if i.category == "modeling"
        ))

        report.overall_score = max(0, min(1.0, (
            weights["completeness"] * report.completeness_score +
            weights["consistency"] * report.consistency_score +
            weights["plausibility"] * report.plausibility_score +
            weights["modeling"] * modeling_score -
            error_penalty - warning_penalty
        )))

        # Grade assignment
        score = report.overall_score
        if score >= 0.9:
            report.confidence_grade = "A"
        elif score >= 0.8:
            report.confidence_grade = "B"
        elif score >= 0.7:
            report.confidence_grade = "C"
        elif score >= 0.6:
            report.confidence_grade = "D"
        else:
            report.confidence_grade = "F"

        # Summary
        errors = sum(1 for i in report.issues if i.severity == "error")
        warnings = sum(1 for i in report.issues if i.severity == "warning")
        report.summary = (
            f"Data quality grade: {report.confidence_grade} "
            f"(score: {report.overall_score:.0%}). "
            f"{errors} errors, {warnings} warnings detected."
        )

        return report

    def _check_completeness(self, data: Dict, report: QualityReport):
        """Check if all expected data sections are present."""
        present_sections = set()
        for key in data:
            if data[key]:
                present_sections.add(key.lower())

        # Check against standard expectation
        expected = EXPECTED_SECTIONS["standard"]
        found = sum(1 for s in expected if s in present_sections)
        report.completeness_score = found / len(expected) if expected else 0

        for section in expected:
            if section not in present_sections:
                report.issues.append(QualityIssue(
                    severity="warning",
                    category="completeness",
                    field=section,
                    message=f"Missing expected section: {section.upper()}",
                ))

        # BEPU-specific completeness
        if "bepu" in data and isinstance(data["bepu"], dict):
            bepu = data["bepu"]
            critical_fields = ["floor_area_sqft", "total_electricity_kwh", "eui_kwh_sqft_yr"]
            for field_name in critical_fields:
                if field_name not in bepu:
                    report.issues.append(QualityIssue(
                        severity="warning",
                        category="completeness",
                        field=field_name,
                        message=f"Missing critical BEPU field: {field_name}",
                    ))

        # PS-E specific completeness
        if "ps_e" in data:
            ps_e = data["ps_e"]
            if isinstance(ps_e, list):
                months_found = set(r.get("Month") for r in ps_e if r.get("Month") != "ANNUAL")
                expected_months = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                                   "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"}
                missing_months = expected_months - months_found
                if missing_months:
                    report.issues.append(QualityIssue(
                        severity="warning",
                        category="completeness",
                        field="ps_e",
                        message=f"Missing months in PS-E: {', '.join(sorted(missing_months))}",
                    ))

    def _check_consistency(self, data: Dict, metrics: Dict, report: QualityReport):
        """Cross-validate data across reports."""
        issues_before = len(report.issues)

        # Check EUI consistency between BEPU data and computed value
        if "bepu" in data and isinstance(data["bepu"], dict):
            bepu = data["bepu"]
            reported_eui = bepu.get("eui_kwh_sqft_yr", 0)
            kwh = bepu.get("total_electricity_kwh", 0)
            area = bepu.get("floor_area_sqft", 0)

            if reported_eui > 0 and kwh > 0 and area > 0:
                computed_eui = kwh / area
                if abs(computed_eui - reported_eui) / reported_eui > 0.05:
                    report.issues.append(QualityIssue(
                        severity="warning",
                        category="consistency",
                        field="eui_kwh_sqft_yr",
                        message=f"EUI inconsistency: reported {reported_eui:.2f}, computed {computed_eui:.2f}",
                        value=reported_eui,
                    ))

        # Check PS-E totals vs BEPU total
        if "ps_e" in data and "bepu" in data:
            ps_e = data["ps_e"]
            bepu = data.get("bepu", {})
            if isinstance(ps_e, list) and isinstance(bepu, dict):
                annual_rows = [r for r in ps_e if r.get("Month") == "ANNUAL"]
                if annual_rows:
                    ps_e_total = annual_rows[0].get("Total", 0)
                    bepu_total = bepu.get("total_electricity_kwh", 0)
                    if ps_e_total > 0 and bepu_total > 0:
                        ratio = ps_e_total / bepu_total if bepu_total > 0 else 0
                        if ratio < 0.5 or ratio > 2.0:
                            report.issues.append(QualityIssue(
                                severity="warning",
                                category="consistency",
                                field="total_energy",
                                message=f"PS-E total ({ps_e_total:,.0f}) differs significantly from BEPU total ({bepu_total:,.0f})",
                            ))

        # Check cost consistency
        if "es_d" in data and isinstance(data["es_d"], dict):
            es_d = data["es_d"]
            cost_sqft = es_d.get("cost_per_sqft", 0)
            total_cost = es_d.get("total_cost", 0)
            area = data.get("bepu", {}).get("floor_area_sqft", 0) if isinstance(data.get("bepu"), dict) else 0

            if cost_sqft > 0 and total_cost > 0 and area > 0:
                computed_cost_sqft = total_cost / area
                if abs(computed_cost_sqft - cost_sqft) / cost_sqft > 0.1:
                    report.issues.append(QualityIssue(
                        severity="info",
                        category="consistency",
                        field="cost_per_sqft",
                        message=f"Cost/sqft: reported ${cost_sqft:.2f}, computed ${computed_cost_sqft:.2f}",
                    ))

        issues_added = len(report.issues) - issues_before
        report.consistency_score = max(0, 1.0 - issues_added * 0.15)

    def _check_plausibility(self, data: Dict, metrics: Dict, report: QualityReport):
        """Check if values are within reasonable ranges."""
        issues_before = len(report.issues)

        # Check all numeric values against known ranges
        all_values = {}
        for section_key, section_data in data.items():
            if isinstance(section_data, dict):
                for k, v in section_data.items():
                    if isinstance(v, (int, float)):
                        all_values[k] = v

        # Also check metrics
        if metrics:
            for k, v in metrics.items():
                if isinstance(v, (int, float)):
                    all_values[k] = v

        for key, value in all_values.items():
            if key in REASONABLE_RANGES:
                low, high = REASONABLE_RANGES[key]
                if value < low or value > high:
                    severity = "error" if (value < low * 0.1 or value > high * 10) else "warning"
                    report.issues.append(QualityIssue(
                        severity=severity,
                        category="range",
                        field=key,
                        message=f"{key} = {value:,.2f} is outside reasonable range ({low:,.2f} - {high:,.2f})",
                        value=value,
                        expected_range=(low, high),
                    ))

        issues_added = len(report.issues) - issues_before
        report.plausibility_score = max(0, 1.0 - issues_added * 0.1)

    def _check_modeling_errors(self, data: Dict, report: QualityReport):
        """Detect common eQuest modeling errors."""
        # Check for zero-area building
        if "bepu" in data and isinstance(data["bepu"], dict):
            area = data["bepu"].get("floor_area_sqft", 0)
            if area == 0:
                report.issues.append(QualityIssue(
                    severity="error",
                    category="modeling",
                    field="floor_area_sqft",
                    message="Floor area is zero - likely a modeling error",
                ))

        # Check for zero energy but non-zero area
        if "bepu" in data and isinstance(data["bepu"], dict):
            bepu = data["bepu"]
            area = bepu.get("floor_area_sqft", 0)
            kwh = bepu.get("total_electricity_kwh", 0)
            if area > 0 and kwh == 0:
                report.issues.append(QualityIssue(
                    severity="error",
                    category="modeling",
                    field="total_electricity_kwh",
                    message="Total electricity is zero despite non-zero floor area",
                ))

        # Check for equal cooling and heating loads (common modeling error)
        if "ls_c" in data and isinstance(data["ls_c"], dict):
            cooling = data["ls_c"].get("cooling_load_kbtu_h", 0)
            heating = data["ls_c"].get("heating_load_kbtu_h", 0)
            if cooling > 0 and heating > 0:
                if abs(cooling - heating) < 0.01:
                    report.issues.append(QualityIssue(
                        severity="warning",
                        category="modeling",
                        field="peak_loads",
                        message="Cooling and heating loads are exactly equal - may indicate modeling error",
                    ))

        # Check for flat monthly profile (all months identical)
        if "ps_e" in data and isinstance(data["ps_e"], list):
            monthly = [r for r in data["ps_e"] if r.get("Month") != "ANNUAL"]
            if len(monthly) >= 6:
                totals = [r.get("Total", 0) for r in monthly]
                if totals and max(totals) > 0:
                    cv = (max(totals) - min(totals)) / max(totals)
                    if cv < 0.02:
                        report.issues.append(QualityIssue(
                            severity="warning",
                            category="modeling",
                            field="monthly_profile",
                            message="Monthly energy profile is nearly flat - may indicate modeling issue",
                        ))

        # Check for negative values
        for key, val in data.items():
            if isinstance(val, dict):
                for k, v in val.items():
                    if isinstance(v, (int, float)) and v < 0 and k not in ("latitude", "longitude", "timezone"):
                        report.issues.append(QualityIssue(
                            severity="error",
                            category="modeling",
                            field=k,
                            message=f"Negative value detected for {k}: {v}",
                            value=v,
                        ))
