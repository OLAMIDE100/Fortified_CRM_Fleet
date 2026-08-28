from data.transcript_logs_1000 import transcript_logs
from helper_scripts.db import get_connection


def create_transcript_logs_table(conn):
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transcript_logs (
        log_id TEXT PRIMARY KEY,
        lead_id TEXT,
        timestamp TEXT,
        speaker TEXT,
        message TEXT
    )
    """)

    conn.commit()
    print("✓ Transcript logs table created in Postgres.")



def load_transcript_logs_table(conn):
    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT INTO transcript_logs (log_id, lead_id, timestamp, speaker, message)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (log_id) DO UPDATE SET
            lead_id = EXCLUDED.lead_id,
            timestamp = EXCLUDED.timestamp,
            speaker = EXCLUDED.speaker,
            message = EXCLUDED.message
        """,
        transcript_logs,
    )
    conn.commit()
    print("✓ Transcript logs table loaded in Postgres.")


def init_historical_db():
    conn = get_connection()
    
    create_transcript_logs_table(conn)
    load_transcript_logs_table(conn)

    conn.close()
    print("✓ Postgres historical transcript logs initialized.")


if __name__ == "__main__":
    init_historical_db()
