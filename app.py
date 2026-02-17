"""
eQuest RAG v3.0 - 100x Production Backend
Flask API for eQuest energy modeling analysis with RAG, diagnostics,
benchmarking, carbon/ESG, scenario simulation, portfolio analytics,
financial modeling, and executive AI intelligence.
"""

import os
import io
import re
import json
import uuid
import hashlib
import logging
import threading
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, asdict
from functools import wraps
from collections import deque

import pandas as pd
import numpy as np
from flask import Flask, request, jsonify, send_file, g
from flask_cors import CORS
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("equestrag")

# ---------------------------------------------------------------------------
# Optional dependency imports
# ---------------------------------------------------------------------------
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    import faiss
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False

try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

try:
    from llm_pdf_generator import generate_llm_enhanced_report
    ENHANCED_PDF_AVAILABLE = True
except ImportError:
    ENHANCED_PDF_AVAILABLE = False

# ---------------------------------------------------------------------------
# Engine module imports (new v3.0 modules)
# ---------------------------------------------------------------------------
try:
    from equest_parser import eQuestParserV2, UnitNormalizer, ParseResult
    PARSER_V2_AVAILABLE = True
except ImportError:
    PARSER_V2_AVAILABLE = False

try:
    from external_inputs import InpFileParser, EpwFileParser, UtilityBillParser, IntervalDataParser
    EXTERNAL_INPUTS_AVAILABLE = True
except ImportError:
    EXTERNAL_INPUTS_AVAILABLE = False

try:
    from data_quality import DataQualityEngine
    DATA_QUALITY_AVAILABLE = True
except ImportError:
    DATA_QUALITY_AVAILABLE = False

try:
    from engineering_metrics import EngineeringMetricsEngine
    ENGINEERING_METRICS_AVAILABLE = True
except ImportError:
    ENGINEERING_METRICS_AVAILABLE = False

try:
    from diagnostics import DiagnosticsEngine
    DIAGNOSTICS_AVAILABLE = True
except ImportError:
    DIAGNOSTICS_AVAILABLE = False

try:
    from benchmarking import BenchmarkingEngine
    BENCHMARKING_AVAILABLE = True
except ImportError:
    BENCHMARKING_AVAILABLE = False

try:
    from carbon_esg import CarbonESGEngine
    CARBON_ESG_AVAILABLE = True
except ImportError:
    CARBON_ESG_AVAILABLE = False

try:
    from scenario_simulation import ScenarioSimulationEngine
    SIMULATION_AVAILABLE = True
except ImportError:
    SIMULATION_AVAILABLE = False

try:
    from portfolio import PortfolioAnalyticsEngine
    PORTFOLIO_AVAILABLE = True
except ImportError:
    PORTFOLIO_AVAILABLE = False

try:
    from financial_model import FinancialModelingEngine
    FINANCIAL_AVAILABLE = True
except ImportError:
    FINANCIAL_AVAILABLE = False

try:
    from executive_ai import ExecutiveAIEngine
    EXECUTIVE_AI_AVAILABLE = True
except ImportError:
    EXECUTIVE_AI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_FILE_SIZE = 50 * 1024 * 1024
MAX_REQUEST_SIZE = 200 * 1024 * 1024
SESSION_TTL = timedelta(hours=4)
ALLOWED_EXTENSIONS = {".txt", ".pdf", ".csv", ".xlsx", ".inp", ".epw"}
ALLOWED_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000,https://equest-rag.vercel.app"
).split(",")
ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS]
DB_PATH = os.environ.get("EQUEST_DB_PATH", "equest_rag.db")

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DocumentChunk:
    text: str
    metadata: Dict[str, Any]
    chunk_id: str
    embedding: np.ndarray = None

    def to_dict(self):
        return {
            "text": self.text,
            "metadata": self.metadata,
            "chunk_id": self.chunk_id,
        }


# ---------------------------------------------------------------------------
# Legacy eQuest Parser (kept for backward compatibility)
# ---------------------------------------------------------------------------
class eQuestParser:
    """Parses eQuest simulation output files into structured data."""

    @staticmethod
    def extract_metadata(content: str) -> Dict[str, str]:
        metadata = {}
        lines = content.split("\n")
        for line in lines:
            if "WEATHER FILE" in line:
                match = re.search(r"WEATHER FILE-\s*(.+)", line)
                if match:
                    metadata["weather_file"] = match.group(1).strip()
            if "Project" in line:
                parts = line.split()
                if len(parts) > 0:
                    metadata["project_name"] = parts[0]
            if re.search(r"\d{2}/\d{2}/\d{4}", line):
                match = re.search(r"(\d{2}/\d{2}/\d{4})", line)
                if match:
                    metadata["simulation_date"] = match.group(1)
        return metadata

    @staticmethod
    def parse_ps_e(content: str) -> pd.DataFrame:
        lines = content.split("\n")
        data = []
        months = [
            "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
            "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
        ]
        current_month = None

        for line in lines:
            line = line.strip()
            if any(month in line for month in months):
                for month in months:
                    if line.startswith(month):
                        current_month = month
                        break

            if current_month and ("MBTU" in line or "KWH" in line or "THERM" in line):
                parts = line.split()
                if len(parts) > 12 and parts[0] in ["MBTU", "KWH", "THERM"]:
                    try:
                        def safe_float(val):
                            return 0.0 if val == "." else float(val)

                        row = {
                            "Month": current_month,
                            "Unit": parts[0],
                            "Lights": safe_float(parts[1]),
                            "Equipment": safe_float(parts[3]),
                            "Heating": safe_float(parts[4]),
                            "Cooling": safe_float(parts[5]),
                            "Vent_Fans": safe_float(parts[8]),
                            "Hot_Water": safe_float(parts[11]),
                            "Total": safe_float(parts[13]),
                        }
                        data.append(row)
                        current_month = None
                    except (ValueError, IndexError):
                        continue

        if data:
            totals = {
                "Month": "ANNUAL",
                "Unit": data[0]["Unit"],
                "Lights": sum(d["Lights"] for d in data),
                "Equipment": sum(d["Equipment"] for d in data),
                "Heating": sum(d["Heating"] for d in data),
                "Cooling": sum(d["Cooling"] for d in data),
                "Vent_Fans": sum(d["Vent_Fans"] for d in data),
                "Hot_Water": sum(d["Hot_Water"] for d in data),
                "Total": sum(d["Total"] for d in data),
            }
            data.append(totals)

        return pd.DataFrame(data) if data else pd.DataFrame()

    @staticmethod
    def parse_bepu(content: str) -> Dict[str, Any]:
        result = {}
        lines = content.split("\n")
        for line in lines:
            if "FLOOR AREA" in line:
                match = re.search(r"(\d+)\s+SQFT", line)
                if match:
                    result["floor_area_sqft"] = int(match.group(1))
            if "TOTAL ELECTRICITY" in line:
                match = re.search(r"(\d+\.?\d*)\s+KWH", line)
                if match:
                    result["total_electricity_kwh"] = float(match.group(1))
            if "KWH /SQFT-YR" in line:
                match = re.search(r"(\d+\.?\d*)\s+KWH\s+/SQFT-YR", line)
                if match:
                    result["eui_kwh_sqft_yr"] = float(match.group(1))
            if "TOTAL GAS" in line:
                match = re.search(r"(\d+\.?\d*)\s+THERM", line)
                if match:
                    result["total_gas_therm"] = float(match.group(1))
        return result

    @staticmethod
    def parse_ls_c(content: str) -> Dict[str, Any]:
        result = {}
        lines = content.split("\n")
        in_cooling = False
        in_heating = False
        for line in lines:
            if "COOLING LOAD" in line:
                in_cooling = True
                in_heating = False
            if "HEATING LOAD" in line:
                in_heating = True
                in_cooling = False
            if "TOTAL LOAD" in line:
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        val = float(parts[2])
                        if in_cooling:
                            result["cooling_load_kbtu_h"] = val
                        elif in_heating:
                            result["heating_load_kbtu_h"] = val
                    except (ValueError, IndexError):
                        pass
        if "cooling_load_kbtu_h" in result:
            result["cooling_tons"] = round(
                result["cooling_load_kbtu_h"] * 0.293 / 3.517, 1
            )
        return result

    @staticmethod
    def parse_es_d(content: str) -> Dict[str, float]:
        result = {}
        lines = content.split("\n")
        for line in lines:
            if "ENERGY COST/GROSS BLDG AREA:" in line:
                parts = line.split(":")
                if len(parts) > 1:
                    try:
                        result["cost_per_sqft"] = float(parts[1].strip())
                    except ValueError:
                        pass
            if "TOTAL" in line and "$" in line:
                match = re.search(r"\$\s*([\d,]+\.?\d*)", line)
                if match:
                    try:
                        result["total_cost"] = float(match.group(1).replace(",", ""))
                    except ValueError:
                        pass
        return result

    @staticmethod
    def parse_lv_d(content: str) -> Dict[str, Any]:
        result = {"surfaces": [], "summary": {}}
        lines = content.split("\n")
        for line in lines:
            if "U-VALUE" in line or "R-VALUE" in line:
                result["summary"]["has_envelope_data"] = True
        return result


# ---------------------------------------------------------------------------
# Enhanced Vector Store (Upgraded RAG Architecture)
# ---------------------------------------------------------------------------
class EnhancedVectorStore:
    """Multi-vector store with hybrid search (keyword + embeddings)."""

    def __init__(self, embedding_model_name: str = "all-MiniLM-L6-v2"):
        self.chunks: List[DocumentChunk] = []
        self.structured_data_chunks: List[DocumentChunk] = []
        self.index = None
        self.embedding_dim = 384

        if EMBEDDINGS_AVAILABLE:
            try:
                self.model = SentenceTransformer(embedding_model_name)
                self.embedding_dim = self.model.get_sentence_embedding_dimension()
                self.index = faiss.IndexFlatL2(self.embedding_dim)
                self.use_embeddings = True
            except Exception:
                self.use_embeddings = False
                self.model = None
        else:
            self.use_embeddings = False
            self.model = None

    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size - overlap):
            chunk = " ".join(words[i: i + chunk_size])
            if len(chunk.strip()) > 50:
                chunks.append(chunk)
        return chunks

    def add_document(self, text: str, metadata: Dict[str, Any], chunk_size: int = 500):
        text_chunks = self.chunk_text(text, chunk_size)

        for i, chunk_text in enumerate(text_chunks):
            chunk_id = hashlib.md5(f"{chunk_text}{i}".encode()).hexdigest()
            chunk_metadata = metadata.copy()
            chunk_metadata["chunk_index"] = i
            chunk_metadata["total_chunks"] = len(text_chunks)

            if self.use_embeddings and self.model:
                embedding = self.model.encode(chunk_text, convert_to_numpy=True)
                self.index.add(np.array([embedding], dtype=np.float32))
            else:
                embedding = self._create_simple_embedding(chunk_text)

            chunk = DocumentChunk(
                text=chunk_text,
                metadata=chunk_metadata,
                chunk_id=chunk_id,
                embedding=embedding,
            )
            self.chunks.append(chunk)

    def add_structured_data(self, data: Dict[str, Any], source: str = "analysis"):
        """Add structured JSON data as searchable chunks (v3.0 multi-vector)."""
        text = json.dumps(data, indent=2, default=str)
        chunk_id = hashlib.md5(text[:500].encode()).hexdigest()
        metadata = {"type": "structured", "source": source}

        if self.use_embeddings and self.model:
            summary = self._summarize_structured(data)
            embedding = self.model.encode(summary, convert_to_numpy=True)
            self.index.add(np.array([embedding], dtype=np.float32))
        else:
            embedding = self._create_simple_embedding(text)

        chunk = DocumentChunk(
            text=text[:2000],
            metadata=metadata,
            chunk_id=chunk_id,
            embedding=embedding,
        )
        self.chunks.append(chunk)
        self.structured_data_chunks.append(chunk)

    def _summarize_structured(self, data: Dict[str, Any]) -> str:
        """Create a text summary of structured data for embedding."""
        parts = []
        for key, value in data.items():
            if isinstance(value, dict):
                for k, v in value.items():
                    parts.append(f"{key} {k}: {v}")
            elif isinstance(value, (int, float)):
                parts.append(f"{key}: {value}")
            elif isinstance(value, str):
                parts.append(f"{key}: {value}")
        return " ".join(parts[:100])

    def _create_simple_embedding(self, text: str) -> np.ndarray:
        text_lower = text.lower()
        features = {
            "energy": ["energy", "consumption", "kwh", "electricity", "eui"],
            "cooling": ["cooling", "chiller", "refrigeration", "tons"],
            "heating": ["heating", "boiler", "furnace", "gas"],
            "lighting": ["lighting", "lights", "illumination", "led"],
            "cost": ["cost", "price", "dollar", "expense", "rate"],
            "load": ["load", "peak", "demand", "capacity"],
            "carbon": ["carbon", "co2", "emissions", "esg", "greenhouse"],
            "envelope": ["envelope", "wall", "roof", "window", "insulation"],
            "benchmark": ["benchmark", "ashrae", "compliance", "code", "standard"],
            "simulation": ["simulation", "scenario", "retrofit", "payback", "roi"],
        }
        vec = []
        for keywords in features.values():
            score = sum(1 for kw in keywords if kw in text_lower)
            vec.append(score)
        total = sum(vec) if sum(vec) > 0 else 1
        vec = [v / total for v in vec]
        return np.array(vec, dtype=np.float32)

    def search(self, query: str, top_k: int = 5) -> List[Tuple[DocumentChunk, float]]:
        """Hybrid search: combines embedding similarity with keyword matching."""
        embedding_results = self._search_embeddings(query, top_k * 2)
        keyword_results = self._search_keywords(query, top_k)

        # Merge and deduplicate
        seen = set()
        merged = []
        for chunk, score in embedding_results + keyword_results:
            if chunk.chunk_id not in seen:
                seen.add(chunk.chunk_id)
                merged.append((chunk, score))

        # Sort by score
        merged.sort(key=lambda x: x[1], reverse=True)
        return merged[:top_k]

    def _search_embeddings(self, query: str, top_k: int) -> List[Tuple[DocumentChunk, float]]:
        if self.use_embeddings and self.model and self.index and self.index.ntotal > 0:
            query_embedding = self.model.encode(query, convert_to_numpy=True)
            query_embedding = np.array([query_embedding], dtype=np.float32)
            distances, indices = self.index.search(
                query_embedding, min(top_k, self.index.ntotal)
            )
            results = []
            for dist, idx in zip(distances[0], indices[0]):
                if idx < len(self.chunks):
                    similarity = 1 / (1 + dist)
                    results.append((self.chunks[idx], similarity))
            return results
        else:
            query_emb = self._create_simple_embedding(query)
            scores = []
            for chunk in self.chunks:
                if chunk.embedding is not None:
                    cosine_sim = np.dot(query_emb, chunk.embedding) / (
                        np.linalg.norm(query_emb) * np.linalg.norm(chunk.embedding) + 1e-10
                    )
                else:
                    cosine_sim = 0
                scores.append((chunk, float(cosine_sim)))
            scores.sort(key=lambda x: x[1], reverse=True)
            return scores[:top_k]

    def _search_keywords(self, query: str, top_k: int) -> List[Tuple[DocumentChunk, float]]:
        """Keyword-based search for hybrid retrieval."""
        query_terms = set(query.lower().split())
        scores = []
        for chunk in self.chunks:
            text_lower = chunk.text.lower()
            matches = sum(1 for term in query_terms if term in text_lower)
            if matches > 0:
                score = matches / len(query_terms) if query_terms else 0
                scores.append((chunk, score * 0.5))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# ---------------------------------------------------------------------------
# Document Processor (extended with .inp, .epw, .csv support)
# ---------------------------------------------------------------------------
class DocumentProcessor:
    """Extracts text from uploaded files."""
    ALLOWED_EXTENSIONS = {".txt", ".pdf", ".csv", ".xlsx", ".inp", ".epw"}

    @staticmethod
    def validate_file(file) -> Tuple[bool, str]:
        if not file or not file.filename:
            return False, "No file provided"
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in DocumentProcessor.ALLOWED_EXTENSIONS:
            return False, f"Unsupported file type: {ext}"
        return True, ""

    @staticmethod
    def extract_text_from_pdf(file) -> str:
        if not PDF_AVAILABLE:
            return "PDF processing not available."
        try:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            logger.warning("PDF extraction error: %s", e)
            return ""

    @staticmethod
    def extract_text_from_txt(file) -> str:
        try:
            return file.read().decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning("TXT extraction error: %s", e)
            return ""

    @staticmethod
    def process_file(file) -> Tuple[str, str]:
        filename = file.filename.lower()
        if filename.endswith(".pdf"):
            return DocumentProcessor.extract_text_from_pdf(file), "pdf"
        elif filename.endswith((".txt", ".inp", ".epw")):
            return DocumentProcessor.extract_text_from_txt(file), "txt"
        elif filename.endswith(".csv"):
            return DocumentProcessor.extract_text_from_txt(file), "csv"
        else:
            return "", "unknown"


# ---------------------------------------------------------------------------
# AI Agent (upgraded with structured context injection)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert energy modeling analyst specializing in eQuest building energy simulation software. You have deep knowledge of:

- Building energy performance metrics (EUI, peak loads, consumption patterns)
- HVAC systems, building envelopes, and mechanical systems
- Energy codes and standards (ASHRAE 90.1, Title 24, IECC)
- eQuest report types (PS-E, BEPU, LS-C, ES-D, LV-D, SS-P, LS-B, SV-A, SV-B)
- Energy cost analysis and utility rate structures
- Building commissioning and retro-commissioning
- Carbon emissions and ESG scoring
- Financial analysis for energy retrofits (payback, NPV, IRR)
- Building diagnostics and anomaly detection
- Benchmarking against CBECS and ASHRAE standards

When answering questions:
1. Reference specific data from the provided context
2. Use proper engineering units and terminology
3. Provide actionable insights when possible
4. Compare values against industry benchmarks when relevant
5. Be precise with numbers - use the exact values from the data
6. Include root-cause analysis when discussing issues
7. Recommend specific improvement measures with expected savings

If the data doesn't contain information to answer the question, say so clearly."""


class AIAgent:
    """RAG-powered AI agent with structured JSON context injection."""

    def __init__(self, vector_store: EnhancedVectorStore, api_key: str = None):
        self.vector_store = vector_store
        self.api_key = api_key
        self.client = None

        if api_key and OPENAI_AVAILABLE:
            try:
                self.client = OpenAI(api_key=api_key)
            except Exception:
                pass

    def query(self, user_query: str, building_data: Dict[str, Any],
              executive_context: str = "") -> Dict[str, Any]:
        relevant_docs = self.vector_store.search(user_query, top_k=5)
        context = self._build_context(relevant_docs, building_data, executive_context)

        if self.client:
            response = self._query_openai(user_query, context)
        else:
            response = self._query_local(user_query, building_data)

        sources = list({
            chunk.metadata.get("filename", "Unknown")
            for chunk, _ in relevant_docs[:3]
        })

        return {"response": response, "sources": sources}

    def _build_context(self, docs, building_data, executive_context=""):
        parts = []

        # Structured JSON context injection (v3.0)
        if executive_context:
            parts.append(executive_context)
            parts.append("")

        # Building data summary
        if building_data:
            parts.append("=== BUILDING DATA SUMMARY ===")
            for section in ("bepu", "ls_c", "es_d"):
                data = building_data.get(section, {})
                if isinstance(data, dict):
                    for k, v in data.items():
                        if not isinstance(v, (list, dict)):
                            parts.append(f"  {k}: {v}")
            parts.append("")

        # Relevant document chunks
        parts.append("=== RELEVANT DOCUMENT EXCERPTS ===")
        for chunk, score in docs:
            if score > 0.05:
                source = chunk.metadata.get("filename", "unknown")
                doc_type = chunk.metadata.get("type", "document")
                parts.append(
                    f"[{doc_type} - {source}] (relevance: {score:.2f})\n{chunk.text[:600]}"
                )
                parts.append("")

        return "\n".join(parts)

    def _query_openai(self, query, context):
        try:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Building Data Context:\n{context}\n\nUser Question: {query}"},
            ]
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=2000,
                temperature=0.3,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("OpenAI query error: %s", e)
            return "Unable to process your query with AI. Please check your API key and try again."

    def _query_local(self, query, building_data):
        query_lower = query.lower()
        parts = []

        if "eui" in query_lower and "bepu" in building_data:
            bepu = building_data["bepu"]
            if isinstance(bepu, dict):
                eui = bepu.get("eui_kwh_sqft_yr", "N/A")
                area = bepu.get("floor_area_sqft", "N/A")
                parts.append(f"Building EUI: {eui} kWh/sqft/year")
                parts.append(f"Floor Area: {area:,} sqft" if isinstance(area, (int, float)) else f"Floor Area: {area}")

        if any(w in query_lower for w in ["cool", "load", "peak"]) and "ls_c" in building_data:
            ls_c = building_data["ls_c"]
            if isinstance(ls_c, dict):
                cool = ls_c.get("cooling_load_kbtu_h", "N/A")
                tons = ls_c.get("cooling_tons", "N/A")
                parts.append(f"Peak Cooling Load: {cool} kBTU/h ({tons} tons)")
                heat = ls_c.get("heating_load_kbtu_h")
                if heat:
                    parts.append(f"Peak Heating Load: {heat} kBTU/h")

        if any(w in query_lower for w in ["cost", "price", "dollar"]) and "es_d" in building_data:
            es_d = building_data["es_d"]
            if isinstance(es_d, dict):
                cost = es_d.get("cost_per_sqft", "N/A")
                parts.append(f"Energy Cost: ${cost}/sqft/year")

        if any(w in query_lower for w in ["energy", "consumption", "electric"]) and "bepu" in building_data:
            bepu = building_data["bepu"]
            if isinstance(bepu, dict):
                kwh = bepu.get("total_electricity_kwh", "N/A")
                parts.append(f"Total Electricity: {kwh:,.0f} kWh" if isinstance(kwh, (int, float)) else f"Total Electricity: {kwh}")

        if any(w in query_lower for w in ["carbon", "co2", "emission", "esg"]):
            parts.append("Carbon and ESG analysis is available. Use the /carbon endpoint or the Carbon tab for detailed emissions data.")

        if any(w in query_lower for w in ["benchmark", "compare", "ashrae", "code"]):
            parts.append("Benchmarking is available. Use the /benchmark endpoint or Benchmarking tab for code compliance analysis.")

        if any(w in query_lower for w in ["simulat", "scenario", "retrofit", "payback"]):
            parts.append("Scenario simulation is available. Use the /simulate endpoint or Scenarios tab for retrofit analysis.")

        if parts:
            return "\n".join(parts)

        # Generic fallback
        available = []
        if "bepu" in building_data:
            available.append("building performance (BEPU)")
        if "ps_e" in building_data:
            available.append("monthly energy consumption (PS-E)")
        if "ls_c" in building_data:
            available.append("peak loads (LS-C)")
        if "es_d" in building_data:
            available.append("energy costs (ES-D)")

        if available:
            return (
                f"I have data from: {', '.join(available)}. "
                "Try asking about EUI, peak loads, energy consumption, costs, "
                "carbon emissions, benchmarking, or retrofit scenarios. "
                "For enhanced AI responses, add your OpenAI API key."
            )
        return "No building data available. Please upload and process eQuest files first."


# ---------------------------------------------------------------------------
# Enterprise Session Management (DB-backed with audit logging)
# ---------------------------------------------------------------------------
_sessions: Dict[str, Dict] = {}
_sessions_lock = threading.Lock()
_audit_log: deque = deque(maxlen=10000)


def _init_db():
    """Initialize SQLite database for persistent storage."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT,
                building_data TEXT,
                metrics TEXT,
                created_at TEXT,
                updated_at TEXT,
                version INTEGER DEFAULT 1
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                action TEXT,
                details TEXT,
                timestamp TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS file_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT,
                filename TEXT,
                file_type TEXT,
                version INTEGER DEFAULT 1,
                uploaded_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            )
        """)
        conn.commit()
        conn.close()
        logger.info("Database initialized at %s", DB_PATH)
    except Exception as e:
        logger.warning("Database init failed (using in-memory): %s", e)


def _log_audit(session_id: str, action: str, details: str = ""):
    """Log an audit event."""
    entry = {
        "session_id": session_id[:8] if session_id else "system",
        "action": action,
        "details": details,
        "timestamp": datetime.now().isoformat(),
    }
    _audit_log.append(entry)
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO audit_log (session_id, action, details, timestamp) VALUES (?, ?, ?, ?)",
            (entry["session_id"], action, details, entry["timestamp"])
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _cleanup_sessions():
    """Remove expired sessions."""
    now = datetime.now()
    with _sessions_lock:
        expired = [
            sid for sid, data in _sessions.items()
            if now - data["created_at"] > SESSION_TTL
        ]
        for sid in expired:
            del _sessions[sid]
            logger.info("Cleaned up expired session %s", sid[:8])


def get_session(session_id: str) -> Optional[Dict]:
    """Retrieve session data if valid."""
    _cleanup_sessions()
    with _sessions_lock:
        session = _sessions.get(session_id)
        if session and datetime.now() - session["created_at"] < SESSION_TTL:
            session["last_access"] = datetime.now()
            return session
    return None


def create_session() -> str:
    """Create a new user session with isolated storage."""
    session_id = str(uuid.uuid4())
    with _sessions_lock:
        _sessions[session_id] = {
            "vector_store": EnhancedVectorStore(),
            "building_data": {},
            "analysis_cache": {},
            "created_at": datetime.now(),
            "last_access": datetime.now(),
        }
    _log_audit(session_id, "session_created")
    logger.info("Created session %s", session_id[:8])
    return session_id


def require_session(f):
    """Decorator that injects session into the route handler."""
    @wraps(f)
    def decorated(*args, **kwargs):
        session_id = request.headers.get("X-Session-ID")
        if not session_id:
            return jsonify({"success": False, "error": "Missing session. Please process files first."}), 400
        session = get_session(session_id)
        if not session:
            return jsonify({"success": False, "error": "Session expired. Please re-upload your files."}), 410
        return f(session=session, session_id=session_id, *args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Metrics Computation (delegates to EngineeringMetricsEngine when available)
# ---------------------------------------------------------------------------
def compute_metrics(building_data: Dict[str, Any]) -> Dict[str, Any]:
    """Compute comprehensive metrics from parsed building data."""
    if ENGINEERING_METRICS_AVAILABLE:
        engine = EngineeringMetricsEngine()
        return engine.compute(building_data)

    # Fallback legacy metrics
    metrics = {}
    if "bepu" in building_data:
        bepu = building_data["bepu"]
        if isinstance(bepu, dict):
            if "eui_kwh_sqft_yr" in bepu:
                metrics["eui"] = bepu["eui_kwh_sqft_yr"]
            if "total_electricity_kwh" in bepu:
                metrics["total_kwh"] = bepu["total_electricity_kwh"]
                metrics["avg_power_kw"] = round(bepu["total_electricity_kwh"] / 8760, 2)
            if "floor_area_sqft" in bepu:
                metrics["floor_area_sqft"] = bepu["floor_area_sqft"]
            if "total_gas_therm" in bepu:
                metrics["total_gas_therm"] = bepu["total_gas_therm"]

    if "ls_c" in building_data:
        ls_c = building_data["ls_c"]
        if isinstance(ls_c, dict):
            if "cooling_load_kbtu_h" in ls_c:
                metrics["peak_cooling_kbtu_h"] = ls_c["cooling_load_kbtu_h"]
                metrics["peak_cooling_tons"] = ls_c.get("cooling_tons", round(ls_c["cooling_load_kbtu_h"] * 0.293 / 3.517, 1))
            if "heating_load_kbtu_h" in ls_c:
                metrics["peak_heating_kbtu_h"] = ls_c["heating_load_kbtu_h"]

    if "es_d" in building_data:
        es_d = building_data["es_d"]
        if isinstance(es_d, dict):
            if "cost_per_sqft" in es_d:
                metrics["cost_per_sqft"] = es_d["cost_per_sqft"]
            if "total_cost" in es_d:
                metrics["total_annual_cost"] = es_d["total_cost"]

    if "cost_per_sqft" in metrics and "floor_area_sqft" in metrics and "total_annual_cost" not in metrics:
        metrics["total_annual_cost"] = round(metrics["cost_per_sqft"] * metrics["floor_area_sqft"], 2)

    return metrics


# ---------------------------------------------------------------------------
# Flask Application
# ---------------------------------------------------------------------------
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_SIZE

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Initialize database
_init_db()


# ---------------------------------------------------------------------------
# Routes: Core (backward-compatible)
# ---------------------------------------------------------------------------

@app.route("/api/process", methods=["POST"])
def process_files():
    """Upload and parse eQuest files. Creates or reuses a session."""
    try:
        session_id = request.headers.get("X-Session-ID")
        if session_id:
            session = get_session(session_id)
        else:
            session = None

        if not session:
            session_id = create_session()
            session = get_session(session_id)

        session["vector_store"] = EnhancedVectorStore()
        session["building_data"] = {}
        session["analysis_cache"] = {}

        vector_store = session["vector_store"]
        building_data = session["building_data"]

        api_key = request.form.get("api_key", "")
        parser = eQuestParser()
        parser_v2 = eQuestParserV2() if PARSER_V2_AVAILABLE else None
        doc_processor = DocumentProcessor()

        file_keys = ["ps_e", "ps_e2", "bepu", "ls_c", "es_d", "lv_d",
                      "ss_p", "ls_b", "sv_a", "sv_b", "hourly",
                      "inp_file", "epw_file", "utility_bills", "interval_data"]
        files_processed = []

        for key in file_keys:
            if key not in request.files:
                continue
            file = request.files[key]
            valid, err = doc_processor.validate_file(file)
            if not valid:
                continue

            content, file_type = doc_processor.process_file(file)
            if not content or len(content) < 10:
                continue

            # Extract metadata from first file
            if "metadata" not in building_data:
                if parser_v2:
                    building_data["metadata"] = parser_v2.extract_metadata(content)
                else:
                    building_data["metadata"] = parser.extract_metadata(content)

            # Parse by report type (v2 parser for new types, legacy for existing)
            if key in ("ps_e", "ps_e2"):
                if parser_v2:
                    result = parser_v2.parse(content, "PS-E")
                    ps_data = result.data.get("ps_e", [])
                    if ps_data:
                        building_data[key] = ps_data
                    else:
                        df = parser.parse_ps_e(content)
                        if not df.empty:
                            building_data[key] = df.to_dict("records")
                else:
                    df = parser.parse_ps_e(content)
                    if not df.empty:
                        building_data[key] = df.to_dict("records")

                if building_data.get(key):
                    vector_store.add_document(content, {"type": key, "filename": file.filename})
                    files_processed.append(key)

            elif key == "bepu":
                if parser_v2:
                    result = parser_v2.parse(content, "BEPU")
                    bepu_data = result.data if result.data else parser.parse_bepu(content)
                else:
                    bepu_data = parser.parse_bepu(content)
                if bepu_data:
                    building_data["bepu"] = bepu_data
                    vector_store.add_document(content, {"type": "bepu", "filename": file.filename})
                    files_processed.append("bepu")

            elif key == "ls_c":
                if parser_v2:
                    result = parser_v2.parse(content, "LS-C")
                    ls_c_data = result.data if result.data else parser.parse_ls_c(content)
                else:
                    ls_c_data = parser.parse_ls_c(content)
                if ls_c_data:
                    building_data["ls_c"] = ls_c_data
                    vector_store.add_document(content, {"type": "ls_c", "filename": file.filename})
                    files_processed.append("ls_c")

            elif key == "es_d":
                if parser_v2:
                    result = parser_v2.parse(content, "ES-D")
                    es_d_data = result.data if result.data else parser.parse_es_d(content)
                else:
                    es_d_data = parser.parse_es_d(content)
                if es_d_data:
                    building_data["es_d"] = es_d_data
                    vector_store.add_document(content, {"type": "es_d", "filename": file.filename})
                    files_processed.append("es_d")

            elif key == "lv_d":
                if parser_v2:
                    result = parser_v2.parse(content, "LV-D")
                    lv_d_data = result.data if result.data else parser.parse_lv_d(content)
                else:
                    lv_d_data = parser.parse_lv_d(content)
                if lv_d_data:
                    building_data["lv_d"] = lv_d_data
                    vector_store.add_document(content, {"type": "lv_d", "filename": file.filename})
                    files_processed.append("lv_d")

            # New v3.0 report types
            elif key in ("ss_p", "ls_b", "sv_a", "sv_b", "hourly") and parser_v2:
                type_map = {"ss_p": "SS-P", "ls_b": "LS-B", "sv_a": "SV-A", "sv_b": "SV-B", "hourly": "HOURLY"}
                result = parser_v2.parse(content, type_map[key])
                if result.data:
                    building_data[key] = result.data
                    vector_store.add_document(content, {"type": key, "filename": file.filename})
                    files_processed.append(key)

            # External input files
            elif key == "inp_file" and EXTERNAL_INPUTS_AVAILABLE:
                inp_parser = InpFileParser()
                inp_data = inp_parser.parse(content)
                if inp_data:
                    building_data["inp"] = inp_data
                    vector_store.add_document(content, {"type": "inp", "filename": file.filename})
                    files_processed.append("inp")

            elif key == "epw_file" and EXTERNAL_INPUTS_AVAILABLE:
                epw_parser = EpwFileParser()
                epw_data = epw_parser.parse(content)
                if epw_data:
                    building_data["weather"] = epw_data
                    vector_store.add_document(
                        json.dumps(epw_data.get("annual_summary", {})),
                        {"type": "weather", "filename": file.filename}
                    )
                    files_processed.append("weather")

            elif key == "utility_bills" and EXTERNAL_INPUTS_AVAILABLE:
                bill_parser = UtilityBillParser()
                bill_data = bill_parser.parse_csv(content)
                if bill_data.get("bills"):
                    building_data["utility_bills"] = bill_data
                    files_processed.append("utility_bills")

            elif key == "interval_data" and EXTERNAL_INPUTS_AVAILABLE:
                interval_parser = IntervalDataParser()
                interval_data = interval_parser.parse(content)
                if interval_data.get("summary"):
                    building_data["interval_data"] = interval_data
                    files_processed.append("interval_data")

        # Process additional documents
        if "additional_docs" in request.files:
            for file in request.files.getlist("additional_docs"):
                valid, err = doc_processor.validate_file(file)
                if not valid:
                    continue
                content, file_type = doc_processor.process_file(file)
                if content and len(content) > 50:
                    vector_store.add_document(
                        content, {"type": "additional", "filename": file.filename}
                    )
                    files_processed.append(f"additional:{file.filename}")

        metrics = compute_metrics(building_data)

        # Add structured data to vector store for enhanced RAG
        if metrics:
            vector_store.add_structured_data(metrics, "metrics")

        _log_audit(session_id, "files_processed", f"files={len(files_processed)}")

        logger.info(
            "Session %s: processed %d files, %d chunks",
            session_id[:8], len(files_processed), len(vector_store.chunks),
        )

        return jsonify({
            "success": True,
            "session_id": session_id,
            "building_data": building_data,
            "metrics": metrics,
            "num_chunks": len(vector_store.chunks),
            "files_processed": files_processed,
        })

    except Exception as e:
        logger.exception("Process error")
        return jsonify({"success": False, "error": "Failed to process files. Please check file formats and try again."}), 500


@app.route("/api/query", methods=["POST"])
@require_session
def query_endpoint(session, session_id):
    """Ask the AI agent a question about the building data."""
    try:
        data = request.json
        if not data or not data.get("query", "").strip():
            return jsonify({"success": False, "error": "Query is required"}), 400

        user_query = data["query"].strip()
        api_key = data.get("api_key", "")

        # Build executive context for AI root-cause mode
        executive_context = ""
        if EXECUTIVE_AI_AVAILABLE and session.get("analysis_cache", {}).get("executive"):
            exec_engine = ExecutiveAIEngine()
            executive_context = exec_engine.generate_ai_prompt_context(
                session["analysis_cache"]["executive"]
            )

        agent = AIAgent(session["vector_store"], api_key)
        result = agent.query(user_query, session["building_data"], executive_context)

        _log_audit(session_id, "query", user_query[:100])

        return jsonify({
            "success": True,
            "response": result["response"],
            "sources": result["sources"],
        })

    except Exception as e:
        logger.exception("Query error")
        return jsonify({"success": False, "error": "Failed to process query"}), 500


@app.route("/api/search", methods=["POST"])
@require_session
def search_endpoint(session, session_id):
    """Search the vector store for relevant document chunks."""
    try:
        data = request.json
        if not data or not data.get("query", "").strip():
            return jsonify({"success": False, "error": "Search query is required"}), 400

        query_text = data["query"].strip()
        top_k = min(int(data.get("top_k", 10)), 50)

        results = session["vector_store"].search(query_text, top_k=top_k)

        formatted = [
            {
                "text": chunk.text[:500],
                "score": round(float(score), 4),
                "filename": chunk.metadata.get("filename", "Unknown"),
                "type": chunk.metadata.get("type", "unknown"),
            }
            for chunk, score in results
        ]

        return jsonify({"success": True, "results": formatted})

    except Exception as e:
        logger.exception("Search error")
        return jsonify({"success": False, "error": "Search failed"}), 500


@app.route("/api/export/<fmt>", methods=["POST"])
@require_session
def export_data_endpoint(session, session_id, fmt):
    """Export building data as JSON or PDF."""
    try:
        building_data = session["building_data"]
        api_key = ""
        if request.json:
            api_key = request.json.get("api_key", "")

        if fmt == "json":
            export_payload = {
                "report_metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "report_type": "eQuest Energy Analysis",
                    "version": "3.0",
                },
                "building_data": building_data,
                "metrics": compute_metrics(building_data),
                "analysis": session.get("analysis_cache", {}),
            }
            _log_audit(session_id, "export_json")
            return jsonify(export_payload)

        elif fmt == "pdf":
            if ENHANCED_PDF_AVAILABLE:
                try:
                    gen_data = dict(building_data)
                    for key in ("ps_e", "ps_e2"):
                        if key in gen_data and isinstance(gen_data[key], list):
                            gen_data[f"{key}_electric"] = pd.DataFrame(gen_data[key])
                    _, pdf_buffer = generate_llm_enhanced_report(
                        gen_data, vector_store=session["vector_store"], api_key=api_key or None,
                    )
                    _log_audit(session_id, "export_pdf")
                    return send_file(
                        pdf_buffer, mimetype="application/pdf", as_attachment=True,
                        download_name=f'equest_report_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf',
                    )
                except Exception as e:
                    logger.warning("Enhanced PDF failed, falling back: %s", e)

            if not REPORTLAB_AVAILABLE:
                return jsonify({"success": False, "error": "PDF generation not available on this server"}), 501

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            story = []
            story.append(Paragraph("eQuest Energy Analysis Report v3.0", styles["Title"]))
            story.append(Spacer(1, 20))
            story.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y')}", styles["Normal"]))
            story.append(Spacer(1, 12))

            if "bepu" in building_data and isinstance(building_data["bepu"], dict):
                story.append(Paragraph("Building Performance", styles["Heading2"]))
                for key, value in building_data["bepu"].items():
                    story.append(Paragraph(f"{key.replace('_', ' ').title()}: {value}", styles["Normal"]))
                story.append(Spacer(1, 12))

            if "ls_c" in building_data and isinstance(building_data["ls_c"], dict):
                story.append(Paragraph("Peak Loads", styles["Heading2"]))
                for key, value in building_data["ls_c"].items():
                    if not isinstance(value, (list, dict)):
                        story.append(Paragraph(f"{key.replace('_', ' ').title()}: {value}", styles["Normal"]))
                story.append(Spacer(1, 12))

            metrics = compute_metrics(building_data)
            if metrics:
                story.append(Paragraph("Key Metrics", styles["Heading2"]))
                table_data = [["Metric", "Value"]]
                for k, v in metrics.items():
                    if not isinstance(v, (dict, list)):
                        label = k.replace("_", " ").title()
                        table_data.append([label, f"{v:,.2f}" if isinstance(v, float) else str(v)])
                t = Table(table_data, colWidths=[250, 200])
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2874A6")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("PADDING", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#EBF5FB")),
                ]))
                story.append(t)

            doc.build(story)
            buffer.seek(0)
            _log_audit(session_id, "export_pdf")
            return send_file(
                buffer, mimetype="application/pdf", as_attachment=True,
                download_name=f'equest_report_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf',
            )

        else:
            return jsonify({"success": False, "error": f"Unsupported format: {fmt}"}), 400

    except Exception as e:
        logger.exception("Export error")
        return jsonify({"success": False, "error": "Export failed"}), 500


@app.route("/api/chart-data", methods=["GET"])
@require_session
def chart_data_endpoint(session, session_id):
    """Return structured data optimized for frontend charting."""
    try:
        building_data = session["building_data"]
        charts = {}

        for key in ("ps_e", "ps_e2"):
            if key in building_data and isinstance(building_data[key], list):
                monthly = [row for row in building_data[key] if row.get("Month") != "ANNUAL"]
                annual = [row for row in building_data[key] if row.get("Month") == "ANNUAL"]
                if monthly:
                    charts["monthly_consumption"] = monthly
                if annual:
                    row = annual[0]
                    charts["end_use_breakdown"] = [
                        {"name": "Lighting", "value": row.get("Lights", 0)},
                        {"name": "Equipment", "value": row.get("Equipment", 0)},
                        {"name": "Heating", "value": row.get("Heating", 0)},
                        {"name": "Cooling", "value": row.get("Cooling", 0)},
                        {"name": "Ventilation", "value": row.get("Vent_Fans", 0)},
                        {"name": "Hot Water", "value": row.get("Hot_Water", 0)},
                    ]
                    charts["end_use_breakdown"] = [d for d in charts["end_use_breakdown"] if d["value"] > 0]
                break

        if "ls_c" in building_data and isinstance(building_data["ls_c"], dict):
            ls_c = building_data["ls_c"]
            charts["peak_loads"] = [
                {"name": "Cooling", "value": ls_c.get("cooling_load_kbtu_h", 0), "unit": "kBTU/h"},
                {"name": "Heating", "value": ls_c.get("heating_load_kbtu_h", 0), "unit": "kBTU/h"},
            ]

        if "bepu" in building_data and isinstance(building_data["bepu"], dict):
            eui = building_data["bepu"].get("eui_kwh_sqft_yr", 0)
            charts["eui_benchmark"] = [
                {"name": "This Building", "value": eui},
                {"name": "Excellent (<12)", "value": 12},
                {"name": "Good (<18)", "value": 18},
                {"name": "Average (<25)", "value": 25},
                {"name": "Poor (>25)", "value": 35},
            ]

        return jsonify({"success": True, "charts": charts})

    except Exception as e:
        logger.exception("Chart data error")
        return jsonify({"success": False, "error": "Failed to generate chart data"}), 500


# ---------------------------------------------------------------------------
# Routes: New v3.0 API Platform (/analyze, /simulate, /benchmark, /carbon, /portfolio)
# ---------------------------------------------------------------------------

@app.route("/api/analyze", methods=["POST"])
@require_session
def analyze_endpoint(session, session_id):
    """Full building analysis: quality, diagnostics, metrics, executive summary."""
    try:
        building_data = session["building_data"]
        metrics = compute_metrics(building_data)
        params = request.json or {}
        building_type = params.get("building_type", "office")
        climate_zone = params.get("climate_zone", "4A")

        result = {"metrics": metrics}

        # Data quality
        if DATA_QUALITY_AVAILABLE:
            quality_engine = DataQualityEngine()
            quality = quality_engine.analyze(building_data, metrics)
            result["data_quality"] = quality.to_dict()

        # Diagnostics
        if DIAGNOSTICS_AVAILABLE:
            diag_engine = DiagnosticsEngine()
            diagnostics = diag_engine.analyze(building_data, metrics, building_type)
            result["diagnostics"] = diagnostics.to_dict()

        # Benchmarking
        if BENCHMARKING_AVAILABLE:
            bench_engine = BenchmarkingEngine()
            benchmark = bench_engine.benchmark(building_data, metrics, building_type, climate_zone)
            result["benchmarking"] = benchmark

        # Carbon & ESG
        if CARBON_ESG_AVAILABLE:
            carbon_engine = CarbonESGEngine()
            carbon = carbon_engine.analyze(building_data, metrics)
            result["carbon"] = carbon

        # Executive summary
        if EXECUTIVE_AI_AVAILABLE:
            exec_engine = ExecutiveAIEngine()
            executive = exec_engine.generate_executive_report(
                building_data, metrics,
                diagnostics=result.get("diagnostics"),
                benchmarking=result.get("benchmarking"),
                carbon=result.get("carbon"),
                quality=result.get("data_quality"),
            )
            result["executive"] = executive

        # Cache results
        session["analysis_cache"] = result

        _log_audit(session_id, "full_analysis")

        return jsonify({"success": True, **result})

    except Exception as e:
        logger.exception("Analysis error")
        return jsonify({"success": False, "error": "Analysis failed"}), 500


@app.route("/api/simulate", methods=["POST"])
@require_session
def simulate_endpoint(session, session_id):
    """Run scenario simulations with payback and ROI calculations."""
    try:
        if not SIMULATION_AVAILABLE:
            return jsonify({"success": False, "error": "Simulation engine not available"}), 501

        building_data = session["building_data"]
        metrics = compute_metrics(building_data)
        params = request.json or {}

        sim_engine = ScenarioSimulationEngine()
        result = sim_engine.simulate(
            building_data, metrics,
            scenarios=params.get("scenarios"),
            electricity_rate=params.get("electricity_rate", 0.12),
            gas_rate=params.get("gas_rate", 1.20),
            carbon_price=params.get("carbon_price", 50.0),
            discount_rate=params.get("discount_rate", 0.05),
        )

        # Also run financial analysis
        if FINANCIAL_AVAILABLE:
            fin_engine = FinancialModelingEngine()
            financial = fin_engine.analyze(
                building_data, metrics,
                electricity_rate=params.get("electricity_rate", 0.12),
                gas_rate=params.get("gas_rate", 1.20),
            )
            result["financial"] = financial

        session["analysis_cache"]["simulation"] = result
        _log_audit(session_id, "simulation")

        return jsonify({"success": True, **result})

    except Exception as e:
        logger.exception("Simulation error")
        return jsonify({"success": False, "error": "Simulation failed"}), 500


@app.route("/api/benchmark", methods=["POST"])
@require_session
def benchmark_endpoint(session, session_id):
    """Benchmark building against standards and peers."""
    try:
        if not BENCHMARKING_AVAILABLE:
            return jsonify({"success": False, "error": "Benchmarking engine not available"}), 501

        building_data = session["building_data"]
        metrics = compute_metrics(building_data)
        params = request.json or {}

        bench_engine = BenchmarkingEngine()
        result = bench_engine.benchmark(
            building_data, metrics,
            building_type=params.get("building_type", "office"),
            climate_zone=params.get("climate_zone", "4A"),
        )

        session["analysis_cache"]["benchmarking"] = result
        _log_audit(session_id, "benchmark")

        return jsonify({"success": True, **result})

    except Exception as e:
        logger.exception("Benchmark error")
        return jsonify({"success": False, "error": "Benchmarking failed"}), 500


@app.route("/api/carbon", methods=["POST"])
@require_session
def carbon_endpoint(session, session_id):
    """Carbon emissions and ESG analysis."""
    try:
        if not CARBON_ESG_AVAILABLE:
            return jsonify({"success": False, "error": "Carbon/ESG engine not available"}), 501

        building_data = session["building_data"]
        metrics = compute_metrics(building_data)
        params = request.json or {}

        carbon_engine = CarbonESGEngine()
        result = carbon_engine.analyze(
            building_data, metrics,
            region=params.get("region", "US_average"),
        )

        session["analysis_cache"]["carbon"] = result
        _log_audit(session_id, "carbon_analysis")

        return jsonify({"success": True, **result})

    except Exception as e:
        logger.exception("Carbon analysis error")
        return jsonify({"success": False, "error": "Carbon analysis failed"}), 500


@app.route("/api/portfolio", methods=["POST"])
def portfolio_endpoint():
    """Portfolio analytics across multiple buildings."""
    try:
        if not PORTFOLIO_AVAILABLE:
            return jsonify({"success": False, "error": "Portfolio engine not available"}), 501

        data = request.json
        if not data or not data.get("buildings"):
            return jsonify({"success": False, "error": "Buildings data required"}), 400

        portfolio_engine = PortfolioAnalyticsEngine()
        result = portfolio_engine.analyze_portfolio(data["buildings"])

        _log_audit("portfolio", "portfolio_analysis", f"buildings={len(data['buildings'])}")

        return jsonify({"success": True, **result})

    except Exception as e:
        logger.exception("Portfolio error")
        return jsonify({"success": False, "error": "Portfolio analysis failed"}), 500


@app.route("/api/financial", methods=["POST"])
@require_session
def financial_endpoint(session, session_id):
    """Financial modeling and retrofit analysis."""
    try:
        if not FINANCIAL_AVAILABLE:
            return jsonify({"success": False, "error": "Financial engine not available"}), 501

        building_data = session["building_data"]
        metrics = compute_metrics(building_data)
        params = request.json or {}

        fin_engine = FinancialModelingEngine()
        result = fin_engine.analyze(
            building_data, metrics,
            electricity_rate=params.get("electricity_rate", 0.12),
            gas_rate=params.get("gas_rate", 1.20),
            escalation_rate=params.get("escalation_rate", 0.03),
            discount_rate=params.get("discount_rate", 0.05),
            analysis_period=params.get("analysis_period", 25),
        )

        session["analysis_cache"]["financial"] = result
        _log_audit(session_id, "financial_analysis")

        return jsonify({"success": True, **result})

    except Exception as e:
        logger.exception("Financial analysis error")
        return jsonify({"success": False, "error": "Financial analysis failed"}), 500


# ---------------------------------------------------------------------------
# Routes: Enterprise Features
# ---------------------------------------------------------------------------

@app.route("/api/audit-log", methods=["GET"])
def audit_log_endpoint():
    """Retrieve audit log entries."""
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        entries = list(_audit_log)[-limit:]
        return jsonify({"success": True, "entries": entries, "total": len(entries)})
    except Exception as e:
        logger.exception("Audit log error")
        return jsonify({"success": False, "error": "Failed to retrieve audit log"}), 500


@app.route("/api/project/save", methods=["POST"])
@require_session
def save_project(session, session_id):
    """Save current session as a persistent project."""
    try:
        data = request.json or {}
        project_name = data.get("name", f"Project_{datetime.now().strftime('%Y%m%d_%H%M')}")
        project_id = data.get("project_id", str(uuid.uuid4()))

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        building_data_json = json.dumps(session["building_data"], default=str)
        metrics_json = json.dumps(compute_metrics(session["building_data"]), default=str)
        now = datetime.now().isoformat()

        c.execute("""
            INSERT OR REPLACE INTO projects (id, name, building_data, metrics, created_at, updated_at, version)
            VALUES (?, ?, ?, ?, COALESCE((SELECT created_at FROM projects WHERE id = ?), ?), ?,
                    COALESCE((SELECT version FROM projects WHERE id = ?), 0) + 1)
        """, (project_id, project_name, building_data_json, metrics_json, project_id, now, now, project_id))
        conn.commit()
        conn.close()

        _log_audit(session_id, "project_saved", project_id)

        return jsonify({"success": True, "project_id": project_id, "name": project_name})

    except Exception as e:
        logger.exception("Save project error")
        return jsonify({"success": False, "error": "Failed to save project"}), 500


@app.route("/api/project/load/<project_id>", methods=["GET"])
def load_project(project_id):
    """Load a saved project into a new session."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name, building_data, metrics FROM projects WHERE id = ?", (project_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            return jsonify({"success": False, "error": "Project not found"}), 404

        name, building_data_json, metrics_json = row
        building_data = json.loads(building_data_json)
        metrics = json.loads(metrics_json)

        session_id = create_session()
        session = get_session(session_id)
        session["building_data"] = building_data

        _log_audit(session_id, "project_loaded", project_id)

        return jsonify({
            "success": True,
            "session_id": session_id,
            "project_name": name,
            "building_data": building_data,
            "metrics": metrics,
        })

    except Exception as e:
        logger.exception("Load project error")
        return jsonify({"success": False, "error": "Failed to load project"}), 500


@app.route("/api/projects", methods=["GET"])
def list_projects():
    """List all saved projects."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, name, created_at, updated_at, version FROM projects ORDER BY updated_at DESC")
        rows = c.fetchall()
        conn.close()

        projects = [
            {"id": r[0], "name": r[1], "created_at": r[2], "updated_at": r[3], "version": r[4]}
            for r in rows
        ]

        return jsonify({"success": True, "projects": projects})

    except Exception as e:
        logger.exception("List projects error")
        return jsonify({"success": False, "error": "Failed to list projects"}), 500


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "version": "3.0",
        "capabilities": {
            "embeddings": EMBEDDINGS_AVAILABLE,
            "pdf_processing": PDF_AVAILABLE,
            "openai": OPENAI_AVAILABLE,
            "pdf_generation": REPORTLAB_AVAILABLE,
            "enhanced_pdf": ENHANCED_PDF_AVAILABLE,
            "parser_v2": PARSER_V2_AVAILABLE,
            "external_inputs": EXTERNAL_INPUTS_AVAILABLE,
            "data_quality": DATA_QUALITY_AVAILABLE,
            "engineering_metrics": ENGINEERING_METRICS_AVAILABLE,
            "diagnostics": DIAGNOSTICS_AVAILABLE,
            "benchmarking": BENCHMARKING_AVAILABLE,
            "carbon_esg": CARBON_ESG_AVAILABLE,
            "simulation": SIMULATION_AVAILABLE,
            "portfolio": PORTFOLIO_AVAILABLE,
            "financial": FINANCIAL_AVAILABLE,
            "executive_ai": EXECUTIVE_AI_AVAILABLE,
        },
        "active_sessions": len(_sessions),
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
