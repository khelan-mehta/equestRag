"""
Portfolio Analytics Mode
Multi-building comparison, ranking by EUI/cost/carbon, and risk scoring.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("equestrag.portfolio")


@dataclass
class BuildingRecord:
    """Represents a building in the portfolio."""
    building_id: str
    name: str = ""
    floor_area_sqft: float = 0
    eui_kwh_sqft: float = 0
    eui_kbtu_sqft: float = 0
    total_kwh: float = 0
    total_gas_therm: float = 0
    total_cost: float = 0
    cost_per_sqft: float = 0
    carbon_mt: float = 0
    carbon_intensity_kg_sqft: float = 0
    building_type: str = "office"
    climate_zone: str = "4A"
    efficiency_grade: str = ""
    risk_score: float = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class PortfolioAnalyticsEngine:
    """Analyzes and compares multiple buildings in a portfolio."""

    def analyze_portfolio(self, buildings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze a portfolio of buildings."""
        records = [self._create_record(b) for b in buildings]

        result = {
            "summary": self._compute_summary(records),
            "rankings": {
                "by_eui": self._rank_by(records, "eui_kbtu_sqft", ascending=True),
                "by_cost": self._rank_by(records, "cost_per_sqft", ascending=True),
                "by_carbon": self._rank_by(records, "carbon_intensity_kg_sqft", ascending=True),
                "by_risk": self._rank_by(records, "risk_score", ascending=False),
            },
            "risk_assessment": self._assess_risk(records),
            "comparisons": self._compare_buildings(records),
            "recommendations": self._portfolio_recommendations(records),
        }

        return result

    def _create_record(self, building: Dict[str, Any]) -> BuildingRecord:
        """Create a BuildingRecord from raw building data."""
        data = building.get("building_data", building)
        metrics = building.get("metrics", {})
        bepu = data.get("bepu", {}) if isinstance(data.get("bepu"), dict) else {}

        record = BuildingRecord(
            building_id=building.get("id", building.get("building_id", "")),
            name=building.get("name", data.get("metadata", {}).get("project_name", "Unknown")),
            floor_area_sqft=bepu.get("floor_area_sqft", metrics.get("floor_area_sqft", 0)),
            eui_kwh_sqft=bepu.get("eui_kwh_sqft_yr", metrics.get("eui", 0)),
            total_kwh=bepu.get("total_electricity_kwh", metrics.get("total_kwh", 0)),
            total_gas_therm=bepu.get("total_gas_therm", metrics.get("total_gas_therm", 0)),
            cost_per_sqft=metrics.get("cost_per_sqft", 0),
            total_cost=metrics.get("total_annual_cost", 0),
            carbon_mt=metrics.get("carbon_total_metric_tons", 0),
            building_type=building.get("building_type", "office"),
            climate_zone=building.get("climate_zone", "4A"),
            efficiency_grade=metrics.get("efficiency_grade", ""),
        )

        # Derived fields
        record.eui_kbtu_sqft = round(record.eui_kwh_sqft * 3.412, 1) if record.eui_kwh_sqft > 0 else 0
        if record.floor_area_sqft > 0 and record.carbon_mt > 0:
            record.carbon_intensity_kg_sqft = round(record.carbon_mt * 1000 / record.floor_area_sqft, 2)

        # Risk scoring
        record.risk_score = self._compute_building_risk(record)

        return record

    def _compute_building_risk(self, record: BuildingRecord) -> float:
        """Compute risk score (0-100, higher = more risk)."""
        risk = 0

        # EUI risk (higher EUI = more risk)
        if record.eui_kbtu_sqft > 0:
            if record.eui_kbtu_sqft > 120:
                risk += 30
            elif record.eui_kbtu_sqft > 90:
                risk += 20
            elif record.eui_kbtu_sqft > 60:
                risk += 10

        # Cost risk
        if record.cost_per_sqft > 0:
            if record.cost_per_sqft > 5.0:
                risk += 25
            elif record.cost_per_sqft > 3.0:
                risk += 15
            elif record.cost_per_sqft > 2.0:
                risk += 5

        # Carbon risk
        if record.carbon_intensity_kg_sqft > 0:
            if record.carbon_intensity_kg_sqft > 10:
                risk += 25
            elif record.carbon_intensity_kg_sqft > 6:
                risk += 15
            elif record.carbon_intensity_kg_sqft > 3:
                risk += 5

        # Data completeness risk
        if record.eui_kwh_sqft <= 0:
            risk += 10
        if record.total_cost <= 0:
            risk += 5

        return min(100, risk)

    def _compute_summary(self, records: List[BuildingRecord]) -> Dict[str, Any]:
        """Compute portfolio-level summary."""
        total_area = sum(r.floor_area_sqft for r in records)
        total_kwh = sum(r.total_kwh for r in records)
        total_gas = sum(r.total_gas_therm for r in records)
        total_cost = sum(r.total_cost for r in records)
        total_carbon = sum(r.carbon_mt for r in records)

        eui_values = [r.eui_kbtu_sqft for r in records if r.eui_kbtu_sqft > 0]

        return {
            "total_buildings": len(records),
            "total_area_sqft": total_area,
            "total_kwh": total_kwh,
            "total_gas_therm": total_gas,
            "total_cost": round(total_cost, 2),
            "total_carbon_mt": round(total_carbon, 2),
            "avg_eui_kbtu": round(sum(eui_values) / len(eui_values), 1) if eui_values else 0,
            "min_eui_kbtu": round(min(eui_values), 1) if eui_values else 0,
            "max_eui_kbtu": round(max(eui_values), 1) if eui_values else 0,
            "weighted_avg_eui": round(total_kwh * 3.412 / total_area, 1) if total_area > 0 else 0,
            "avg_cost_per_sqft": round(total_cost / total_area, 2) if total_area > 0 else 0,
            "portfolio_carbon_intensity": round(total_carbon * 1000 / total_area, 2) if total_area > 0 else 0,
        }

    def _rank_by(self, records: List[BuildingRecord],
                  field: str, ascending: bool = True) -> List[Dict[str, Any]]:
        """Rank buildings by a specific field."""
        sortable = [(r, getattr(r, field, 0)) for r in records if getattr(r, field, 0) > 0]
        sortable.sort(key=lambda x: x[1], reverse=not ascending)

        return [
            {
                "rank": i + 1,
                "building_id": r.building_id,
                "name": r.name,
                "value": round(val, 2),
                "floor_area_sqft": r.floor_area_sqft,
            }
            for i, (r, val) in enumerate(sortable)
        ]

    def _assess_risk(self, records: List[BuildingRecord]) -> Dict[str, Any]:
        """Portfolio-level risk assessment."""
        high_risk = [r for r in records if r.risk_score >= 60]
        medium_risk = [r for r in records if 30 <= r.risk_score < 60]
        low_risk = [r for r in records if r.risk_score < 30]

        return {
            "high_risk_count": len(high_risk),
            "medium_risk_count": len(medium_risk),
            "low_risk_count": len(low_risk),
            "avg_risk_score": round(sum(r.risk_score for r in records) / len(records), 1) if records else 0,
            "high_risk_buildings": [
                {"building_id": r.building_id, "name": r.name, "risk_score": r.risk_score}
                for r in high_risk
            ],
        }

    def _compare_buildings(self, records: List[BuildingRecord]) -> Dict[str, Any]:
        """Side-by-side comparison of buildings."""
        if len(records) < 2:
            return {}

        return {
            "buildings": [
                {
                    "building_id": r.building_id,
                    "name": r.name,
                    "eui_kbtu": r.eui_kbtu_sqft,
                    "cost_per_sqft": r.cost_per_sqft,
                    "carbon_intensity": r.carbon_intensity_kg_sqft,
                    "floor_area": r.floor_area_sqft,
                    "risk_score": r.risk_score,
                }
                for r in records
            ],
        }

    def _portfolio_recommendations(self, records: List[BuildingRecord]) -> List[str]:
        """Generate portfolio-level recommendations."""
        recs = []

        # Identify worst performers
        eui_sorted = sorted(
            [r for r in records if r.eui_kbtu_sqft > 0],
            key=lambda r: r.eui_kbtu_sqft, reverse=True
        )
        if eui_sorted:
            worst = eui_sorted[0]
            recs.append(
                f"Priority audit: {worst.name} has the highest EUI at {worst.eui_kbtu_sqft:.0f} kBTU/sqft/yr"
            )

        # High-risk buildings
        high_risk = [r for r in records if r.risk_score >= 60]
        if high_risk:
            names = ", ".join(r.name for r in high_risk[:3])
            recs.append(f"High-risk buildings requiring immediate attention: {names}")

        # Carbon hotspots
        carbon_sorted = sorted(
            [r for r in records if r.carbon_mt > 0],
            key=lambda r: r.carbon_mt, reverse=True
        )
        if carbon_sorted and len(carbon_sorted) >= 2:
            top = carbon_sorted[0]
            total_carbon = sum(r.carbon_mt for r in carbon_sorted)
            pct = top.carbon_mt / total_carbon * 100 if total_carbon > 0 else 0
            recs.append(
                f"{top.name} accounts for {pct:.0f}% of portfolio carbon emissions ({top.carbon_mt:.1f} MT)"
            )

        return recs
