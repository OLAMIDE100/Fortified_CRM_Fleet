"""Persist OpenTelemetry CRM metrics in Postgres."""

from __future__ import annotations

import logging
from typing import Any, Optional

from helper_scripts.db import get_connection
from helper_scripts.telemetry import PipelineTelemetry

logger = logging.getLogger(__name__)






def save_pipeline_telemetry(telemetry: PipelineTelemetry) -> int:
    """Insert one pipeline run + its node spans. Returns run id."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO otel_pipeline_runs (
                    lead_id, action, duration_seconds,
                    input_tokens, output_tokens, total_tokens,
                    cost_usd, model
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    telemetry.lead_id,
                    telemetry.action,
                    telemetry.duration_seconds,
                    telemetry.input_tokens,
                    telemetry.output_tokens,
                    telemetry.total_tokens,
                    telemetry.cost_usd,
                    telemetry.model,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            run_id = int(row[0])

            if telemetry.nodes:
                cur.executemany(
                    """
                    INSERT INTO otel_node_spans (
                        run_id, seq, node, duration_seconds,
                        input_tokens, output_tokens, total_tokens,
                        cost_usd, model, uses_llm
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            run_id,
                            seq,
                            node.node,
                            node.duration_seconds,
                            node.input_tokens,
                            node.output_tokens,
                            node.total_tokens,
                            node.cost_usd,
                            node.model or None,
                            node.uses_llm,
                        )
                        for seq, node in enumerate(telemetry.nodes)
                    ],
                )
        conn.commit()
        logger.info(
            "stored otel run_id=%s lead=%s action=%s cost_usd=%.6f",
            run_id,
            telemetry.lead_id,
            telemetry.action,
            telemetry.cost_usd,
        )
        return run_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _nodes_for_run(cur, run_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT node, duration_seconds, input_tokens, output_tokens,
               total_tokens, cost_usd, COALESCE(model, ''), uses_llm
        FROM otel_node_spans
        WHERE run_id = %s
        ORDER BY seq ASC, id ASC
        """,
        (run_id,),
    )
    return [
        {
            "node": r[0],
            "duration_seconds": float(r[1]),
            "input_tokens": int(r[2]),
            "output_tokens": int(r[3]),
            "total_tokens": int(r[4]),
            "cost_usd": float(r[5]),
            "model": r[6] or "",
            "uses_llm": bool(r[7]),
        }
        for r in cur.fetchall()
    ]


def _row_to_run(cur, row) -> dict[str, Any]:
    run_id = int(row[0])
    return {
        "id": run_id,
        "lead_id": row[1],
        "action": row[2],
        "duration_seconds": float(row[3]),
        "input_tokens": int(row[4]),
        "output_tokens": int(row[5]),
        "total_tokens": int(row[6]),
        "cost_usd": float(row[7]),
        "model": row[8] or "",
        "created_at": row[9].isoformat() if row[9] is not None else None,
        "nodes": _nodes_for_run(cur, run_id),
    }


def get_pipeline_run(run_id: int) -> Optional[dict[str, Any]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, lead_id, action, duration_seconds,
                       input_tokens, output_tokens, total_tokens,
                       cost_usd, model, created_at
                FROM otel_pipeline_runs
                WHERE id = %s
                """,
                (run_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return _row_to_run(cur, row)
    finally:
        conn.close()


def list_pipeline_runs(
    *,
    lead_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[object] = []
    if lead_id and lead_id.strip():
        clauses.append("lead_id = %s")
        params.append(lead_id.strip())
    if action and action.strip():
        clauses.append("action = %s")
        params.append(action.strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, lead_id, action, duration_seconds,
                       input_tokens, output_tokens, total_tokens,
                       cost_usd, model, created_at
                FROM otel_pipeline_runs
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
            return [_row_to_run(cur, row) for row in rows]
    finally:
        conn.close()
