"""Canonical net-identity helpers.

ZapTrace uses ``Net.id`` as the machine identity everywhere routing, export,
DRC/DFM, proof checks, and manufacturing evidence exchange references to a
net. ``Net.name`` is a human label only and may be duplicated or changed.
"""

from __future__ import annotations

from dataclasses import dataclass

from zaptrace.core.models import Design, RouteResult, TraceSegment


@dataclass(frozen=True)
class NetIdentityReport:
    """Result of routing-net identity normalization."""

    changed_trace_count: int = 0
    changed_via_count: int = 0
    unknown_refs: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.unknown_refs


def canonical_net_id(design: Design, ref: str | None) -> str | None:
    """Return the canonical ``Net.id`` for *ref*.

    ``ref`` may already be a net id. A unique human ``Net.name`` is accepted as
    a compatibility alias so legacy artifacts can be normalized at boundaries.
    Ambiguous or unknown aliases return ``None`` instead of guessing.
    """
    if not ref:
        return None
    if ref in design.nets:
        return ref
    matches = [net.id for net in design.nets.values() if net.name == ref]
    if len(matches) == 1:
        return matches[0]
    return None


def canonical_routing_net_ids(design: Design, routing: RouteResult | None) -> NetIdentityReport:
    """Normalize a ``RouteResult`` in-place so traces/vias reference ``Net.id``.

    Unknown refs are reported and left unchanged; callers can fail release gates
    on ``report.ok is False``.
    """
    if routing is None:
        return NetIdentityReport()

    changed_traces = 0
    changed_vias = 0
    unknown: list[str] = []

    normalized_traces: list[TraceSegment] = []
    for trace in getattr(routing, "traces", []):
        canonical = canonical_net_id(design, trace.net_id)
        if canonical is None:
            if trace.net_id:
                unknown.append(trace.net_id)
            normalized_traces.append(trace)
            continue
        if canonical != trace.net_id:
            changed_traces += 1
            if hasattr(trace, "model_copy"):
                trace = trace.model_copy(update={"net_id": canonical})
            else:
                trace.net_id = canonical
        normalized_traces.append(trace)
    routing.traces = normalized_traces

    normalized_vias = []
    for via in getattr(routing, "vias", []):
        if len(via) < 5:
            normalized_vias.append(via)
            continue
        x, y, diameter, hole, ref = via
        canonical = canonical_net_id(design, ref)
        if canonical is None:
            if ref:
                unknown.append(str(ref))
            normalized_vias.append(via)
            continue
        if canonical != ref:
            changed_vias += 1
            normalized_vias.append((x, y, diameter, hole, canonical))
        else:
            normalized_vias.append(via)
    if hasattr(routing, "vias"):
        routing.vias = normalized_vias

    return NetIdentityReport(
        changed_trace_count=changed_traces,
        changed_via_count=changed_vias,
        unknown_refs=tuple(sorted(set(unknown))),
    )
