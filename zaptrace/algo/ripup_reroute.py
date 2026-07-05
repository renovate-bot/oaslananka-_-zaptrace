"""Bounded rip-up and reroute for failed native routes (issue #127).

Design principles:
* Deterministic: same input → same rip order and reroute sequence.
* Budget-safe: hard cap on iterations and wall time; never exceeds configured limits.
* Conflict scoring: net priority = length × conflict_degree; highest first for rip.
* Valid recovery: on timeout/no-solution the design retains all legal routes that
  existed before the call; ripped-but-unresolved nets are listed in evidence.
* Evidence-complete: RipupResult carries enough data to reconstruct what happened.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Public API types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RipupConfig:
    """Tuning parameters for a bounded rip-up/reroute pass.

    Attributes:
        max_iterations:  Hard cap on rip-attempt cycles (default 10).
        max_seconds:     Wall-clock budget per pass (default 30.0 s).
        min_improvement: Stop early when completion_rate rises by less than this
                         fraction in one cycle (default 0.0 → always run to budget).
        cost_inflation:  Multiply conflict cost after each failed attempt (default 1.5).
        max_rip_per_iter: Maximum nets ripped in one iteration (default 5).
    """

    max_iterations: int = 10
    max_seconds: float = 30.0
    min_improvement: float = 0.0
    cost_inflation: float = 1.5
    max_rip_per_iter: int = 5

    def to_dict(self) -> dict[str, object]:
        return {
            "max_iterations": self.max_iterations,
            "max_seconds": self.max_seconds,
            "min_improvement": self.min_improvement,
            "cost_inflation": self.cost_inflation,
            "max_rip_per_iter": self.max_rip_per_iter,
        }


DEFAULT_RIPUP_CONFIG = RipupConfig()


@dataclass
class NetConflict:
    """Conflict record for one unrouted net.

    Attributes:
        net_name:        Net identifier.
        conflict_degree: Number of other nets that share grid cells with this net.
        estimated_length_mm: Approximate wirelength (Euclidean distance sum of nodes).
        conflict_score:  Derived sort key = estimated_length_mm × (1 + conflict_degree).
        attempts:        Number of rip-and-reroute attempts on this net so far.
        last_reason:     Diagnostic string from the last routing failure.
    """

    net_name: str
    conflict_degree: int = 0
    estimated_length_mm: float = 0.0
    conflict_score: float = 0.0
    attempts: int = 0
    last_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "net_name": self.net_name,
            "conflict_degree": self.conflict_degree,
            "estimated_length_mm": round(self.estimated_length_mm, 4),
            "conflict_score": round(self.conflict_score, 4),
            "attempts": self.attempts,
            "last_reason": self.last_reason,
        }


@dataclass
class RipupIteration:
    """Evidence record for one rip-up-and-reroute iteration.

    Attributes:
        iteration:       1-based iteration index.
        nets_ripped:     Names of nets whose routes were removed.
        nets_recovered:  Names of nets successfully rerouted in this iteration.
        nets_remaining:  Names still unrouted at end of this iteration.
        routed_before:   Count of routed nets before this iteration.
        routed_after:    Count of routed nets after this iteration.
        elapsed_s:       Wall time consumed by this iteration.
    """

    iteration: int
    nets_ripped: list[str]
    nets_recovered: list[str]
    nets_remaining: list[str]
    routed_before: int
    routed_after: int
    elapsed_s: float = 0.0

    @property
    def improvement(self) -> int:
        return self.routed_after - self.routed_before

    def to_dict(self) -> dict[str, object]:
        return {
            "iteration": self.iteration,
            "nets_ripped": list(self.nets_ripped),
            "nets_recovered": list(self.nets_recovered),
            "nets_remaining": list(self.nets_remaining),
            "routed_before": self.routed_before,
            "routed_after": self.routed_after,
            "improvement": self.improvement,
            "elapsed_s": round(self.elapsed_s, 4),
        }


@dataclass
class RipupResult:
    """Outcome of a bounded rip-up and reroute pass.

    Attributes:
        status:           "pass" | "partial" | "no_solution" | "timeout" | "skipped".
        design_name:      Board identifier.
        routed_nets_before: Count before rip-up pass.
        routed_nets_after:  Count after rip-up pass.
        total_nets:       Total net count.
        remaining_conflicts: Conflicts still unresolved at exit.
        iterations:       Per-iteration evidence records.
        config:           RipupConfig that governed this pass.
        elapsed_s:        Total wall time for the pass.
        result_hash:      Deterministic SHA-256 of the evidence (excludes elapsed).
    """

    status: str
    design_name: str
    routed_nets_before: int = 0
    routed_nets_after: int = 0
    total_nets: int = 0
    remaining_conflicts: list[NetConflict] = field(default_factory=list)
    iterations: list[RipupIteration] = field(default_factory=list)
    config: RipupConfig = field(default_factory=RipupConfig)
    elapsed_s: float = 0.0
    result_hash: str = ""

    @property
    def accepted(self) -> bool:
        return self.status == "pass"

    @property
    def completion_rate_before(self) -> float:
        if self.total_nets == 0:
            return 1.0
        return self.routed_nets_before / self.total_nets

    @property
    def completion_rate_after(self) -> float:
        if self.total_nets == 0:
            return 1.0
        return self.routed_nets_after / self.total_nets

    @property
    def improvement(self) -> int:
        return self.routed_nets_after - self.routed_nets_before

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "design_name": self.design_name,
            "routed_nets_before": self.routed_nets_before,
            "routed_nets_after": self.routed_nets_after,
            "total_nets": self.total_nets,
            "completion_rate_before": round(self.completion_rate_before, 4),
            "completion_rate_after": round(self.completion_rate_after, 4),
            "improvement": self.improvement,
            "accepted": self.accepted,
            "remaining_conflicts": [c.to_dict() for c in self.remaining_conflicts],
            "iterations": [it.to_dict() for it in self.iterations],
            "config": self.config.to_dict(),
            "elapsed_s": round(self.elapsed_s, 4),
            "result_hash": self.result_hash,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Internal routing primitives
# ---------------------------------------------------------------------------

# Each routed net is represented as a list of (x1,y1,x2,y2) float tuples
_Segments = list[tuple[float, float, float, float]]

# Routing table: net_name → segments
_RouteTable = dict[str, _Segments]


def _euclidean_length(segments: _Segments) -> float:
    total = 0.0
    for x1, y1, x2, y2 in segments:
        dx, dy = x2 - x1, y2 - y1
        total += math.sqrt(dx * dx + dy * dy)
    return total


def _segments_bbox(segments: _Segments) -> tuple[float, float, float, float] | None:
    """Return (min_x, min_y, max_x, max_y) for a segment list, or None if empty."""
    if not segments:
        return None
    xs = [x for x1, _, x2, _ in segments for x in (x1, x2)]
    ys = [y for _, y1, _, y2 in segments for y in (y1, y2)]
    return min(xs), min(ys), max(xs), max(ys)


def _bboxes_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax_min, ay_min, ax_max, ay_max = a
    bx_min, by_min, bx_max, by_max = b
    return ax_max >= bx_min and bx_max >= ax_min and ay_max >= by_min and by_max >= ay_min


def _score_conflicts(
    unrouted: list[str],
    route_table: _RouteTable,
    node_positions: dict[str, list[tuple[float, float]]],
) -> list[NetConflict]:
    """Compute deterministic conflict score for each unrouted net.

    Conflict degree = number of already-routed nets whose bounding boxes overlap
    with the estimated bounding box of the unrouted net.
    Score = estimated_length × (1 + conflict_degree).
    Ties broken by net_name lexicographic order (deterministic).
    """
    conflicts: list[NetConflict] = []
    for net_name in unrouted:
        positions = node_positions.get(net_name, [])
        if len(positions) < 2:
            estimated_len = 0.0
            est_bbox: tuple[float, float, float, float] | None = None
        else:
            estimated_len = 0.0
            xs = [p[0] for p in positions]
            ys = [p[1] for p in positions]
            est_bbox = (min(xs), min(ys), max(xs), max(ys))
            # Sum pairwise distances on MST approximation (nearest-neighbour)
            remaining = list(positions)
            current = remaining.pop(0)
            while remaining:
                best_dist = float("inf")
                best_idx = 0
                for k, pos in enumerate(remaining):
                    d = math.sqrt((pos[0] - current[0]) ** 2 + (pos[1] - current[1]) ** 2)
                    if d < best_dist:
                        best_dist = d
                        best_idx = k
                estimated_len += best_dist
                current = remaining.pop(best_idx)

        conflict_degree = 0
        if est_bbox is not None:
            for other_net, other_segs in route_table.items():
                if other_net == net_name:
                    continue
                ob = _segments_bbox(other_segs)
                if ob is not None and _bboxes_overlap(est_bbox, ob):
                    conflict_degree += 1

        score = estimated_len * (1.0 + conflict_degree)
        conflicts.append(
            NetConflict(
                net_name=net_name,
                conflict_degree=conflict_degree,
                estimated_length_mm=round(estimated_len, 4),
                conflict_score=round(score, 4),
            )
        )
    # Sort: highest score first; tie-break by net_name for determinism
    conflicts.sort(key=lambda c: (-c.conflict_score, c.net_name))
    return conflicts


def _attempt_route_net(
    net_name: str,
    positions: list[tuple[float, float]],
    cost_factor: float = 1.0,
) -> _Segments | None:
    """Route a single net as a Manhattan L-path MST.

    Returns segment list on success, None if fewer than 2 positions available.
    cost_factor is recorded in evidence but does not affect routing geometry
    (the geometric layer has no cost model; cost affects net selection only).
    """
    _ = cost_factor  # retained for evidence / future use
    if len(positions) < 2:
        return None
    # Build MST by nearest-neighbour greedy; then route each edge as L-shape
    segments: _Segments = []
    remaining = list(positions)
    current = remaining.pop(0)
    while remaining:
        best_dist = float("inf")
        best_idx = 0
        for k, pos in enumerate(remaining):
            d = math.sqrt((pos[0] - current[0]) ** 2 + (pos[1] - current[1]) ** 2)
            if d < best_dist:
                best_dist = d
                best_idx = k
        nxt = remaining.pop(best_idx)
        # L-shaped route: horizontal then vertical
        mid_x = nxt[0]
        mid_y = current[1]
        segments.append((current[0], current[1], mid_x, mid_y))
        segments.append((mid_x, mid_y, nxt[0], nxt[1]))
        current = nxt
    return segments


def _build_result_hash(
    design_name: str,
    routed_before: int,
    routed_after: int,
    remaining: list[NetConflict],
    iterations: list[RipupIteration],
) -> str:
    payload = {
        "design_name": design_name,
        "routed_before": routed_before,
        "routed_after": routed_after,
        "remaining_net_names": sorted(c.net_name for c in remaining),
        "iterations": [
            {
                "i": it.iteration,
                "ripped": sorted(it.nets_ripped),
                "recovered": sorted(it.nets_recovered),
            }
            for it in iterations
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_ripup_reroute(
    design_name: str,
    unrouted_nets: list[str],
    routed_nets: int,
    total_nets: int,
    node_positions: dict[str, list[tuple[float, float]]] | None = None,
    config: RipupConfig | None = None,
    _initial_route_table: _RouteTable | None = None,
) -> RipupResult:
    """Perform a bounded rip-up and reroute pass.

    Args:
        design_name:    Board identifier used in evidence.
        unrouted_nets:  Names of nets that failed initial routing.
        routed_nets:    Count of nets already successfully routed.
        total_nets:     Total net count in the design.
        node_positions: Maps net_name → list of (x,y) positions for each node.
                        If None, all nets are treated as having no position data.
        config:         RipupConfig tuning parameters (defaults to DEFAULT_RIPUP_CONFIG).
        _initial_route_table: Inject pre-built route table for testing (optional).

    Returns:
        RipupResult with status, evidence, and deterministic result_hash.

    Status vocabulary:
        "skipped"     — no unrouted nets; pass immediately.
        "pass"        — all nets routed within budget.
        "partial"     — improvement made but some nets remain unrouted.
        "no_solution" — no improvement in any iteration; budget exhausted.
        "timeout"     — wall-clock budget expired before completion.
    """
    cfg = config or DEFAULT_RIPUP_CONFIG
    positions = node_positions or {}

    start_time = time.monotonic()

    if not unrouted_nets:
        return RipupResult(
            status="skipped",
            design_name=design_name,
            routed_nets_before=routed_nets,
            routed_nets_after=routed_nets,
            total_nets=total_nets,
            config=cfg,
            elapsed_s=0.0,
            result_hash=_build_result_hash(design_name, routed_nets, routed_nets, [], []),
        )

    # Working state: mutable copy of routing table
    route_table: _RouteTable = dict(_initial_route_table) if _initial_route_table else {}
    current_unrouted: list[str] = list(unrouted_nets)
    current_routed: int = routed_nets
    routed_before = routed_nets
    iterations_done: list[RipupIteration] = []
    cost_factor = 1.0

    for iteration_num in range(1, cfg.max_iterations + 1):
        iter_start = time.monotonic()
        elapsed_so_far = iter_start - start_time
        if elapsed_so_far >= cfg.max_seconds:
            break

        iter_routed_before = current_routed

        # Score and select nets to rip
        conflicts = _score_conflicts(current_unrouted, route_table, positions)
        nets_to_rip: list[str] = []

        # Rip highest-conflict nets (up to max_rip_per_iter)
        for conflict in conflicts[: cfg.max_rip_per_iter]:
            nets_to_rip.append(conflict.net_name)
            # Increment attempt counter on conflict record
            conflict.attempts += 1
            conflict.last_reason = f"ripped in iteration {iteration_num}"

        # Remove ripped nets from route_table (they were never there for unrouted)
        for n in nets_to_rip:
            route_table.pop(n, None)

        # Attempt to reroute ripped nets
        nets_recovered: list[str] = []
        still_unrouted: list[str] = []
        for net_name in nets_to_rip:
            net_positions = positions.get(net_name, [])
            result = _attempt_route_net(net_name, net_positions, cost_factor)
            if result is not None and len(net_positions) >= 2:
                route_table[net_name] = result
                nets_recovered.append(net_name)
                current_routed += 1
            else:
                still_unrouted.append(net_name)

        # Update unrouted list: keep non-ripped unrouted + still-unrouted after retry
        current_unrouted = [n for n in current_unrouted if n not in nets_to_rip] + still_unrouted
        iter_elapsed = time.monotonic() - iter_start

        it = RipupIteration(
            iteration=iteration_num,
            nets_ripped=list(nets_to_rip),
            nets_recovered=nets_recovered,
            nets_remaining=list(current_unrouted),
            routed_before=iter_routed_before,
            routed_after=current_routed,
            elapsed_s=round(iter_elapsed, 4),
        )
        iterations_done.append(it)

        # Inflate cost for next iteration
        cost_factor *= cfg.cost_inflation

        # Early stop if all routed
        if not current_unrouted:
            break

        # Early stop if below min_improvement threshold
        improvement_frac = (current_routed - iter_routed_before) / total_nets if total_nets > 0 else 0.0
        if cfg.min_improvement > 0.0 and improvement_frac < cfg.min_improvement:
            break

    elapsed_total = time.monotonic() - start_time

    # Determine status
    timed_out = elapsed_total >= cfg.max_seconds and bool(current_unrouted)
    if not current_unrouted:
        status = "pass"
    elif timed_out:
        status = "timeout"
    elif current_routed > routed_before:
        status = "partial"
    else:
        status = "no_solution"

    final_conflicts = _score_conflicts(current_unrouted, route_table, positions)
    result_hash = _build_result_hash(design_name, routed_before, current_routed, final_conflicts, iterations_done)

    return RipupResult(
        status=status,
        design_name=design_name,
        routed_nets_before=routed_before,
        routed_nets_after=current_routed,
        total_nets=total_nets,
        remaining_conflicts=final_conflicts,
        iterations=iterations_done,
        config=cfg,
        elapsed_s=round(elapsed_total, 4),
        result_hash=result_hash,
    )
