"""
Executive AI Intelligence Layer
Auto-generates: executive summary, top inefficiencies, risk assessment,
ranked improvements, and compliance summary.
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("equestrag.executive_ai")


class ExecutiveAIEngine:
    """Generates executive-level intelligence and summaries."""

    def generate_executive_report(self, building_data: Dict[str, Any],
                                   metrics: Dict[str, Any],
                                   diagnostics: Dict[str, Any] = None,
                                   benchmarking: Dict[str, Any] = None,
                                   carbon: Dict[str, Any] = None,
                                   quality: Dict[str, Any] = None,
                                   financial: Dict[str, Any] = None,
                                   simulation: Dict[str, Any] = None) -> Dict[str, Any]:
        return {
            "executive_summary": self._generate_summary(
                building_data, metrics, benchmarking, carbon
            ),
            "top_inefficiencies": self._identify_inefficiencies(
                building_data, metrics, diagnostics
            ),
            "risk_assessment": self._assess_risks(
                diagnostics, quality, benchmarking
            ),
            "ranked_improvements": self._rank_improvements(
                simulation, financial, metrics
            ),
            "compliance_summary": self._summarize_compliance(
                benchmarking, quality
            ),
            "key_metrics_dashboard": self._build_dashboard(
                metrics, carbon, benchmarking
            ),
        }

    def _generate_summary(self, data: Dict, metrics: Dict,
                           benchmarking: Dict = None,
                           carbon: Dict = None) -> Dict[str, Any]:
        bepu = data.get("bepu", {}) if isinstance(data.get("bepu"), dict) else {}
        summary = {
            "building_name": data.get("metadata", {}).get("project_name", "Building"),
            "floor_area_sqft": bepu.get("floor_area_sqft", 0),
            "highlights": [],
            "key_numbers": {},
        }

        # Key numbers
        if bepu.get("total_electricity_kwh"):
            summary["key_numbers"]["annual_energy_kwh"] = bepu["total_electricity_kwh"]
        if bepu.get("eui_kwh_sqft_yr"):
            summary["key_numbers"]["eui_kwh_sqft"] = bepu["eui_kwh_sqft_yr"]
            summary["key_numbers"]["eui_kbtu_sqft"] = round(bepu["eui_kwh_sqft_yr"] * 3.412, 1)

        if metrics.get("total_annual_cost"):
            summary["key_numbers"]["annual_cost"] = metrics["total_annual_cost"]
        if metrics.get("peak_cooling_tons"):
            summary["key_numbers"]["peak_cooling_tons"] = metrics["peak_cooling_tons"]

        # Highlights
        if benchmarking:
            grade = benchmarking.get("efficiency_grade", {})
            if grade:
                summary["highlights"].append(
                    f"Efficiency grade: {grade.get('grade', 'N/A')} ({grade.get('label', '')})"
                )
            eui_bench = benchmarking.get("eui_benchmark", {})
            if eui_bench.get("pct_vs_median") is not None:
                pct = eui_bench["pct_vs_median"]
                direction = "better" if pct < 0 else "worse"
                summary["highlights"].append(
                    f"EUI is {abs(pct):.0f}% {direction} than median for {eui_bench.get('building_type', 'similar')} buildings"
                )

        if carbon:
            emissions = carbon.get("carbon_emissions", {})
            if emissions.get("total_metric_tons"):
                summary["highlights"].append(
                    f"Annual carbon emissions: {emissions['total_metric_tons']:.1f} metric tons CO2"
                )
            esg = carbon.get("esg_score", {})
            if esg.get("grade"):
                summary["highlights"].append(f"ESG readiness: {esg['grade']} ({esg.get('readiness', '')})")

        if metrics.get("seasonal_variation"):
            summary["highlights"].append(
                f"Seasonal energy variation: {metrics['seasonal_variation']:.0f}%"
            )

        return summary

    def _identify_inefficiencies(self, data: Dict, metrics: Dict,
                                   diagnostics: Dict = None) -> List[Dict[str, Any]]:
        inefficiencies = []

        # From diagnostics
        if diagnostics:
            diag_list = diagnostics.get("diagnostics", [])
            for d in diag_list:
                if d.get("severity") in ("critical", "warning"):
                    inefficiencies.append({
                        "title": d.get("title", ""),
                        "severity": d.get("severity", ""),
                        "description": d.get("description", ""),
                        "recommendation": d.get("recommendation", ""),
                        "category": d.get("category", ""),
                    })

        # End-use analysis
        end_use = metrics.get("end_use_breakdown", {})
        if isinstance(end_use, dict):
            dominant = end_use.get("dominant_end_use", "")
            dominant_pct = end_use.get("dominant_percentage", 0)
            if dominant_pct > 40:
                inefficiencies.append({
                    "title": f"High {dominant} Energy Consumption",
                    "severity": "warning",
                    "description": f"{dominant} accounts for {dominant_pct:.0f}% of total energy, exceeding typical 25-35% range.",
                    "recommendation": f"Audit {dominant.lower()} systems for efficiency improvements.",
                    "category": "End-Use",
                })

        # High cost per sqft
        cost_sqft = metrics.get("cost_per_sqft", 0)
        if cost_sqft > 4.0:
            inefficiencies.append({
                "title": "High Energy Cost",
                "severity": "warning",
                "description": f"Energy cost of ${cost_sqft:.2f}/sqft/yr exceeds typical $2.00-$3.50 range.",
                "recommendation": "Review utility rates, demand charges, and energy efficiency measures.",
                "category": "Cost",
            })

        # Sort by severity (critical first)
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        inefficiencies.sort(key=lambda x: severity_order.get(x.get("severity", "info"), 3))

        return inefficiencies[:5]  # Top 5

    def _assess_risks(self, diagnostics: Dict = None,
                       quality: Dict = None,
                       benchmarking: Dict = None) -> Dict[str, Any]:
        risk_items = []
        overall_risk = "Low"

        if quality:
            grade = quality.get("confidence_grade", "")
            if grade in ("D", "F"):
                risk_items.append({
                    "risk": "Data Quality",
                    "level": "High",
                    "detail": f"Data confidence grade is {grade}. Results may be unreliable.",
                })
                overall_risk = "High"
            elif grade == "C":
                risk_items.append({
                    "risk": "Data Quality",
                    "level": "Medium",
                    "detail": f"Data confidence grade is {grade}. Some data may be incomplete.",
                })
                if overall_risk == "Low":
                    overall_risk = "Medium"

        if diagnostics:
            critical = diagnostics.get("critical_count", 0)
            if critical > 0:
                risk_items.append({
                    "risk": "Modeling Issues",
                    "level": "High",
                    "detail": f"{critical} critical diagnostic issues found.",
                })
                overall_risk = "High"

        if benchmarking:
            compliance = benchmarking.get("code_compliance", {})
            if compliance.get("overall_pass") is False:
                risk_items.append({
                    "risk": "Code Compliance",
                    "level": "High",
                    "detail": "Building does not meet current ASHRAE 90.1 requirements.",
                })
                overall_risk = "High"

        return {
            "overall_risk": overall_risk,
            "risk_items": risk_items,
        }

    def _rank_improvements(self, simulation: Dict = None,
                            financial: Dict = None,
                            metrics: Dict = None) -> List[Dict[str, Any]]:
        improvements = []

        # From simulation
        if simulation:
            scenarios = simulation.get("scenarios", [])
            for s in scenarios:
                if s.get("annual_cost_savings", 0) > 0:
                    improvements.append({
                        "measure": s.get("display_name", s.get("scenario_name", "")),
                        "annual_savings": s.get("annual_cost_savings", 0),
                        "implementation_cost": s.get("implementation_cost", 0),
                        "payback_years": s.get("simple_payback_years"),
                        "roi_pct": s.get("roi_pct", 0),
                        "energy_reduction_pct": s.get("savings_pct", 0),
                        "carbon_reduction_mt": s.get("carbon_reduction_mt", 0),
                    })

        # From financial retrofit analysis
        if financial:
            retrofits = financial.get("retrofit_analysis", [])
            for r in retrofits:
                # Avoid duplicates
                if not any(imp["measure"] == r.get("name") for imp in improvements):
                    improvements.append({
                        "measure": r.get("name", ""),
                        "annual_savings": r.get("annual_cost_savings", 0),
                        "implementation_cost": r.get("implementation_cost", 0),
                        "payback_years": r.get("simple_payback_years"),
                        "roi_pct": r.get("irr_pct", 0),
                        "npv": r.get("npv", 0),
                        "cost_effective": r.get("cost_effective", False),
                    })

        # Sort by ROI (highest first)
        improvements.sort(key=lambda x: x.get("roi_pct", 0), reverse=True)
        return improvements

    def _summarize_compliance(self, benchmarking: Dict = None,
                               quality: Dict = None) -> Dict[str, Any]:
        summary = {
            "overall_status": "Unknown",
            "checks": [],
        }

        if benchmarking:
            compliance = benchmarking.get("code_compliance", {})
            summary["overall_status"] = "Pass" if compliance.get("overall_pass") else "Fail"

            envelope = compliance.get("envelope", [])
            for check in envelope:
                summary["checks"].append({
                    "component": check.get("component", ""),
                    "passes": check.get("passes", False),
                    "actual": check.get("actual"),
                    "required": check.get("required"),
                })

        return summary

    def _build_dashboard(self, metrics: Dict, carbon: Dict = None,
                          benchmarking: Dict = None) -> Dict[str, Any]:
        dashboard = {
            "energy": {},
            "cost": {},
            "carbon": {},
            "performance": {},
        }

        # Energy
        dashboard["energy"] = {
            "total_kwh": metrics.get("total_kwh", 0),
            "eui_kwh_sqft": metrics.get("eui_kwh_sqft_yr", metrics.get("eui", 0)),
            "eui_kbtu_sqft": metrics.get("eui_kbtu_sqft_yr", 0),
            "peak_cooling_tons": metrics.get("peak_cooling_tons", 0),
            "peak_heating_kbtu": metrics.get("peak_heating_kbtu_h", 0),
        }

        # Cost
        dashboard["cost"] = {
            "annual_total": metrics.get("total_annual_cost", 0),
            "cost_per_sqft": metrics.get("cost_per_sqft", 0),
            "cost_per_kwh": metrics.get("cost_per_kwh", 0),
        }

        # Carbon
        if carbon:
            emissions = carbon.get("carbon_emissions", {})
            dashboard["carbon"] = {
                "total_mt": emissions.get("total_metric_tons", 0),
                "intensity_kg_sqft": carbon.get("carbon_intensity", {}).get("kg_co2_per_sqft", 0),
                "esg_grade": carbon.get("esg_score", {}).get("grade", ""),
            }

        # Performance
        if benchmarking:
            grade = benchmarking.get("efficiency_grade", {})
            dashboard["performance"] = {
                "grade": grade.get("grade", ""),
                "percentile": grade.get("percentile", 0),
                "compliance": benchmarking.get("code_compliance", {}).get("overall_pass"),
            }

        return dashboard

    def generate_ai_prompt_context(self, executive_report: Dict[str, Any]) -> str:
        """Generate structured context for AI queries."""
        parts = []

        summary = executive_report.get("executive_summary", {})
        parts.append("=== EXECUTIVE SUMMARY ===")
        parts.append(f"Building: {summary.get('building_name', 'Unknown')}")
        parts.append(f"Floor Area: {summary.get('floor_area_sqft', 0):,.0f} sqft")
        for key, val in summary.get("key_numbers", {}).items():
            parts.append(f"  {key}: {val}")
        for h in summary.get("highlights", []):
            parts.append(f"  - {h}")
        parts.append("")

        # Inefficiencies
        ineff = executive_report.get("top_inefficiencies", [])
        if ineff:
            parts.append("=== TOP INEFFICIENCIES ===")
            for i, item in enumerate(ineff, 1):
                parts.append(f"  {i}. [{item.get('severity', '')}] {item.get('title', '')}")
                parts.append(f"     {item.get('description', '')}")
            parts.append("")

        # Risk
        risk = executive_report.get("risk_assessment", {})
        parts.append(f"=== RISK ASSESSMENT: {risk.get('overall_risk', 'Unknown')} ===")
        for r in risk.get("risk_items", []):
            parts.append(f"  [{r.get('level', '')}] {r.get('risk', '')}: {r.get('detail', '')}")
        parts.append("")

        # Improvements
        improvements = executive_report.get("ranked_improvements", [])
        if improvements:
            parts.append("=== RANKED IMPROVEMENTS ===")
            for i, imp in enumerate(improvements[:5], 1):
                parts.append(
                    f"  {i}. {imp.get('measure', '')}: "
                    f"saves ${imp.get('annual_savings', 0):,.0f}/yr, "
                    f"payback {imp.get('payback_years', 'N/A')} yrs"
                )
            parts.append("")

        # Dashboard
        dash = executive_report.get("key_metrics_dashboard", {})
        parts.append("=== KEY METRICS ===")
        for category, values in dash.items():
            if isinstance(values, dict):
                for k, v in values.items():
                    if v:
                        parts.append(f"  {category}.{k}: {v}")

        return "\n".join(parts)
