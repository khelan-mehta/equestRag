import json
import io
from datetime import datetime
from typing import Dict, Any, List
import pandas as pd
import numpy as np

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, 
        Spacer, PageBreak, Image, KeepTogether
    )
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

try:
    import plotly.graph_objects as go
    import plotly.express as px
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


class LLMDataExtractor:
    """Extract and structure all available data using LLM"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.client = None
        if api_key and OPENAI_AVAILABLE:
            try:
                self.client = OpenAI(api_key=api_key)
            except Exception as e:
                print(f"OpenAI initialization failed: {e}")
    
    def extract_all_data(self, building_data: Dict[str, Any], 
                        vector_store=None) -> Dict[str, Any]:
        """Use LLM to comprehensively extract and structure all available data"""
        
        # Create comprehensive data snapshot
        data_snapshot = self._create_data_snapshot(building_data, vector_store)
        
        if self.client:
            # Use LLM to extract insights and structure data
            extracted_data = self._llm_extract(data_snapshot)
        else:
            # Fallback to rule-based extraction
            extracted_data = self._rule_based_extract(building_data)
        
        return extracted_data
    
    def _create_data_snapshot(self, building_data: Dict[str, Any], 
                             vector_store=None) -> str:
        """Create a comprehensive text snapshot of all data"""
        snapshot = []
        
        # Metadata
        if "metadata" in building_data:
            snapshot.append("=== PROJECT METADATA ===")
            for k, v in building_data["metadata"].items():
                snapshot.append(f"{k}: {v}")
            snapshot.append("")
        
        # BEPU Data
        if "bepu" in building_data:
            snapshot.append("=== BUILDING PERFORMANCE (BEPU) ===")
            for k, v in building_data["bepu"].items():
                snapshot.append(f"{k}: {v}")
            snapshot.append("")
        
        # LS-C Data
        if "ls_c" in building_data:
            snapshot.append("=== PEAK LOADS (LS-C) ===")
            for k, v in building_data["ls_c"].items():
                snapshot.append(f"{k}: {v}")
            snapshot.append("")
        
        # PS-E Data
        if "ps_e_electric" in building_data:
            df = building_data["ps_e_electric"]
            snapshot.append("=== MONTHLY ELECTRIC CONSUMPTION (PS-E) ===")
            snapshot.append(df.to_string())
            snapshot.append("")
        
        # ES-D Data
        if "es_d" in building_data:
            snapshot.append("=== ENERGY COST (ES-D) ===")
            for k, v in building_data["es_d"].items():
                snapshot.append(f"{k}: {v}")
            snapshot.append("")
        
        # LV-D Data
        if "lv_d" in building_data:
            snapshot.append("=== BUILDING ENVELOPE (LV-D) ===")
            snapshot.append(json.dumps(building_data["lv_d"], indent=2))
            snapshot.append("")
        
        # Hourly Data Summary
        if "hourly" in building_data:
            df = building_data["hourly"]
            snapshot.append("=== HOURLY DATA SUMMARY ===")
            snapshot.append(f"Total Records: {len(df)}")
            if "Var 20" in df.columns:
                snapshot.append(f"Total Energy: {df['Var 20'].sum():,.0f} kWh")
                snapshot.append(f"Peak Demand: {df['Var 20'].max():,.2f} kW")
                snapshot.append(f"Average Load: {df['Var 20'].mean():,.2f} kW")
            snapshot.append("")
        
        # Vector store documents
        if vector_store and hasattr(vector_store, 'chunks'):
            snapshot.append("=== ADDITIONAL DOCUMENTS ===")
            unique_docs = set()
            for chunk in vector_store.chunks:
                doc_type = chunk.metadata.get('type', 'unknown')
                filename = chunk.metadata.get('filename', 'Unknown')
                unique_docs.add(f"{doc_type}: {filename}")
            for doc in sorted(unique_docs):
                snapshot.append(doc)
            snapshot.append("")
        
        return "\n".join(snapshot)
    
    def _llm_extract(self, data_snapshot: str) -> Dict[str, Any]:
        """Use LLM to extract comprehensive insights"""
        
        system_prompt = """You are an expert energy analyst. Extract ALL available data from the building energy simulation results and structure it comprehensively.

Your task:
1. Identify ALL numerical metrics, performance indicators, and key data points
2. Calculate derived metrics (ratios, percentages, comparisons)
3. Identify trends and patterns in the data
4. Extract energy breakdown by category
5. Identify peak conditions and their timing
6. Calculate efficiency metrics
7. Provide data for visualization (monthly trends, end-use breakdown, etc.)

Return a JSON object with this structure:
{
    "executive_summary": {
        "total_energy_kwh": number,
        "eui_kwh_sqft_yr": number,
        "floor_area_sqft": number,
        "key_findings": [list of strings]
    },
    "energy_consumption": {
        "annual_electric_kwh": number,
        "annual_gas_therm": number,
        "monthly_data": [array of {month, value}],
        "end_use_breakdown": {category: kwh}
    },
    "peak_loads": {
        "cooling_kbtu_h": number,
        "cooling_tons": number,
        "heating_kbtu_h": number,
        "cooling_peak_time": string,
        "heating_peak_time": string
    },
    "efficiency_metrics": {
        "eui": number,
        "avg_power_kw": number,
        "load_factor": number,
        "cooling_to_heating_ratio": number
    },
    "cost_analysis": {
        "total_cost_usd": number,
        "cost_per_sqft": number,
        "cost_per_kwh": number
    },
    "monthly_patterns": {
        "peak_month": string,
        "lowest_month": string,
        "seasonal_variation": number
    },
    "recommendations": [list of actionable insights]
}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Extract and structure all data from:\n\n{data_snapshot}"}
                ],
                response_format={"type": "json_object"},
                max_tokens=4000,
                temperature=0.1
            )
            
            return json.loads(response.choices[0].message.content)
        
        except Exception as e:
            print(f"LLM extraction failed: {e}")
            return {}
    
    def _rule_based_extract(self, building_data: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback rule-based extraction"""
        
        extracted = {
            "executive_summary": {},
            "energy_consumption": {},
            "peak_loads": {},
            "efficiency_metrics": {},
            "cost_analysis": {},
            "monthly_patterns": {},
            "recommendations": []
        }
        
        # BEPU data
        if "bepu" in building_data:
            bepu = building_data["bepu"]
            extracted["executive_summary"]["total_energy_kwh"] = bepu.get("total_electricity_kwh", 0)
            extracted["executive_summary"]["eui_kwh_sqft_yr"] = bepu.get("eui_kwh_sqft_yr", 0)
            extracted["executive_summary"]["floor_area_sqft"] = bepu.get("floor_area_sqft", 0)
            
            extracted["energy_consumption"]["annual_electric_kwh"] = bepu.get("total_electricity_kwh", 0)
            extracted["energy_consumption"]["annual_gas_therm"] = bepu.get("total_gas_therm", 0)
            
            extracted["efficiency_metrics"]["eui"] = bepu.get("eui_kwh_sqft_yr", 0)
            if bepu.get("total_electricity_kwh"):
                extracted["efficiency_metrics"]["avg_power_kw"] = bepu["total_electricity_kwh"] / 8760
        
        # LS-C data
        if "ls_c" in building_data:
            ls_c = building_data["ls_c"]
            cooling_kbtu = ls_c.get("cooling_load_kbtu_h", 0)
            extracted["peak_loads"]["cooling_kbtu_h"] = cooling_kbtu
            extracted["peak_loads"]["cooling_tons"] = cooling_kbtu * 0.293 / 3.517
            extracted["peak_loads"]["heating_kbtu_h"] = ls_c.get("heating_load_kbtu_h", 0)
            extracted["peak_loads"]["cooling_peak_time"] = ls_c.get("cooling_peak_time", "N/A")
            extracted["peak_loads"]["heating_peak_time"] = ls_c.get("heating_peak_time", "N/A")
        
        # PS-E data
        if "ps_e_electric" in building_data:
            df = building_data["ps_e_electric"]
            annual = df[df["Month"] == "ANNUAL"]
            
            if not annual.empty:
                end_use = {}
                for col in ["Cooling", "Heating", "Lights", "Equipment", "Vent_Fans", "Pumps_Aux", "Hot_Water"]:
                    if col in annual.columns:
                        end_use[col] = float(annual[col].values[0])
                extracted["energy_consumption"]["end_use_breakdown"] = end_use
            
            df_monthly = df[df["Month"] != "ANNUAL"]
            if not df_monthly.empty and "Total" in df_monthly.columns:
                extracted["monthly_patterns"]["peak_month"] = df_monthly.loc[df_monthly["Total"].idxmax(), "Month"]
                extracted["monthly_patterns"]["lowest_month"] = df_monthly.loc[df_monthly["Total"].idxmin(), "Month"]
                
                monthly_data = []
                for _, row in df_monthly.iterrows():
                    monthly_data.append({"month": row["Month"], "value": float(row["Total"])})
                extracted["energy_consumption"]["monthly_data"] = monthly_data
        
        # ES-D data
        if "es_d" in building_data:
            es_d = building_data["es_d"]
            extracted["cost_analysis"]["cost_per_sqft"] = es_d.get("cost_per_sqft", 0)
            
            if es_d.get("cost_per_sqft") and extracted["executive_summary"].get("floor_area_sqft"):
                extracted["cost_analysis"]["total_cost_usd"] = (
                    es_d["cost_per_sqft"] * extracted["executive_summary"]["floor_area_sqft"]
                )
        
        return extracted


class VisualizationGenerator:
    """Generate all possible visualizations from extracted data"""
    
    def __init__(self, extracted_data: Dict[str, Any], building_data: Dict[str, Any]):
        self.extracted_data = extracted_data
        self.building_data = building_data
    
    @staticmethod
    def _safe_set_bar_colors(chart, colors_list: List, num_bars: int):
        """Safely set bar colors, handling different ReportLab versions"""
        try:
            # Method 1: Direct bar access
            for i in range(min(num_bars, len(colors_list))):
                chart.bars[i].fillColor = colors_list[i]
        except (AttributeError, TypeError, IndexError):
            try:
                # Method 2: Set strokeColor instead
                for i in range(min(num_bars, len(colors_list))):
                    chart.bars[i].strokeColor = colors_list[i]
            except:
                try:
                    # Method 3: Set default color
                    chart.bars.fillColor = colors_list[0] if colors_list else colors.blue
                except:
                    pass  # Give up gracefully
    
    def generate_all_visualizations(self) -> Dict[str, Any]:
        """Generate all possible charts and graphs"""
        
        visualizations = {}
        
        # Wrap each visualization in try-except for robustness
        try:
            if "energy_consumption" in self.extracted_data:
                if "end_use_breakdown" in self.extracted_data["energy_consumption"]:
                    visualizations["end_use_pie"] = self._create_end_use_pie()
        except Exception as e:
            print(f"Error creating end-use pie chart: {e}")
        
        try:
            if "monthly_data" in self.extracted_data.get("energy_consumption", {}):
                visualizations["monthly_bar"] = self._create_monthly_bar()
        except Exception as e:
            print(f"Error creating monthly bar chart: {e}")
        
        try:
            if "ps_e_electric" in self.building_data:
                visualizations["monthly_stacked"] = self._create_monthly_stacked()
        except Exception as e:
            print(f"Error creating monthly stacked chart: {e}")
        
        try:
            if "hourly" in self.building_data:
                visualizations["load_profile"] = self._create_load_profile()
        except Exception as e:
            print(f"Error creating load profile: {e}")
        
        try:
            if "peak_loads" in self.extracted_data:
                visualizations["peak_comparison"] = self._create_peak_comparison()
        except Exception as e:
            print(f"Error creating peak comparison: {e}")
        
        try:
            if "efficiency_metrics" in self.extracted_data:
                visualizations["eui_benchmark"] = self._create_eui_benchmark()
        except Exception as e:
            print(f"Error creating EUI benchmark: {e}")
        
        return visualizations
    
    def _create_end_use_pie(self) -> Drawing:
        """Create end-use breakdown pie chart"""
        drawing = Drawing(300, 200)
        
        breakdown = self.extracted_data["energy_consumption"]["end_use_breakdown"]
        
        labels = list(breakdown.keys())
        values = list(breakdown.values())
        
        # Filter zeros
        filtered = [(l, v) for l, v in zip(labels, values) if v > 0]
        if not filtered:
            return drawing
        
        labels, values = zip(*filtered)
        
        pie = Pie()
        pie.x = 50
        pie.y = 50
        pie.width = 200
        pie.height = 200
        pie.data = values
        pie.labels = [l.replace("_", " ") for l in labels]
        pie.slices.strokeWidth = 0.5
        
        colors_list = [
            colors.HexColor("#FFD93D"), colors.HexColor("#6BCB77"),
            colors.HexColor("#FF6B6B"), colors.HexColor("#FFA500"),
            colors.HexColor("#4D96FF"), colors.HexColor("#9D84B7"),
            colors.HexColor("#FF8787")
        ]
        
        for i, color in enumerate(colors_list[:len(values)]):
            pie.slices[i].fillColor = color
        
        drawing.add(pie)
        return drawing
    
    def _create_monthly_bar(self) -> Drawing:
        """Create monthly consumption bar chart"""
        drawing = Drawing(400, 250)
        
        monthly_data = self.extracted_data["energy_consumption"]["monthly_data"]
        
        months = [d["month"] for d in monthly_data]
        values = [d["value"] for d in monthly_data]
        
        chart = VerticalBarChart()
        chart.x = 50
        chart.y = 50
        chart.height = 150
        chart.width = 300
        chart.data = [values]
        chart.categoryAxis.categoryNames = months
        chart.valueAxis.valueMin = 0
        chart.valueAxis.valueMax = max(values) * 1.1 if values else 100
        chart.bars[0].fillColor = colors.HexColor("#4D96FF")
        
        drawing.add(chart)
        return drawing
    
    def _create_monthly_stacked(self) -> Drawing:
        """Create stacked bar chart for monthly breakdown"""
        drawing = Drawing(500, 300)
        
        df = self.building_data["ps_e_electric"]
        df_monthly = df[df["Month"] != "ANNUAL"]
        
        if df_monthly.empty:
            return drawing
        
        # Create stacked data
        categories = ["Cooling", "Heating", "Lights", "Equipment"]
        data = []
        for cat in categories:
            if cat in df_monthly.columns:
                data.append(df_monthly[cat].tolist())
        
        if not data:
            return drawing
        
        chart = VerticalBarChart()
        chart.x = 50
        chart.y = 50
        chart.height = 200
        chart.width = 400
        chart.data = data
        chart.categoryAxis.categoryNames = df_monthly["Month"].tolist()
        chart.valueAxis.valueMin = 0
        
        colors_map = [
            colors.HexColor("#FF6B6B"), colors.HexColor("#FFA500"),
            colors.HexColor("#FFD93D"), colors.HexColor("#6BCB77")
        ]
        
        # Use safe color setter
        self._safe_set_bar_colors(chart, colors_map, len(data))
        
        drawing.add(chart)
        return drawing
    
    def _create_load_profile(self) -> Drawing:
        """Create load profile line chart"""
        drawing = Drawing(500, 250)
        
        df = self.building_data["hourly"]
        if "Var 20" in df.columns:
            values = df["Var 20"].head(168).tolist()  # One week
            
            chart = HorizontalLineChart()
            chart.x = 50
            chart.y = 50
            chart.height = 150
            chart.width = 400
            chart.data = [values]
            chart.lines[0].strokeColor = colors.HexColor("#4D96FF")
            chart.lines[0].strokeWidth = 2
            
            drawing.add(chart)
        
        return drawing
    
    def _create_peak_comparison(self) -> Drawing:
        """Create peak loads comparison chart"""
        drawing = Drawing(300, 200)
        
        peak_loads = self.extracted_data["peak_loads"]
        
        cooling = peak_loads.get("cooling_kbtu_h", 0)
        heating = peak_loads.get("heating_kbtu_h", 0)
        
        chart = VerticalBarChart()
        chart.x = 75
        chart.y = 50
        chart.height = 120
        chart.width = 150
        chart.data = [[cooling, heating]]
        chart.categoryAxis.categoryNames = ["Cooling", "Heating"]
        chart.valueAxis.valueMin = 0
        chart.bars[0].fillColor = colors.HexColor("#FF6B6B")
        
        drawing.add(chart)
        return drawing
    
    def _create_eui_benchmark(self) -> Drawing:
        """Create EUI benchmark comparison"""
        drawing = Drawing(300, 200)
        
        building_eui = self.extracted_data["efficiency_metrics"].get("eui", 0)
        
        # Benchmark values
        benchmarks = {
            "Building": building_eui,
            "Excellent": 12,
            "Good": 18,
            "Average": 25
        }
        
        chart = VerticalBarChart()
        chart.x = 50
        chart.y = 50
        chart.height = 120
        chart.width = 200
        chart.data = [list(benchmarks.values())]
        chart.categoryAxis.categoryNames = list(benchmarks.keys())
        chart.valueAxis.valueMin = 0
        
        colors_list = [colors.HexColor("#4D96FF"), colors.HexColor("#6BCB77"),
                      colors.HexColor("#FFD93D"), colors.HexColor("#FFA500")]
        
        for i, color in enumerate(colors_list):
            chart.bars[0][i].fillColor = color
        
        drawing.add(chart)
        return drawing


class EnhancedPDFReportGenerator:
    """Generate comprehensive PDF with LLM-extracted data and visualizations"""
    
    def __init__(self, building_data: Dict[str, Any], api_key: str = None):
        self.building_data = building_data
        self.api_key = api_key
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
        
        # Extract comprehensive data
        self.extractor = LLMDataExtractor(api_key)
        self.extracted_data = self.extractor.extract_all_data(building_data)
        
        # Generate visualizations
        self.viz_gen = VisualizationGenerator(self.extracted_data, building_data)
        self.visualizations = self.viz_gen.generate_all_visualizations()
    
    def _setup_custom_styles(self):
        """Setup custom styles"""
        self.styles.add(ParagraphStyle(
            name="CustomTitle",
            parent=self.styles["Heading1"],
            fontSize=28,
            textColor=colors.HexColor("#1A5490"),
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold"
        ))
        
        self.styles.add(ParagraphStyle(
            name="SectionHeader",
            parent=self.styles["Heading2"],
            fontSize=18,
            textColor=colors.HexColor("#2874A6"),
            spaceAfter=15,
            spaceBefore=20,
            fontName="Helvetica-Bold"
        ))
        
        self.styles.add(ParagraphStyle(
            name="SubSection",
            parent=self.styles["Heading3"],
            fontSize=14,
            textColor=colors.HexColor("#3498DB"),
            spaceAfter=10,
            spaceBefore=10,
            fontName="Helvetica-Bold"
        ))
    
    def create_comprehensive_json(self) -> str:
        """Create comprehensive JSON export"""
        export_data = {
            "report_metadata": {
                "generated_at": datetime.now().isoformat(),
                "report_type": "Comprehensive eQuest Energy Analysis",
                "version": "2.0",
                "generated_by": "LLM-Enhanced Analysis"
            },
            "extracted_insights": self.extracted_data,
            "raw_data": {}
        }
        
        # Add all raw data
        for key, value in self.building_data.items():
            if isinstance(value, pd.DataFrame):
                export_data["raw_data"][key] = value.to_dict("records")
            else:
                export_data["raw_data"][key] = value
        
        return json.dumps(export_data, indent=2, default=str)
    
    def generate_pdf(self, filename: str = "comprehensive_energy_report.pdf"):
        """Generate comprehensive PDF report"""
        
        if not REPORTLAB_AVAILABLE:
            raise ImportError("ReportLab required for PDF generation")
        
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, 
            pagesize=letter,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch,
            leftMargin=0.75*inch,
            rightMargin=0.75*inch
        )
        story = []
        
        # Cover Page
        story.extend(self._create_cover_page())
        story.append(PageBreak())
        
        # Executive Summary
        story.extend(self._create_executive_summary())
        story.append(PageBreak())
        
        # Energy Consumption Analysis
        story.extend(self._create_energy_analysis())
        story.append(PageBreak())
        
        # Peak Loads Analysis
        story.extend(self._create_peak_loads_section())
        
        # Efficiency Metrics
        story.extend(self._create_efficiency_section())
        story.append(PageBreak())
        
        # Cost Analysis
        story.extend(self._create_cost_section())
        
        # Monthly Patterns
        story.extend(self._create_monthly_patterns())
        
        # Recommendations
        if self.extracted_data.get("recommendations"):
            story.append(PageBreak())
            story.extend(self._create_recommendations())
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer
    
    def _create_cover_page(self) -> List:
        """Create cover page"""
        elements = []
        
        elements.append(Spacer(1, 2*inch))
        elements.append(Paragraph("COMPREHENSIVE ENERGY ANALYSIS REPORT", 
                                 self.styles["CustomTitle"]))
        elements.append(Spacer(1, 0.5*inch))
        
        # Project info
        if "metadata" in self.building_data:
            metadata = self.building_data["metadata"]
            info_data = []
            for k, v in metadata.items():
                info_data.append([k.replace("_", " ").title(), str(v)])
            
            if info_data:
                t = Table(info_data, colWidths=[3*inch, 3*inch])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor("#ECF0F1")),
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 12),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('PADDING', (0, 0), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey)
                ]))
                elements.append(t)
        
        elements.append(Spacer(1, 1*inch))
        elements.append(Paragraph(
            f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}",
            self.styles["Normal"]
        ))
        
        return elements
    
    def _create_executive_summary(self) -> List:
        """Create executive summary"""
        elements = []
        
        elements.append(Paragraph("Executive Summary", self.styles["SectionHeader"]))
        elements.append(Spacer(1, 0.2*inch))
        
        summary = self.extracted_data.get("executive_summary", {})
        
        # Key metrics
        metrics_data = []
        if summary.get("total_energy_kwh"):
            metrics_data.append(["Total Annual Energy", 
                               f"{summary['total_energy_kwh']:,.0f} kWh"])
        if summary.get("eui_kwh_sqft_yr"):
            metrics_data.append(["Energy Use Intensity", 
                               f"{summary['eui_kwh_sqft_yr']:.2f} kWh/sqft/yr"])
        if summary.get("floor_area_sqft"):
            metrics_data.append(["Building Floor Area", 
                               f"{summary['floor_area_sqft']:,.0f} sqft"])
        
        if metrics_data:
            t = Table(metrics_data, colWidths=[3*inch, 3*inch])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#E8F6F3")),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 12),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('PADDING', (0, 0), (-1, -1), 12),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey)
            ]))
            elements.append(t)
        
        # Key findings
        if summary.get("key_findings"):
            elements.append(Spacer(1, 0.3*inch))
            elements.append(Paragraph("Key Findings", self.styles["SubSection"]))
            for finding in summary["key_findings"]:
                elements.append(Paragraph(f"• {finding}", self.styles["Normal"]))
                elements.append(Spacer(1, 0.1*inch))
        
        return elements
    
    def _create_energy_analysis(self) -> List:
        """Create energy consumption analysis section"""
        elements = []
        
        elements.append(Paragraph("Energy Consumption Analysis", 
                                 self.styles["SectionHeader"]))
        elements.append(Spacer(1, 0.2*inch))
        
        # End-use breakdown visualization
        if "end_use_pie" in self.visualizations:
            elements.append(Paragraph("Annual Energy Breakdown by End-Use", 
                                     self.styles["SubSection"]))
            elements.append(self.visualizations["end_use_pie"])
            elements.append(Spacer(1, 0.3*inch))
        
        # End-use table
        if "end_use_breakdown" in self.extracted_data.get("energy_consumption", {}):
            breakdown = self.extracted_data["energy_consumption"]["end_use_breakdown"]
            total = sum(breakdown.values())
            
            table_data = [["End Use", "Consumption (kWh)", "Percentage"]]
            for category, value in sorted(breakdown.items(), 
                                         key=lambda x: x[1], reverse=True):
                if value > 0:
                    pct = (value / total * 100) if total > 0 else 0
                    table_data.append([
                        category.replace("_", " "),
                        f"{value:,.0f}",
                        f"{pct:.1f}%"
                    ])
            
            t = Table(table_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#3498DB")),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('PADDING', (0, 0), (-1, -1), 8)
            ]))
            elements.append(t)
        
        # Monthly bar chart
        if "monthly_bar" in self.visualizations:
            elements.append(Spacer(1, 0.3*inch))
            elements.append(Paragraph("Monthly Energy Consumption Pattern", 
                                     self.styles["SubSection"]))
            elements.append(self.visualizations["monthly_bar"])
        
        return elements
    
    def _create_peak_loads_section(self) -> List:
        """Create peak loads analysis section"""
        elements = []
        
        elements.append(Paragraph("Peak Load Analysis", self.styles["SectionHeader"]))
        elements.append(Spacer(1, 0.2*inch))
        
        peak_loads = self.extracted_data.get("peak_loads", {})
        
        # Peak loads table
        load_data = []
        if peak_loads.get("cooling_kbtu_h"):
            cooling_kbtu = peak_loads["cooling_kbtu_h"]
            cooling_tons = peak_loads.get("cooling_tons", cooling_kbtu * 0.293 / 3.517)
            load_data.append([
                "Peak Cooling Load",
                f"{cooling_kbtu:.2f} kBTU/h ({cooling_tons:.1f} tons)"
            ])
            if peak_loads.get("cooling_peak_time"):
                load_data.append([
                    "Cooling Peak Time",
                    peak_loads["cooling_peak_time"]
                ])
        
        if peak_loads.get("heating_kbtu_h"):
            load_data.append([
                "Peak Heating Load",
                f"{peak_loads['heating_kbtu_h']:.2f} kBTU/h"
            ])
            if peak_loads.get("heating_peak_time"):
                load_data.append([
                    "Heating Peak Time",
                    peak_loads["heating_peak_time"]
                ])
        
        if load_data:
            t = Table(load_data, colWidths=[3*inch, 3*inch])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#FEF5E7")),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 11),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('PADDING', (0, 0), (-1, -1), 12),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey)
            ]))
            elements.append(t)
        
        # Peak comparison chart
        if "peak_comparison" in self.visualizations:
            elements.append(Spacer(1, 0.3*inch))
            elements.append(Paragraph("Cooling vs Heating Peak Comparison", 
                                     self.styles["SubSection"]))
            elements.append(self.visualizations["peak_comparison"])
        
        return elements
    
    def _create_efficiency_section(self) -> List:
        """Create efficiency metrics section"""
        elements = []
        
        elements.append(Paragraph("Efficiency Metrics", self.styles["SectionHeader"]))
        elements.append(Spacer(1, 0.2*inch))
        
        efficiency = self.extracted_data.get("efficiency_metrics", {})
        
        # Metrics table
        metrics_data = []
        if efficiency.get("eui"):
            metrics_data.append([
                "Energy Use Intensity (EUI)",
                f"{efficiency['eui']:.2f} kWh/sqft/yr"
            ])
        if efficiency.get("avg_power_kw"):
            metrics_data.append([
                "Average Power Demand",
                f"{efficiency['avg_power_kw']:.2f} kW"
            ])
        if efficiency.get("load_factor"):
            metrics_data.append([
                "Load Factor",
                f"{efficiency['load_factor']:.2%}"
            ])
        if efficiency.get("cooling_to_heating_ratio"):
            metrics_data.append([
                "Cooling to Heating Ratio",
                f"{efficiency['cooling_to_heating_ratio']:.2f}"
            ])
        
        if metrics_data:
            t = Table(metrics_data, colWidths=[3.5*inch, 2.5*inch])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#E8F8F5")),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 11),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('PADDING', (0, 0), (-1, -1), 12),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey)
            ]))
            elements.append(t)
        
        # EUI benchmark chart
        if "eui_benchmark" in self.visualizations:
            elements.append(Spacer(1, 0.3*inch))
            elements.append(Paragraph("EUI Benchmark Comparison", 
                                     self.styles["SubSection"]))
            elements.append(self.visualizations["eui_benchmark"])
            elements.append(Spacer(1, 0.2*inch))
            
            # Interpretation
            eui = efficiency.get("eui", 0)
            if eui < 12:
                interpretation = "Excellent - Building performs significantly better than typical office buildings"
            elif eui < 18:
                interpretation = "Good - Building meets or exceeds efficiency standards"
            elif eui < 25:
                interpretation = "Average - Building performs at typical office building levels"
            else:
                interpretation = "Below Average - Significant opportunity for energy efficiency improvements"
            
            elements.append(Paragraph(f"<b>Performance Rating:</b> {interpretation}", 
                                     self.styles["Normal"]))
        
        return elements
    
    def _create_cost_section(self) -> List:
        """Create cost analysis section"""
        elements = []
        
        elements.append(Paragraph("Cost Analysis", self.styles["SectionHeader"]))
        elements.append(Spacer(1, 0.2*inch))
        
        cost = self.extracted_data.get("cost_analysis", {})
        
        # Cost table
        cost_data = []
        if cost.get("total_cost_usd"):
            cost_data.append([
                "Total Annual Energy Cost",
                f"${cost['total_cost_usd']:,.2f}"
            ])
        if cost.get("cost_per_sqft"):
            cost_data.append([
                "Cost per Square Foot",
                f"${cost['cost_per_sqft']:.2f}/sqft/yr"
            ])
        if cost.get("cost_per_kwh"):
            cost_data.append([
                "Average Cost per kWh",
                f"${cost['cost_per_kwh']:.4f}/kWh"
            ])
        
        # Calculate monthly cost if annual available
        if cost.get("total_cost_usd"):
            monthly_cost = cost["total_cost_usd"] / 12
            cost_data.append([
                "Average Monthly Cost",
                f"${monthly_cost:,.2f}"
            ])
        
        if cost_data:
            t = Table(cost_data, colWidths=[3.5*inch, 2.5*inch])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#FEF9E7")),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 11),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('PADDING', (0, 0), (-1, -1), 12),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey)
            ]))
            elements.append(t)
        
        return elements
    
    def _create_monthly_patterns(self) -> List:
        """Create monthly patterns analysis"""
        elements = []
        
        elements.append(Paragraph("Monthly Consumption Patterns", 
                                 self.styles["SectionHeader"]))
        elements.append(Spacer(1, 0.2*inch))
        
        patterns = self.extracted_data.get("monthly_patterns", {})
        
        # Patterns summary
        if patterns:
            summary_text = []
            if patterns.get("peak_month"):
                summary_text.append(f"<b>Peak Consumption Month:</b> {patterns['peak_month']}")
            if patterns.get("lowest_month"):
                summary_text.append(f"<b>Lowest Consumption Month:</b> {patterns['lowest_month']}")
            if patterns.get("seasonal_variation"):
                summary_text.append(f"<b>Seasonal Variation:</b> {patterns['seasonal_variation']:.1f}%")
            
            for text in summary_text:
                elements.append(Paragraph(text, self.styles["Normal"]))
                elements.append(Spacer(1, 0.1*inch))
        
        # Monthly stacked chart
        if "monthly_stacked" in self.visualizations:
            elements.append(Spacer(1, 0.2*inch))
            elements.append(Paragraph("Monthly Energy Breakdown by Category", 
                                     self.styles["SubSection"]))
            elements.append(self.visualizations["monthly_stacked"])
        
        return elements
    
    def _create_recommendations(self) -> List:
        """Create recommendations section"""
        elements = []
        
        elements.append(Paragraph("Recommendations", self.styles["SectionHeader"]))
        elements.append(Spacer(1, 0.2*inch))
        
        recommendations = self.extracted_data.get("recommendations", [])
        
        if recommendations:
            for i, rec in enumerate(recommendations, 1):
                elements.append(Paragraph(f"<b>{i}.</b> {rec}", 
                                         self.styles["Normal"]))
                elements.append(Spacer(1, 0.15*inch))
        else:
            # Generate basic recommendations based on data
            elements.append(Paragraph(
                "Based on the analysis, consider the following energy efficiency improvements:",
                self.styles["Normal"]
            ))
            elements.append(Spacer(1, 0.2*inch))
            
            basic_recs = [
                "Conduct detailed energy audit to identify specific saving opportunities",
                "Review HVAC system performance and maintenance schedules",
                "Evaluate lighting system efficiency and upgrade to LED where applicable",
                "Consider implementing building automation systems for optimized operations",
                "Assess building envelope performance and identify air sealing opportunities"
            ]
            
            for i, rec in enumerate(basic_recs, 1):
                elements.append(Paragraph(f"<b>{i}.</b> {rec}", 
                                         self.styles["Normal"]))
                elements.append(Spacer(1, 0.15*inch))
        
        return elements


# Integration function for Streamlit app
def generate_llm_enhanced_report(building_data: Dict[str, Any], 
                                 vector_store=None,
                                 api_key: str = None) -> tuple:
    """
    Generate comprehensive JSON and PDF reports using LLM
    
    Returns:
        tuple: (json_string, pdf_buffer)
    """
    
    # Create enhanced generator
    generator = EnhancedPDFReportGenerator(building_data, api_key)
    
    # Generate JSON
    json_data = generator.create_comprehensive_json()
    
    # Generate PDF
    pdf_buffer = generator.generate_pdf()
    
    return json_data, pdf_buffer


# Example usage function
def example_usage():
    """Example of how to use the enhanced PDF generator"""
    
    # Sample building data
    building_data = {
        "metadata": {
            "project_name": "Sample Office Building",
            "weather_file": "USA_CA_San.Francisco.724940",
            "simulation_date": "10/10/2024"
        },
        "bepu": {
            "floor_area_sqft": 50000,
            "volume_cuft": 500000,
            "total_electricity_kwh": 750000,
            "total_gas_therm": 15000,
            "eui_kwh_sqft_yr": 15.0
        },
        "ls_c": {
            "cooling_load_kbtu_h": 1500,
            "heating_load_kbtu_h": 800,
            "cooling_peak_time": "3:00PM Jul 15",
            "heating_peak_time": "7:00AM Jan 10"
        },
        "ps_e_electric": pd.DataFrame({
            "Month": ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", 
                     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "ANNUAL"],
            "Cooling": [1000, 1200, 2000, 3500, 5000, 7000,
                       8000, 7500, 5500, 3000, 1500, 1000, 45200],
            "Heating": [5000, 4500, 3500, 2000, 500, 0,
                       0, 0, 500, 2000, 3500, 4800, 26300],
            "Lights": [8000, 7500, 8200, 8000, 8300, 8100,
                      8200, 8100, 8000, 8200, 8000, 8300, 97900],
            "Equipment": [10000, 9500, 10200, 10000, 10300, 10100,
                         10200, 10100, 10000, 10200, 10000, 10300, 120900],
            "Vent_Fans": [3000, 2800, 3100, 3000, 3200, 3100,
                         3200, 3100, 3000, 3100, 3000, 3200, 37800],
            "Pumps_Aux": [1500, 1400, 1550, 1500, 1600, 1550,
                         1600, 1550, 1500, 1550, 1500, 1600, 18900],
            "Hot_Water": [2000, 1800, 1900, 1800, 1700, 1600,
                         1500, 1500, 1600, 1800, 1900, 2000, 21100],
            "Total": [30500, 28700, 30450, 29800, 30600, 31450,
                     32700, 31850, 30100, 29850, 29400, 31200, 366600]
        }),
        "es_d": {
            "cost_per_sqft": 2.45
        }
    }
    
    # Generate reports (with or without API key)
    json_data, pdf_buffer = generate_llm_enhanced_report(
        building_data, 
        api_key="your-api-key-here"  # Optional
    )
    
    # Save JSON
    with open("comprehensive_report.json", "w") as f:
        f.write(json_data)
    
    # Save PDF
    with open("comprehensive_report.pdf", "wb") as f:
        f.write(pdf_buffer.read())
    
    print("Reports generated successfully!")


if __name__ == "__main__":
    example_usage()