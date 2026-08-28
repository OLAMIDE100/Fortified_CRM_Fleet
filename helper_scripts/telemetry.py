"""OpenTelemetry tracing for CRM graph nodes (duration, tokens, cost)."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from functools import wraps
from typing import Any, Callable, Iterator, Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger(__name__)

# USD per 1M tokens — override via env (defaults: gemini-2.5-flash ballpark)
_DEFAULT_INPUT_PER_M = float(os.getenv("OTEL_MODEL_INPUT_USD_PER_1M", "0.15"))
_DEFAULT_OUTPUT_PER_M = float(os.getenv("OTEL_MODEL_OUTPUT_USD_PER_1M", "0.60"))
_DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_tracer: Optional[trace.Tracer] = None
_configured = False


@dataclass
class NodeTelemetry:
    node: str
    duration_seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    uses_llm: bool = False


@dataclass
class PipelineTelemetry:
    lead_id: str
    action: str
    duration_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = _DEFAULT_MODEL
    nodes: list[NodeTelemetry] = field(default_factory=list)
    run_id: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "lead_id": self.lead_id,
            "action": self.action,
            "duration_seconds": round(self.duration_seconds, 4),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "model": self.model,
            "nodes": [
                {
                    **asdict(n),
                    "duration_seconds": round(n.duration_seconds, 4),
                    "cost_usd": round(n.cost_usd, 6),
                }
                for n in self.nodes
            ],
        }


class _Collector:
    def __init__(self, lead_id: str, action: str):
        self.lead_id = lead_id
        self.action = action
        self.nodes: list[NodeTelemetry] = []
        self.started = time.perf_counter()

    def add(self, node: NodeTelemetry) -> None:
        self.nodes.append(node)

    def finish(self) -> PipelineTelemetry:
        duration = time.perf_counter() - self.started
        input_tokens = sum(n.input_tokens for n in self.nodes)
        output_tokens = sum(n.output_tokens for n in self.nodes)
        cost = sum(n.cost_usd for n in self.nodes)
        return PipelineTelemetry(
            lead_id=self.lead_id,
            action=self.action,
            duration_seconds=duration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost,
            model=_DEFAULT_MODEL,
            nodes=list(self.nodes),
        )


_current_collector: ContextVar[Optional[_Collector]] = ContextVar(
    "crm_otel_collector", default=None
)

# Set by ADK agent invocations so traced_node can attribute Gemini usage.
_last_llm_usage: ContextVar[Optional[dict[str, Any]]] = ContextVar(
    "crm_last_llm_usage", default=None
)


def set_last_llm_usage(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model: str = "",
) -> None:
    _last_llm_usage.set(
        {
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "model": model or _DEFAULT_MODEL,
        }
    )


def estimate_cost_usd(
    input_tokens: int,
    output_tokens: int,
    *,
    input_per_1m: float = _DEFAULT_INPUT_PER_M,
    output_per_1m: float = _DEFAULT_OUTPUT_PER_M,
) -> float:
    return (input_tokens / 1_000_000.0) * input_per_1m + (
        output_tokens / 1_000_000.0
    ) * output_per_1m


def setup_telemetry(service_name: str = "agentic-crm-backend") -> None:
    """Configure TracerProvider once (console + optional OTLP)."""
    global _tracer, _configured
    if _configured:
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": os.getenv("SERVICE_VERSION", "0.1.0"),
        }
    )
    provider = TracerProvider(resource=resource)

    # Always log spans locally (visible in docker logs)
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            )
            logger.info("OTLP exporter enabled → %s", endpoint)
        except Exception as exc:  # pragma: no cover
            logger.warning("Failed to configure OTLP exporter: %s", exc)

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("agentic_crm", "0.1.0")
    _configured = True


def get_tracer() -> trace.Tracer:
    if not _configured:
        setup_telemetry()
    assert _tracer is not None
    return _tracer


@contextmanager
def start_pipeline(lead_id: str, action: str) -> Iterator[Callable[[], PipelineTelemetry]]:
    """Record node telemetry for one pipeline run; call the yielded finish() for summary."""
    collector = _Collector(lead_id=lead_id, action=action)
    token = _current_collector.set(collector)
    tracer = get_tracer()

    try:
        with tracer.start_as_current_span("crm.pipeline") as span:
            span.set_attribute("crm.lead_id", lead_id)
            span.set_attribute("crm.action", action)
            span.set_attribute("gen_ai.request.model", _DEFAULT_MODEL)

            def finish() -> PipelineTelemetry:
                summary = collector.finish()
                span.set_attribute("crm.duration_seconds", summary.duration_seconds)
                span.set_attribute(
                    "gen_ai.usage.input_tokens", summary.input_tokens
                )
                span.set_attribute(
                    "gen_ai.usage.output_tokens", summary.output_tokens
                )
                span.set_attribute(
                    "gen_ai.usage.total_tokens", summary.total_tokens
                )
                span.set_attribute("gen_ai.usage.cost_usd", summary.cost_usd)
                logger.info(
                    "pipeline lead=%s action=%s duration=%.3fs "
                    "tokens_in=%s tokens_out=%s cost_usd=%.6f",
                    lead_id,
                    action,
                    summary.duration_seconds,
                    summary.input_tokens,
                    summary.output_tokens,
                    summary.cost_usd,
                )
                return summary

            try:
                yield finish
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
    finally:
        _current_collector.reset(token)


def traced_node(node_name: str, *, uses_llm: bool = False) -> Callable:
    """Decorator: time a CRM node and capture Gemini/ADK token usage when applicable."""

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(state: dict, *args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            start = time.perf_counter()
            input_tokens = output_tokens = 0
            cost = 0.0
            model = _DEFAULT_MODEL
            usage_token = _last_llm_usage.set(None)

            with tracer.start_as_current_span(f"crm.node.{node_name}") as span:
                span.set_attribute("crm.node", node_name)
                span.set_attribute("crm.lead_id", state.get("lead_id", ""))
                span.set_attribute("crm.uses_llm", uses_llm)
                try:
                    result = fn(state, *args, **kwargs)

                    if uses_llm:
                        usage = _last_llm_usage.get() or {}
                        input_tokens = int(usage.get("input_tokens") or 0)
                        output_tokens = int(usage.get("output_tokens") or 0)
                        model = str(usage.get("model") or model)
                        cost = estimate_cost_usd(input_tokens, output_tokens)

                    duration = time.perf_counter() - start
                    total = input_tokens + output_tokens
                    span.set_attribute("crm.duration_seconds", duration)
                    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
                    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
                    span.set_attribute("gen_ai.usage.total_tokens", total)
                    span.set_attribute("gen_ai.usage.cost_usd", cost)
                    span.set_attribute("gen_ai.request.model", model)

                    metrics = NodeTelemetry(
                        node=node_name,
                        duration_seconds=duration,
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=total,
                        cost_usd=cost,
                        model=model if uses_llm else "",
                        uses_llm=uses_llm,
                    )
                    collector = _current_collector.get()
                    if collector is not None:
                        collector.add(metrics)

                    logger.info(
                        "node=%s duration=%.3fs in=%s out=%s cost_usd=%.6f",
                        node_name,
                        duration,
                        input_tokens,
                        output_tokens,
                        cost,
                    )
                    return result
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    raise
                finally:
                    _last_llm_usage.reset(usage_token)

        return wrapper

    return decorator
