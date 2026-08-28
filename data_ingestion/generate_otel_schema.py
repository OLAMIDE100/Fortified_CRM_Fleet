from helper_scripts.db import get_connection


def create_otel_pipeline_runs_table(conn) -> None:
    """Create otel_pipeline_runs if missing."""
    try:
        cursor = conn.cursor()
        cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS otel_pipeline_runs (
                        id BIGSERIAL PRIMARY KEY,
                        lead_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        duration_seconds DOUBLE PRECISION NOT NULL,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0,
                        cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                        model TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """
                )

        conn.commit()
        print("✓ OpenTelemetry pipeline runs table created in Postgres.")
    except Exception as e:
        print(f"Error creating otel_pipeline_runs table: {e}")
        raise e

def create_otel_node_spans_table(conn) -> None:
    """Create otel_node_spans if missing."""
    try:
        cursor = conn.cursor()
        cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS otel_node_spans (
                        id BIGSERIAL PRIMARY KEY,
                        run_id BIGINT NOT NULL
                            REFERENCES otel_pipeline_runs(id) ON DELETE CASCADE,
                        seq INTEGER NOT NULL,
                        node TEXT NOT NULL,
                        duration_seconds DOUBLE PRECISION NOT NULL,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0,
                        cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
                        model TEXT,
                        uses_llm BOOLEAN NOT NULL DEFAULT FALSE
                    )
                    """
                )
        conn.commit()
        print("✓ OpenTelemetry node spans table created in Postgres.")
    except Exception as e:
        print(f"Error creating otel_node_spans table: {e}")
        raise e

def create_otel_indexes(conn) -> None:
    try:
        cursor = conn.cursor()
        cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_otel_pipeline_runs_lead_id
                ON otel_pipeline_runs (lead_id)
                """
            )
        cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_otel_pipeline_runs_created_at
                ON otel_pipeline_runs (created_at DESC)
                """
            )
        cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_otel_node_spans_run_id
                ON otel_node_spans (run_id)
                """
            )
        conn.commit()
        print("✓ OpenTelemetry indexes created in Postgres.")
    except Exception as e:
        print(f"Error creating otel indexes: {e}")
        raise e


def init_otel_schema():
    conn = get_connection()
    create_otel_pipeline_runs_table(conn)
    create_otel_node_spans_table(conn)
    create_otel_indexes(conn)
    conn.close()
    print("✓ OpenTelemetry schema initialized in Postgres.")


if __name__ == "__main__":
    init_otel_schema()  