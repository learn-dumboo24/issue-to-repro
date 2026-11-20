"""Record OpenTelemetry spans (ADK's own plus the backtest's) as JSON lines.

One line per finished span. Attributes that look like credentials are dropped and long values are
truncated, so trace files are safe to keep next to results and small enough to commit.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

SERVICE_NAME = "issue-to-repro"
MAX_VALUE_CHARS = 2_000
SECRET_KEY = re.compile(r"api[_.-]?key|authorization|token(?!s)|secret|password", re.IGNORECASE)
TRACER = trace.get_tracer("issue_to_repro")


def clean_attributes(attributes: Any) -> dict[str, Any]:
    """Drop credential-like keys; truncate long strings; keep JSON-friendly values."""
    cleaned: dict[str, Any] = {}
    for key, value in dict(attributes or {}).items():
        if SECRET_KEY.search(key):
            continue
        if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
            value = value[:MAX_VALUE_CHARS] + f"... [{len(value)} chars]"
        elif isinstance(value, tuple | list):
            value = [v if not isinstance(v, str) else v[:MAX_VALUE_CHARS] for v in value]
        cleaned[key] = value
    return cleaned


def span_record(span: ReadableSpan) -> dict[str, Any]:
    ctx = span.get_span_context()
    parent = span.parent
    start, end = span.start_time or 0, span.end_time or 0
    return {
        "name": span.name,
        "trace_id": f"{ctx.trace_id:032x}" if ctx else "",
        "span_id": f"{ctx.span_id:016x}" if ctx else "",
        "parent_id": f"{parent.span_id:016x}" if parent else None,
        "start_ns": start,
        "duration_ms": round((end - start) / 1e6, 1),
        "status": span.status.status_code.name,
        "attributes": clean_attributes(span.attributes),
    }


class JsonlSpanExporter(SpanExporter):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self.path.open("a", encoding="utf-8") as out:
            for span in spans:
                out.write(json.dumps(span_record(span), default=str) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def configure_tracing(path: str | Path) -> TracerProvider:
    """Install a tracer provider that writes every finished span to `path` (JSON lines).

    OpenTelemetry allows one global provider per process; call this once, before running agents.
    """
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    provider.add_span_processor(SimpleSpanProcessor(JsonlSpanExporter(path)))
    trace.set_tracer_provider(provider)
    return provider


def load_spans(path: str | Path) -> list[dict[str, Any]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]
