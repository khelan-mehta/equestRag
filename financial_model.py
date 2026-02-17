"""
Financial Modeling Module
Total annual cost, cost per kWh, retrofit cost modeling,
payback period, and IRR estimation.
"""

import logging
import math
from typing import Dict, Any, List, Optional

logger = logging.getLogger("equestrag.financial")


class FinancialModelingEngine:
    """Comprehensive financial analysis for building energy investments."""

    def analyze(self, building_data: Dict[str, Any],
                metrics: Dict[str, Any],
                electricity_rate: float = 0.12,
                gas_rate: float = 1.20,
                escalation_rate: float = 0.03,
                discount_rate: float = 0.05,
                analysis_period: int = 25) -> Dict[str, Any]:

        result = {
            "current_costs": self._compute_current_costs(
                building_data, metrics, electricity_rate, gas_rate
            ),
            "cost_projections": self._project_costs(
                building_data, metrics, electricity_rate, gas_rate,
                escalation_rate, analysis_period
            ),
            "retrofit_analysis": self._analyze_retrofits(
                building_data, metrics, electricity_rate, gas_rate,
                escalation_rate, discount_rate, analysis_period
            ),
            "rate_sensitivity": self._rate_sensitivity(
                building_data, metrics, electricity_rate, gas_rate
            ),
        }

        return result

    def _compute_current_costs(self, data: Dict, metrics: Dict,
                                elec_rate: float, gas_rate: float) -> Dict[str, Any]:
        bepu = data.get("bepu", {}) if isinstance(data.get("bepu"), dict) else {}
        es_d = data.get("es_d", {}) if isinstance(data.get("es_d"), dict) else {}

        total_kwh = bepu.get("total_electricity_kwh", metrics.get("total_kwh", 0))
        total_gas = bepu.get("total_gas_therm", metrics.get("total_gas_therm", 0))
        floor_area = bepu.get("floor_area_sqft", metrics.get("floor_area_sqft", 0))

        elec_cost = total_kwh * elec_rate
        gas_cost = total_gas * gas_rate
        total_cost = elec_cost + gas_cost

        result = {
            "annual_electricity_kwh": total_kwh,
            "annual_gas_therm": total_gas,
            "electricity_rate": elec_rate,
            "gas_rate": gas_rate,
            "annual_electric_cost": round(elec_cost, 2),
            "annual_gas_cost": round(gas_cost, 2),
            "annual_total_cost": round(total_cost, 2),
            "monthly_avg_cost": round(total_cost / 12, 2),
        }

        if floor_area > 0:
            result["cost_per_sqft"] = round(total_cost / floor_area, 2)
        if total_kwh > 0:
            result["blended_cost_per_kwh"] = round(total_cost / total_kwh, 4) if total_kwh > 0 else 0

        # Use reported cost if available
        if es_d.get("total_cost", 0) > 0:
            result["reported_total_cost"] = es_d["total_cost"]
        if es_d.get("cost_per_sqft", 0) > 0:
            result["reported_cost_per_sqft"] = es_d["cost_per_sqft"]

        return result

    def _project_costs(self, data: Dict, metrics: Dict,
                        elec_rate: float, gas_rate: float,
                        escalation_rate: float, years: int) -> Dict[str, Any]:
        bepu = data.get("bepu", {}) if isinstance(data.get("bepu"), dict) else {}
        total_kwh = bepu.get("total_electricity_kwh", metrics.get("total_kwh", 0))
        total_gas = bepu.get("total_gas_therm", metrics.get("total_gas_therm", 0))

        yearly_projection = []
        cumulative_cost = 0

        for year in range(1, years + 1):
            rate_factor = (1 + escalation_rate) ** (year - 1)
            annual_elec = total_kwh * elec_rate * rate_factor
            annual_gas = total_gas * gas_rate * rate_factor
            annual_total = annual_elec + annual_gas
            cumulative_cost += annual_total

            yearly_projection.append({
                "year": year,
                "electricity_cost": round(annual_elec, 2),
                "gas_cost": round(annual_gas, 2),
                "total_cost": round(annual_total, 2),
                "cumulative_cost": round(cumulative_cost, 2),
                "rate_factor": round(rate_factor, 3),
            })

        return {
            "escalation_rate": escalation_rate,
            "analysis_period_years": years,
            "total_lifecycle_cost": round(cumulative_cost, 2),
            "yearly_projections": yearly_projection,
            "year_5_cost": yearly_projection[4]["total_cost"] if len(yearly_projection) >= 5 else 0,
            "year_10_cost": yearly_projection[9]["total_cost"] if len(yearly_projection) >= 10 else 0,
        }

    def _analyze_retrofits(self, data: Dict, metrics: Dict,
                            elec_rate: float, gas_rate: float,
                            escalation_rate: float, discount_rate: float,
                            analysis_period: int) -> List[Dict[str, Any]]:
        bepu = data.get("bepu", {}) if isinstance(data.get("bepu"), dict) else {}
        total_kwh = bepu.get("total_electricity_kwh", metrics.get("total_kwh", 0))
        total_gas = bepu.get("total_gas_therm", metrics.get("total_gas_therm", 0))
        floor_area = bepu.get("floor_area_sqft", metrics.get("floor_area_sqft", 0))

        if total_kwh <= 0 or floor_area <= 0:
            return []

        retrofits = [
            {
                "name": "LED Lighting Retrofit",
                "savings_pct_electric": 0.20,
                "savings_pct_gas": 0,
                "cost_per_sqft": 2.50,
                "lifetime": 15,
            },
            {
                "name": "HVAC System Upgrade",
                "savings_pct_electric": 0.15,
                "savings_pct_gas": 0.15,
                "cost_per_sqft": 8.00,
                "lifetime": 20,
            },
            {
                "name": "Building Envelope Improvement",
                "savings_pct_electric": 0.08,
                "savings_pct_gas": 0.15,
                "cost_per_sqft": 5.00,
                "lifetime": 30,
            },
            {
                "name": "Smart Building Controls",
                "savings_pct_electric": 0.10,
                "savings_pct_gas": 0.05,
                "cost_per_sqft": 3.00,
                "lifetime": 10,
            },
            {
                "name": "Variable Frequency Drives",
                "savings_pct_electric": 0.08,
                "savings_pct_gas": 0,
                "cost_per_sqft": 1.50,
                "lifetime": 15,
            },
        ]

        results = []
        for retrofit in retrofits:
            kwh_savings = total_kwh * retrofit["savings_pct_electric"]
            gas_savings = total_gas * retrofit["savings_pct_gas"]
            annual_savings = kwh_savings * elec_rate + gas_savings * gas_rate
            implementation_cost = floor_area * retrofit["cost_per_sqft"]

            if annual_savings <= 0:
                continue

            # Simple payback
            simple_payback = implementation_cost / annual_savings

            # NPV calculation
            npv = -implementation_cost
            lifetime = min(retrofit["lifetime"], analysis_period)
            for year in range(1, lifetime + 1):
                escalated_savings = annual_savings * (1 + escalation_rate) ** (year - 1)
                npv += escalated_savings / (1 + discount_rate) ** year

            # IRR estimation using bisection method
            irr = self._estimate_irr(implementation_cost, annual_savings,
                                      escalation_rate, lifetime)

            # Savings-to-investment ratio
            sir = (annual_savings * lifetime) / implementation_cost if implementation_cost > 0 else 0

            results.append({
                "name": retrofit["name"],
                "implementation_cost": round(implementation_cost, 2),
                "cost_per_sqft": retrofit["cost_per_sqft"],
                "annual_kwh_savings": round(kwh_savings, 0),
                "annual_gas_savings": round(gas_savings, 0),
                "annual_cost_savings": round(annual_savings, 2),
                "simple_payback_years": round(simple_payback, 1),
                "npv": round(npv, 2),
                "irr_pct": round(irr * 100, 1) if irr is not None else None,
                "sir": round(sir, 2),
                "lifetime_years": lifetime,
                "lifetime_savings": round(annual_savings * lifetime, 2),
                "cost_effective": npv > 0,
            })

        # Sort by NPV (best first)
        results.sort(key=lambda x: x.get("npv", 0), reverse=True)
        return results

    def _estimate_irr(self, investment: float, annual_savings: float,
                       escalation: float, years: int) -> Optional[float]:
        """Estimate IRR using bisection method."""
        if investment <= 0 or annual_savings <= 0:
            return None

        def npv_at_rate(rate):
            total = -investment
            for year in range(1, years + 1):
                cash_flow = annual_savings * (1 + escalation) ** (year - 1)
                total += cash_flow / (1 + rate) ** year
            return total

        # Bisection
        low, high = -0.5, 2.0
        if npv_at_rate(low) < 0:
            return None
        if npv_at_rate(high) > 0:
            return high

        for _ in range(100):
            mid = (low + high) / 2
            if npv_at_rate(mid) > 0:
                low = mid
            else:
                high = mid
            if abs(high - low) < 0.0001:
                break

        return (low + high) / 2

    def _rate_sensitivity(self, data: Dict, metrics: Dict,
                           base_elec_rate: float, base_gas_rate: float) -> Dict[str, Any]:
        """Analyze cost sensitivity to rate changes."""
        bepu = data.get("bepu", {}) if isinstance(data.get("bepu"), dict) else {}
        total_kwh = bepu.get("total_electricity_kwh", metrics.get("total_kwh", 0))
        total_gas = bepu.get("total_gas_therm", metrics.get("total_gas_therm", 0))

        scenarios = []
        for pct_change in [-20, -10, 0, 10, 20, 30, 50]:
            factor = 1 + pct_change / 100
            new_elec = base_elec_rate * factor
            new_gas = base_gas_rate * factor
            total_cost = total_kwh * new_elec + total_gas * new_gas
            scenarios.append({
                "rate_change_pct": pct_change,
                "electricity_rate": round(new_elec, 4),
                "gas_rate": round(new_gas, 4),
                "annual_cost": round(total_cost, 2),
            })

        return {
            "base_rates": {"electricity": base_elec_rate, "gas": base_gas_rate},
            "scenarios": scenarios,
        }
