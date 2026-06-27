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
// Module registration
// ---------------------------------------------------------------------------

#[pymodule]
fn _core(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(place_components, m)?)?;
    m.add_function(wrap_pyfunction!(route_mst, m)?)?;
    Ok(())
}
