"""
Benchmarking & Code Compliance Engine
Climate-zone based benchmarking, building-type comparison,
ASHRAE/IECC compliance, efficiency grading, and percentile ranking.
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("equestrag.benchmarking")

# ---------------------------------------------------------------------------
# Benchmark databases
# ---------------------------------------------------------------------------

# EUI benchmarks by building type (kBTU/sqft/yr) - based on CBECS data
BUILDING_TYPE_EUI = {
    "office_small": {"p25": 35, "median": 55, "p75": 80, "mean": 65},
    "office_medium": {"p25": 40, "median": 65, "p75": 95, "mean": 75},
    "office_large": {"p25": 50, "median": 75, "p75": 110, "mean": 85},
    "office": {"p25": 40, "median": 65, "p75": 90, "mean": 72},
    "retail": {"p25": 30, "median": 55, "p75": 85, "mean": 60},
    "school_primary": {"p25": 30, "median": 50, "p75": 75, "mean": 55},
    "school_secondary": {"p25": 35, "median": 55, "p75": 80, "mean": 60},
    "school": {"p25": 30, "median": 50, "p75": 75, "mean": 55},
    "hospital": {"p25": 120, "median": 180, "p75": 250, "mean": 195},
    "hotel": {"p25": 50, "median": 80, "p75": 120, "mean": 90},
    "warehouse": {"p25": 15, "median": 25, "p75": 40, "mean": 30},
    "restaurant": {"p25": 150, "median": 250, "p75": 400, "mean": 280},
    "multifamily": {"p25": 30, "median": 50, "p75": 70, "mean": 55},
    "laboratory": {"p25": 100, "median": 200, "p75": 350, "mean": 240},
    "data_center": {"p25": 200, "median": 400, "p75": 800, "mean": 500},
    "default": {"p25": 35, "median": 60, "p75": 90, "mean": 70},
}

# Climate zone adjustment factors (relative to baseline)
CLIMATE_ZONE_FACTORS = {
    "1A": 1.15, "1B": 1.10,
    "2A": 1.10, "2B": 1.05,
    "3A": 1.00, "3B": 0.95, "3C": 0.85,
    "4A": 1.00, "4B": 0.95, "4C": 0.90,
    "5A": 1.05, "5B": 1.00, "5C": 0.95,
    "6A": 1.10, "6B": 1.05,
    "7": 1.15,
    "8": 1.20,
}

# ASHRAE 90.1-2019 envelope requirements by climate zone
ASHRAE_ENVELOPE = {
    "1": {"wall_u": 0.124, "roof_u": 0.063, "window_u": 1.22, "shgc": 0.25},
    "2": {"wall_u": 0.124, "roof_u": 0.063, "window_u": 0.75, "shgc": 0.25},
    "3": {"wall_u": 0.124, "roof_u": 0.063, "window_u": 0.65, "shgc": 0.25},
    "4": {"wall_u": 0.124, "roof_u": 0.063, "window_u": 0.55, "shgc": 0.40},
    "5": {"wall_u": 0.090, "roof_u": 0.063, "window_u": 0.55, "shgc": 0.40},
    "6": {"wall_u": 0.090, "roof_u": 0.048, "window_u": 0.55, "shgc": 0.40},
    "7": {"wall_u": 0.080, "roof_u": 0.048, "window_u": 0.45, "shgc": 0.40},
    "8": {"wall_u": 0.071, "roof_u": 0.048, "window_u": 0.45, "shgc": 0.40},
}

# ASHRAE 90.1 lighting power density limits (W/sqft)
ASHRAE_LPD = {
    "office": 0.82,
    "retail": 1.06,
    "school": 0.87,
    "hospital": 0.96,
    "hotel": 0.75,
    "warehouse": 0.66,
    "restaurant": 0.90,
    "multifamily": 0.60,
    "default": 0.82,
}


class BenchmarkingEngine:
    """Benchmarks building performance against standards and peers."""

    def benchmark(self, building_data: Dict[str, Any],
                  metrics: Dict[str, Any],
                  building_type: str = "office",
                  climate_zone: str = "4A") -> Dict[str, Any]:
        result = {
            "eui_benchmark": self._benchmark_eui(building_data, metrics, building_type, climate_zone),
            "efficiency_grade": {},
            "code_compliance": self._check_code_compliance(building_data, climate_zone, building_type),
            "peer_comparison": self._compare_to_peers(metrics, building_type, climate_zone),
            "improvement_potential": {},
        }

        # Overall grade
        result["efficiency_grade"] = self._compute_grade(result)

        # Improvement potential
        result["improvement_potential"] = self._compute_improvement_potential(
            metrics, building_type, climate_zone
        )

        return result

    def _benchmark_eui(self, data: Dict, metrics: Dict,
                       building_type: str, climate_zone: str) -> Dict[str, Any]:
        bepu = data.get("bepu", {})
        if not isinstance(bepu, dict):
            return {}

        eui_kwh = bepu.get("eui_kwh_sqft_yr", 0)
        if eui_kwh <= 0:
            return {}

        eui_kbtu = eui_kwh * 3.412

        # Get benchmarks
        benchmarks = BUILDING_TYPE_EUI.get(building_type.lower(), BUILDING_TYPE_EUI["default"])
        cz_factor = CLIMATE_ZONE_FACTORS.get(climate_zone, 1.0)

        # Adjust benchmarks for climate zone
        adj_benchmarks = {k: v * cz_factor for k, v in benchmarks.items()}

        # Calculate percentile
        if eui_kbtu <= adj_benchmarks["p25"]:
            percentile = round(25 * eui_kbtu / adj_benchmarks["p25"]) if adj_benchmarks["p25"] > 0 else 0
        elif eui_kbtu <= adj_benchmarks["median"]:
            percentile = 25 + round(25 * (eui_kbtu - adj_benchmarks["p25"]) /
                                    (adj_benchmarks["median"] - adj_benchmarks["p25"]))
        elif eui_kbtu <= adj_benchmarks["p75"]:
            percentile = 50 + round(25 * (eui_kbtu - adj_benchmarks["median"]) /
                                    (adj_benchmarks["p75"] - adj_benchmarks["median"]))
        else:
            percentile = min(99, 75 + round(25 * (eui_kbtu - adj_benchmarks["p75"]) /
                                             max(adj_benchmarks["p75"], 1)))

        # Better/worse than median
        if adj_benchmarks["median"] > 0:
            pct_vs_median = round((eui_kbtu - adj_benchmarks["median"]) / adj_benchmarks["median"] * 100, 1)
        else:
            pct_vs_median = 0

        return {
            "building_eui_kbtu": round(eui_kbtu, 1),
            "building_eui_kwh": round(eui_kwh, 2),
            "benchmark_p25": round(adj_benchmarks["p25"], 1),
            "benchmark_median": round(adj_benchmarks["median"], 1),
            "benchmark_p75": round(adj_benchmarks["p75"], 1),
            "benchmark_mean": round(adj_benchmarks["mean"], 1),
            "percentile": min(99, max(1, percentile)),
            "pct_vs_median": pct_vs_median,
            "better_than_median": pct_vs_median < 0,
            "climate_zone": climate_zone,
            "building_type": building_type,
            "climate_adjustment_factor": cz_factor,
        }

    def _check_code_compliance(self, data: Dict, climate_zone: str,
                                building_type: str) -> Dict[str, Any]:
        compliance = {
            "envelope": [],
            "lighting": {},
            "overall_pass": True,
        }

        # Get ASHRAE requirements for this climate zone
        cz_num = climate_zone[0] if climate_zone else "4"
        ashrae = ASHRAE_ENVELOPE.get(cz_num, ASHRAE_ENVELOPE["4"])

        # Check envelope
        lv_d = data.get("lv_d", {})
        if isinstance(lv_d, dict):
            summary = lv_d.get("summary", {})

            if "avg_wall_u_value" in summary:
                wall_u = summary["avg_wall_u_value"]
                passes = wall_u <= ashrae["wall_u"]
                compliance["envelope"].append({
                    "component": "Wall U-Value",
                    "actual": wall_u,
                    "required": ashrae["wall_u"],
                    "passes": passes,
                    "unit": "BTU/h-ft2-F",
                })
                if not passes:
                    compliance["overall_pass"] = False

            if "avg_roof_u_value" in summary:
                roof_u = summary["avg_roof_u_value"]
                passes = roof_u <= ashrae["roof_u"]
                compliance["envelope"].append({
                    "component": "Roof U-Value",
                    "actual": roof_u,
                    "required": ashrae["roof_u"],
                    "passes": passes,
                    "unit": "BTU/h-ft2-F",
                })
                if not passes:
                    compliance["overall_pass"] = False

            if "avg_window_u_value" in summary:
                win_u = summary["avg_window_u_value"]
                passes = win_u <= ashrae["window_u"]
                compliance["envelope"].append({
                    "component": "Window U-Value",
                    "actual": win_u,
                    "required": ashrae["window_u"],
                    "passes": passes,
                    "unit": "BTU/h-ft2-F",
                })
                if not passes:
                    compliance["overall_pass"] = False

            if "avg_shgc" in summary:
                shgc = summary["avg_shgc"]
                passes = shgc <= ashrae["shgc"]
                compliance["envelope"].append({
                    "component": "Window SHGC",
                    "actual": shgc,
                    "required": ashrae["shgc"],
                    "passes": passes,
                    "unit": "dimensionless",
                })
                if not passes:
                    compliance["overall_pass"] = False

            if "window_wall_ratio" in summary:
                wwr = summary["window_wall_ratio"]
                passes = wwr <= 0.40
                compliance["envelope"].append({
                    "component": "Window-Wall Ratio",
                    "actual": wwr,
                    "required": 0.40,
                    "passes": passes,
                    "unit": "ratio",
                })

        # Lighting power density check
        lpd_limit = ASHRAE_LPD.get(building_type.lower(), ASHRAE_LPD["default"])
        compliance["lighting"] = {
            "lpd_limit_w_sqft": lpd_limit,
            "building_type": building_type,
            "standard": "ASHRAE 90.1-2019",
        }

        return compliance

    def _compare_to_peers(self, metrics: Dict, building_type: str,
                           climate_zone: str) -> Dict[str, Any]:
        result = {}

        benchmarks = BUILDING_TYPE_EUI.get(building_type.lower(), BUILDING_TYPE_EUI["default"])
        cz_factor = CLIMATE_ZONE_FACTORS.get(climate_zone, 1.0)

        # Cost comparison
        cost_sqft = metrics.get("cost_per_sqft", 0)
        if cost_sqft > 0:
            # Typical cost benchmarks
            typical_costs = {
                "office": 2.50, "retail": 2.00, "school": 1.80,
                "hospital": 3.50, "hotel": 2.80, "warehouse": 0.80,
                "default": 2.50,
            }
            typical = typical_costs.get(building_type.lower(), typical_costs["default"])
            result["cost_comparison"] = {
                "actual_cost_sqft": cost_sqft,
                "typical_cost_sqft": typical,
                "pct_difference": round((cost_sqft - typical) / typical * 100, 1) if typical > 0 else 0,
            }

        return result

    def _compute_grade(self, result: Dict) -> Dict[str, Any]:
        eui_bench = result.get("eui_benchmark", {})
        percentile = eui_bench.get("percentile", 50)

        if percentile <= 10:
            grade = "A+"
            label = "Outstanding"
        elif percentile <= 25:
            grade = "A"
            label = "Excellent"
        elif percentile <= 40:
            grade = "B"
            label = "Good"
        elif percentile <= 60:
            grade = "C"
            label = "Average"
        elif percentile <= 75:
            grade = "D"
            label = "Below Average"
        else:
            grade = "F"
            label = "Poor"

        # Compliance bonus/penalty
        compliance = result.get("code_compliance", {})
        if compliance.get("overall_pass") is False:
            if grade in ("A+", "A"):
                grade = "B"
            elif grade == "B":
                grade = "C"

        return {
            "grade": grade,
            "label": label,
            "percentile": percentile,
        }

    def _compute_improvement_potential(self, metrics: Dict, building_type: str,
                                        climate_zone: str) -> Dict[str, Any]:
        benchmarks = BUILDING_TYPE_EUI.get(building_type.lower(), BUILDING_TYPE_EUI["default"])
        cz_factor = CLIMATE_ZONE_FACTORS.get(climate_zone, 1.0)

        eui_kbtu = metrics.get("eui_kbtu_sqft_yr", 0)
        if eui_kbtu <= 0:
            eui_kwh = metrics.get("eui", metrics.get("eui_kwh_sqft_yr", 0))
            eui_kbtu = eui_kwh * 3.412 if eui_kwh > 0 else 0

        if eui_kbtu <= 0:
            return {}

        target_eui = benchmarks["p25"] * cz_factor
        floor_area = metrics.get("floor_area_sqft", 0)
        cost_kwh = metrics.get("cost_per_kwh", 0.12)

        if eui_kbtu > target_eui:
            savings_pct = round((eui_kbtu - target_eui) / eui_kbtu * 100, 1)
            savings_kbtu = eui_kbtu - target_eui
            savings_kwh = savings_kbtu / 3.412
            annual_kwh_savings = savings_kwh * floor_area if floor_area > 0 else 0
            annual_cost_savings = annual_kwh_savings * cost_kwh

            return {
                "target_eui_kbtu": round(target_eui, 1),
                "current_eui_kbtu": round(eui_kbtu, 1),
                "savings_potential_pct": savings_pct,
                "savings_kbtu_sqft": round(savings_kbtu, 1),
                "annual_kwh_savings": round(annual_kwh_savings, 0) if annual_kwh_savings > 0 else None,
                "annual_cost_savings": round(annual_cost_savings, 2) if annual_cost_savings > 0 else None,
            }

        return {
            "target_eui_kbtu": round(target_eui, 1),
            "current_eui_kbtu": round(eui_kbtu, 1),
            "savings_potential_pct": 0,
            "note": "Building already performs at or better than target",
        }
