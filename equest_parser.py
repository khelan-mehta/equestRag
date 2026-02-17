"""
eQuest Parsing Engine v2.0
Section-based state machine parser with dynamic table detection,
unit normalization, data validation, and missing section detection.
Supports: PS-E, BEPU, LS-C, ES-D, LV-D, SS-P, LS-B, SV-A, SV-B, hourly reports.
"""

import re
import logging
from enum import Enum, auto
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field

import pandas as pd
import numpy as np

logger = logging.getLogger("equestrag.parser")

# ---------------------------------------------------------------------------
# Unit conversion constants
# ---------------------------------------------------------------------------
UNIT_CONVERSIONS = {
    ("MBTU", "KWH"): 293.07107,
    ("MBTU", "THERM"): 10.0,
    ("KWH", "MBTU"): 1 / 293.07107,
    ("KWH", "THERM"): 1 / 29.3071,
    ("THERM", "KWH"): 29.3071,
    ("THERM", "MBTU"): 0.1,
    ("KBTU/H", "TONS"): 1 / 12.0,
    ("KBTU/H", "KW"): 0.29307107,
    ("TONS", "KBTU/H"): 12.0,
    ("SQFT", "SQM"): 0.092903,
    ("SQM", "SQFT"): 10.7639,
}

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

MONTH_ORDER = {m: i for i, m in enumerate(MONTHS)}


# ---------------------------------------------------------------------------
# Parser state machine states
# ---------------------------------------------------------------------------
class ParserState(Enum):
    SEEKING_HEADER = auto()
    IN_HEADER = auto()
    IN_TABLE_HEADER = auto()
    IN_DATA_ROWS = auto()
    IN_SUMMARY = auto()
    IN_SECTION = auto()
    COMPLETE = auto()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ParsedTable:
    """Represents a dynamically detected table from eQuest output."""
    headers: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    unit: str = ""
    section_name: str = ""


@dataclass
class ValidationResult:
    """Result of data validation."""
    is_valid: bool = True
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    missing_sections: List[str] = field(default_factory=list)
    completeness_score: float = 1.0


@dataclass
class ParseResult:
    """Complete result from parsing an eQuest file."""
    report_type: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    tables: List[ParsedTable] = field(default_factory=list)
    metadata: Dict[str, str] = field(default_factory=dict)
    validation: ValidationResult = field(default_factory=ValidationResult)
    raw_sections: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Unit normalizer
# ---------------------------------------------------------------------------
class UnitNormalizer:
    """Normalizes units across different eQuest reports."""

    @staticmethod
    def convert(value: float, from_unit: str, to_unit: str) -> float:
        from_u = from_unit.upper().strip()
        to_u = to_unit.upper().strip()
        if from_u == to_u:
            return value
        factor = UNIT_CONVERSIONS.get((from_u, to_u))
        if factor is None:
            logger.warning("No conversion factor for %s -> %s", from_u, to_u)
            return value
        return value * factor

    @staticmethod
    def normalize_energy_to_kwh(value: float, unit: str) -> float:
        u = unit.upper().strip()
        if u == "KWH":
            return value
        if u == "MBTU":
            return value * 293.07107
        if u in ("THERM", "THERMS"):
            return value * 29.3071
        return value

    @staticmethod
    def normalize_energy_to_kbtu(value: float, unit: str) -> float:
        u = unit.upper().strip()
        if u in ("KBTU", "KBTU/H"):
            return value
        if u == "KWH":
            return value * 3.412
        if u in ("THERM", "THERMS"):
            return value * 100.0
        if u == "MBTU":
            return value * 1000.0
        return value


# ---------------------------------------------------------------------------
# Safe value parsing
# ---------------------------------------------------------------------------
def safe_float(val: str) -> float:
    """Parse a string to float, handling eQuest-specific formats."""
    if not val or val.strip() in (".", "-", "*", "N/A", ""):
        return 0.0
    cleaned = val.strip().replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def safe_int(val: str) -> int:
    try:
        return int(safe_float(val))
    except (ValueError, OverflowError):
        return 0


# ---------------------------------------------------------------------------
# Dynamic table detector
# ---------------------------------------------------------------------------
class TableDetector:
    """Detects and parses tabular data from eQuest output."""

    @staticmethod
    def detect_table(lines: List[str], start_idx: int) -> Optional[Tuple[int, ParsedTable]]:
        """Detect a table starting from a given line index.
        Returns (end_idx, ParsedTable) or None."""
        if start_idx >= len(lines):
            return None

        # Look for separator lines (dashes, equals)
        sep_pattern = re.compile(r'^[\s]*[-=]{5,}')
        col_pattern = re.compile(r'\s{2,}')

        # Find header row by looking for separator above/below
        i = start_idx
        headers = []
        header_idx = -1

        while i < min(start_idx + 10, len(lines)):
            line = lines[i]
            if sep_pattern.match(line):
                # Check line above for headers
                if i > 0 and lines[i - 1].strip():
                    header_line = lines[i - 1]
                    headers = [h.strip() for h in col_pattern.split(header_line.strip()) if h.strip()]
                    header_idx = i - 1
                    i += 1
                    break
                # Check line below for headers
                if i + 1 < len(lines) and lines[i + 1].strip():
                    header_line = lines[i + 1]
                    headers = [h.strip() for h in col_pattern.split(header_line.strip()) if h.strip()]
                    header_idx = i + 1
                    i = header_idx + 1
                    # Skip another separator if present
                    if i < len(lines) and sep_pattern.match(lines[i]):
                        i += 1
                    break
            i += 1

        if not headers:
            return None

        # Parse data rows
        table = ParsedTable(headers=headers, section_name="")
        data_start = i
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            if not stripped or sep_pattern.match(line):
                if table.rows:
                    break
                i += 1
                continue

            parts = [p.strip() for p in col_pattern.split(stripped) if p.strip()]
            if len(parts) >= 2:
                row = {}
                for j, header in enumerate(headers):
                    if j < len(parts):
                        row[header] = parts[j]
                    else:
                        row[header] = ""
                table.rows.append(row)
            i += 1

        if table.rows:
            return (i, table)
        return None

    @staticmethod
    def detect_column_positions(header_line: str) -> List[Tuple[int, int, str]]:
        """Detect column positions from a header line with fixed-width columns."""
        columns = []
        in_word = False
        start = 0
        for i, ch in enumerate(header_line):
            if ch != ' ' and not in_word:
                start = i
                in_word = True
            elif ch == ' ' and in_word:
                columns.append((start, i, header_line[start:i].strip()))
                in_word = False
        if in_word:
            columns.append((start, len(header_line), header_line[start:].strip()))
        return columns


# ---------------------------------------------------------------------------
# Section-based state machine parser
# ---------------------------------------------------------------------------
class eQuestParserV2:
    """
    Section-based state machine parser for eQuest simulation output.
    Replaces regex-based parsing with structured section detection.
    """

    def __init__(self):
        self.normalizer = UnitNormalizer()
        self.table_detector = TableDetector()

    # ── Public API ─────────────────────────────────────────────────────

    def parse(self, content: str, report_type: str = "auto") -> ParseResult:
        """Parse eQuest content with automatic report type detection."""
        if report_type == "auto":
            report_type = self.detect_report_type(content)

        result = ParseResult(report_type=report_type)
        result.metadata = self.extract_metadata(content)
        result.raw_sections = self._split_sections(content)

        parser_map = {
            "PS-E": self._parse_ps_e,
            "BEPU": self._parse_bepu,
            "LS-C": self._parse_ls_c,
            "LS-B": self._parse_ls_b,
            "ES-D": self._parse_es_d,
            "LV-D": self._parse_lv_d,
            "SS-P": self._parse_ss_p,
            "SV-A": self._parse_sv_a,
            "SV-B": self._parse_sv_b,
            "HOURLY": self._parse_hourly,
        }

        parser_fn = parser_map.get(report_type)
        if parser_fn:
            result.data = parser_fn(content)
        else:
            # Try all parsers and use whichever produces data
            for rtype, fn in parser_map.items():
                try:
                    data = fn(content)
                    if data:
                        result.data = data
                        result.report_type = rtype
                        break
                except Exception:
                    continue

        result.validation = self.validate(result)
        return result

    def detect_report_type(self, content: str) -> str:
        """Auto-detect the eQuest report type from content."""
        content_upper = content.upper()

        type_patterns = [
            ("PS-E", [r"PS-E\b", r"ALL\s+FUEL\s+METERS", r"MBTU.*KWH.*THERM"]),
            ("BEPU", [r"BEPU\b", r"BUILDING\s+ENERGY\s+PERFORMANCE", r"TOTAL\s+ELECTRICITY"]),
            ("LS-C", [r"LS-C\b", r"ZONE\s+PEAK\s+LOADS", r"COOLING\s+LOAD.*HEATING\s+LOAD"]),
            ("LS-B", [r"LS-B\b", r"ZONE\s+LOAD\s+BREAKDOWN", r"SPACE\s+PEAK\s+LOAD"]),
            ("ES-D", [r"ES-D\b", r"ENERGY\s+COST\s+SUMMARY", r"ENERGY\s+COST/GROSS"]),
            ("LV-D", [r"LV-D\b", r"WALL\s+PARAMETERS", r"U-VALUE.*R-VALUE"]),
            ("SS-P", [r"SS-P\b", r"SYSTEM\s+SUMMARY", r"SYSTEM\s+TYPE"]),
            ("SV-A", [r"SV-A\b", r"PLANT\s+ENERGY", r"PLANT\s+REPORT"]),
            ("SV-B", [r"SV-B\b", r"SYSTEM\s+REPORT", r"SYSTEM\s+ENERGY"]),
        ]

        for rtype, patterns in type_patterns:
            matches = sum(1 for p in patterns if re.search(p, content_upper))
            if matches >= 2:
                return rtype

        # Check for hourly data (CSV-like with timestamps)
        lines = content.split("\n")[:10]
        if any("," in line and re.search(r"\d{1,2}/\d{1,2}", line) for line in lines):
            return "HOURLY"

        return "UNKNOWN"

    # ── Metadata extraction ────────────────────────────────────────────

    def extract_metadata(self, content: str) -> Dict[str, str]:
        """Extract project metadata using state machine approach."""
        metadata = {}
        lines = content.split("\n")

        for line in lines[:100]:  # Check first 100 lines for metadata
            # Weather file
            wf_match = re.search(r"WEATHER\s+FILE[-\s]*(.+?)(?:\s{2,}|$)", line, re.IGNORECASE)
            if wf_match:
                metadata["weather_file"] = wf_match.group(1).strip()

            # Project name
            pn_match = re.search(r"(?:PROJECT|INPUT\s+FILE)[-:\s]+(.+?)(?:\s{2,}|$)", line, re.IGNORECASE)
            if pn_match and "project_name" not in metadata:
                metadata["project_name"] = pn_match.group(1).strip()

            # Simulation date
            date_match = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", line)
            if date_match and "simulation_date" not in metadata:
                metadata["simulation_date"] = date_match.group(1)

            # Run period
            rp_match = re.search(r"RUN\s+PERIOD[-:\s]+(.+?)(?:\s{2,}|$)", line, re.IGNORECASE)
            if rp_match:
                metadata["run_period"] = rp_match.group(1).strip()

            # Floor area
            fa_match = re.search(r"FLOOR\s+AREA\s*=?\s*([\d,.]+)\s*(?:SQFT|SF)", line, re.IGNORECASE)
            if fa_match:
                metadata["floor_area_sqft"] = fa_match.group(1).replace(",", "")

            # Building type
            bt_match = re.search(r"BUILDING\s+TYPE[-:\s]+(.+?)(?:\s{2,}|$)", line, re.IGNORECASE)
            if bt_match:
                metadata["building_type"] = bt_match.group(1).strip()

        return metadata

    # ── Section splitter ───────────────────────────────────────────────

    def _split_sections(self, content: str) -> Dict[str, str]:
        """Split content into named sections."""
        sections = {}
        current_section = "HEADER"
        section_lines = []

        for line in content.split("\n"):
            # Detect section boundaries
            section_match = re.match(
                r'^\s*(REPORT[-\s]*|SECTION[-\s]*)?'
                r'(PS-E|BEPU|LS-[A-D]|ES-D|LV-D|SS-[A-Z]|SV-[A-Z])\s',
                line, re.IGNORECASE
            )
            if section_match:
                if section_lines:
                    sections[current_section] = "\n".join(section_lines)
                current_section = section_match.group(2).upper()
                section_lines = [line]
            else:
                section_lines.append(line)

        if section_lines:
            sections[current_section] = "\n".join(section_lines)

        return sections

    # ── PS-E Parser (All Fuel Meters) ──────────────────────────────────

    def _parse_ps_e(self, content: str) -> Dict[str, Any]:
        """State machine parser for PS-E (All Fuel Meters) report."""
        lines = content.split("\n")
        meters = {}  # meter_name -> list of monthly rows
        current_meter = "default"
        state = ParserState.SEEKING_HEADER
        data_rows = []
        current_month = None

        for line in lines:
            stripped = line.strip()

            # Detect meter names (e.g., "EM1", "ELECTRIC METER", etc.)
            meter_match = re.match(r'^(?:METER|EM|GM|SM)\s*\d*\s*[-:]\s*(.+)', stripped, re.IGNORECASE)
            if meter_match:
                if data_rows:
                    meters[current_meter] = data_rows
                    data_rows = []
                current_meter = meter_match.group(1).strip()
                continue

            # Detect month start
            for month in MONTHS:
                if stripped.startswith(month) and (len(stripped) == 3 or not stripped[3:4].isalpha()):
                    current_month = month
                    break

            # Parse energy data lines
            if current_month and any(u in stripped for u in ("MBTU", "KWH", "THERM")):
                parts = stripped.split()
                if len(parts) >= 2 and parts[0] in ("MBTU", "KWH", "THERM"):
                    unit = parts[0]
                    values = parts[1:]
                    # Standard PS-E columns:
                    # Unit Lights Task_Lt Misc_Eq Space_Htg Space_Clg Heat_Rej Pumps_Aux Vent_Fans Refrig SHW/HT Ext_Use Total
                    col_names = [
                        "Lights", "Task_Lights", "Equipment", "Heating",
                        "Cooling", "Heat_Reject", "Pumps_Aux", "Vent_Fans",
                        "Refrig", "Hot_Water", "Ext_Use", "Total"
                    ]

                    row = {"Month": current_month, "Unit": unit}
                    for i, col in enumerate(col_names):
                        if i < len(values):
                            row[col] = safe_float(values[i])
                        else:
                            row[col] = 0.0

                    data_rows.append(row)
                    current_month = None

        if data_rows:
            meters[current_meter] = data_rows

        # Build result
        result = {}
        for meter_name, rows in meters.items():
            if rows:
                # Compute annual totals
                numeric_cols = [c for c in rows[0].keys() if c not in ("Month", "Unit")]
                totals = {"Month": "ANNUAL", "Unit": rows[0].get("Unit", "")}
                for col in numeric_cols:
                    totals[col] = round(sum(r.get(col, 0.0) for r in rows), 2)
                rows_with_annual = rows + [totals]

                df = pd.DataFrame(rows_with_annual)
                key = f"ps_e_{meter_name}" if meter_name != "default" else "ps_e"
                result[key] = df.to_dict("records")

        # If only one meter, also store as flat ps_e
        if len(meters) == 1:
            key = list(meters.keys())[0]
            result["ps_e"] = result.get(f"ps_e_{key}", result.get("ps_e", []))

        return result if result else self._parse_ps_e_legacy(content)

    def _parse_ps_e_legacy(self, content: str) -> Dict[str, Any]:
        """Fallback legacy PS-E parser for compatibility."""
        lines = content.split("\n")
        data = []
        current_month = None

        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(m) for m in MONTHS):
                for m in MONTHS:
                    if stripped.startswith(m):
                        current_month = m
                        break

            if current_month and any(u in stripped for u in ("MBTU", "KWH", "THERM")):
                parts = stripped.split()
                if len(parts) > 12 and parts[0] in ("MBTU", "KWH", "THERM"):
                    row = {
                        "Month": current_month,
                        "Unit": parts[0],
                        "Lights": safe_float(parts[1]),
                        "Equipment": safe_float(parts[3]),
                        "Heating": safe_float(parts[4]),
                        "Cooling": safe_float(parts[5]),
                        "Vent_Fans": safe_float(parts[8]),
                        "Hot_Water": safe_float(parts[11]),
                        "Total": safe_float(parts[13]) if len(parts) > 13 else 0.0,
                    }
                    data.append(row)
                    current_month = None

        if data:
            totals = {"Month": "ANNUAL", "Unit": data[0]["Unit"]}
            for col in ["Lights", "Equipment", "Heating", "Cooling", "Vent_Fans", "Hot_Water", "Total"]:
                totals[col] = round(sum(d[col] for d in data), 2)
            data.append(totals)

        return {"ps_e": data} if data else {}

    # ── BEPU Parser (Building Energy Performance) ──────────────────────

    def _parse_bepu(self, content: str) -> Dict[str, Any]:
        """State machine parser for BEPU report."""
        result = {}
        lines = content.split("\n")
        state = ParserState.SEEKING_HEADER

        patterns = {
            "floor_area_sqft": (r"FLOOR\s+AREA\s*[=:]*\s*([\d,.]+)\s*SQFT", int),
            "volume_cuft": (r"VOLUME\s*[=:]*\s*([\d,.]+)\s*(?:CU\.?\s*FT|CUFT)", int),
            "total_electricity_kwh": (r"TOTAL\s+ELECTRICITY\s*[=:]*\s*([\d,.]+)\s*KWH", float),
            "total_gas_therm": (r"TOTAL\s+GAS\s*[=:]*\s*([\d,.]+)\s*THERM", float),
            "eui_kwh_sqft_yr": (r"([\d,.]+)\s*KWH\s*/\s*SQFT[-\s]*YR", float),
            "eui_kbtu_sqft_yr": (r"([\d,.]+)\s*KBTU\s*/\s*SQFT[-\s]*YR", float),
            "total_site_energy_mbtu": (r"TOTAL\s+SITE\s+ENERGY\s*[=:]*\s*([\d,.]+)\s*MBTU", float),
            "total_source_energy_mbtu": (r"TOTAL\s+SOURCE\s+ENERGY\s*[=:]*\s*([\d,.]+)\s*MBTU", float),
            "peak_electric_kw": (r"PEAK\s+ELECTRIC\s*[=:]*\s*([\d,.]+)\s*KW", float),
            "electric_cost": (r"ELECTRICITY\s+COST\s*[=:]*\s*\$?\s*([\d,.]+)", float),
            "gas_cost": (r"GAS\s+COST\s*[=:]*\s*\$?\s*([\d,.]+)", float),
        }

        for line in lines:
            for key, (pattern, converter) in patterns.items():
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    val_str = match.group(1).replace(",", "")
                    try:
                        result[key] = converter(float(val_str))
                    except (ValueError, OverflowError):
                        pass

        # Derived metrics
        if "total_electricity_kwh" in result and "floor_area_sqft" in result:
            if "eui_kwh_sqft_yr" not in result and result["floor_area_sqft"] > 0:
                result["eui_kwh_sqft_yr"] = round(
                    result["total_electricity_kwh"] / result["floor_area_sqft"], 2
                )

        return result

    # ── LS-C Parser (Peak Loads by Zone) ──────────────────────────────

    def _parse_ls_c(self, content: str) -> Dict[str, Any]:
        """State machine parser for LS-C report."""
        result = {}
        lines = content.split("\n")
        in_cooling = False
        in_heating = False
        zones = []
        current_zone = None

        for line in lines:
            stripped = line.strip()

            # Zone detection
            zone_match = re.match(r'^(ZONE|SPACE)\s*[-:=]\s*(.+)', stripped, re.IGNORECASE)
            if zone_match:
                current_zone = zone_match.group(2).strip()

            # Section detection
            if "COOLING" in stripped.upper() and "LOAD" in stripped.upper():
                in_cooling = True
                in_heating = False
            elif "HEATING" in stripped.upper() and "LOAD" in stripped.upper():
                in_heating = True
                in_cooling = False

            # Peak load values
            if "TOTAL LOAD" in stripped.upper() or "GRAND TOTAL" in stripped.upper():
                parts = stripped.split()
                for i, part in enumerate(parts):
                    val = safe_float(part)
                    if val > 0:
                        if in_cooling and "cooling_load_kbtu_h" not in result:
                            result["cooling_load_kbtu_h"] = val
                        elif in_heating and "heating_load_kbtu_h" not in result:
                            result["heating_load_kbtu_h"] = val
                        break

            # Peak time detection
            time_match = re.search(r'(\d{1,2}:\d{2}\s*(?:AM|PM)?)\s+(\w+\s+\d+)', stripped, re.IGNORECASE)
            if time_match:
                if in_cooling and "cooling_peak_time" not in result:
                    result["cooling_peak_time"] = f"{time_match.group(1)} {time_match.group(2)}"
                elif in_heating and "heating_peak_time" not in result:
                    result["heating_peak_time"] = f"{time_match.group(1)} {time_match.group(2)}"

            # Zone-level loads
            if current_zone and (in_cooling or in_heating):
                load_match = re.search(r'([\d,.]+)\s*(?:KBTU|KBTU/H)', stripped, re.IGNORECASE)
                if load_match:
                    zone_data = {
                        "zone": current_zone,
                        "load_kbtu_h": safe_float(load_match.group(1)),
                        "type": "cooling" if in_cooling else "heating"
                    }
                    zones.append(zone_data)

        # Derived metrics
        if "cooling_load_kbtu_h" in result:
            result["cooling_tons"] = round(result["cooling_load_kbtu_h"] / 12.0, 1)
            result["cooling_kw"] = round(result["cooling_load_kbtu_h"] * 0.29307107, 1)

        if "heating_load_kbtu_h" in result:
            result["heating_kw"] = round(result["heating_load_kbtu_h"] * 0.29307107, 1)

        if "cooling_load_kbtu_h" in result and "heating_load_kbtu_h" in result:
            if result["heating_load_kbtu_h"] > 0:
                result["cooling_heating_ratio"] = round(
                    result["cooling_load_kbtu_h"] / result["heating_load_kbtu_h"], 2
                )

        if zones:
            result["zone_loads"] = zones

        return result

    # ── LS-B Parser (Zone Load Breakdown) ─────────────────────────────

    def _parse_ls_b(self, content: str) -> Dict[str, Any]:
        """Parser for LS-B (Zone Load Breakdown) report."""
        result = {"zones": []}
        lines = content.split("\n")
        current_zone = None
        zone_data = {}

        for line in lines:
            stripped = line.strip()

            zone_match = re.match(r'^(?:ZONE|SPACE)\s*[-:=]\s*(.+)', stripped, re.IGNORECASE)
            if zone_match:
                if zone_data and current_zone:
                    zone_data["zone_name"] = current_zone
                    result["zones"].append(zone_data)
                current_zone = zone_match.group(1).strip()
                zone_data = {}
                continue

            # Component load extraction
            components = [
                ("walls", r"WALLS?\s*[=:]*\s*([\d,.]+)"),
                ("roof", r"ROOF\s*[=:]*\s*([\d,.]+)"),
                ("windows", r"(?:WINDOW|GLASS|GLAZING)\s*[=:]*\s*([\d,.]+)"),
                ("infiltration", r"INFILTRAT\w*\s*[=:]*\s*([\d,.]+)"),
                ("lights", r"LIGHTS?\s*[=:]*\s*([\d,.]+)"),
                ("people", r"(?:PEOPLE|OCCUPAN)\s*[=:]*\s*([\d,.]+)"),
                ("equipment", r"(?:EQUIP|MISC)\s*[=:]*\s*([\d,.]+)"),
                ("ventilation", r"VENTILAT\w*\s*[=:]*\s*([\d,.]+)"),
                ("floor", r"FLOOR\s*[=:]*\s*([\d,.]+)"),
            ]

            for comp_name, pattern in components:
                match = re.search(pattern, stripped, re.IGNORECASE)
                if match:
                    zone_data[comp_name] = safe_float(match.group(1))

            # Area and CFM
            area_match = re.search(r"AREA\s*[=:]*\s*([\d,.]+)\s*(?:SQFT|SF)", stripped, re.IGNORECASE)
            if area_match:
                zone_data["area_sqft"] = safe_float(area_match.group(1))

            cfm_match = re.search(r"([\d,.]+)\s*CFM", stripped, re.IGNORECASE)
            if cfm_match:
                zone_data["cfm"] = safe_float(cfm_match.group(1))

        # Don't forget the last zone
        if zone_data and current_zone:
            zone_data["zone_name"] = current_zone
            result["zones"].append(zone_data)

        # Summary
        if result["zones"]:
            total_area = sum(z.get("area_sqft", 0) for z in result["zones"])
            result["total_zones"] = len(result["zones"])
            result["total_area_sqft"] = total_area

        return result

    # ── ES-D Parser (Energy Cost Summary) ──────────────────────────────

    def _parse_es_d(self, content: str) -> Dict[str, Any]:
        """State machine parser for ES-D report."""
        result = {}
        lines = content.split("\n")
        monthly_costs = []
        current_month = None

        for line in lines:
            stripped = line.strip()

            # Cost per sqft
            cost_match = re.search(
                r"ENERGY\s+COST\s*/\s*GROSS\s+BLDG\s+AREA\s*:\s*([\d,.]+)",
                stripped, re.IGNORECASE
            )
            if cost_match:
                result["cost_per_sqft"] = safe_float(cost_match.group(1))

            # Total cost with dollar sign
            total_match = re.search(r"TOTAL\b.*?\$\s*([\d,.]+)", stripped, re.IGNORECASE)
            if total_match:
                result["total_cost"] = safe_float(total_match.group(1))

            # Electric rate
            rate_match = re.search(r"ELEC(?:TRIC)?\s+RATE\s*[=:]*\s*\$?\s*([\d,.]+)", stripped, re.IGNORECASE)
            if rate_match:
                result["electric_rate"] = safe_float(rate_match.group(1))

            # Gas rate
            gas_rate_match = re.search(r"GAS\s+RATE\s*[=:]*\s*\$?\s*([\d,.]+)", stripped, re.IGNORECASE)
            if gas_rate_match:
                result["gas_rate"] = safe_float(gas_rate_match.group(1))

            # Monthly cost rows
            for month in MONTHS:
                if stripped.startswith(month):
                    dollar_match = re.search(r'\$\s*([\d,.]+)', stripped)
                    if dollar_match:
                        monthly_costs.append({
                            "month": month,
                            "cost": safe_float(dollar_match.group(1))
                        })

            # Electric cost breakdown
            elec_cost_match = re.search(
                r"ELECTRICITY\s+COST\s*[=:]*\s*\$?\s*([\d,.]+)",
                stripped, re.IGNORECASE
            )
            if elec_cost_match:
                result["electricity_cost"] = safe_float(elec_cost_match.group(1))

            gas_cost_match = re.search(
                r"GAS\s+COST\s*[=:]*\s*\$?\s*([\d,.]+)",
                stripped, re.IGNORECASE
            )
            if gas_cost_match:
                result["gas_cost"] = safe_float(gas_cost_match.group(1))

        if monthly_costs:
            result["monthly_costs"] = monthly_costs

        return result

    # ── LV-D Parser (Building Envelope) ────────────────────────────────

    def _parse_lv_d(self, content: str) -> Dict[str, Any]:
        """State machine parser for LV-D report."""
        result = {"surfaces": [], "summary": {}}
        lines = content.split("\n")
        current_surface = None

        for line in lines:
            stripped = line.strip()

            # Surface detection
            surface_match = re.match(
                r'^(WALL|ROOF|FLOOR|WINDOW|DOOR|UNDERGROUND)\s*[-:]\s*(.+)',
                stripped, re.IGNORECASE
            )
            if surface_match:
                if current_surface:
                    result["surfaces"].append(current_surface)
                current_surface = {
                    "type": surface_match.group(1).upper(),
                    "name": surface_match.group(2).strip(),
                }
                continue

            # U-value
            u_match = re.search(r"U[-\s]*VALUE\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if u_match:
                result["summary"]["has_envelope_data"] = True
                val = safe_float(u_match.group(1))
                if current_surface:
                    current_surface["u_value"] = val
                if "avg_u_value" not in result["summary"]:
                    result["summary"]["avg_u_value"] = val

            # R-value
            r_match = re.search(r"R[-\s]*VALUE\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if r_match:
                result["summary"]["has_envelope_data"] = True
                val = safe_float(r_match.group(1))
                if current_surface:
                    current_surface["r_value"] = val

            # Area
            area_match = re.search(r"AREA\s*[=:]*\s*([\d,.]+)\s*(?:SQFT|SF)", stripped, re.IGNORECASE)
            if area_match and current_surface:
                current_surface["area_sqft"] = safe_float(area_match.group(1))

            # SHGC (for windows)
            shgc_match = re.search(r"SHGC\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if shgc_match and current_surface:
                current_surface["shgc"] = safe_float(shgc_match.group(1))

            # VLT (visible light transmittance)
            vlt_match = re.search(r"VLT\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if vlt_match and current_surface:
                current_surface["vlt"] = safe_float(vlt_match.group(1))

        if current_surface:
            result["surfaces"].append(current_surface)

        # Compute summary
        if result["surfaces"]:
            wall_surfaces = [s for s in result["surfaces"] if s["type"] == "WALL"]
            window_surfaces = [s for s in result["surfaces"] if s["type"] == "WINDOW"]
            roof_surfaces = [s for s in result["surfaces"] if s["type"] == "ROOF"]

            if wall_surfaces:
                u_vals = [s["u_value"] for s in wall_surfaces if "u_value" in s]
                if u_vals:
                    result["summary"]["avg_wall_u_value"] = round(sum(u_vals) / len(u_vals), 4)
                    result["summary"]["total_wall_area"] = sum(
                        s.get("area_sqft", 0) for s in wall_surfaces
                    )

            if window_surfaces:
                u_vals = [s["u_value"] for s in window_surfaces if "u_value" in s]
                if u_vals:
                    result["summary"]["avg_window_u_value"] = round(sum(u_vals) / len(u_vals), 4)
                shgc_vals = [s["shgc"] for s in window_surfaces if "shgc" in s]
                if shgc_vals:
                    result["summary"]["avg_shgc"] = round(sum(shgc_vals) / len(shgc_vals), 2)

                total_window_area = sum(s.get("area_sqft", 0) for s in window_surfaces)
                total_wall_area = result["summary"].get("total_wall_area", 0)
                if total_wall_area > 0:
                    result["summary"]["window_wall_ratio"] = round(
                        total_window_area / (total_wall_area + total_window_area), 2
                    )

            if roof_surfaces:
                u_vals = [s["u_value"] for s in roof_surfaces if "u_value" in s]
                if u_vals:
                    result["summary"]["avg_roof_u_value"] = round(sum(u_vals) / len(u_vals), 4)

        return result

    # ── SS-P Parser (System Summary) ──────────────────────────────────

    def _parse_ss_p(self, content: str) -> Dict[str, Any]:
        """Parser for SS-P (System Summary) report."""
        result = {"systems": []}
        lines = content.split("\n")
        current_system = None

        for line in lines:
            stripped = line.strip()

            # System detection
            sys_match = re.match(
                r'^(?:SYSTEM|SYS)\s*[-:=]\s*(.+)',
                stripped, re.IGNORECASE
            )
            if sys_match:
                if current_system:
                    result["systems"].append(current_system)
                current_system = {"name": sys_match.group(1).strip()}
                continue

            if not current_system:
                continue

            # System type
            type_match = re.search(r"SYSTEM\s+TYPE\s*[=:]*\s*(.+?)(?:\s{2,}|$)", stripped, re.IGNORECASE)
            if type_match:
                current_system["system_type"] = type_match.group(1).strip()

            # Supply CFM
            cfm_match = re.search(r"SUPPLY\s+(?:AIR\s+)?(?:CFM|FLOW)\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if cfm_match:
                current_system["supply_cfm"] = safe_float(cfm_match.group(1))

            # Cooling capacity
            cool_cap = re.search(r"COOL(?:ING)?\s+CAP(?:ACITY)?\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if cool_cap:
                current_system["cooling_capacity"] = safe_float(cool_cap.group(1))

            # Heating capacity
            heat_cap = re.search(r"HEAT(?:ING)?\s+CAP(?:ACITY)?\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if heat_cap:
                current_system["heating_capacity"] = safe_float(heat_cap.group(1))

            # COP / EER
            cop_match = re.search(r"COP\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if cop_match:
                current_system["cop"] = safe_float(cop_match.group(1))

            eer_match = re.search(r"EER\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if eer_match:
                current_system["eer"] = safe_float(eer_match.group(1))

            # Fan power
            fan_match = re.search(r"FAN\s+(?:POWER|KW)\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if fan_match:
                current_system["fan_kw"] = safe_float(fan_match.group(1))

            # Zones served
            zone_match = re.search(r"ZONES?\s+SERVED\s*[=:]*\s*(\d+)", stripped, re.IGNORECASE)
            if zone_match:
                current_system["zones_served"] = safe_int(zone_match.group(1))

        if current_system:
            result["systems"].append(current_system)

        result["total_systems"] = len(result["systems"])
        return result

    # ── SV-A Parser (Plant/Equipment Reports) ─────────────────────────

    def _parse_sv_a(self, content: str) -> Dict[str, Any]:
        """Parser for SV-A (Plant Energy) report."""
        result = {"equipment": []}
        lines = content.split("\n")
        current_equip = None

        for line in lines:
            stripped = line.strip()

            equip_match = re.match(
                r'^(?:PLANT|EQUIP|CHILLER|BOILER|TOWER)\s*[-:=]\s*(.+)',
                stripped, re.IGNORECASE
            )
            if equip_match:
                if current_equip:
                    result["equipment"].append(current_equip)
                current_equip = {"name": equip_match.group(1).strip()}
                continue

            if not current_equip:
                continue

            # Equipment type
            type_match = re.search(r"(?:TYPE|EQUIP\s+TYPE)\s*[=:]*\s*(.+?)(?:\s{2,}|$)", stripped, re.IGNORECASE)
            if type_match:
                current_equip["type"] = type_match.group(1).strip()

            # Capacity
            cap_match = re.search(r"CAPACITY\s*[=:]*\s*([\d,.]+)\s*(\w+)", stripped, re.IGNORECASE)
            if cap_match:
                current_equip["capacity"] = safe_float(cap_match.group(1))
                current_equip["capacity_unit"] = cap_match.group(2)

            # Energy consumption
            energy_match = re.search(r"ENERGY\s*[=:]*\s*([\d,.]+)\s*(\w+)", stripped, re.IGNORECASE)
            if energy_match:
                current_equip["energy"] = safe_float(energy_match.group(1))
                current_equip["energy_unit"] = energy_match.group(2)

            # COP/efficiency
            eff_match = re.search(r"(?:COP|EFF|EFFICIENCY)\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if eff_match:
                current_equip["efficiency"] = safe_float(eff_match.group(1))

            # Run hours
            hours_match = re.search(r"(?:HOURS|RUN\s*HRS?)\s*[=:]*\s*([\d,.]+)", stripped, re.IGNORECASE)
            if hours_match:
                current_equip["run_hours"] = safe_float(hours_match.group(1))

        if current_equip:
            result["equipment"].append(current_equip)

        return result

    # ── SV-B Parser (System Energy Reports) ───────────────────────────

    def _parse_sv_b(self, content: str) -> Dict[str, Any]:
        """Parser for SV-B (System Energy) report."""
        result = {"system_energy": []}
        lines = content.split("\n")

        current_system = None
        monthly_data = []

        for line in lines:
            stripped = line.strip()

            sys_match = re.match(r'^(?:SYSTEM|SYS)\s*[-:=]\s*(.+)', stripped, re.IGNORECASE)
            if sys_match:
                if current_system and monthly_data:
                    result["system_energy"].append({
                        "system": current_system,
                        "monthly": monthly_data
                    })
                current_system = sys_match.group(1).strip()
                monthly_data = []
                continue

            # Monthly energy data
            for month in MONTHS:
                if stripped.startswith(month):
                    parts = stripped.split()
                    if len(parts) >= 3:
                        monthly_data.append({
                            "month": month,
                            "cooling_kwh": safe_float(parts[1]) if len(parts) > 1 else 0,
                            "heating_kwh": safe_float(parts[2]) if len(parts) > 2 else 0,
                            "fan_kwh": safe_float(parts[3]) if len(parts) > 3 else 0,
                            "total_kwh": safe_float(parts[-1]) if len(parts) > 4 else 0,
                        })

        if current_system and monthly_data:
            result["system_energy"].append({
                "system": current_system,
                "monthly": monthly_data
            })

        return result

    # ── Hourly Report Parser ──────────────────────────────────────────

    def _parse_hourly(self, content: str) -> Dict[str, Any]:
        """Parser for hourly eQuest reports (CSV-like format)."""
        result = {}
        lines = content.split("\n")

        # Try to detect CSV format
        if lines and "," in lines[0]:
            try:
                import io
                df = pd.read_csv(io.StringIO(content))
                result["hourly_data"] = df.to_dict("records")
                result["total_records"] = len(df)

                # Compute summary stats for numeric columns
                numeric_cols = df.select_dtypes(include=[np.number]).columns
                summary = {}
                for col in numeric_cols:
                    summary[col] = {
                        "min": round(float(df[col].min()), 2),
                        "max": round(float(df[col].max()), 2),
                        "mean": round(float(df[col].mean()), 2),
                        "sum": round(float(df[col].sum()), 2),
                    }
                result["column_stats"] = summary
            except Exception as e:
                logger.warning("Hourly CSV parse failed: %s", e)

        return result

    # ── Validation ────────────────────────────────────────────────────

    def validate(self, result: ParseResult) -> ValidationResult:
        """Validate parsed data for completeness and consistency."""
        validation = ValidationResult()
        data = result.data

        if not data:
            validation.is_valid = False
            validation.errors.append("No data could be parsed from the file")
            validation.completeness_score = 0.0
            return validation

        report_type = result.report_type

        # Check expected fields per report type
        expected_fields = {
            "PS-E": ["ps_e"],
            "BEPU": ["floor_area_sqft", "total_electricity_kwh"],
            "LS-C": ["cooling_load_kbtu_h"],
            "ES-D": ["cost_per_sqft"],
            "LV-D": ["surfaces", "summary"],
            "LS-B": ["zones"],
            "SS-P": ["systems"],
        }

        expected = expected_fields.get(report_type, [])
        present = sum(1 for f in expected if f in data)
        if expected:
            validation.completeness_score = present / len(expected)
        else:
            validation.completeness_score = 1.0 if data else 0.0

        missing = [f for f in expected if f not in data]
        if missing:
            validation.missing_sections = missing
            validation.warnings.append(f"Missing expected fields: {', '.join(missing)}")

        # Value range validation
        if report_type == "BEPU":
            eui = data.get("eui_kwh_sqft_yr", 0)
            if eui > 0:
                if eui > 200:
                    validation.warnings.append(f"EUI of {eui} kWh/sqft/yr seems unusually high")
                elif eui < 1:
                    validation.warnings.append(f"EUI of {eui} kWh/sqft/yr seems unusually low")

            area = data.get("floor_area_sqft", 0)
            if area > 0 and area < 100:
                validation.warnings.append(f"Floor area of {area} sqft seems unusually small")

        if report_type == "LS-C":
            cooling = data.get("cooling_load_kbtu_h", 0)
            heating = data.get("heating_load_kbtu_h", 0)
            if cooling > 0 and heating > 0:
                ratio = cooling / heating
                if ratio > 100:
                    validation.warnings.append(
                        f"Cooling/heating ratio of {ratio:.1f} is unusually high"
                    )

        if validation.errors:
            validation.is_valid = False

        return validation
