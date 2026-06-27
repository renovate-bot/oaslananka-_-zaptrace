"""DFM checker — validates a Design against a manufacturer's FabProfile."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from zaptrace.core.board import canonical_board_definition
from zaptrace.core.models import Design, DRCViolation, TraceSegment
from zaptrace.core.net_identity import canonical_routing_net_ids
from zaptrace.fab.profile import FabProfile


@dataclass
class DFMViolation:
    """A single DFM violation found during validation."""

    rule_id: str
    severity: str  # "error" | "warning" | "info"
    message: str
    location: str = ""
    actual: str = ""
    expected: str = ""


@dataclass
class DFMCheckResult:
    """Complete DFM validation result."""

    violations: list[DFMViolation] = field(default_factory=list)
    profile_name: str = ""

    @property
    def passed(self) -> bool:
        return self.errors == 0

    @property
    def total_violations(self) -> int:
        return len(self.violations)

    @property
    def errors(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning")

    def _add(self, rule_id: str, severity: str, message: str, **kw: str) -> None:
        self.violations.append(DFMViolation(rule_id=rule_id, severity=severity, message=message, **kw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "profile": self.profile_name,
            "total": self.total_violations,
            "errors": self.errors,
            "warnings": self.warnings,
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "severity": v.severity,
                    "message": v.message,
                    "location": v.location,
                    "actual": v.actual,
                    "expected": v.expected,
                }
                for v in self.violations
            ],
        }

    def to_drc_violations(self) -> list[DRCViolation]:
        """Convert DFM violations to standard DRC violation format."""
        from zaptrace.core.models import DRCSeverity

        return [
            DRCViolation(
                rule_id=v.rule_id,
                severity=DRCSeverity.ERROR if v.severity == "error" else DRCSeverity.WARNING,
                message=v.message,
                location=v.location,
            )
            for v in self.violations
        ]


class DFMChecker:
    """Validate a Design against a manufacturer's FabProfile.

    Usage:
        profile = load_profile("jlcpcb-2layer")
        checker = DFMChecker(profile)
        result = checker.check(design)
    """

    def __init__(self, profile: FabProfile) -> None:
        self.profile = profile

    def check(self, design: Design) -> DFMCheckResult:
        """Run all DFM checks against the design."""
        result = DFMCheckResult(profile_name=self.profile.name)
        self._check_profile_freshness(result)

        self._check_board_dimensions(design, result)
        self._check_trace_widths(design, result)
        self._check_clearances(design, result)
        self._check_drill_holes(design, result)
        self._check_vias(design, result)
        self._check_layer_count(design, result)
        self._check_annular_ring(design, result)
        self._check_solder_mask(design, result)
        self._check_special_features(design, result)

        return result

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_profile_freshness(self, result: DFMCheckResult) -> None:
        for warning in self.profile.freshness_warnings():
            result._add(
                "fab-profile-stale",
                "warning",
                warning,
                expected="recent sourced fab capability metadata",
            )

    def _check_board_dimensions(self, design: Design, result: DFMCheckResult) -> None:
        bd = canonical_board_definition(design)
        w = bd.width
        h = bd.height

        if w is not None and w < self.profile.min_board_width_mm:
            result._add(
                "board-width-min",
                "error",
                f"Board width ({w:.1f}mm) below minimum ({self.profile.min_board_width_mm}mm)",
                actual=f"{w:.1f}mm",
                expected=f">= {self.profile.min_board_width_mm}mm",
            )
        if w is not None and w > self.profile.max_board_width_mm:
            result._add(
                "board-width-max",
                "error",
                f"Board width ({w:.1f}mm) exceeds maximum ({self.profile.max_board_width_mm}mm)",
                actual=f"{w:.1f}mm",
                expected=f"<= {self.profile.max_board_width_mm}mm",
            )
        if h is not None and h < self.profile.min_board_height_mm:
            result._add(
                "board-height-min",
                "error",
                f"Board height ({h:.1f}mm) below minimum ({self.profile.min_board_height_mm}mm)",
                actual=f"{h:.1f}mm",
                expected=f">= {self.profile.min_board_height_mm}mm",
            )
        if h is not None and h > self.profile.max_board_height_mm:
            result._add(
                "board-height-max",
                "error",
                f"Board height ({h:.1f}mm) exceeds maximum ({self.profile.max_board_height_mm}mm)",
                actual=f"{h:.1f}mm",
                expected=f"<= {self.profile.max_board_height_mm}mm",
            )

    def _check_trace_widths(self, design: Design, result: DFMCheckResult) -> None:
        routing = design.routing
        canonical_routing_net_ids(design, routing)
        if routing is None or not routing.traces:
            return

        min_signal = self.profile.min_trace_mm
        min_power = self.profile.min_trace_power_mm

        for i, seg in enumerate(routing.traces):
            net = design.nets.get(seg.net_id) if seg.net_id else None
            is_power = net is not None and net.type in ("power", "ground")
            threshold = min_power if is_power else min_signal
            if seg.width < threshold:
                loc = f"{seg.net_id} seg#{i}"
                result._add(
                    "trace-width",
                    "error" if is_power else "warning",
                    f"Trace width {seg.width:.3f}mm below "
                    f"{'power' if is_power else 'signal'} minimum {threshold:.3f}mm",
                    location=loc,
                    actual=f"{seg.width:.3f}mm",
                    expected=f">= {threshold:.3f}mm",
                )

    def _check_clearances(self, design: Design, result: DFMCheckResult) -> None:
        min_space = self.profile.min_space_mm
        routing = design.routing
        canonical_routing_net_ids(design, routing)
        if routing is None or not routing.traces:
            return

        traces = list(routing.traces)
        # Pre-compute bounding boxes for AABB pre-filtering
        bboxes = []
        for t in traces:
            x1, y1 = t.start[0], t.start[1]
            x2, y2 = t.end[0], t.end[1]
            bboxes.append(
                (
                    min(x1, x2) - min_space,
                    min(y1, y2) - min_space,
                    max(x1, x2) + min_space,
                    max(y1, y2) + min_space,
                )
            )
        for i, t1 in enumerate(traces):
            bx1, by1, bx2, by2 = bboxes[i]
            for j, t2 in enumerate(traces[i + 1 :], start=i + 1):
                if t1.net_id and t2.net_id and t1.net_id == t2.net_id:
                    continue
                # AABB pre-filter: skip only when the current pair boxes do not overlap.
                bx3, by3, bx4, by4 = bboxes[j]
                if bx2 < bx3 or bx4 < bx1 or by2 < by3 or by4 < by1:
                    continue
                dist = self._segment_distance(t1, t2)
                if dist < min_space:
                    result._add(
                        "clearance",
                        "error",
                        f"Clearance {dist:.3f}mm below minimum {min_space:.3f}mm",
                        location=f"{t1.net_id or '?'} / {t2.net_id or '?'}",
                        actual=f"{dist:.3f}mm",
                        expected=f">= {min_space:.3f}mm",
                    )

    def _check_drill_holes(self, design: Design, result: DFMCheckResult) -> None:
        min_d = self.profile.min_drill_mm
        max_d = self.profile.max_drill_mm

        for comp in design.components.values():
            fp = comp.footprint_def
            if fp is None:
                continue
            for pad in fp.pads:
                drill = pad.drill
                if drill is None:
                    continue
                d = float(drill) if not isinstance(drill, (int, float)) else drill
                if d <= 0:
                    continue  # SMD pad
                pid = pad.id
                if d < min_d:
                    result._add(
                        "drill-min",
                        "error",
                        f"Drill hole {d:.3f}mm below minimum {min_d:.3f}mm",
                        location=f"{comp.ref} pad {pid}",
                        actual=f"{d:.3f}mm",
                        expected=f">= {min_d:.3f}mm",
                    )
                if d > max_d:
                    result._add(
                        "drill-max",
                        "warning",
                        f"Drill hole {d:.3f}mm exceeds maximum {max_d:.3f}mm",
                        location=f"{comp.ref} pad {pid}",
                        actual=f"{d:.3f}mm",
                        expected=f"<= {max_d:.3f}mm",
                    )

    def _check_vias(self, design: Design, result: DFMCheckResult) -> None:
        min_dia = self.profile.min_via_diameter_mm
        min_hole = self.profile.min_via_hole_mm
        max_hole = self.profile.max_via_hole_mm

        routing = design.routing
        canonical_routing_net_ids(design, routing)
        if routing is None:
            return

        for i, via in enumerate(getattr(routing, "vias", [])):
            if len(via) < 4:
                continue
            _x, _y, via_diameter, via_hole, *rest = via
            net_id = str(rest[0]) if rest else ""
            if via_diameter < min_dia:
                result._add(
                    "via-diameter-min",
                    "warning",
                    f"Via diameter {via_diameter:.3f}mm below minimum {min_dia:.3f}mm",
                    location=f"{net_id or '?'} via#{i}",
                    actual=f"{via_diameter:.3f}mm",
                    expected=f">= {min_dia:.3f}mm",
                )
            if via_hole < min_hole:
                result._add(
                    "via-hole-min",
                    "error",
                    f"Via hole {via_hole:.3f}mm below minimum {min_hole:.3f}mm",
                    location=f"{net_id or '?'} via#{i}",
                    actual=f"{via_hole:.3f}mm",
                    expected=f">= {min_hole:.3f}mm",
                )
            if via_hole > max_hole:
                result._add(
                    "via-hole-max",
                    "warning",
                    f"Via hole {via_hole:.3f}mm exceeds maximum {max_hole:.3f}mm",
                    location=f"{net_id or '?'} via#{i}",
                    actual=f"{via_hole:.3f}mm",
                    expected=f"<= {max_hole:.3f}mm",
                )

        for i, seg in enumerate(routing.traces):
            if not seg.via:
                continue
            if seg.via_diameter < min_dia:
                result._add(
                    "via-diameter-min",
                    "warning",
                    f"Via diameter {seg.via_diameter:.3f}mm below minimum {min_dia:.3f}mm",
                    location=f"{seg.net_id} seg#{i}",
                    actual=f"{seg.via_diameter:.3f}mm",
                    expected=f">= {min_dia:.3f}mm",
                )
            if seg.via_hole < min_hole:
                result._add(
                    "via-hole-min",
                    "error",
                    f"Via hole {seg.via_hole:.3f}mm below minimum {min_hole:.3f}mm",
                    location=f"{seg.net_id} seg#{i}",
                    actual=f"{seg.via_hole:.3f}mm",
                    expected=f">= {min_hole:.3f}mm",
                )
            if seg.via_hole > max_hole:
                result._add(
                    "via-hole-max",
                    "warning",
                    f"Via hole {seg.via_hole:.3f}mm exceeds maximum {max_hole:.3f}mm",
                    location=f"{seg.net_id} seg#{i}",
                    actual=f"{seg.via_hole:.3f}mm",
                    expected=f"<= {max_hole:.3f}mm",
                )

    def _check_layer_count(self, design: Design, result: DFMCheckResult) -> None:
        bd = canonical_board_definition(design)
        layers = bd.layers
        allowed = self.profile.capabilities.layer_counts
        if allowed and layers not in allowed:
            result._add(
                "layer-count",
                "error",
                f"Layer count ({layers}) not supported by {self.profile.name} (supported: {allowed})",
                actual=str(layers),
                expected=str(allowed),
            )

    def _check_annular_ring(self, design: Design, result: DFMCheckResult) -> None:
        min_ring = self.profile.min_annular_ring_mm
        routing = design.routing
        if routing is None:
            return
        for i, seg in enumerate(routing.traces):
            if not seg.via:
                continue
            ring = (seg.via_diameter - seg.via_hole) / 2
            if ring < min_ring:
                result._add(
                    "annular-ring",
                    "error",
                    f"Annular ring {ring:.3f}mm below minimum {min_ring:.3f}mm",
                    location=f"{seg.net_id} seg#{i}",
                    actual=f"{ring:.3f}mm",
                    expected=f">= {min_ring:.3f}mm",
                )

    def _check_solder_mask(self, design: Design, result: DFMCheckResult) -> None:
        """Check solder-mask sliver clearance between routed copper features."""
        min_sliver = self.profile.min_solder_mask_sliver_mm
        routing = design.routing
        canonical_routing_net_ids(design, routing)
        if routing is None or not routing.traces:
            return
        traces = list(routing.traces)
        for i, t1 in enumerate(traces):
            for j, t2 in enumerate(traces[i + 1 :], start=i + 1):
                if t1.layer != t2.layer:
                    continue
                if t1.net_id and t2.net_id and t1.net_id == t2.net_id:
                    continue
                center_gap = self._segment_distance(t1, t2)
                copper_gap = center_gap - (t1.width + t2.width) / 2
                if copper_gap < min_sliver:
                    result._add(
                        "solder-mask-sliver",
                        "warning",
                        f"Solder mask sliver {copper_gap:.3f}mm below minimum {min_sliver:.3f}mm",
                        location=f"trace#{i}/trace#{j}",
                        actual=f"{copper_gap:.3f}mm",
                        expected=f">= {min_sliver:.3f}mm",
                    )

    def _check_special_features(self, design: Design, result: DFMCheckResult) -> None:
        needs = self._detect_special_features(design)
        if needs.get("castellated") and not self.profile.castellated_pads:
            result._add(
                "castellated-pads",
                "error",
                f"Design uses castellated pads but {self.profile.name} does not support them",
            )
        if needs.get("edge_plating") and not self.profile.edge_plating:
            result._add(
                "edge-plating",
                "warning",
                f"Design uses edge plating but {self.profile.name} does not support it",
            )
        if needs.get("impedance") and not self.profile.impedance_control:
            result._add(
                "impedance-control",
                "error",
                "Design requires controlled impedance but profile does not support it",
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_special_features(design: Design) -> dict[str, bool]:
        features: dict[str, bool] = {}
        for comp in design.components.values():
            props = comp.properties or {}
            if props.get("castellated"):
                features["castellated"] = True
            if props.get("edge_plating") or props.get("half_cut"):
                features["edge_plating"] = True
        for net in design.nets.values():
            c = net.constraints
            if c and c.impedance_target is not None:
                features["impedance"] = True
        return features

    @staticmethod
    def _segment_distance(s1: TraceSegment, s2: TraceSegment) -> float:
        try:
            a = (s1.start[0], s1.start[1])
            b = (s1.end[0], s1.end[1])
            c = (s2.start[0], s2.start[1])
            d = (s2.end[0], s2.end[1])

            # Check for segment intersection first — crossing segments have distance 0
            if DFMChecker._segments_intersect(a, b, c, d):
                return 0.0

            return min(
                DFMChecker._point_segment_dist(a, c, d),
                DFMChecker._point_segment_dist(b, c, d),
                DFMChecker._point_segment_dist(c, a, b),
                DFMChecker._point_segment_dist(d, a, b),
            )
        except (AttributeError, IndexError, TypeError, ValueError):
            return float("inf")

    @staticmethod
    def _segments_intersect(
        a: tuple[float, float],
        b: tuple[float, float],
        c: tuple[float, float],
        d: tuple[float, float],
    ) -> bool:
        """Return True if segment AB intersects segment CD (including endpoints)."""

        def orient(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:  # noqa: ANN001
            return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

        def on_segment(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> bool:  # noqa: ANN001
            return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(p[1], r[1])

        o1 = orient(a, b, c)
        o2 = orient(a, b, d)
        o3 = orient(c, d, a)
        o4 = orient(c, d, b)
        if o1 == 0 and on_segment(a, c, b):
            return True
        if o2 == 0 and on_segment(a, d, b):
            return True
        if o3 == 0 and on_segment(c, a, d):
            return True
        if o4 == 0 and on_segment(c, b, d):
            return True
        return (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0)

    @staticmethod
    def _point_segment_dist(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        px, py = p
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        proj_x = ax + t * dx
        proj_y = ay + t * dy
        return math.sqrt((px - proj_x) ** 2 + (py - proj_y) ** 2)

    @staticmethod
    def _gap_between(s1: object, s2: object) -> float | None:
        """Estimate gap between two slot-like objects."""
        get = getattr
        for obj in (s1, s2):
            pos = get(obj, "position", None) or get(obj, "center", None)
            if pos is None:
                return None
        p1 = get(s1, "position", None) or get(s1, "center")
        p2 = get(s2, "position", None) or get(s2, "center")
        w1 = get(s1, "width", 0) or 0
        w2 = get(s2, "width", 0) or 0
        cx = (p1[0] - p2[0]) ** 2
        cy = (p1[1] - p2[1]) ** 2
        dist = math.sqrt(cx + cy)
        return dist - (w1 + w2) / 2
