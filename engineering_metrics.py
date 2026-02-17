"""
Engineering Metrics Engine
Computes: load factor, seasonal variation, cooling/heating ratio,
kWh per ton, W/sqft, cost per kWh, carbon emissions, and more.
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("equestrag.metrics")

# ---------------------------------------------------------------------------
# Carbon emission factors (lbs CO2 per unit)
# ---------------------------------------------------------------------------
EMISSION_FACTORS = {
    "electricity_lbs_per_kwh": 0.855,   # US average grid
    "natural_gas_lbs_per_therm": 11.7,   # Natural gas combustion
    "fuel_oil_lbs_per_gallon": 22.4,
    "propane_lbs_per_gallon": 12.7,
    "steam_lbs_per_mlb": 66.4,
}

# Regional grid emission factors (lbs CO2 per kWh)
REGIONAL_EMISSION_FACTORS = {
    "US_average": 0.855,
    "NERC_WECC": 0.675,
    "NERC_RFC": 0.932,
    "NERC_SERC": 0.915,
    "NERC_TRE": 0.880,
    "NERC_NPCC": 0.530,
    "NERC_MRO": 1.035,
    "NERC_SPP": 0.963,
    "California": 0.450,
    "Pacific_Northwest": 0.250,
    "New_England": 0.520,
    "Southeast": 0.900,
    "Midwest": 1.000,
}


class EngineeringMetricsEngine:
    """Computes comprehensive engineering metrics from building data."""

    def compute(self, building_data: Dict[str, Any],
                region: str = "US_average") -> Dict[str, Any]:
        """Compute all engineering metrics."""
        metrics = {}

        # Extract source data
        bepu = building_data.get("bepu", {}) if isinstance(building_data.get("bepu"), dict) else {}
        ls_c = building_data.get("ls_c", {}) if isinstance(building_data.get("ls_c"), dict) else {}
        es_d = building_data.get("es_d", {}) if isinstance(building_data.get("es_d"), dict) else {}
        ps_e = building_data.get("ps_e", [])
        if isinstance(ps_e, dict):
            ps_e = ps_e.get("ps_e", [])

        # ── Basic metrics ──────────────────────────────────────────
        floor_area = bepu.get("floor_area_sqft", 0)
        total_kwh = bepu.get("total_electricity_kwh", 0)
        total_gas = bepu.get("total_gas_therm", 0)
        eui = bepu.get("eui_kwh_sqft_yr", 0)

        if floor_area > 0:
            metrics["floor_area_sqft"] = floor_area

        if total_kwh > 0:
            metrics["total_kwh"] = total_kwh
            metrics["avg_power_kw"] = round(total_kwh / 8760, 2)

        if total_gas > 0:
            metrics["total_gas_therm"] = total_gas

        if eui > 0:
            metrics["eui_kwh_sqft_yr"] = eui
            # Also compute in kBTU/sqft/yr
            metrics["eui_kbtu_sqft_yr"] = round(eui * 3.412, 2)

        # ── W/sqft (lighting + equipment power density) ────────────
        if floor_area > 0 and total_kwh > 0:
            metrics["w_per_sqft"] = round((total_kwh / 8760 * 1000) / floor_area, 2)

        # ── Peak loads ─────────────────────────────────────────────
        cooling_kbtu = ls_c.get("cooling_load_kbtu_h", 0)
        heating_kbtu = ls_c.get("heating_load_kbtu_h", 0)

        if cooling_kbtu > 0:
            metrics["peak_cooling_kbtu_h"] = cooling_kbtu
            metrics["peak_cooling_tons"] = round(cooling_kbtu / 12.0, 1)
            metrics["peak_cooling_kw"] = round(cooling_kbtu * 0.29307107, 1)

        if heating_kbtu > 0:
            metrics["peak_heating_kbtu_h"] = heating_kbtu
            metrics["peak_heating_kw"] = round(heating_kbtu * 0.29307107, 1)

        # ── Cooling/Heating ratio ──────────────────────────────────
        if cooling_kbtu > 0 and heating_kbtu > 0:
            metrics["cooling_heating_ratio"] = round(cooling_kbtu / heating_kbtu, 2)

        # ── Load factor ────────────────────────────────────────────
        if total_kwh > 0 and cooling_kbtu > 0:
            peak_kw = cooling_kbtu * 0.29307107
            if peak_kw > 0:
                metrics["load_factor"] = round((total_kwh / 8760) / peak_kw, 3)

        # ── kWh per ton ────────────────────────────────────────────
        if total_kwh > 0 and cooling_kbtu > 0:
            cooling_tons = cooling_kbtu / 12.0
            if cooling_tons > 0:
                metrics["kwh_per_ton"] = round(total_kwh / cooling_tons, 1)

        # ── Sqft per ton ───────────────────────────────────────────
        if floor_area > 0 and cooling_kbtu > 0:
            cooling_tons = cooling_kbtu / 12.0
            if cooling_tons > 0:
                metrics["sqft_per_ton"] = round(floor_area / cooling_tons, 0)

        # ── BTU/sqft (total site energy intensity) ─────────────────
        if floor_area > 0:
            total_btu = (total_kwh * 3412) + (total_gas * 100000)
            metrics["btu_per_sqft"] = round(total_btu / floor_area, 0)

        # ── Cost metrics ───────────────────────────────────────────
        cost_per_sqft = es_d.get("cost_per_sqft", 0)
        total_cost = es_d.get("total_cost", 0)

        if cost_per_sqft > 0:
            metrics["cost_per_sqft"] = cost_per_sqft
        if total_cost > 0:
            metrics["total_annual_cost"] = total_cost
        elif cost_per_sqft > 0 and floor_area > 0:
            metrics["total_annual_cost"] = round(cost_per_sqft * floor_area, 2)

        if metrics.get("total_annual_cost", 0) > 0 and total_kwh > 0:
            metrics["cost_per_kwh"] = round(metrics["total_annual_cost"] / total_kwh, 4)

        if metrics.get("total_annual_cost", 0) > 0:
            metrics["monthly_avg_cost"] = round(metrics["total_annual_cost"] / 12, 2)

        # ── Seasonal variation ─────────────────────────────────────
        monthly_metrics = self._compute_monthly_metrics(ps_e)
        if monthly_metrics:
            metrics.update(monthly_metrics)

        # ── Carbon emissions ───────────────────────────────────────
        carbon = self._compute_carbon(total_kwh, total_gas, region)
        metrics.update(carbon)

        # ── End-use breakdown percentages ──────────────────────────
        end_use = self._compute_end_use_breakdown(ps_e)
        if end_use:
            metrics["end_use_breakdown"] = end_use

        return metrics

    def _compute_monthly_metrics(self, ps_e: List) -> Dict[str, Any]:
        """Compute seasonal variation and monthly pattern metrics."""
        if not isinstance(ps_e, list):
            return {}

        monthly = [r for r in ps_e if r.get("Month") not in ("ANNUAL", None)]
        if len(monthly) < 6:
            return {}

        totals = [r.get("Total", 0) for r in monthly]
        if not totals or max(totals) == 0:
            return {}

        result = {}
        result["seasonal_variation"] = round(
            (max(totals) - min(totals)) / max(totals) * 100, 1
        )

        # Peak and min months
        peak_idx = totals.index(max(totals))
        min_idx = totals.index(min(totals))
        result["peak_month"] = monthly[peak_idx].get("Month", "")
        result["lowest_month"] = monthly[min_idx].get("Month", "")
        result["peak_monthly_total"] = max(totals)
        result["min_monthly_total"] = min(totals)
        result["avg_monthly_total"] = round(sum(totals) / len(totals), 2)

        # Summer vs winter ratio
        summer_months = {"JUN", "JUL", "AUG"}
        winter_months = {"DEC", "JAN", "FEB"}
        summer_total = sum(r.get("Total", 0) for r in monthly if r.get("Month") in summer_months)
        winter_total = sum(r.get("Total", 0) for r in monthly if r.get("Month") in winter_months)
        if winter_total > 0:
            result["summer_winter_ratio"] = round(summer_total / winter_total, 2)

        # Cooling-dominant months
        cooling_months = sum(
            1 for r in monthly
            if r.get("Cooling", 0) > r.get("Heating", 0)
        )
        result["cooling_dominant_months"] = cooling_months
        result["heating_dominant_months"] = len(monthly) - cooling_months

        return result

    def _compute_carbon(self, total_kwh: float, total_gas: float,
                        region: str = "US_average") -> Dict[str, Any]:
        """Compute carbon emissions."""
        result = {}
        emission_factor = REGIONAL_EMISSION_FACTORS.get(region, 0.855)

        electric_co2_lbs = total_kwh * emission_factor
        gas_co2_lbs = total_gas * EMISSION_FACTORS["natural_gas_lbs_per_therm"]
        total_co2_lbs = electric_co2_lbs + gas_co2_lbs

        if total_co2_lbs > 0:
            result["carbon_total_lbs"] = round(total_co2_lbs, 0)
            result["carbon_total_metric_tons"] = round(total_co2_lbs / 2204.62, 2)
            result["carbon_electric_lbs"] = round(electric_co2_lbs, 0)
            result["carbon_gas_lbs"] = round(gas_co2_lbs, 0)
            result["carbon_intensity_lbs_per_sqft"] = 0  # needs floor area
            result["tree_equivalence"] = round(total_co2_lbs / 2204.62 / 0.06, 0)
            result["car_equivalence"] = round(total_co2_lbs / 2204.62 / 4.6, 1)

        return result

    def _compute_end_use_breakdown(self, ps_e: List) -> Optional[Dict[str, Any]]:
        """Compute end-use percentages from PS-E data."""
        if not isinstance(ps_e, list):
            return None

        annual = [r for r in ps_e if r.get("Month") == "ANNUAL"]
        if not annual:
            return None

        row = annual[0]
        categories = {
            "Lighting": row.get("Lights", 0),
            "Equipment": row.get("Equipment", 0),
            "Heating": row.get("Heating", 0),
            "Cooling": row.get("Cooling", 0),
            "Ventilation": row.get("Vent_Fans", 0),
            "Hot Water": row.get("Hot_Water", 0),
            "Pumps": row.get("Pumps_Aux", 0),
        }

        total = sum(categories.values())
        if total == 0:
            return None

        breakdown = {}
        for name, value in categories.items():
            if value > 0:
                breakdown[name] = {
                    "value": round(value, 2),
                    "percentage": round(value / total * 100, 1),
                }

        # Find dominant end-use
        dominant = max(categories, key=categories.get)
        breakdown["dominant_end_use"] = dominant
        breakdown["dominant_percentage"] = round(categories[dominant] / total * 100, 1)

        return breakdown
