from __future__ import annotations

from fastembed import TextEmbedding
from pgvector.psycopg import register_vector
from dotenv import load_dotenv

from helper_scripts.db import get_connection

load_dotenv()

EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384
EMBEDDINGS_TABLE = "transcript_embeddings"


class VectorRAGManager:
    """Semantic search over player transcripts stored in Postgres/pgvector."""

    def __init__(self):
        self.embed_model = TextEmbedding(model_name=EMBED_MODEL_NAME)

    def search_player_history(self, lead_id: str, query: str, limit: int = 3) -> list[str]:
        """Cosine similarity search filtered by lead_id."""
        query_vector = list(self.embed_model.embed([query]))[0].tolist()

        conn = get_connection()
        try:
            register_vector(conn)
            cur = conn.cursor()
            # <=> is cosine distance in pgvector (lower is more similar)
            cur.execute(
                f"""
                SELECT text
                FROM {EMBEDDINGS_TABLE}
                WHERE lead_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (lead_id, query_vector, limit),
            )
            return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()


def search_player_history(lead_id: str, query: str, limit: int = 3) -> list[str]:
    """ADK-callable tool: semantic search over player transcript history in pgvector."""
    return VectorRAGManager().search_player_history(lead_id, query, limit=limit)
