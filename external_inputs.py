"""
External Building Input Support
Parsers for .inp files, .epw weather files, utility bills (CSV/PDF), and interval meter data.
"""

import re
import io
import csv
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger("equestrag.external_inputs")


# ---------------------------------------------------------------------------
# eQuest .inp file parser
# ---------------------------------------------------------------------------
class InpFileParser:
    """Parse eQuest .inp (input) files for building model parameters."""

    def parse(self, content: str) -> Dict[str, Any]:
        result = {
            "building": {},
            "zones": [],
            "systems": [],
            "schedules": [],
            "constructions": [],
            "materials": [],
            "windows": [],
            "walls": [],
        }

        lines = content.split("\n")
        current_block = None
        block_type = None
        block_name = ""
        block_data = {}

        for line in lines:
            stripped = line.strip()

            # Skip comments and empty lines
            if stripped.startswith("$") or not stripped:
                continue

            # Block start: "name" = TYPE
            block_start = re.match(r'^"(.+?)"\s*=\s*(\S+)', stripped)
            if block_start:
                # Save previous block
                if current_block and block_data:
                    self._store_block(result, block_type, block_name, block_data)

                block_name = block_start.group(1)
                block_type = block_start.group(2).upper()
                block_data = {"name": block_name, "type": block_type}
                current_block = True
                continue

            # End of block
            if stripped == ".." and current_block:
                if block_data:
                    self._store_block(result, block_type, block_name, block_data)
                current_block = None
                block_type = None
                block_name = ""
                block_data = {}
                continue

            # Properties within a block
            if current_block:
                prop_match = re.match(r'(\S+)\s*=\s*(.+)', stripped)
                if prop_match:
                    key = prop_match.group(1).strip()
                    val = prop_match.group(2).strip().strip('"')
                    block_data[key] = val

        # Store last block
        if current_block and block_data:
            self._store_block(result, block_type, block_name, block_data)

        # Compute summary
        result["summary"] = self._compute_summary(result)
        return result

    def _store_block(self, result: Dict, block_type: str, name: str, data: Dict):
        type_map = {
            "FLOOR": "zones",
            "SPACE": "zones",
            "ZONE": "zones",
            "SYSTEM": "systems",
            "SCHEDULE-PD": "schedules",
            "CONSTRUCTION": "constructions",
            "MATERIAL": "materials",
            "WINDOW": "windows",
            "EXTERIOR-WALL": "walls",
            "INTERIOR-WALL": "walls",
            "UNDERGROUND-WALL": "walls",
            "ROOF": "walls",
        }

        # Building-level properties
        if block_type in ("SITE-PARAMETERS", "BUILD-PARAMETERS", "RUN-PERIOD-PD"):
            result["building"].update(data)
            return

        target = type_map.get(block_type, None)
        if target and target in result:
            result[target].append(data)

    def _compute_summary(self, result: Dict) -> Dict[str, Any]:
        summary = {
            "total_zones": len(result["zones"]),
            "total_systems": len(result["systems"]),
            "total_constructions": len(result["constructions"]),
            "total_windows": len(result["windows"]),
            "total_walls": len(result["walls"]),
        }

        # Extract building params
        bldg = result["building"]
        if "GROSS-AREA" in bldg:
            try:
                summary["gross_area"] = float(bldg["GROSS-AREA"])
            except ValueError:
                pass
        if "ABOVE-GRADE-STORIES" in bldg:
            try:
                summary["stories"] = int(float(bldg["ABOVE-GRADE-STORIES"]))
            except ValueError:
                pass
        if "LATITUDE" in bldg:
            try:
                summary["latitude"] = float(bldg["LATITUDE"])
            except ValueError:
                pass
        if "LONGITUDE" in bldg:
            try:
                summary["longitude"] = float(bldg["LONGITUDE"])
            except ValueError:
                pass

        return summary


# ---------------------------------------------------------------------------
# EPW Weather file parser
# ---------------------------------------------------------------------------
class EpwFileParser:
    """Parse EnergyPlus Weather (.epw) files."""

    def parse(self, content: str) -> Dict[str, Any]:
        lines = content.split("\n")
        result = {
            "location": {},
            "design_conditions": {},
            "monthly_summary": [],
            "annual_summary": {},
        }

        # Parse header lines (first 8 lines)
        if len(lines) < 8:
            return result

        # Line 1: LOCATION
        loc_parts = lines[0].split(",")
        if len(loc_parts) >= 10 and loc_parts[0] == "LOCATION":
            result["location"] = {
                "city": loc_parts[1].strip(),
                "state": loc_parts[2].strip(),
                "country": loc_parts[3].strip(),
                "data_source": loc_parts[4].strip(),
                "wmo_number": loc_parts[5].strip(),
                "latitude": float(loc_parts[6]) if loc_parts[6].strip() else 0,
                "longitude": float(loc_parts[7]) if loc_parts[7].strip() else 0,
                "timezone": float(loc_parts[8]) if loc_parts[8].strip() else 0,
                "elevation_m": float(loc_parts[9]) if loc_parts[9].strip() else 0,
            }

        # Parse hourly data (starts at line 8)
        hourly_data = []
        for line in lines[8:]:
            parts = line.split(",")
            if len(parts) < 35:
                continue
            try:
                record = {
                    "year": int(parts[0]),
                    "month": int(parts[1]),
                    "day": int(parts[2]),
                    "hour": int(parts[3]),
                    "dry_bulb_c": float(parts[6]),
                    "dew_point_c": float(parts[7]),
                    "rel_humidity": float(parts[8]),
                    "pressure_pa": float(parts[9]),
                    "wind_speed_m_s": float(parts[21]),
                    "wind_dir_deg": float(parts[20]),
                    "global_horiz_rad_wh_m2": float(parts[13]),
                    "direct_normal_rad_wh_m2": float(parts[14]),
                    "diffuse_horiz_rad_wh_m2": float(parts[15]),
                }
                hourly_data.append(record)
            except (ValueError, IndexError):
                continue

        if hourly_data:
            df = pd.DataFrame(hourly_data)

            # Monthly summary
            monthly = df.groupby("month").agg({
                "dry_bulb_c": ["mean", "min", "max"],
                "rel_humidity": "mean",
                "wind_speed_m_s": "mean",
                "global_horiz_rad_wh_m2": "sum",
            }).reset_index()

            month_names = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

            for _, row in monthly.iterrows():
                m = int(row["month"].iloc[0]) if hasattr(row["month"], 'iloc') else int(row["month"])
                result["monthly_summary"].append({
                    "month": month_names[m - 1] if m <= 12 else str(m),
                    "avg_temp_c": round(float(row[("dry_bulb_c", "mean")]), 1),
                    "min_temp_c": round(float(row[("dry_bulb_c", "min")]), 1),
                    "max_temp_c": round(float(row[("dry_bulb_c", "max")]), 1),
                    "avg_humidity": round(float(row[("rel_humidity", "mean")]), 1),
                    "avg_wind_speed": round(float(row[("wind_speed_m_s", "mean")]), 1),
                    "total_solar_wh_m2": round(float(row[("global_horiz_rad_wh_m2", "sum")]), 0),
                })

            # Annual summary
            result["annual_summary"] = {
                "avg_temp_c": round(float(df["dry_bulb_c"].mean()), 1),
                "min_temp_c": round(float(df["dry_bulb_c"].min()), 1),
                "max_temp_c": round(float(df["dry_bulb_c"].max()), 1),
                "hdd_18c": self._calc_hdd(df, 18.0),
                "cdd_18c": self._calc_cdd(df, 18.0),
                "hdd_65f": self._calc_hdd(df, 18.3),  # 65F = 18.3C
                "cdd_65f": self._calc_cdd(df, 18.3),
                "avg_humidity": round(float(df["rel_humidity"].mean()), 1),
                "total_solar_kwh_m2": round(float(df["global_horiz_rad_wh_m2"].sum()) / 1000, 1),
                "total_records": len(df),
            }

            # Climate zone estimation
            result["climate_zone"] = self._estimate_climate_zone(result["annual_summary"])

        return result

    def _calc_hdd(self, df: pd.DataFrame, base_temp_c: float) -> int:
        daily = df.groupby(["month", "day"])["dry_bulb_c"].mean()
        return int(sum(max(base_temp_c - t, 0) for t in daily))

    def _calc_cdd(self, df: pd.DataFrame, base_temp_c: float) -> int:
        daily = df.groupby(["month", "day"])["dry_bulb_c"].mean()
        return int(sum(max(t - base_temp_c, 0) for t in daily))

    def _estimate_climate_zone(self, annual: Dict) -> str:
        """Estimate ASHRAE climate zone from weather data."""
        cdd = annual.get("cdd_65f", 0)
        hdd = annual.get("hdd_65f", 0)

        if cdd > 5000:
            return "1A" if annual.get("avg_humidity", 0) > 60 else "1B"
        elif cdd > 3500:
            return "2A" if annual.get("avg_humidity", 0) > 55 else "2B"
        elif cdd > 2500:
            return "3A" if annual.get("avg_humidity", 0) > 50 else "3B"
        elif hdd < 3000:
            return "3C"
        elif hdd < 4000:
            return "4A" if annual.get("avg_humidity", 0) > 50 else "4B"
        elif hdd < 5000:
            return "4C" if annual.get("avg_humidity", 0) < 40 else "4A"
        elif hdd < 6000:
            return "5A" if annual.get("avg_humidity", 0) > 45 else "5B"
        elif hdd < 7000:
            return "5C" if annual.get("avg_humidity", 0) < 35 else "5A"
        elif hdd < 8000:
            return "6A" if annual.get("avg_humidity", 0) > 40 else "6B"
        elif hdd < 9000:
            return "7"
        else:
            return "8"


# ---------------------------------------------------------------------------
# Utility Bill Parser (CSV)
# ---------------------------------------------------------------------------
class UtilityBillParser:
    """Parse utility bill data from CSV files."""

    def parse_csv(self, content: str) -> Dict[str, Any]:
        result = {
            "bills": [],
            "summary": {},
        }

        try:
            reader = csv.DictReader(io.StringIO(content))
            rows = list(reader)
        except Exception:
            # Try without headers
            lines = content.strip().split("\n")
            if not lines:
                return result
            rows = []
            for line in lines:
                parts = line.split(",")
                if len(parts) >= 3:
                    rows.append({
                        "date": parts[0].strip(),
                        "usage": parts[1].strip(),
                        "cost": parts[2].strip(),
                    })

        total_usage = 0.0
        total_cost = 0.0

        for row in rows:
            bill = {}
            # Try common column names
            for date_key in ["date", "Date", "DATE", "billing_date", "period", "month"]:
                if date_key in row:
                    bill["date"] = row[date_key]
                    break

            for usage_key in ["usage", "Usage", "kwh", "kWh", "KWH", "consumption", "therms", "Therms"]:
                if usage_key in row:
                    try:
                        bill["usage"] = float(row[usage_key].replace(",", "").replace("$", ""))
                        total_usage += bill["usage"]
                    except (ValueError, AttributeError):
                        pass
                    break

            for cost_key in ["cost", "Cost", "COST", "amount", "Amount", "total", "charge"]:
                if cost_key in row:
                    try:
                        bill["cost"] = float(row[cost_key].replace(",", "").replace("$", ""))
                        total_cost += bill["cost"]
                    except (ValueError, AttributeError):
                        pass
                    break

            for demand_key in ["demand", "Demand", "peak_kw", "kW", "peak"]:
                if demand_key in row:
                    try:
                        bill["demand_kw"] = float(row[demand_key].replace(",", ""))
                    except (ValueError, AttributeError):
                        pass
                    break

            if bill:
                result["bills"].append(bill)

        if result["bills"]:
            result["summary"] = {
                "total_usage": round(total_usage, 2),
                "total_cost": round(total_cost, 2),
                "avg_monthly_usage": round(total_usage / len(result["bills"]), 2),
                "avg_monthly_cost": round(total_cost / len(result["bills"]), 2),
                "num_bills": len(result["bills"]),
            }
            if total_usage > 0:
                result["summary"]["avg_cost_per_unit"] = round(total_cost / total_usage, 4)

        return result


# ---------------------------------------------------------------------------
# Interval Meter Data Parser
# ---------------------------------------------------------------------------
class IntervalDataParser:
    """Parse interval (15-min or hourly) meter data."""

    def parse(self, content: str) -> Dict[str, Any]:
        result = {
            "intervals": [],
            "summary": {},
        }

        try:
            df = pd.read_csv(io.StringIO(content))
        except Exception:
            return result

        if df.empty:
            return result

        # Detect timestamp column
        ts_col = None
        for col in df.columns:
            if any(kw in col.lower() for kw in ["time", "date", "timestamp", "interval"]):
                ts_col = col
                break
        if ts_col is None:
            ts_col = df.columns[0]

        # Detect value column
        val_col = None
        for col in df.columns:
            if col != ts_col and df[col].dtype in [np.float64, np.int64, float, int]:
                val_col = col
                break
        if val_col is None:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                val_col = numeric_cols[0]

        if val_col is None:
            return result

        # Parse timestamps
        try:
            df[ts_col] = pd.to_datetime(df[ts_col])
        except Exception:
            pass

        values = df[val_col].astype(float)
        result["summary"] = {
            "total_records": len(df),
            "total_consumption": round(float(values.sum()), 2),
            "peak_demand": round(float(values.max()), 2),
            "min_demand": round(float(values.min()), 2),
            "avg_demand": round(float(values.mean()), 2),
            "load_factor": round(float(values.mean() / values.max()), 3) if values.max() > 0 else 0,
            "value_column": val_col,
        }

        # Determine interval
        if len(df) > 1 and pd.api.types.is_datetime64_any_dtype(df[ts_col]):
            diff = (df[ts_col].iloc[1] - df[ts_col].iloc[0]).total_seconds()
            if diff <= 900:
                result["summary"]["interval_minutes"] = 15
            elif diff <= 3600:
                result["summary"]["interval_minutes"] = 60
            else:
                result["summary"]["interval_minutes"] = int(diff / 60)

        # Hourly profile (average by hour)
        if pd.api.types.is_datetime64_any_dtype(df[ts_col]):
            df["hour"] = df[ts_col].dt.hour
            hourly = df.groupby("hour")[val_col].mean()
            result["hourly_profile"] = [
                {"hour": int(h), "avg_demand": round(float(v), 2)}
                for h, v in hourly.items()
            ]

            # Daily totals
            df["date"] = df[ts_col].dt.date
            daily = df.groupby("date")[val_col].sum()
            result["daily_totals"] = [
                {"date": str(d), "total": round(float(v), 2)}
                for d, v in daily.items()
            ]

        return result
