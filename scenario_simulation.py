"""
Scenario Simulation Engine
Simulate: lighting reduction, HVAC efficiency improvement, envelope improvement,
demand reduction, carbon reduction. Includes payback and ROI calculations.
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("equestrag.simulation")

# Typical cost estimates ($/sqft unless noted)
DEFAULT_MEASURE_COSTS = {
    "led_lighting": {"cost_per_sqft": 2.50, "lifetime_years": 15},
    "hvac_upgrade": {"cost_per_sqft": 8.00, "lifetime_years": 20},
    "vfd_motors": {"cost_per_sqft": 1.50, "lifetime_years": 15},
    "envelope_insulation": {"cost_per_sqft": 5.00, "lifetime_years": 30},
    "window_upgrade": {"cost_per_sqft": 12.00, "lifetime_years": 25},
    "smart_controls": {"cost_per_sqft": 3.00, "lifetime_years": 10},
    "demand_response": {"cost_per_sqft": 0.50, "lifetime_years": 10},
    "solar_pv": {"cost_per_watt": 2.50, "lifetime_years": 25},
    "heat_pump": {"cost_per_sqft": 6.00, "lifetime_years": 20},
    "energy_recovery": {"cost_per_sqft": 4.00, "lifetime_years": 20},
}

# Typical energy savings percentages
DEFAULT_SAVINGS = {
    "led_lighting": {"lighting": 0.40, "cooling": 0.05},
    "hvac_upgrade": {"cooling": 0.20, "heating": 0.15, "fans": 0.10},
    "vfd_motors": {"fans": 0.30, "pumps": 0.25},
    "envelope_insulation": {"heating": 0.15, "cooling": 0.10},
    "window_upgrade": {"heating": 0.10, "cooling": 0.15},
    "smart_controls": {"lighting": 0.15, "cooling": 0.10, "heating": 0.10},
    "demand_response": {"total": 0.05},
    "heat_pump": {"heating": 0.40, "gas": 0.50},
    "energy_recovery": {"heating": 0.20, "cooling": 0.10},
}


class ScenarioSimulationEngine:
    """Simulates energy efficiency improvement scenarios with financial analysis."""

    def simulate(self, building_data: Dict[str, Any],
                 metrics: Dict[str, Any],
                 scenarios: Optional[List[str]] = None,
                 electricity_rate: float = 0.12,
                 gas_rate: float = 1.20,
                 carbon_price: float = 50.0,
                 discount_rate: float = 0.05) -> Dict[str, Any]:
        """Run all or specified scenarios."""
        if scenarios is None:
            scenarios = list(DEFAULT_SAVINGS.keys())

        results = {
            "baseline": self._compute_baseline(building_data, metrics, electricity_rate, gas_rate),
            "scenarios": [],
            "combined_scenario": {},
        }

        total_savings_kwh = 0
        total_savings_cost = 0
        total_investment = 0

        for scenario_name in scenarios:
            scenario = self._simulate_scenario(
                building_data, metrics, scenario_name,
                electricity_rate, gas_rate, carbon_price, discount_rate
            )
            if scenario:
                results["scenarios"].append(scenario)
                total_savings_kwh += scenario.get("annual_kwh_savings", 0)
                total_savings_cost += scenario.get("annual_cost_savings", 0)
                total_investment += scenario.get("implementation_cost", 0)

        # Combined scenario (sum of all, capped at reasonable limits)
        baseline_kwh = results["baseline"].get("annual_kwh", 0)
        capped_savings = min(total_savings_kwh, baseline_kwh * 0.60)  # Max 60% total reduction

        if total_investment > 0 and total_savings_cost > 0:
            results["combined_scenario"] = {
                "total_investment": round(total_investment, 2),
                "annual_kwh_savings": round(capped_savings, 0),
                "annual_cost_savings": round(total_savings_cost, 2),
                "total_reduction_pct": round(capped_savings / baseline_kwh * 100, 1) if baseline_kwh > 0 else 0,
                "simple_payback_years": round(total_investment / total_savings_cost, 1),
                "remaining_kwh": round(baseline_kwh - capped_savings, 0),
            }

        return results

    def _compute_baseline(self, data: Dict, metrics: Dict,
                           elec_rate: float, gas_rate: float) -> Dict[str, Any]:
        bepu = data.get("bepu", {}) if isinstance(data.get("bepu"), dict) else {}
        total_kwh = bepu.get("total_electricity_kwh", metrics.get("total_kwh", 0))
        total_gas = bepu.get("total_gas_therm", metrics.get("total_gas_therm", 0))
        floor_area = bepu.get("floor_area_sqft", metrics.get("floor_area_sqft", 0))

        annual_elec_cost = total_kwh * elec_rate
        annual_gas_cost = total_gas * gas_rate

        return {
            "annual_kwh": total_kwh,
            "annual_gas_therm": total_gas,
            "annual_electric_cost": round(annual_elec_cost, 2),
            "annual_gas_cost": round(annual_gas_cost, 2),
            "annual_total_cost": round(annual_elec_cost + annual_gas_cost, 2),
            "floor_area_sqft": floor_area,
            "eui_kwh_sqft": round(total_kwh / floor_area, 2) if floor_area > 0 else 0,
        }

    def _simulate_scenario(self, data: Dict, metrics: Dict,
                            scenario_name: str,
                            elec_rate: float, gas_rate: float,
                            carbon_price: float, discount_rate: float) -> Optional[Dict[str, Any]]:
        savings_config = DEFAULT_SAVINGS.get(scenario_name)
        cost_config = DEFAULT_MEASURE_COSTS.get(scenario_name)
        if not savings_config or not cost_config:
            return None

        bepu = data.get("bepu", {}) if isinstance(data.get("bepu"), dict) else {}
        total_kwh = bepu.get("total_electricity_kwh", metrics.get("total_kwh", 0))
        total_gas = bepu.get("total_gas_therm", metrics.get("total_gas_therm", 0))
        floor_area = bepu.get("floor_area_sqft", metrics.get("floor_area_sqft", 0))

        if total_kwh <= 0 or floor_area <= 0:
            return None

        # Get end-use breakdown from PS-E
        end_use = self._get_end_use_totals(data)

        # Calculate savings
        kwh_savings = 0
        gas_savings = 0

        for end_use_name, pct in savings_config.items():
            if end_use_name == "total":
                kwh_savings += total_kwh * pct
            elif end_use_name == "gas":
                gas_savings += total_gas * pct
            elif end_use_name == "lighting":
                kwh_savings += end_use.get("Lights", total_kwh * 0.25) * pct
            elif end_use_name == "cooling":
                kwh_savings += end_use.get("Cooling", total_kwh * 0.20) * pct
            elif end_use_name == "heating":
                kwh_savings += end_use.get("Heating", total_kwh * 0.15) * pct
            elif end_use_name == "fans":
                kwh_savings += end_use.get("Vent_Fans", total_kwh * 0.10) * pct
            elif end_use_name == "pumps":
                kwh_savings += end_use.get("Pumps_Aux", total_kwh * 0.05) * pct

        # Cost savings
        annual_cost_savings = (kwh_savings * elec_rate) + (gas_savings * gas_rate)

        # Carbon savings
        carbon_savings_mt = (kwh_savings / 1000) * 0.388 + gas_savings * 0.00531

        # Implementation cost
        if "cost_per_sqft" in cost_config:
            implementation_cost = floor_area * cost_config["cost_per_sqft"]
        elif "cost_per_watt" in cost_config:
            # Solar: estimate system size
            system_kw = kwh_savings / 1400  # Approximate kWh per kW installed
            implementation_cost = system_kw * 1000 * cost_config["cost_per_watt"]
        else:
            implementation_cost = 0

        # Payback
        simple_payback = (implementation_cost / annual_cost_savings
                          if annual_cost_savings > 0 else float('inf'))

        # IRR estimation (simplified)
        lifetime = cost_config.get("lifetime_years", 15)
        npv = -implementation_cost + sum(
            annual_cost_savings / (1 + discount_rate) ** year
            for year in range(1, lifetime + 1)
        )

        # ROI
        total_savings = annual_cost_savings * lifetime
        roi = ((total_savings - implementation_cost) / implementation_cost * 100
               if implementation_cost > 0 else 0)

        return {
            "scenario_name": scenario_name,
            "display_name": scenario_name.replace("_", " ").title(),
            "annual_kwh_savings": round(kwh_savings, 0),
            "annual_gas_savings_therm": round(gas_savings, 0),
            "annual_cost_savings": round(annual_cost_savings, 2),
            "carbon_reduction_mt": round(carbon_savings_mt, 2),
            "implementation_cost": round(implementation_cost, 2),
            "simple_payback_years": round(simple_payback, 1) if simple_payback < 100 else None,
            "npv": round(npv, 2),
            "roi_pct": round(roi, 1),
            "lifetime_years": lifetime,
            "savings_pct": round(kwh_savings / total_kwh * 100, 1) if total_kwh > 0 else 0,
            "new_eui_kwh": round((total_kwh - kwh_savings) / floor_area, 2) if floor_area > 0 else 0,
        }

    def _get_end_use_totals(self, data: Dict) -> Dict[str, float]:
        """Extract annual end-use totals from PS-E data."""
        ps_e = data.get("ps_e", [])
        if not isinstance(ps_e, list):
            return {}

        annual = [r for r in ps_e if r.get("Month") == "ANNUAL"]
        if annual:
            return annual[0]
        return {}
