"""
neurocode-backend/tools/rag_engine.py

Codebase RAG (Retrieval Augmented Generation) Engine:
- Recursively scans active workspace code files (.py, .ts, .js, .md, etc.)
- Chunks code files into semantic blocks with file path metadata
- Computes relevant code snippets using similarity matching
- Returns formatted context for Gemini / Groq LLM reasoning
"""

import os
import re
import math
import time
import logging
import asyncio
import httpx
import config

logger = logging.getLogger("neurocode.rag_engine")

IGNORE_DIRS = {".git", ".venv", "node_modules", "out", "dist", "__pycache__", ".next", ".vscode", "build"}
ALLOWED_EXTS = {".py", ".ts", ".js", ".json", ".md", ".html", ".css", ".sql", ".sh"}  # never secrets files

class RAGEngine:
    def __init__(self):
        self.api_key = config.GEMINI_API_KEY
        self.embedding_model = "text-embedding-004"
        self._index_cache = {}  # path -> list of {file, content, tokens}
        self._indexed_at = {}  # path -> time.monotonic() of the last scan
        self.max_index_age_s = 60  # rescan after this, so new and edited files are found

    def _tokenize(self, text: str) -> set:
        """Helper to extract lowercase word tokens for TF-IDF / similarity matching."""
        words = re.findall(r'[a-zA-Z0-9_]{3,}', text.lower())
        return set(words)

    def _scan_and_chunk(self, workspace_path: str):
        """Scans workspace directory and builds chunk index."""
        if not workspace_path or not os.path.exists(workspace_path):
            return []

        chunks = []
        for root, dirs, files in os.walk(workspace_path):
            # Exclude ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                # Never index secrets files (.env, .env.local, ...): their text would reach the LLM prompt
                if ext not in ALLOWED_EXTS or file.lower().startswith(".env"):
                    continue

                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, workspace_path)

                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    if not content.strip():
                        continue

                    # Chunk by ~500 char blocks or functions
                    lines = content.splitlines()
                    chunk_lines = []
                    current_len = 0

                    for line in lines:
                        chunk_lines.append(line)
                        current_len += len(line)
                        if current_len >= 500:
                            block_text = "\n".join(chunk_lines)
                            chunks.append({
                                "file": rel_path,
                                "content": block_text,
                                "tokens": self._tokenize(block_text)
                            })
                            chunk_lines = []
                            current_len = 0

                    if chunk_lines:
                        block_text = "\n".join(chunk_lines)
                        chunks.append({
                            "file": rel_path,
                            "content": block_text,
                            "tokens": self._tokenize(block_text)
                        })
                except Exception as e:
                    logger.debug(f"[RAG] Error reading file {rel_path}: {e}")

        return chunks

    async def retrieve_context(self, query: str, workspace_path: str = None, top_k: int = 3) -> str:
        """
        Retrieves top-k most relevant codebase snippets for the given user query.
        Returns formatted context string for LLM prompts.
        """
        raw_path = workspace_path or config.REPO_PATH
        if not raw_path:
            return ""
        target_path = os.path.abspath(raw_path)
        if not os.path.exists(target_path):
            return ""

        # Build or get cached index
        age = time.monotonic() - self._indexed_at.get(target_path, float("-inf"))
        if target_path not in self._index_cache or age > self.max_index_age_s:
            logger.info(f"[RAG] Indexing workspace at: {target_path}")
            self._index_cache[target_path] = self._scan_and_chunk(target_path)
            self._indexed_at[target_path] = time.monotonic()

        chunks = self._index_cache[target_path]
        if not chunks:
            return ""

        query_tokens = self._tokenize(query)
        if not query_tokens:
            return ""

        # Score chunks based on token overlap & frequency
        scored_chunks = []
        for chunk in chunks:
            overlap = query_tokens.intersection(chunk["tokens"])
            score = len(overlap)
            if score > 0:
                scored_chunks.append((score, chunk))

        # Sort by relevance score descending
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        top_chunks = scored_chunks[:top_k]

        if not top_chunks:
            return ""

        context_blocks = []
        for score, chunk in top_chunks:
            context_blocks.append(f"--- File: {chunk['file']} ---\n{chunk['content'][:600]}")

        formatted_context = "\n\n".join(context_blocks)
        logger.info(f"[RAG] Retrieved {len(top_chunks)} relevant codebase snippets for query: '{query}'")
        return formatted_context

rag_engine = RAGEngine()
