"""
Carbon & ESG Module
CO2 emissions, carbon intensity, ESG readiness scoring,
tree equivalence, and portfolio carbon summary.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger("equestrag.carbon_esg")

# Grid emission factors by region (metric tons CO2 per MWh)
GRID_EMISSION_FACTORS_MT_PER_MWH = {
    "US_average": 0.388,
    "WECC": 0.306,
    "RFC": 0.423,
    "SERC": 0.415,
    "TRE": 0.399,
    "NPCC": 0.240,
    "MRO": 0.470,
    "SPP": 0.437,
    "FRCC": 0.397,
    "California": 0.204,
    "Pacific_Northwest": 0.113,
    "New_England": 0.236,
    "New_York": 0.200,
    "Southeast": 0.408,
    "Midwest": 0.454,
    "Texas": 0.399,
}

# Natural gas: 0.00531 metric tons CO2 per therm
GAS_EMISSION_FACTOR = 0.00531

# ESG framework categories
ESG_CATEGORIES = {
    "energy_efficiency": {"weight": 0.30, "description": "Building energy performance vs benchmarks"},
    "carbon_intensity": {"weight": 0.25, "description": "Carbon emissions per sqft"},
    "renewable_readiness": {"weight": 0.15, "description": "Readiness for renewable energy"},
    "envelope_performance": {"weight": 0.15, "description": "Building envelope quality"},
    "operational_efficiency": {"weight": 0.15, "description": "Operational patterns and waste"},
}


class CarbonESGEngine:
    """Computes carbon emissions, ESG scores, and sustainability metrics."""

    def analyze(self, building_data: Dict[str, Any],
                metrics: Dict[str, Any],
                region: str = "US_average") -> Dict[str, Any]:
        result = {
            "carbon_emissions": self._compute_emissions(building_data, metrics, region),
            "carbon_intensity": self._compute_intensity(building_data, metrics, region),
            "esg_score": self._compute_esg_score(building_data, metrics),
            "equivalences": {},
            "reduction_opportunities": self._compute_reduction_opportunities(building_data, metrics, region),
        }

        # Compute equivalences
        total_mt = result["carbon_emissions"].get("total_metric_tons", 0)
        if total_mt > 0:
            result["equivalences"] = self._compute_equivalences(total_mt)

        return result

    def _compute_emissions(self, data: Dict, metrics: Dict,
                            region: str) -> Dict[str, Any]:
        bepu = data.get("bepu", {})
        if not isinstance(bepu, dict):
            bepu = {}

        total_kwh = bepu.get("total_electricity_kwh", metrics.get("total_kwh", 0))
        total_gas = bepu.get("total_gas_therm", metrics.get("total_gas_therm", 0))

        grid_factor = GRID_EMISSION_FACTORS_MT_PER_MWH.get(region, 0.388)

        electric_mt = (total_kwh / 1000) * grid_factor  # MWh * MT/MWh
        gas_mt = total_gas * GAS_EMISSION_FACTOR

        total_mt = electric_mt + gas_mt

        result = {
            "electric_kwh": total_kwh,
            "gas_therms": total_gas,
            "electric_co2_metric_tons": round(electric_mt, 2),
            "gas_co2_metric_tons": round(gas_mt, 2),
            "total_metric_tons": round(total_mt, 2),
            "total_lbs": round(total_mt * 2204.62, 0),
            "total_kg": round(total_mt * 1000, 0),
            "grid_region": region,
            "grid_factor_mt_per_mwh": grid_factor,
            "electric_pct_of_total": round(electric_mt / total_mt * 100, 1) if total_mt > 0 else 0,
            "gas_pct_of_total": round(gas_mt / total_mt * 100, 1) if total_mt > 0 else 0,
        }

        # Monthly breakdown if PS-E data available
        ps_e = data.get("ps_e", [])
        if isinstance(ps_e, list):
            monthly = [r for r in ps_e if r.get("Month") not in ("ANNUAL", None)]
            if monthly:
                monthly_carbon = []
                for row in monthly:
                    month_total = row.get("Total", 0)
                    # Approximate: assume total is electric only for monthly
                    month_mt = (month_total / 1000) * grid_factor
                    monthly_carbon.append({
                        "month": row.get("Month", ""),
                        "co2_metric_tons": round(month_mt, 3),
                    })
                result["monthly_breakdown"] = monthly_carbon

        return result

    def _compute_intensity(self, data: Dict, metrics: Dict,
                            region: str) -> Dict[str, Any]:
        bepu = data.get("bepu", {})
        if not isinstance(bepu, dict):
            bepu = {}

        floor_area = bepu.get("floor_area_sqft", metrics.get("floor_area_sqft", 0))
        total_kwh = bepu.get("total_electricity_kwh", metrics.get("total_kwh", 0))
        total_gas = bepu.get("total_gas_therm", metrics.get("total_gas_therm", 0))

        grid_factor = GRID_EMISSION_FACTORS_MT_PER_MWH.get(region, 0.388)
        total_mt = (total_kwh / 1000) * grid_factor + total_gas * GAS_EMISSION_FACTOR

        result = {}
        if floor_area > 0 and total_mt > 0:
            result["kg_co2_per_sqft"] = round(total_mt * 1000 / floor_area, 2)
            result["kg_co2_per_sqm"] = round(total_mt * 1000 / (floor_area * 0.0929), 2)
            result["lbs_co2_per_sqft"] = round(total_mt * 2204.62 / floor_area, 2)

            # Benchmark: typical office = 5-8 kg CO2/sqft/yr
            if result["kg_co2_per_sqft"] < 3:
                result["intensity_rating"] = "Low"
            elif result["kg_co2_per_sqft"] < 6:
                result["intensity_rating"] = "Moderate"
            elif result["kg_co2_per_sqft"] < 10:
                result["intensity_rating"] = "High"
            else:
                result["intensity_rating"] = "Very High"

        return result

    def _compute_esg_score(self, data: Dict, metrics: Dict) -> Dict[str, Any]:
        scores = {}
        bepu = data.get("bepu", {}) if isinstance(data.get("bepu"), dict) else {}

        # Energy efficiency score (0-100)
        eui = bepu.get("eui_kwh_sqft_yr", 0)
        if eui > 0:
            eui_kbtu = eui * 3.412
            if eui_kbtu < 40:
                scores["energy_efficiency"] = 95
            elif eui_kbtu < 60:
                scores["energy_efficiency"] = 80
            elif eui_kbtu < 80:
                scores["energy_efficiency"] = 65
            elif eui_kbtu < 100:
                scores["energy_efficiency"] = 50
            elif eui_kbtu < 130:
                scores["energy_efficiency"] = 35
            else:
                scores["energy_efficiency"] = 20

        # Carbon intensity score
        total_kwh = bepu.get("total_electricity_kwh", 0)
        floor_area = bepu.get("floor_area_sqft", 0)
        if total_kwh > 0 and floor_area > 0:
            kwh_per_sqft = total_kwh / floor_area
            if kwh_per_sqft < 10:
                scores["carbon_intensity"] = 90
            elif kwh_per_sqft < 15:
                scores["carbon_intensity"] = 75
            elif kwh_per_sqft < 20:
                scores["carbon_intensity"] = 60
            elif kwh_per_sqft < 30:
                scores["carbon_intensity"] = 45
            else:
                scores["carbon_intensity"] = 25

        # Envelope score
        lv_d = data.get("lv_d", {})
        if isinstance(lv_d, dict) and lv_d.get("summary", {}).get("has_envelope_data"):
            scores["envelope_performance"] = 70  # Base score for having data
            summary = lv_d.get("summary", {})
            wwr = summary.get("window_wall_ratio", 0)
            if 0 < wwr <= 0.30:
                scores["envelope_performance"] = 85
            elif wwr <= 0.40:
                scores["envelope_performance"] = 70
            elif wwr > 0.40:
                scores["envelope_performance"] = 50

        # Operational efficiency from monthly variation
        seasonal_var = metrics.get("seasonal_variation", 0)
        if seasonal_var > 0:
            # Moderate variation is good (shows weather response)
            if 15 < seasonal_var < 50:
                scores["operational_efficiency"] = 80
            elif seasonal_var <= 15:
                scores["operational_efficiency"] = 50  # Too flat
            else:
                scores["operational_efficiency"] = 60  # Too variable

        # Renewable readiness (default moderate)
        scores["renewable_readiness"] = 50  # Default

        # Compute weighted total
        total_score = 0
        total_weight = 0
        category_details = {}

        for category, config in ESG_CATEGORIES.items():
            if category in scores:
                weight = config["weight"]
                score = scores[category]
                total_score += score * weight
                total_weight += weight
                category_details[category] = {
                    "score": score,
                    "weight": weight,
                    "description": config["description"],
                }

        overall = round(total_score / total_weight, 1) if total_weight > 0 else 0

        # ESG grade
        if overall >= 80:
            grade = "A"
            readiness = "ESG Ready"
        elif overall >= 65:
            grade = "B"
            readiness = "ESG Emerging"
        elif overall >= 50:
            grade = "C"
            readiness = "ESG Developing"
        else:
            grade = "D"
            readiness = "ESG Needs Improvement"

        return {
            "overall_score": overall,
            "grade": grade,
            "readiness": readiness,
            "categories": category_details,
        }

    def _compute_equivalences(self, total_mt: float) -> Dict[str, Any]:
        return {
            "trees_needed_to_offset": round(total_mt / 0.06, 0),
            "cars_equivalent": round(total_mt / 4.6, 1),
            "homes_equivalent": round(total_mt / 7.5, 1),
            "flights_nyc_la": round(total_mt / 0.9, 1),
            "gallons_gas_equivalent": round(total_mt / 0.00887, 0),
            "acres_forest_needed": round(total_mt / 0.73, 1),
            "smartphones_charged": round(total_mt * 1000 / 0.008, 0),
        }

    def _compute_reduction_opportunities(self, data: Dict, metrics: Dict,
                                          region: str) -> List[Dict[str, Any]]:
        opportunities = []
        bepu = data.get("bepu", {}) if isinstance(data.get("bepu"), dict) else {}
        total_kwh = bepu.get("total_electricity_kwh", 0)
        total_gas = bepu.get("total_gas_therm", 0)
        grid_factor = GRID_EMISSION_FACTORS_MT_PER_MWH.get(region, 0.388)

        # LED lighting upgrade
        ps_e = data.get("ps_e", [])
        if isinstance(ps_e, list):
            annual = [r for r in ps_e if r.get("Month") == "ANNUAL"]
            if annual:
                lights = annual[0].get("Lights", 0)
                if lights > 0:
                    savings_kwh = lights * 0.40  # 40% savings
                    savings_mt = (savings_kwh / 1000) * grid_factor
                    opportunities.append({
                        "measure": "LED Lighting Upgrade",
                        "energy_savings_kwh": round(savings_kwh, 0),
                        "carbon_reduction_mt": round(savings_mt, 2),
                        "estimated_reduction_pct": 40,
                        "category": "Lighting",
                    })

        # HVAC efficiency improvement
        if total_kwh > 0:
            hvac_savings = total_kwh * 0.15  # 15% savings from HVAC upgrade
            savings_mt = (hvac_savings / 1000) * grid_factor
            opportunities.append({
                "measure": "HVAC Efficiency Upgrade",
                "energy_savings_kwh": round(hvac_savings, 0),
                "carbon_reduction_mt": round(savings_mt, 2),
                "estimated_reduction_pct": 15,
                "category": "HVAC",
            })

        # Envelope improvements
        if total_kwh > 0:
            envelope_savings = total_kwh * 0.10
            savings_mt = (envelope_savings / 1000) * grid_factor
            opportunities.append({
                "measure": "Building Envelope Improvement",
                "energy_savings_kwh": round(envelope_savings, 0),
                "carbon_reduction_mt": round(savings_mt, 2),
                "estimated_reduction_pct": 10,
                "category": "Envelope",
            })

        # Renewable energy
        if total_kwh > 0:
            solar_potential = total_kwh * 0.30  # 30% offset
            savings_mt = (solar_potential / 1000) * grid_factor
            opportunities.append({
                "measure": "Rooftop Solar PV",
                "energy_savings_kwh": round(solar_potential, 0),
                "carbon_reduction_mt": round(savings_mt, 2),
                "estimated_reduction_pct": 30,
                "category": "Renewable",
            })

        return opportunities

    def portfolio_carbon_summary(self, buildings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate carbon summary across a portfolio of buildings."""
        total_mt = sum(b.get("carbon_emissions", {}).get("total_metric_tons", 0) for b in buildings)
        total_area = sum(b.get("floor_area_sqft", 0) for b in buildings)
        total_kwh = sum(b.get("total_kwh", 0) for b in buildings)

        return {
            "total_buildings": len(buildings),
            "total_carbon_mt": round(total_mt, 2),
            "total_area_sqft": total_area,
            "avg_carbon_intensity_kg_sqft": round(total_mt * 1000 / total_area, 2) if total_area > 0 else 0,
            "total_kwh": total_kwh,
            "equivalences": self._compute_equivalences(total_mt),
        }
