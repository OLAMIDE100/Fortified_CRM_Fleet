from __future__ import annotations

from helper_scripts.db import get_connection
from fastembed import TextEmbedding
from pgvector.psycopg import register_vector



EMBEDDINGS_TABLE = "transcript_embeddings"
EMBEDDING_DIM = 384
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBED_MODEL = TextEmbedding(model_name=EMBED_MODEL_NAME)


def create_transcript_embeddings_table(conn) -> None: 
    """Enable pgvector and create the embeddings table + indexes."""
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.commit()

    register_vector(conn)
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {EMBEDDINGS_TABLE} (
            log_id TEXT PRIMARY KEY,
            lead_id TEXT NOT NULL,
            timestamp TEXT,
            speaker TEXT,
            text TEXT NOT NULL,
            embedding vector({EMBEDDING_DIM}) NOT NULL
        )
        """
    )
    cur.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {EMBEDDINGS_TABLE}_lead_id_idx
        ON {EMBEDDINGS_TABLE} (lead_id)
        """
    )
    # Cosine-distance ANN index (safe to run repeatedly)
    cur.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {EMBEDDINGS_TABLE}_embedding_hnsw_idx
        ON {EMBEDDINGS_TABLE}
        USING hnsw (embedding vector_cosine_ops)
        """
    )
    conn.commit()
    print("✓ Transcript embeddings table created in Postgres.")



def index_logs_from_db(conn, embed_model, reindex: bool = False) -> int:
    """
    Embed transcript_logs rows and upsert into transcript_embeddings.

    If reindex is False and the table already has rows, skip embedding work.
    """
    register_vector(conn)
    cur = conn.cursor()

    if not reindex:
        cur.execute(f"SELECT COUNT(*) FROM {EMBEDDINGS_TABLE}")
        existing = cur.fetchone()[0]
        if existing:
            print(
                f"✓ Using {existing} existing embeddings in Postgres "
                f"(pass reindex=True to rebuild)."
            )
            return existing

    cur.execute(
        "SELECT log_id, lead_id, timestamp, speaker, message FROM transcript_logs"
    )
    rows = cur.fetchall()
    if not rows:
        print("! No transcript_logs found. Run generate_logs.py first.")
        return 0

    documents = []
    meta = []
    for log_id, lead_id, timestamp, speaker, message in rows:
        text_chunk = f"[{timestamp}] {speaker}: {message}"
        documents.append(text_chunk)
        meta.append((log_id, lead_id, timestamp, speaker, text_chunk))

    print(f" -> Embedding {len(documents)} transcripts with {EMBED_MODEL_NAME}...")
    embeddings = list(embed_model.embed(documents))

    cur.execute(f"TRUNCATE {EMBEDDINGS_TABLE}")
    upsert_sql = f"""
        INSERT INTO {EMBEDDINGS_TABLE}
            (log_id, lead_id, timestamp, speaker, text, embedding)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (log_id) DO UPDATE SET
            lead_id = EXCLUDED.lead_id,
            timestamp = EXCLUDED.timestamp,
            speaker = EXCLUDED.speaker,
            text = EXCLUDED.text,
            embedding = EXCLUDED.embedding
    """
    batch = [
        (log_id, lead_id, timestamp, speaker, text, emb.tolist())
        for (log_id, lead_id, timestamp, speaker, text), emb in zip(meta, embeddings)
    ]
    cur.executemany(upsert_sql, batch)
    conn.commit()
    print(f"✓ Stored {len(batch)} embeddings in Postgres ({EMBEDDINGS_TABLE}).")
    return len(batch)


def init_embeddings():
    conn = get_connection()
    try:
        create_transcript_embeddings_table(conn)
        index_logs_from_db(conn, EMBED_MODEL, reindex=True)
        print("✓ Transcript embeddings initialized in Postgres.")
    finally:
        conn.close()


if __name__ == "__main__":
    init_embeddings()
