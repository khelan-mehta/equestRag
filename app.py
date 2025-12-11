from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import pandas as pd
import numpy as np
import io
import json
from datetime import datetime
import traceback
import os
from werkzeug.utils import secure_filename

# Import all the classes from your original code
from dataclasses import dataclass, asdict
import hashlib
import pickle
from pathlib import Path
import re
from typing import List, Dict, Any, Tuple

# Import optional dependencies with fallbacks
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


# Import your existing classes (paste them here)
@dataclass
class DocumentChunk:
    text: str
    metadata: Dict[str, Any]
    chunk_id: str
    embedding: np.ndarray = None

    def to_dict(self):
        return {"text": self.text, "metadata": self.metadata, "chunk_id": self.chunk_id}


class eQuestParser:
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
            "JAN",
            "FEB",
            "MAR",
            "APR",
            "MAY",
            "JUN",
            "JUL",
            "AUG",
            "SEP",
            "OCT",
            "NOV",
            "DEC",
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
                        row = {
                            "Month": current_month,
                            "Unit": parts[0],
                            "Lights": float(
                                parts[1].replace(".", "0")
                                if parts[1] == "."
                                else parts[1]
                            ),
                            "Equipment": float(
                                parts[3].replace(".", "0")
                                if parts[3] == "."
                                else parts[3]
                            ),
                            "Heating": float(
                                parts[4].replace(".", "0")
                                if parts[4] == "."
                                else parts[4]
                            ),
                            "Cooling": float(
                                parts[5].replace(".", "0")
                                if parts[5] == "."
                                else parts[5]
                            ),
                            "Vent_Fans": float(
                                parts[8].replace(".", "0")
                                if parts[8] == "."
                                else parts[8]
                            ),
                            "Hot_Water": float(
                                parts[11].replace(".", "0")
                                if parts[11] == "."
                                else parts[11]
                            ),
                            "Total": float(
                                parts[13].replace(".", "0")
                                if parts[13] == "."
                                else parts[13]
                            ),
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

        return result

    @staticmethod
    def parse_ls_c(content: str) -> Dict[str, Any]:
        result = {}
        lines = content.split("\n")
        in_cooling = False

        for line in lines:
            if "COOLING LOAD" in line:
                in_cooling = True

            if "TOTAL LOAD" in line and in_cooling:
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        result["cooling_load_kbtu_h"] = float(parts[2])
                    except (ValueError, IndexError):
                        pass

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

        return result

    @staticmethod
    def parse_lv_d(content: str) -> Dict[str, Any]:
        result = {"surfaces": [], "summary": {}}
        return result


class EnhancedVectorStore:
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

    def _create_simple_embedding(self, text: str) -> np.ndarray:
        text_lower = text.lower()
        features = {
            "energy": ["energy", "consumption", "kwh"],
            "cooling": ["cooling", "chiller"],
            "heating": ["heating", "boiler"],
            "lighting": ["lighting", "lights"],
        }
        vec = []
        for category, keywords in features.items():
            score = sum(1 for keyword in keywords if keyword in text_lower)
            vec.append(score)
        total = sum(vec) if sum(vec) > 0 else 1
        vec = [v / total for v in vec]
        return np.array(vec, dtype=np.float32)

    def search(self, query: str, top_k: int = 5) -> List[Tuple[DocumentChunk, float]]:
        if self.use_embeddings and self.model and self.index.ntotal > 0:
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
                scores.append((chunk, cosine_sim))
            scores.sort(key=lambda x: x[1], reverse=True)
            return scores[:top_k]


class DocumentProcessor:
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
            return f"Error: {str(e)}"

    @staticmethod
    def extract_text_from_txt(file) -> str:
        try:
            return file.read().decode("utf-8", errors="ignore")
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def process_file(file) -> Tuple[str, str]:
        filename = file.filename.lower()
        if filename.endswith(".pdf"):
            return DocumentProcessor.extract_text_from_pdf(file), "pdf"
        elif filename.endswith(".txt"):
            return DocumentProcessor.extract_text_from_txt(file), "txt"
        else:
            return "Unsupported format", "unknown"


class AIAgent:
    def __init__(self, vector_store: EnhancedVectorStore, api_key: str = None):
        self.vector_store = vector_store
        self.api_key = api_key
        self.client = None

        if api_key and OPENAI_AVAILABLE:
            try:
                self.client = OpenAI(api_key=api_key)
            except Exception:
                pass

    def query(self, user_query: str, building_data: Dict[str, Any]) -> Dict[str, Any]:
        relevant_docs = self.vector_store.search(user_query, top_k=5)
        context = self._build_context(relevant_docs, building_data)

        if self.client:
            response = self._query_openai(user_query, context)
        else:
            response = self._query_local(user_query, building_data)

        sources = [
            chunk.metadata.get("filename", "Unknown") for chunk, _ in relevant_docs[:3]
        ]

        return {"response": response, "sources": sources}

    def _build_context(self, docs, building_data):
        parts = []
        for chunk, score in docs:
            if score > 0.1:
                parts.append(f"{chunk.metadata.get('type', 'doc')}: {chunk.text[:500]}")
        return "\n".join(parts)

    def _query_openai(self, query, context):
        try:
            messages = [
                {"role": "system", "content": "You are an energy modeling expert."},
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {query}",
                },
            ]
            response = self.client.chat.completions.create(
                model="gpt-4o-mini", messages=messages, max_tokens=2000
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Error: {str(e)}"

    def _query_local(self, query, building_data):
        if "eui" in query.lower() and "bepu" in building_data:
            eui = building_data["bepu"].get("eui_kwh_sqft_yr", "N/A")
            return f"Building EUI: {eui} kWh/sqft/year"
        return "Local analysis mode. Add OpenAI API key for enhanced responses."


# Flask App
app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Global storage
vector_store = EnhancedVectorStore()
building_data = {}


@app.route("/api/process", methods=["POST"])
def process_files():
    global vector_store, building_data

    try:
        api_key = request.form.get("api_key", "")
        parser = eQuestParser()
        doc_processor = DocumentProcessor()

        building_data = {}

        # Process eQuest files
        file_keys = ["ps_e", "ps_e2", "bepu", "ls_c", "es_d", "lv_d"]

        for key in file_keys:
            if key in request.files:
                file = request.files[key]
                if file and file.filename:
                    content, file_type = doc_processor.process_file(file)

                    # Parse based on type
                    if key in ["ps_e", "ps_e2"]:
                        df = parser.parse_ps_e(content)
                        if not df.empty:
                            building_data[key] = df.to_dict("records")
                            vector_store.add_document(
                                content, {"type": key, "filename": file.filename}
                            )

                    elif key == "bepu":
                        bepu_data = parser.parse_bepu(content)
                        if bepu_data:
                            building_data["bepu"] = bepu_data
                            vector_store.add_document(
                                content, {"type": "bepu", "filename": file.filename}
                            )

                    elif key == "ls_c":
                        ls_c_data = parser.parse_ls_c(content)
                        if ls_c_data:
                            building_data["ls_c"] = ls_c_data
                            vector_store.add_document(
                                content, {"type": "ls_c", "filename": file.filename}
                            )

        # Process additional documents
        if "additional_docs" in request.files:
            files = request.files.getlist("additional_docs")
            for file in files:
                if file and file.filename:
                    content, file_type = doc_processor.process_file(file)
                    if len(content) > 50:
                        vector_store.add_document(
                            content, {"type": "additional", "filename": file.filename}
                        )

        # Calculate metrics
        metrics = {}
        if "bepu" in building_data:
            bepu = building_data["bepu"]
            if "eui_kwh_sqft_yr" in bepu:
                metrics["eui"] = bepu["eui_kwh_sqft_yr"]
            if "total_electricity_kwh" in bepu:
                metrics["total_kwh"] = bepu["total_electricity_kwh"]

        return jsonify(
            {
                "success": True,
                "building_data": building_data,
                "metrics": metrics,
                "num_chunks": len(vector_store.chunks),
            }
        )

    except Exception as e:
        return (
            jsonify(
                {"success": False, "error": str(e), "traceback": traceback.format_exc()}
            ),
            500,
        )


@app.route("/api/query", methods=["POST"])
def query():
    try:
        data = request.json
        user_query = data.get("query", "")
        api_key = data.get("api_key", "")

        agent = AIAgent(vector_store, api_key)
        result = agent.query(user_query, building_data)

        return jsonify(
            {
                "success": True,
                "response": result["response"],
                "sources": result["sources"],
            }
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/search", methods=["POST"])
def search():
    try:
        data = request.json
        query = data.get("query", "")

        results = vector_store.search(query, top_k=10)

        formatted_results = []
        for chunk, score in results:
            formatted_results.append(
                {
                    "text": chunk.text,
                    "score": float(score),
                    "filename": chunk.metadata.get("filename", "Unknown"),
                    "type": chunk.metadata.get("type", "unknown"),
                }
            )

        return jsonify({"success": True, "results": formatted_results})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/export/<format>", methods=["POST"])
def export_data(format):
    try:
        if format == "json":
            export_data = {
                "timestamp": datetime.now().isoformat(),
                "building_data": building_data,
                "metrics": {},
            }
            return jsonify(export_data)

        elif format == "pdf":
            if not REPORTLAB_AVAILABLE:
                return jsonify({"error": "PDF generation not available"}), 500

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            story = []

            story.append(Paragraph("Energy Analysis Report", styles["Title"]))
            story.append(Spacer(1, 12))

            if "bepu" in building_data:
                for key, value in building_data["bepu"].items():
                    story.append(Paragraph(f"{key}: {value}", styles["Normal"]))

            doc.build(story)
            buffer.seek(0)

            return send_file(
                buffer,
                mimetype="application/pdf",
                as_attachment=True,
                download_name=f'report_{datetime.now().strftime("%Y%m%d")}.pdf',
            )

        else:
            return jsonify({"error": "Invalid format"}), 400

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "healthy",
            "embeddings_available": EMBEDDINGS_AVAILABLE,
            "pdf_available": PDF_AVAILABLE,
            "openai_available": OPENAI_AVAILABLE,
            "reportlab_available": REPORTLAB_AVAILABLE,
        }
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
