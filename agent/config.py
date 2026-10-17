"""Shared paths and limits for the Dice Kingdom agent."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"
DB_PATH = REPO_ROOT / "data" / "marketing.duckdb"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

RAG_DIR = Path(__file__).resolve().parent / "rag"
INDEX_DIR = RAG_DIR / "index"              # Chroma store (git-ignored, rebuilt by ingest.py)
MODEL_CACHE_DIR = INDEX_DIR / "models"     # fastembed ONNX weights
COLLECTION = "dice_kingdom_kb"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"     # 384-dim, ~130 MB ONNX, runs on CPU

# Chunking (tokens are approximated as chars / 4)
CHUNK_TARGET_TOKENS = 400
CHUNK_MAX_TOKENS = 500
CHUNK_MIN_TOKENS = 300
CHUNK_OVERLAP_TOKENS = 50

# Retrieval
TOP_K = 5
CANDIDATES_PER_RETRIEVER = 20
RRF_K = 60
MAX_CHUNKS_PER_DOC = 2
DEPRECATED_WEIGHT = 0.35   # score multiplier for deprecated / superseded pages
DRAFT_WEIGHT = 0.7         # score multiplier for drafts

# Agent
MODEL = "claude-sonnet-5-5"
API_KEY_ENV = "DICE_AGENT_API_KEY"
MAX_TOOL_CALLS = 8
MAX_OUTPUT_TOKENS = 4096
SQL_ROW_CAP = 200
SQL_TIMEOUT_S = 30
