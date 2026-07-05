//! ZapTrace Core — Accelerated placement and routing routines.
//!
//! Exposes two main functions via PyO3:
//! - `place_components`: force-directed component placement
//! - `route_nets`: Manhattan minimum-spanning-tree routing

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

// ---------------------------------------------------------------------------
// Placement
// ---------------------------------------------------------------------------

/// Place *n* components on a board using a simple spring-force model.
///
/// Args:
///     n: number of components
///     width_mm: board width
///     height_mm: board height
///     connections: list of (i, j) index pairs for connected components
///     min_spacing_mm: minimum distance between components
///
/// Returns: list of (x_mm, y_mm) tuples
#[pyfunction]
fn place_components(
    n: usize,
    width_mm: f64,
    height_mm: f64,
    connections: Vec<(usize, usize)>,
    min_spacing_mm: f64,
) -> PyResult<Vec<(f64, f64)>> {
    if n == 0 {
        return Ok(Vec::new());
    }

    let margin = min_spacing_mm.max(5.0);
    let grid_cols = ((n as f64 * width_mm / height_mm).sqrt().ceil() as usize).max(1);
    let grid_rows = (n as f64 / grid_cols as f64).ceil() as usize;
    let cell_w = (width_mm - 2.0 * margin) / grid_cols as f64;
    let cell_h = (height_mm - 2.0 * margin) / grid_rows as f64;

    // Initial grid placement
    let mut positions: Vec<(f64, f64)> = (0..n)
        .map(|idx| {
            let col = idx % grid_cols;
            let row = idx / grid_cols;
            (
                margin + col as f64 * cell_w + cell_w / 2.0,
                margin + row as f64 * cell_h + cell_h / 2.0,
            )
        })
        .collect();

    // Force-directed refinement
    let spring_k = 0.05;
    let repulsion_strength = 2.0;
    let repulsion_radius = 10.0;

    for _ in 0..20 {
        let mut forces: Vec<(f64, f64)> = vec![(0.0, 0.0); n];

        // Spring attraction along connections
        for &(a, b) in &connections {
            if a >= n || b >= n {
                return Err(PyValueError::new_err(format!(
                    "Connection index out of bounds: ({}, {}) for n={}",
                    a, b, n
                )));
            }
            let (ax, ay) = positions[a];
            let (bx, by) = positions[b];
            let dx = bx - ax;
            let dy = by - ay;
            forces[a].0 += spring_k * dx;
            forces[a].1 += spring_k * dy;
            forces[b].0 -= spring_k * dx;
            forces[b].1 -= spring_k * dy;
        }

        // Coulomb repulsion
        for i in 0..n {
            for j in (i + 1)..n {
                let (ax, ay) = positions[i];
                let (bx, by) = positions[j];
                let dx = bx - ax;
                let dy = by - ay;
                let dist = (dx * dx + dy * dy).sqrt().max(0.1);
                if dist < repulsion_radius {
                    let rep = repulsion_strength / (dist * dist);
                    let fx = -rep * dx / dist;
                    let fy = -rep * dy / dist;
                    forces[i].0 += fx;
                    forces[i].1 += fy;
                    forces[j].0 -= fx;
                    forces[j].1 -= fy;
                }
            }
        }

        // Apply forces and clamp
        for i in 0..n {
            let (x, y) = positions[i];
            let new_x = (x + forces[i].0).clamp(margin, width_mm - margin);
            let new_y = (y + forces[i].1).clamp(margin, height_mm - margin);
            positions[i] = (new_x, new_y);
        }
    }

    Ok(positions)
}

// ---------------------------------------------------------------------------
// Routing
// ---------------------------------------------------------------------------

/// Route connections using a simple Manhattan L-shape via minimum spanning tree.
///
/// Args:
///     points: list of (x, y) positions
///
/// Returns: list of (x1, y1, x2, y2) segments forming the MST
#[pyfunction]
fn route_mst(points: Vec<(f64, f64)>) -> PyResult<Vec<(f64, f64, f64, f64)>> {
    let n = points.len();
    if n < 2 {
        return Ok(Vec::new());
    }

    // Prim's algorithm
    let mut in_mst = vec![false; n];
    in_mst[0] = true;
    let mut edges: Vec<(usize, usize)> = Vec::with_capacity(n - 1);

    for _ in 0..(n - 1) {
        let mut best_dist = f64::MAX;
        let mut best_i = 0;
        let mut best_j = 1;

        for i in 0..n {
            if !in_mst[i] {
                continue;
            }
            for j in 0..n {
                if in_mst[j] {
                    continue;
                }
                let dx = points[i].0 - points[j].0;
                let dy = points[i].1 - points[j].1;
                let dist = (dx * dx + dy * dy).sqrt();
                if dist < best_dist {
                    best_dist = dist;
                    best_i = i;
                    best_j = j;
                }
            }
        }

        edges.push((best_i, best_j));
        in_mst[best_j] = true;
    }

    // Build Manhattan L-shape segments
    let mut segments: Vec<(f64, f64, f64, f64)> = Vec::with_capacity(edges.len() * 2);
    for &(i, j) in &edges {
        let (x1, y1) = points[i];
        let (x2, y2) = points[j];
        // L-shape: horizontal then vertical
        segments.push((x1, y1, x2, y1));
        segments.push((x2, y1, x2, y2));
    }

    Ok(segments)
}

// ---------------------------------------------------------------------------
// Shove router
// ---------------------------------------------------------------------------

/// Outcome of a single shove step.
#[derive(Clone)]
struct ShoveOutcome {
    /// Resolved trace segments (x1, y1, x2, y2).
    segments: Vec<(f64, f64, f64, f64)>,
    /// Provenance string describing the resolution strategy.
    provenance: String,
    /// Whether a walkaround solution was found.
    resolved: bool,
}

/// Axis-aligned bounding box for an obstacle.
#[allow(clippy::too_many_arguments)]
fn aabb_overlap(
    ax1: f64,
    ay1: f64,
    ax2: f64,
    ay2: f64,
    bx1: f64,
    by1: f64,
    bx2: f64,
    by2: f64,
) -> bool {
    ax1.min(ax2) < bx1.max(bx2)
        && ax1.max(ax2) > bx1.min(bx2)
        && ay1.min(ay2) < by1.max(by2)
        && ay1.max(ay2) > by1.min(by2)
}

/// Try a walkaround detour for a trace crossing an obstacle.
///
/// Generates a deterministic 3-segment L+detour path that bypasses the
/// obstacle bounding box.  Returns the resolved segments and provenance if
/// the detour clears the obstacle; otherwise returns the original L-path.
#[allow(clippy::too_many_arguments)]
fn try_shove_walkaround(
    x1: f64,
    y1: f64,
    x2: f64,
    y2: f64,
    obstacles: &[(f64, f64, f64, f64)],
    clearance: f64,
) -> ShoveOutcome {
    // Build the naive L-path (horizontal then vertical)
    let naive: Vec<(f64, f64, f64, f64)> = vec![(x1, y1, x2, y1), (x2, y1, x2, y2)];

    // Check whether naive path conflicts with any obstacle
    let naive_blocked = obstacles.iter().any(|&(ox1, oy1, ox2, oy2)| {
        aabb_overlap(x1, y1, x2, y1, ox1, oy1, ox2, oy2)
            || aabb_overlap(x2, y1, x2, y2, ox1, oy1, ox2, oy2)
    });

    if !naive_blocked {
        return ShoveOutcome {
            segments: naive,
            provenance: "direct-l-path".into(),
            resolved: true,
        };
    }

    // Attempt a walkaround: detour above all obstacle bounding boxes
    let detour_y = obstacles
        .iter()
        .map(|&(_, _, _, oy2)| oy2 + clearance)
        .fold(f64::NEG_INFINITY, f64::max)
        .max(y1.max(y2) + clearance);

    // 3-segment path: (x1,y1)→(x1,detour_y)→(x2,detour_y)→(x2,y2)
    let walkaround: Vec<(f64, f64, f64, f64)> = vec![
        (x1, y1, x1, detour_y),
        (x1, detour_y, x2, detour_y),
        (x2, detour_y, x2, y2),
    ];

    let walkaround_blocked = obstacles.iter().any(|&(ox1, oy1, ox2, oy2)| {
        walkaround
            .iter()
            .any(|&(sx1, sy1, sx2, sy2)| aabb_overlap(sx1, sy1, sx2, sy2, ox1, oy1, ox2, oy2))
    });

    if !walkaround_blocked {
        return ShoveOutcome {
            segments: walkaround,
            provenance: format!("walkaround-above-y{:.3}", detour_y),
            resolved: true,
        };
    }

    // Fallback: return naive path with a no-solution provenance
    ShoveOutcome {
        segments: naive,
        provenance: "no-solution-naive-fallback".into(),
        resolved: false,
    }
}

/// Route a rubber-band sketch through a shove kernel.
///
/// Route a rubber-band sketch through a shove kernel.
///
/// Each connection is represented as a (x1, y1, x2, y2, net_id) tuple.
/// Obstacles are bounding boxes (x1, y1, x2, y2).  The engine resolves
/// crossings using a deterministic walkaround strategy and returns the
/// routed segments with provenance.
///
/// Args:
///     connections: list of (x1, y1, x2, y2, net_id) tuples
///     obstacles:   list of (x1, y1, x2, y2) obstacle bounding boxes
///     clearance:   minimum clearance distance (mm)
///
/// Returns:
///     list of tuples: (net_id: str, provenance: str, resolved: bool, segments: list of (x1,y1,x2,y2))
#[pyfunction]
#[allow(clippy::type_complexity)]
fn route_shove(
    connections: Vec<(f64, f64, f64, f64, String)>,
    obstacles: Vec<(f64, f64, f64, f64)>,
    clearance: f64,
) -> PyResult<Vec<(String, String, bool, Vec<(f64, f64, f64, f64)>)>> {
    if clearance < 0.0 {
        return Err(PyValueError::new_err("clearance must be non-negative"));
    }

    let mut results = Vec::with_capacity(connections.len());

    for (x1, y1, x2, y2, net_id) in connections {
        let outcome = try_shove_walkaround(x1, y1, x2, y2, &obstacles, clearance);
        results.push((
            net_id,
            outcome.provenance,
            outcome.resolved,
            outcome.segments,
        ));
    }

    Ok(results)
}

// ---------------------------------------------------------------------------
// Module registration
// ---------------------------------------------------------------------------

#[pymodule]
fn _core(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(place_components, m)?)?;
    m.add_function(wrap_pyfunction!(route_mst, m)?)?;
    m.add_function(wrap_pyfunction!(route_shove, m)?)?;
    Ok(())
}
