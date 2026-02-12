"""
eQuest RAG - Production Backend
Flask API for eQuest energy modeling analysis with RAG capabilities.
"""

import os
import io
import re
import json
import uuid
import hashlib
import logging
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from functools import wraps

import pandas as pd
import numpy as np
from flask import Flask, request, jsonify, send_file
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
        SimpleDocTemplate,
        Table,
        TableStyle,
        Paragraph,
        Spacer,
    )
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# Enhanced PDF generator (optional)
try:
    from llm_pdf_generator import generate_llm_enhanced_report

    ENHANCED_PDF_AVAILABLE = True
except ImportError:
    ENHANCED_PDF_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB per file
MAX_REQUEST_SIZE = 200 * 1024 * 1024  # 200 MB total
SESSION_TTL = timedelta(hours=4)
ALLOWED_EXTENSIONS = {".txt", ".pdf", ".csv", ".xlsx"}
ALLOWED_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
).split(",")

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
# eQuest Parser
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

        # Derived metrics
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
                        result["total_cost"] = float(
                            match.group(1).replace(",", "")
                        )
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
# Vector Store
# ---------------------------------------------------------------------------
class EnhancedVectorStore:
    """In-memory vector store backed by FAISS and SentenceTransformers."""

    def __init__(self, embedding_model_name: str = "all-MiniLM-L6-v2"):
        self.chunks: List[DocumentChunk] = []
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

    def chunk_text(
        self, text: str, chunk_size: int = 500, overlap: int = 50
    ) -> List[str]:
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size - overlap):
            chunk = " ".join(words[i : i + chunk_size])
            if len(chunk.strip()) > 50:
                chunks.append(chunk)
        return chunks

    def add_document(
        self, text: str, metadata: Dict[str, Any], chunk_size: int = 500
    ):
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

    def _create_simple_embedding(self, text: str) -> np.ndarray:
        text_lower = text.lower()
        features = {
            "energy": ["energy", "consumption", "kwh", "electricity"],
            "cooling": ["cooling", "chiller", "refrigeration"],
            "heating": ["heating", "boiler", "furnace"],
            "lighting": ["lighting", "lights", "illumination"],
            "cost": ["cost", "price", "dollar", "expense"],
            "load": ["load", "peak", "demand"],
        }
        vec = []
        for keywords in features.values():
            score = sum(1 for kw in keywords if kw in text_lower)
            vec.append(score)
        total = sum(vec) if sum(vec) > 0 else 1
        vec = [v / total for v in vec]
        return np.array(vec, dtype=np.float32)

    def search(
        self, query: str, top_k: int = 5
    ) -> List[Tuple[DocumentChunk, float]]:
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
                        np.linalg.norm(query_emb) * np.linalg.norm(chunk.embedding)
                        + 1e-10
                    )
                else:
                    cosine_sim = 0
                scores.append((chunk, float(cosine_sim)))
            scores.sort(key=lambda x: x[1], reverse=True)
            return scores[:top_k]


# ---------------------------------------------------------------------------
# Document Processor
# ---------------------------------------------------------------------------
class DocumentProcessor:
    """Extracts text from uploaded files."""

    ALLOWED_EXTENSIONS = {".txt", ".pdf", ".csv", ".xlsx"}

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
            logger.warning(f"PDF extraction error: {e}")
            return ""

    @staticmethod
    def extract_text_from_txt(file) -> str:
        try:
            return file.read().decode("utf-8", errors="replace")
        except Exception as e:
            logger.warning(f"TXT extraction error: {e}")
            return ""

    @staticmethod
    def process_file(file) -> Tuple[str, str]:
        filename = file.filename.lower()
        if filename.endswith(".pdf"):
            return DocumentProcessor.extract_text_from_pdf(file), "pdf"
        elif filename.endswith(".txt"):
            return DocumentProcessor.extract_text_from_txt(file), "txt"
        else:
            return "", "unknown"


# ---------------------------------------------------------------------------
# AI Agent
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert energy modeling analyst specializing in eQuest building energy simulation software. You have deep knowledge of:

- Building energy performance metrics (EUI, peak loads, consumption patterns)
- HVAC systems, building envelopes, and mechanical systems
- Energy codes and standards (ASHRAE 90.1, Title 24, IECC)
- eQuest report types (PS-E, BEPU, LS-C, ES-D, LV-D)
- Energy cost analysis and utility rate structures
- Building commissioning and retro-commissioning

When answering questions:
1. Reference specific data from the provided context
2. Use proper engineering units and terminology
3. Provide actionable insights when possible
4. Compare values against industry benchmarks when relevant
5. Be precise with numbers - use the exact values from the data

If the data doesn't contain information to answer the question, say so clearly."""


class AIAgent:
    """RAG-powered AI agent for building energy analysis."""

    def __init__(self, vector_store: EnhancedVectorStore, api_key: str = None):
        self.vector_store = vector_store
        self.api_key = api_key
        self.client = None

        if api_key and OPENAI_AVAILABLE:
            try:
                self.client = OpenAI(api_key=api_key)
            except Exception:
                pass

    def query(
        self, user_query: str, building_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        relevant_docs = self.vector_store.search(user_query, top_k=5)
        context = self._build_context(relevant_docs, building_data)

        if self.client:
            response = self._query_openai(user_query, context)
        else:
            response = self._query_local(user_query, building_data)

        sources = list(
            {
                chunk.metadata.get("filename", "Unknown")
                for chunk, _ in relevant_docs[:3]
            }
        )

        return {"response": response, "sources": sources}

    def _build_context(self, docs, building_data):
        parts = []

        # Add building data summary
        if building_data:
            parts.append("=== BUILDING DATA SUMMARY ===")
            if "bepu" in building_data:
                bepu = building_data["bepu"]
                if isinstance(bepu, dict):
                    for k, v in bepu.items():
                        parts.append(f"  {k}: {v}")
            if "ls_c" in building_data:
                ls_c = building_data["ls_c"]
                if isinstance(ls_c, dict):
                    for k, v in ls_c.items():
                        parts.append(f"  {k}: {v}")
            if "es_d" in building_data:
                es_d = building_data["es_d"]
                if isinstance(es_d, dict):
                    for k, v in es_d.items():
                        parts.append(f"  {k}: {v}")
            parts.append("")

        # Add relevant document chunks
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
                {
                    "role": "user",
                    "content": f"Building Data Context:\n{context}\n\nUser Question: {query}",
                },
            ]
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=2000,
                temperature=0.3,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI query error: {e}")
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
                "Try asking about EUI, peak loads, energy consumption, or costs. "
                "For enhanced AI responses, add your OpenAI API key."
            )
        return "No building data available. Please upload and process eQuest files first."


# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------
_sessions: Dict[str, Dict] = {}
_sessions_lock = threading.Lock()


def _cleanup_sessions():
    """Remove expired sessions."""
    now = datetime.now()
    with _sessions_lock:
        expired = [
            sid
            for sid, data in _sessions.items()
            if now - data["created_at"] > SESSION_TTL
        ]
        for sid in expired:
            del _sessions[sid]
            logger.info("Cleaned up expired session %s", sid[:8])


def get_session(session_id: str) -> Dict | None:
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
            "created_at": datetime.now(),
            "last_access": datetime.now(),
        }
    logger.info("Created session %s", session_id[:8])
    return session_id


def require_session(f):
    """Decorator that injects session into the route handler."""

    @wraps(f)
    def decorated(*args, **kwargs):
        session_id = request.headers.get("X-Session-ID")
        if not session_id:
            return (
                jsonify({"success": False, "error": "Missing session. Please process files first."}),
                400,
            )
        session = get_session(session_id)
        if not session:
            return (
                jsonify({"success": False, "error": "Session expired. Please re-upload your files."}),
                410,
            )
        return f(session=session, session_id=session_id, *args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# Metrics Computation
# ---------------------------------------------------------------------------
def compute_metrics(building_data: Dict[str, Any]) -> Dict[str, Any]:
    """Compute comprehensive metrics from parsed building data."""
    metrics = {}

    if "bepu" in building_data:
        bepu = building_data["bepu"]
        if isinstance(bepu, dict):
            if "eui_kwh_sqft_yr" in bepu:
                metrics["eui"] = bepu["eui_kwh_sqft_yr"]
            if "total_electricity_kwh" in bepu:
                metrics["total_kwh"] = bepu["total_electricity_kwh"]
                # Avg power demand
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

    # Compute total annual cost if we have cost_per_sqft and floor_area
    if (
        "cost_per_sqft" in metrics
        and "floor_area_sqft" in metrics
        and "total_annual_cost" not in metrics
    ):
        metrics["total_annual_cost"] = round(
            metrics["cost_per_sqft"] * metrics["floor_area_sqft"], 2
        )

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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/api/process", methods=["POST"])
def process_files():
    """Upload and parse eQuest files. Creates or reuses a session."""
    try:
        # Session: create new or reuse existing
        session_id = request.headers.get("X-Session-ID")
        if session_id:
            session = get_session(session_id)
        else:
            session = None

        if not session:
            session_id = create_session()
            session = get_session(session_id)

        # Reset session data for reprocessing
        session["vector_store"] = EnhancedVectorStore()
        session["building_data"] = {}

        vector_store = session["vector_store"]
        building_data = session["building_data"]

        api_key = request.form.get("api_key", "")
        parser = eQuestParser()
        doc_processor = DocumentProcessor()

        file_keys = ["ps_e", "ps_e2", "bepu", "ls_c", "es_d", "lv_d"]
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
                building_data["metadata"] = parser.extract_metadata(content)

            # Parse by report type
            if key in ("ps_e", "ps_e2"):
                df = parser.parse_ps_e(content)
                if not df.empty:
                    building_data[key] = df.to_dict("records")
                    vector_store.add_document(
                        content, {"type": key, "filename": file.filename}
                    )
                    files_processed.append(key)

            elif key == "bepu":
                bepu_data = parser.parse_bepu(content)
                if bepu_data:
                    building_data["bepu"] = bepu_data
                    vector_store.add_document(
                        content, {"type": "bepu", "filename": file.filename}
                    )
                    files_processed.append("bepu")

            elif key == "ls_c":
                ls_c_data = parser.parse_ls_c(content)
                if ls_c_data:
                    building_data["ls_c"] = ls_c_data
                    vector_store.add_document(
                        content, {"type": "ls_c", "filename": file.filename}
                    )
                    files_processed.append("ls_c")

            elif key == "es_d":
                es_d_data = parser.parse_es_d(content)
                if es_d_data:
                    building_data["es_d"] = es_d_data
                    vector_store.add_document(
                        content, {"type": "es_d", "filename": file.filename}
                    )
                    files_processed.append("es_d")

            elif key == "lv_d":
                lv_d_data = parser.parse_lv_d(content)
                if lv_d_data:
                    building_data["lv_d"] = lv_d_data
                    vector_store.add_document(
                        content, {"type": "lv_d", "filename": file.filename}
                    )
                    files_processed.append("lv_d")

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

        logger.info(
            "Session %s: processed %d files, %d chunks",
            session_id[:8],
            len(files_processed),
            len(vector_store.chunks),
        )

        return jsonify(
            {
                "success": True,
                "session_id": session_id,
                "building_data": building_data,
                "metrics": metrics,
                "num_chunks": len(vector_store.chunks),
                "files_processed": files_processed,
            }
        )

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

        agent = AIAgent(session["vector_store"], api_key)
        result = agent.query(user_query, session["building_data"])

        return jsonify(
            {
                "success": True,
                "response": result["response"],
                "sources": result["sources"],
            }
        )

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
                    "version": "2.0",
                },
                "building_data": building_data,
                "metrics": compute_metrics(building_data),
            }
            return jsonify(export_payload)

        elif fmt == "pdf":
            # Try enhanced PDF first
            if ENHANCED_PDF_AVAILABLE:
                try:
                    # Convert list-of-dicts back to DataFrames for the generator
                    gen_data = dict(building_data)
                    for key in ("ps_e", "ps_e2"):
                        if key in gen_data and isinstance(gen_data[key], list):
                            gen_data[f"{key}_electric"] = pd.DataFrame(gen_data[key])
                    _, pdf_buffer = generate_llm_enhanced_report(
                        gen_data,
                        vector_store=session["vector_store"],
                        api_key=api_key or None,
                    )
                    return send_file(
                        pdf_buffer,
                        mimetype="application/pdf",
                        as_attachment=True,
                        download_name=f'equest_report_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf',
                    )
                except Exception as e:
                    logger.warning("Enhanced PDF failed, falling back: %s", e)

            # Fallback: simple PDF
            if not REPORTLAB_AVAILABLE:
                return jsonify({"success": False, "error": "PDF generation not available on this server"}), 501

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            story = []

            story.append(Paragraph("eQuest Energy Analysis Report", styles["Title"]))
            story.append(Spacer(1, 20))
            story.append(
                Paragraph(
                    f"Generated: {datetime.now().strftime('%B %d, %Y')}",
                    styles["Normal"],
                )
            )
            story.append(Spacer(1, 12))

            if "bepu" in building_data and isinstance(building_data["bepu"], dict):
                story.append(Paragraph("Building Performance", styles["Heading2"]))
                for key, value in building_data["bepu"].items():
                    story.append(
                        Paragraph(
                            f"{key.replace('_', ' ').title()}: {value}",
                            styles["Normal"],
                        )
                    )
                story.append(Spacer(1, 12))

            if "ls_c" in building_data and isinstance(building_data["ls_c"], dict):
                story.append(Paragraph("Peak Loads", styles["Heading2"]))
                for key, value in building_data["ls_c"].items():
                    story.append(
                        Paragraph(
                            f"{key.replace('_', ' ').title()}: {value}",
                            styles["Normal"],
                        )
                    )
                story.append(Spacer(1, 12))

            metrics = compute_metrics(building_data)
            if metrics:
                story.append(Paragraph("Key Metrics", styles["Heading2"]))
                table_data = [["Metric", "Value"]]
                for k, v in metrics.items():
                    label = k.replace("_", " ").title()
                    if isinstance(v, float):
                        table_data.append([label, f"{v:,.2f}"])
                    else:
                        table_data.append([label, str(v)])
                t = Table(table_data, colWidths=[250, 200])
                t.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2874A6")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("PADDING", (0, 0), (-1, -1), 8),
                            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#EBF5FB")),
                        ]
                    )
                )
                story.append(t)

            doc.build(story)
            buffer.seek(0)

            return send_file(
                buffer,
                mimetype="application/pdf",
                as_attachment=True,
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

        # Monthly consumption data (from ps_e)
        for key in ("ps_e", "ps_e2"):
            if key in building_data and isinstance(building_data[key], list):
                monthly = [
                    row for row in building_data[key] if row.get("Month") != "ANNUAL"
                ]
                annual = [
                    row for row in building_data[key] if row.get("Month") == "ANNUAL"
                ]

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
                    # Filter out zeros
                    charts["end_use_breakdown"] = [
                        d for d in charts["end_use_breakdown"] if d["value"] > 0
                    ]
                break  # Use first available

        # Peak loads comparison
        if "ls_c" in building_data and isinstance(building_data["ls_c"], dict):
            ls_c = building_data["ls_c"]
            charts["peak_loads"] = [
                {
                    "name": "Cooling",
                    "value": ls_c.get("cooling_load_kbtu_h", 0),
                    "unit": "kBTU/h",
                },
                {
                    "name": "Heating",
                    "value": ls_c.get("heating_load_kbtu_h", 0),
                    "unit": "kBTU/h",
                },
            ]

        # EUI benchmark comparison
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


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify(
        {
            "status": "healthy",
            "version": "2.0",
            "capabilities": {
                "embeddings": EMBEDDINGS_AVAILABLE,
                "pdf_processing": PDF_AVAILABLE,
                "openai": OPENAI_AVAILABLE,
                "pdf_generation": REPORTLAB_AVAILABLE,
                "enhanced_pdf": ENHANCED_PDF_AVAILABLE,
            },
            "active_sessions": len(_sessions),
        }
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
