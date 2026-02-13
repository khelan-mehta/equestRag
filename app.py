import os
import io
import re
import json
import hashlib
import logging
import traceback
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Tuple

import pandas as pd
import numpy as np
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Optional dependency imports with graceful fallbacks
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
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("equest")

MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024
ALLOWED_EXTENSIONS = {"txt", "pdf", "csv", "xlsx"}
OPENAI_SERVER_KEY = os.environ.get("OPENAI_API_KEY", "")
DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "uploads")

# ---------------------------------------------------------------------------
# Domain models
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
# eQuest report parsers
# ---------------------------------------------------------------------------

class eQuestParser:
    MONTHS = [
        "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
        "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
    ]

    @staticmethod
    def extract_metadata(content: str) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        for line in content.split("\n"):
            if "WEATHER FILE" in line:
                m = re.search(r"WEATHER FILE-\s*(.+)", line)
                if m:
                    metadata["weather_file"] = m.group(1).strip()
            if "Project" in line:
                parts = line.split()
                if parts:
                    metadata["project_name"] = parts[0]
            m = re.search(r"(\d{2}/\d{2}/\d{4})", line)
            if m:
                metadata["simulation_date"] = m.group(1)
        return metadata

    @classmethod
    def parse_ps_e(cls, content: str) -> pd.DataFrame:
        lines = content.split("\n")
        data: list[dict] = []
        current_month = None

        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(m) for m in cls.MONTHS):
                for m in cls.MONTHS:
                    if stripped.startswith(m):
                        current_month = m
                        break

            if current_month and any(u in stripped for u in ("MBTU", "KWH", "THERM")):
                parts = stripped.split()
                if len(parts) > 13 and parts[0] in ("MBTU", "KWH", "THERM"):
                    try:
                        safe = lambda v: float(v) if v != "." else 0.0
                        row = {
                            "Month": current_month,
                            "Unit": parts[0],
                            "Lights": safe(parts[1]),
                            "Equipment": safe(parts[3]),
                            "Heating": safe(parts[4]),
                            "Cooling": safe(parts[5]),
                            "Vent_Fans": safe(parts[8]),
                            "Hot_Water": safe(parts[11]),
                            "Total": safe(parts[13]),
                        }
                        data.append(row)
                        current_month = None
                    except (ValueError, IndexError):
                        continue

        if data:
            totals = {"Month": "ANNUAL", "Unit": data[0]["Unit"]}
            for col in ("Lights", "Equipment", "Heating", "Cooling", "Vent_Fans", "Hot_Water", "Total"):
                totals[col] = sum(d[col] for d in data)
            data.append(totals)

        return pd.DataFrame(data) if data else pd.DataFrame()

    @staticmethod
    def parse_bepu(content: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for line in content.split("\n"):
            if "FLOOR AREA" in line:
                m = re.search(r"(\d+)\s+SQFT", line)
                if m:
                    result["floor_area_sqft"] = int(m.group(1))
            if "TOTAL ELECTRICITY" in line:
                m = re.search(r"(\d+\.?\d*)\s+KWH", line)
                if m:
                    result["total_electricity_kwh"] = float(m.group(1))
            if "TOTAL GAS" in line:
                m = re.search(r"(\d+\.?\d*)\s+THERM", line)
                if m:
                    result["total_gas_therm"] = float(m.group(1))
            if "KWH /SQFT-YR" in line:
                m = re.search(r"(\d+\.?\d*)\s+KWH\s+/SQFT-YR", line)
                if m:
                    result["eui_kwh_sqft_yr"] = float(m.group(1))
        return result

    @staticmethod
    def parse_ls_c(content: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        in_cooling = False
        in_heating = False
        for line in content.split("\n"):
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
        return result

    @staticmethod
    def parse_es_d(content: str) -> Dict[str, float]:
        result: Dict[str, float] = {}
        for line in content.split("\n"):
            if "ENERGY COST/GROSS BLDG AREA:" in line:
                parts = line.split(":")
                if len(parts) > 1:
                    try:
                        result["cost_per_sqft"] = float(parts[1].strip())
                    except ValueError:
                        pass
            if "TOTAL BUILDING ENERGY COST" in line:
                m = re.search(r"\$?([\d,]+\.?\d*)", line)
                if m:
                    try:
                        result["total_cost"] = float(m.group(1).replace(",", ""))
                    except ValueError:
                        pass
        return result

    @staticmethod
    def parse_lv_d(content: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {"surfaces": [], "summary": {}}
        for line in content.split("\n"):
            if "U-VALUE" in line.upper():
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        result["summary"]["avg_u_value"] = float(parts[-1])
                    except ValueError:
                        pass
        return result


# ---------------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------------

class EnhancedVectorStore:
    def __init__(self, embedding_model_name: str = "all-MiniLM-L6-v2"):
        self.chunks: List[DocumentChunk] = []
        self.index = None
        self.embedding_dim = 384
        self.use_embeddings = False
        self.model = None

        if EMBEDDINGS_AVAILABLE:
            try:
                self.model = SentenceTransformer(embedding_model_name)
                self.embedding_dim = self.model.get_sentence_embedding_dimension()
                self.index = faiss.IndexFlatL2(self.embedding_dim)
                self.use_embeddings = True
                logger.info("Sentence-transformer model loaded successfully")
            except Exception as e:
                logger.warning("Failed to load embedding model: %s", e)

    def reset(self):
        """Clear all stored documents and rebuild index."""
        self.chunks = []
        if self.use_embeddings:
            self.index = faiss.IndexFlatL2(self.embedding_dim)

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
            chunk_metadata = {**metadata, "chunk_index": i, "total_chunks": len(text_chunks)}

            if self.use_embeddings and self.model:
                embedding = self.model.encode(chunk_text, convert_to_numpy=True)
                self.index.add(np.array([embedding], dtype=np.float32))
            else:
                embedding = self._simple_embedding(chunk_text)

            self.chunks.append(DocumentChunk(
                text=chunk_text,
                metadata=chunk_metadata,
                chunk_id=chunk_id,
                embedding=embedding,
            ))

    def _simple_embedding(self, text: str) -> np.ndarray:
        text_lower = text.lower()
        features = {
            "energy": ["energy", "consumption", "kwh", "btu", "therm"],
            "cooling": ["cooling", "chiller", "refrigeration", "ac"],
            "heating": ["heating", "boiler", "furnace", "heat"],
            "lighting": ["lighting", "lights", "lumen", "watt"],
            "envelope": ["wall", "roof", "window", "insulation", "u-value"],
            "ventilation": ["ventilation", "fan", "ahu", "air handling"],
            "cost": ["cost", "dollar", "price", "tariff", "rate"],
            "load": ["load", "peak", "demand", "capacity"],
        }
        vec = []
        for keywords in features.values():
            score = sum(1 for kw in keywords if kw in text_lower)
            vec.append(score)
        total = sum(vec) or 1
        return np.array([v / total for v in vec], dtype=np.float32)

    def search(self, query: str, top_k: int = 5) -> List[Tuple[DocumentChunk, float]]:
        if not self.chunks:
            return []
        if self.use_embeddings and self.model and self.index and self.index.ntotal > 0:
            q_emb = self.model.encode(query, convert_to_numpy=True)
            q_emb = np.array([q_emb], dtype=np.float32)
            distances, indices = self.index.search(q_emb, min(top_k, self.index.ntotal))
            results = []
            for dist, idx in zip(distances[0], indices[0]):
                if 0 <= idx < len(self.chunks):
                    results.append((self.chunks[idx], 1 / (1 + dist)))
            return results
        else:
            q_emb = self._simple_embedding(query)
            scored = []
            for chunk in self.chunks:
                if chunk.embedding is not None:
                    sim = float(np.dot(q_emb, chunk.embedding) / (
                        np.linalg.norm(q_emb) * np.linalg.norm(chunk.embedding) + 1e-10
                    ))
                else:
                    sim = 0.0
                scored.append((chunk, sim))
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]

    @property
    def document_count(self) -> int:
        return len(set(c.metadata.get("filename", "") for c in self.chunks))

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


# ---------------------------------------------------------------------------
# Document processor
# ---------------------------------------------------------------------------

class DocumentProcessor:
    @staticmethod
    def extract_text_from_pdf(file) -> str:
        if not PDF_AVAILABLE:
            return "PDF processing not available – install PyPDF2."
        try:
            reader = PyPDF2.PdfReader(file)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            logger.error("PDF extraction failed: %s", e)
            return f"Error extracting PDF: {e}"

    @staticmethod
    def extract_text_from_txt(file) -> str:
        try:
            return file.read().decode("utf-8", errors="ignore")
        except Exception as e:
            logger.error("TXT extraction failed: %s", e)
            return f"Error: {e}"

    @staticmethod
    def process_file(file) -> Tuple[str, str]:
        filename = file.filename.lower()
        if filename.endswith(".pdf"):
            return DocumentProcessor.extract_text_from_pdf(file), "pdf"
        elif filename.endswith(".txt"):
            return DocumentProcessor.extract_text_from_txt(file), "txt"
        elif filename.endswith(".csv"):
            try:
                df = pd.read_csv(file)
                return df.to_string(), "csv"
            except Exception as e:
                return f"CSV parse error: {e}", "csv"
        elif filename.endswith(".xlsx"):
            try:
                df = pd.read_excel(file)
                return df.to_string(), "xlsx"
            except Exception as e:
                return f"Excel parse error: {e}", "xlsx"
        return "Unsupported format", "unknown"


# ---------------------------------------------------------------------------
# AI agent with conversation history
# ---------------------------------------------------------------------------

class AIAgent:
    SYSTEM_PROMPT = (
        "You are an expert energy modeling analyst specializing in eQuest building simulations. "
        "Answer questions accurately using the provided context from parsed eQuest reports. "
        "When data is available, cite specific numbers. When data is missing, say so clearly. "
        "Provide actionable insights and comparisons to industry benchmarks when relevant."
    )

    def __init__(self, vector_store: EnhancedVectorStore, api_key: str = None):
        self.vector_store = vector_store
        self.api_key = api_key or OPENAI_SERVER_KEY
        self.client = None
        if self.api_key and OPENAI_AVAILABLE:
            try:
                self.client = OpenAI(api_key=self.api_key)
            except Exception as e:
                logger.warning("OpenAI client init failed: %s", e)

    def query(
        self,
        user_query: str,
        building_data: Dict[str, Any],
        conversation_history: List[Dict[str, str]] | None = None,
        model: str | None = None,
    ) -> Dict[str, Any]:
        relevant_docs = self.vector_store.search(user_query, top_k=5)
        context = self._build_context(relevant_docs, building_data)

        if self.client:
            response = self._query_openai(user_query, context, conversation_history, model)
        else:
            response = self._query_local(user_query, building_data)

        sources = list({
            chunk.metadata.get("filename", "Unknown") for chunk, _ in relevant_docs[:3]
        })
        return {"response": response, "sources": sources}

    def _build_context(self, docs, building_data):
        parts = ["=== BUILDING DATA SUMMARY ==="]
        for key, val in building_data.items():
            if isinstance(val, list):
                parts.append(f"{key}: {len(val)} records")
            elif isinstance(val, dict):
                parts.append(f"{key}: {json.dumps(val, default=str)}")
        parts.append("\n=== RELEVANT DOCUMENT CHUNKS ===")
        for chunk, score in docs:
            if score > 0.05:
                parts.append(f"[{chunk.metadata.get('type', 'doc')} | score={score:.3f}]\n{chunk.text[:600]}")
        return "\n".join(parts)

    def _query_openai(self, query, context, history=None, model=None):
        try:
            messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
            if history:
                for msg in history[-10:]:  # keep last 10 turns
                    messages.append({"role": msg["role"], "content": msg["content"]})
            messages.append({
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {query}",
            })
            resp = self.client.chat.completions.create(
                model=model or DEFAULT_MODEL,
                messages=messages,
                max_tokens=3000,
                temperature=0.3,
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.error("OpenAI query failed: %s", e)
            return f"AI query failed: {e}"

    def _query_local(self, query, building_data):
        q = query.lower()
        parts = []

        if "bepu" in building_data:
            bepu = building_data["bepu"]
            if any(w in q for w in ("eui", "energy use intensity", "intensity")):
                parts.append(f"Energy Use Intensity (EUI): {bepu.get('eui_kwh_sqft_yr', 'N/A')} kWh/sqft/yr")
            if any(w in q for w in ("total", "annual", "electricity", "kwh")):
                parts.append(f"Total Electricity: {bepu.get('total_electricity_kwh', 'N/A')} kWh")
            if any(w in q for w in ("area", "floor", "sqft", "size")):
                parts.append(f"Floor Area: {bepu.get('floor_area_sqft', 'N/A')} sqft")

        if "ls_c" in building_data:
            ls_c = building_data["ls_c"]
            if any(w in q for w in ("cool", "load", "peak")):
                parts.append(f"Peak Cooling Load: {ls_c.get('cooling_load_kbtu_h', 'N/A')} kBTU/h")
            if any(w in q for w in ("heat", "load", "peak")):
                parts.append(f"Peak Heating Load: {ls_c.get('heating_load_kbtu_h', 'N/A')} kBTU/h")

        if "es_d" in building_data:
            es_d = building_data["es_d"]
            if any(w in q for w in ("cost", "dollar", "price", "expense")):
                parts.append(f"Energy Cost per sqft: ${es_d.get('cost_per_sqft', 'N/A')}/sqft/yr")

        if "ps_e" in building_data and any(w in q for w in ("month", "breakdown", "consumption")):
            records = building_data["ps_e"]
            if isinstance(records, list) and records:
                annual = next((r for r in records if r.get("Month") == "ANNUAL"), None)
                if annual:
                    parts.append(f"Annual Totals: Lights={annual.get('Lights')}, "
                                 f"Equipment={annual.get('Equipment')}, "
                                 f"Heating={annual.get('Heating')}, "
                                 f"Cooling={annual.get('Cooling')}")

        if parts:
            return "Based on the uploaded eQuest data:\n\n" + "\n".join(f"- {p}" for p in parts)
        return (
            "I can answer questions about your building's energy data. "
            "Try asking about EUI, peak loads, energy costs, or monthly consumption. "
            "For enhanced AI responses, provide an OpenAI API key."
        )


# ---------------------------------------------------------------------------
# Flask application factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    # Determine static folder for serving frontend build
    frontend_dist = Path(__file__).parent / "frontend" / "dist"
    if frontend_dist.is_dir():
        app = Flask(
            __name__,
            static_folder=str(frontend_dist),
            static_url_path="",
        )
    else:
        app = Flask(__name__)

    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

    # CORS: allow all in dev, restrict in prod via env var
    cors_origins = os.environ.get("CORS_ORIGINS", "*")
    CORS(app, resources={r"/api/*": {"origins": cors_origins}})

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # ---- In-memory state (per-worker) ----
    state = {
        "vector_store": EnhancedVectorStore(),
        "building_data": {},
        "conversation_history": [],
    }

    # ------------------------------------------------------------------
    # Serve frontend SPA
    # ------------------------------------------------------------------
    @app.route("/")
    def serve_index():
        if frontend_dist.is_dir():
            return send_from_directory(str(frontend_dist), "index.html")
        return jsonify({"message": "eQuest AI API is running. Deploy frontend to frontend/dist."}), 200

    @app.route("/<path:path>")
    def serve_static(path):
        full = frontend_dist / path
        if frontend_dist.is_dir() and full.is_file():
            return send_from_directory(str(frontend_dist), path)
        # SPA fallback – let React router handle it
        if frontend_dist.is_dir():
            return send_from_directory(str(frontend_dist), "index.html")
        return jsonify({"error": "Not found"}), 404

    # ------------------------------------------------------------------
    # API: Process uploaded files
    # ------------------------------------------------------------------
    @app.route("/api/process", methods=["POST"])
    def process_files():
        try:
            api_key = request.form.get("api_key", "")
            parser = eQuestParser()
            doc_processor = DocumentProcessor()

            # Reset state for new upload
            state["building_data"] = {}
            state["vector_store"].reset()
            state["conversation_history"] = []

            bd = state["building_data"]

            file_keys = ["ps_e", "ps_e2", "bepu", "ls_c", "es_d", "lv_d", "hourly"]
            files_processed = 0

            for key in file_keys:
                if key not in request.files:
                    continue
                file = request.files[key]
                if not file or not file.filename:
                    continue

                content, file_type = doc_processor.process_file(file)
                files_processed += 1
                logger.info("Processing %s (%s) - %d chars", key, file.filename, len(content))

                if key in ("ps_e", "ps_e2"):
                    df = parser.parse_ps_e(content)
                    if not df.empty:
                        bd[key] = df.to_dict("records")
                        state["vector_store"].add_document(
                            content, {"type": key, "filename": file.filename}
                        )
                elif key == "bepu":
                    metadata = parser.extract_metadata(content)
                    if metadata:
                        bd["metadata"] = metadata
                    bepu_data = parser.parse_bepu(content)
                    if bepu_data:
                        bd["bepu"] = bepu_data
                        state["vector_store"].add_document(
                            content, {"type": "bepu", "filename": file.filename}
                        )
                elif key == "ls_c":
                    ls_c = parser.parse_ls_c(content)
                    if ls_c:
                        bd["ls_c"] = ls_c
                        state["vector_store"].add_document(
                            content, {"type": "ls_c", "filename": file.filename}
                        )
                elif key == "es_d":
                    es_d = parser.parse_es_d(content)
                    if es_d:
                        bd["es_d"] = es_d
                        state["vector_store"].add_document(
                            content, {"type": "es_d", "filename": file.filename}
                        )
                elif key == "lv_d":
                    lv_d = parser.parse_lv_d(content)
                    if lv_d and (lv_d.get("surfaces") or lv_d.get("summary")):
                        bd["lv_d"] = lv_d
                        state["vector_store"].add_document(
                            content, {"type": "lv_d", "filename": file.filename}
                        )
                elif key == "hourly":
                    # Store summary stats for hourly data
                    try:
                        file.seek(0)
                        if file.filename.lower().endswith(".csv"):
                            df = pd.read_csv(file)
                        else:
                            df = pd.read_excel(file)
                        bd["hourly_summary"] = {
                            "records": len(df),
                            "columns": list(df.columns),
                            "stats": df.describe().to_dict(),
                        }
                        state["vector_store"].add_document(
                            df.head(100).to_string(),
                            {"type": "hourly", "filename": file.filename},
                        )
                    except Exception as e:
                        logger.warning("Hourly file parse failed: %s", e)

            # Process additional documents
            if "additional_docs" in request.files:
                for file in request.files.getlist("additional_docs"):
                    if file and file.filename:
                        content, ft = doc_processor.process_file(file)
                        if len(content) > 50:
                            state["vector_store"].add_document(
                                content, {"type": "additional", "filename": file.filename}
                            )
                            files_processed += 1

            # Calculate metrics
            metrics = _calculate_metrics(bd)

            logger.info(
                "Processing complete: %d files, %d chunks, %d metrics",
                files_processed,
                state["vector_store"].chunk_count,
                len(metrics),
            )

            return jsonify({
                "success": True,
                "building_data": bd,
                "metrics": metrics,
                "num_chunks": state["vector_store"].chunk_count,
                "num_documents": state["vector_store"].document_count,
                "files_processed": files_processed,
            })

        except Exception as e:
            logger.exception("Processing failed")
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------
    # API: Chat / Query
    # ------------------------------------------------------------------
    @app.route("/api/query", methods=["POST"])
    def query():
        try:
            data = request.json or {}
            user_query = data.get("query", "").strip()
            if not user_query:
                return jsonify({"success": False, "error": "Query is required"}), 400

            api_key = data.get("api_key", "")
            model = data.get("model")
            include_history = data.get("include_history", True)

            agent = AIAgent(state["vector_store"], api_key)

            history = state["conversation_history"] if include_history else None
            result = agent.query(user_query, state["building_data"], history, model)

            # Persist conversation
            state["conversation_history"].append({"role": "user", "content": user_query})
            state["conversation_history"].append({"role": "assistant", "content": result["response"]})

            return jsonify({
                "success": True,
                "response": result["response"],
                "sources": result["sources"],
                "conversation_length": len(state["conversation_history"]) // 2,
            })

        except Exception as e:
            logger.exception("Query failed")
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------
    # API: Clear conversation
    # ------------------------------------------------------------------
    @app.route("/api/conversation/clear", methods=["POST"])
    def clear_conversation():
        state["conversation_history"] = []
        return jsonify({"success": True, "message": "Conversation cleared"})

    # ------------------------------------------------------------------
    # API: Search documents
    # ------------------------------------------------------------------
    @app.route("/api/search", methods=["POST"])
    def search():
        try:
            data = request.json or {}
            q = data.get("query", "").strip()
            top_k = min(data.get("top_k", 10), 50)
            if not q:
                return jsonify({"success": False, "error": "Query is required"}), 400

            results = state["vector_store"].search(q, top_k=top_k)
            formatted = [{
                "text": chunk.text[:500],
                "score": float(score),
                "filename": chunk.metadata.get("filename", "Unknown"),
                "type": chunk.metadata.get("type", "unknown"),
                "chunk_index": chunk.metadata.get("chunk_index", 0),
            } for chunk, score in results]

            return jsonify({"success": True, "results": formatted, "total": len(formatted)})

        except Exception as e:
            logger.exception("Search failed")
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------
    # API: Visualization data
    # ------------------------------------------------------------------
    @app.route("/api/visualizations", methods=["GET"])
    def get_visualization_data():
        bd = state["building_data"]
        viz: Dict[str, Any] = {}

        # Monthly consumption from PS-E
        if "ps_e" in bd and isinstance(bd["ps_e"], list):
            monthly = [r for r in bd["ps_e"] if r.get("Month") != "ANNUAL"]
            annual = next((r for r in bd["ps_e"] if r.get("Month") == "ANNUAL"), None)
            viz["monthly_consumption"] = {
                "labels": [r["Month"] for r in monthly],
                "datasets": {
                    "Lights": [r.get("Lights", 0) for r in monthly],
                    "Equipment": [r.get("Equipment", 0) for r in monthly],
                    "Heating": [r.get("Heating", 0) for r in monthly],
                    "Cooling": [r.get("Cooling", 0) for r in monthly],
                    "Vent_Fans": [r.get("Vent_Fans", 0) for r in monthly],
                    "Hot_Water": [r.get("Hot_Water", 0) for r in monthly],
                    "Total": [r.get("Total", 0) for r in monthly],
                },
            }
            if annual:
                viz["end_use_breakdown"] = {
                    k: v for k, v in annual.items()
                    if k not in ("Month", "Unit", "Total") and isinstance(v, (int, float)) and v > 0
                }

        # Peak loads
        if "ls_c" in bd:
            viz["peak_loads"] = bd["ls_c"]

        # Building performance
        if "bepu" in bd:
            viz["building_performance"] = bd["bepu"]

        # Cost data
        if "es_d" in bd:
            viz["cost_data"] = bd["es_d"]

        # EUI benchmark comparison
        if "bepu" in bd and "eui_kwh_sqft_yr" in bd["bepu"]:
            eui = bd["bepu"]["eui_kwh_sqft_yr"]
            viz["eui_benchmark"] = {
                "building": eui,
                "benchmarks": {
                    "ENERGY_STAR": 15.0,
                    "ASHRAE_90.1": 20.0,
                    "Typical_Office": 25.0,
                    "Typical_Retail": 22.0,
                    "Typical_Hospital": 80.0,
                },
            }

        return jsonify({"success": True, "visualizations": viz})

    # ------------------------------------------------------------------
    # API: Stats / metrics
    # ------------------------------------------------------------------
    @app.route("/api/stats", methods=["GET"])
    def get_stats():
        bd = state["building_data"]
        metrics = _calculate_metrics(bd)
        return jsonify({
            "success": True,
            "metrics": metrics,
            "documents_loaded": state["vector_store"].document_count,
            "chunks_indexed": state["vector_store"].chunk_count,
            "conversation_turns": len(state["conversation_history"]) // 2,
            "data_sections": list(bd.keys()),
        })

    # ------------------------------------------------------------------
    # API: Export
    # ------------------------------------------------------------------
    @app.route("/api/export/<fmt>", methods=["POST"])
    def export_data(fmt):
        try:
            data = request.json or {}
            api_key = data.get("api_key", "")
            bd = state["building_data"]

            if fmt == "json":
                export = {
                    "report_metadata": {
                        "generated_at": datetime.now().isoformat(),
                        "report_type": "eQuest Energy Analysis",
                        "version": "2.0",
                    },
                    "building_data": bd,
                    "metrics": _calculate_metrics(bd),
                }
                return jsonify(export)

            elif fmt == "csv":
                if "ps_e" in bd and isinstance(bd["ps_e"], list):
                    df = pd.DataFrame(bd["ps_e"])
                    buf = io.StringIO()
                    df.to_csv(buf, index=False)
                    buf.seek(0)
                    return send_file(
                        io.BytesIO(buf.getvalue().encode()),
                        mimetype="text/csv",
                        as_attachment=True,
                        download_name=f"energy_data_{datetime.now():%Y%m%d}.csv",
                    )
                return jsonify({"error": "No tabular data available for CSV export"}), 400

            elif fmt == "pdf":
                if not REPORTLAB_AVAILABLE:
                    return jsonify({"error": "PDF generation not available (reportlab missing)"}), 500

                # Try enhanced PDF generator
                try:
                    from llm_pdf_generator import EnhancedPDFReportGenerator
                    gen = EnhancedPDFReportGenerator(bd, api_key or OPENAI_SERVER_KEY)
                    buffer = gen.generate_pdf()
                    return send_file(
                        buffer,
                        mimetype="application/pdf",
                        as_attachment=True,
                        download_name=f"energy_report_{datetime.now():%Y%m%d}.pdf",
                    )
                except Exception as e:
                    logger.warning("Enhanced PDF failed, using basic: %s", e)

                # Fallback to basic PDF
                buffer = _generate_basic_pdf(bd)
                return send_file(
                    buffer,
                    mimetype="application/pdf",
                    as_attachment=True,
                    download_name=f"report_{datetime.now():%Y%m%d}.pdf",
                )
            else:
                return jsonify({"error": f"Unsupported format: {fmt}. Use json, csv, or pdf."}), 400

        except Exception as e:
            logger.exception("Export failed")
            return jsonify({"success": False, "error": str(e)}), 500

    # ------------------------------------------------------------------
    # API: Compare with benchmarks
    # ------------------------------------------------------------------
    @app.route("/api/compare", methods=["POST"])
    def compare_building():
        bd = state["building_data"]
        data = request.json or {}
        building_type = data.get("building_type", "office")

        benchmarks = {
            "office": {"eui": 20.0, "cost_sqft": 2.50, "cooling_tons_per_sqft": 0.004},
            "retail": {"eui": 22.0, "cost_sqft": 2.20, "cooling_tons_per_sqft": 0.003},
            "hospital": {"eui": 80.0, "cost_sqft": 4.50, "cooling_tons_per_sqft": 0.006},
            "school": {"eui": 18.0, "cost_sqft": 1.80, "cooling_tons_per_sqft": 0.003},
            "warehouse": {"eui": 8.0, "cost_sqft": 0.80, "cooling_tons_per_sqft": 0.001},
        }

        bench = benchmarks.get(building_type, benchmarks["office"])
        comparison: Dict[str, Any] = {"building_type": building_type, "benchmark": bench, "your_building": {}, "comparison": {}}

        if "bepu" in bd:
            eui = bd["bepu"].get("eui_kwh_sqft_yr", 0)
            comparison["your_building"]["eui"] = eui
            if bench["eui"] > 0:
                pct = ((eui - bench["eui"]) / bench["eui"]) * 100
                comparison["comparison"]["eui"] = {
                    "difference_pct": round(pct, 1),
                    "status": "better" if pct < 0 else "worse" if pct > 10 else "similar",
                }

        if "es_d" in bd:
            cost = bd["es_d"].get("cost_per_sqft", 0)
            comparison["your_building"]["cost_per_sqft"] = cost
            if bench["cost_sqft"] > 0:
                pct = ((cost - bench["cost_sqft"]) / bench["cost_sqft"]) * 100
                comparison["comparison"]["cost"] = {
                    "difference_pct": round(pct, 1),
                    "status": "better" if pct < 0 else "worse" if pct > 10 else "similar",
                }

        return jsonify({"success": True, **comparison})

    # ------------------------------------------------------------------
    # API: Health check
    # ------------------------------------------------------------------
    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "healthy",
            "version": "2.0.0",
            "timestamp": datetime.now().isoformat(),
            "capabilities": {
                "embeddings": EMBEDDINGS_AVAILABLE,
                "pdf_processing": PDF_AVAILABLE,
                "openai": OPENAI_AVAILABLE,
                "pdf_generation": REPORTLAB_AVAILABLE,
                "server_api_key": bool(OPENAI_SERVER_KEY),
            },
            "state": {
                "documents": state["vector_store"].document_count,
                "chunks": state["vector_store"].chunk_count,
                "data_sections": list(state["building_data"].keys()),
            },
        })

    return app


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _calculate_metrics(bd: Dict[str, Any]) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}

    if "bepu" in bd:
        bepu = bd["bepu"]
        if "eui_kwh_sqft_yr" in bepu:
            metrics["eui"] = bepu["eui_kwh_sqft_yr"]
        if "total_electricity_kwh" in bepu:
            metrics["total_kwh"] = bepu["total_electricity_kwh"]
            metrics["avg_power_kw"] = round(bepu["total_electricity_kwh"] / 8760, 2)
        if "total_gas_therm" in bepu:
            metrics["total_gas_therm"] = bepu["total_gas_therm"]
        if "floor_area_sqft" in bepu:
            metrics["floor_area_sqft"] = bepu["floor_area_sqft"]

    if "ls_c" in bd:
        ls_c = bd["ls_c"]
        if "cooling_load_kbtu_h" in ls_c:
            cooling = ls_c["cooling_load_kbtu_h"]
            metrics["peak_cooling_kbtu_h"] = cooling
            metrics["peak_cooling_tons"] = round(cooling * 0.293 / 3.517, 1)
        if "heating_load_kbtu_h" in ls_c:
            metrics["peak_heating_kbtu_h"] = ls_c["heating_load_kbtu_h"]

    if "es_d" in bd:
        es_d = bd["es_d"]
        if "cost_per_sqft" in es_d:
            metrics["cost_per_sqft"] = es_d["cost_per_sqft"]
        if "total_cost" in es_d:
            metrics["total_annual_cost"] = es_d["total_cost"]
        elif "cost_per_sqft" in es_d and "bepu" in bd and "floor_area_sqft" in bd["bepu"]:
            metrics["total_annual_cost"] = round(
                es_d["cost_per_sqft"] * bd["bepu"]["floor_area_sqft"], 2
            )

    if "ps_e" in bd and isinstance(bd["ps_e"], list):
        monthly = [r for r in bd["ps_e"] if r.get("Month") != "ANNUAL"]
        if monthly:
            totals = [r.get("Total", 0) for r in monthly]
            if totals:
                metrics["peak_month"] = monthly[totals.index(max(totals))]["Month"]
                metrics["lowest_month"] = monthly[totals.index(min(totals))]["Month"]
                if min(totals) > 0:
                    metrics["seasonal_variation"] = round(max(totals) / min(totals), 2)

    return metrics


def _generate_basic_pdf(bd: Dict[str, Any]) -> io.BytesIO:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("eQuest Energy Analysis Report", styles["Title"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 20))

    if "metadata" in bd:
        story.append(Paragraph("Project Information", styles["Heading2"]))
        for k, v in bd["metadata"].items():
            story.append(Paragraph(f"<b>{k.replace('_', ' ').title()}:</b> {v}", styles["Normal"]))
        story.append(Spacer(1, 12))

    if "bepu" in bd:
        story.append(Paragraph("Building Performance (BEPU)", styles["Heading2"]))
        for k, v in bd["bepu"].items():
            story.append(Paragraph(f"<b>{k.replace('_', ' ').title()}:</b> {v}", styles["Normal"]))
        story.append(Spacer(1, 12))

    if "ls_c" in bd:
        story.append(Paragraph("Peak Loads (LS-C)", styles["Heading2"]))
        for k, v in bd["ls_c"].items():
            story.append(Paragraph(f"<b>{k.replace('_', ' ').title()}:</b> {v}", styles["Normal"]))
        story.append(Spacer(1, 12))

    if "es_d" in bd:
        story.append(Paragraph("Energy Cost (ES-D)", styles["Heading2"]))
        for k, v in bd["es_d"].items():
            story.append(Paragraph(f"<b>{k.replace('_', ' ').title()}:</b> {v}", styles["Normal"]))
        story.append(Spacer(1, 12))

    metrics = _calculate_metrics(bd)
    if metrics:
        story.append(Paragraph("Calculated Metrics", styles["Heading2"]))
        table_data = [["Metric", "Value"]]
        for k, v in metrics.items():
            table_data.append([k.replace("_", " ").title(), str(v)])
        t = Table(table_data, colWidths=[3 * inch, 3 * inch])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3498DB")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 1, colors.grey),
            ("PADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(t)

    doc.build(story)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Application entry point
# ---------------------------------------------------------------------------

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
