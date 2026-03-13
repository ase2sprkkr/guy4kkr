from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence
import numpy as np
from itertools import product
import matplotlib.pyplot as plt
from matplotlib import cm
from matplotlib.colors import to_hex

_SITE_ROLE_STYLES = {
    'inactive': {
        'color': '#7cc6ff',
        'edgecolor': '#1c4b73',
        'linewidths': 0.6,
        's': 42,
    },
    'focused': {
        'color': '#8a8a8a',
        'edgecolor': 'none',
        'linewidths': 0.0,
        's': 56,
    },
    'active': {
        'color': '#ff3232',
        'edgecolor': 'black',
        'linewidths': 1.0,
        's': 68,
    },
}

PREVIEW_SITE_STYLE = {
    'edgecolor': 'black',
    'linewidths': 0.9,
    's': 40,
}


def _spacegroup_kinds_from_atoms(atoms: Any, count: int) -> list[Any]:
    arrays = getattr(atoms, 'arrays', {})
    kinds = arrays.get('spacegroup_kinds')
    if kinds is None:
        return list(range(count))
    return list(kinds)


def compute_site_colors(atoms: Any) -> Dict[Any, str]:
    scaled = np.asarray(atoms.get_scaled_positions(wrap=False), dtype=float)
    kinds = _spacegroup_kinds_from_atoms(atoms, len(scaled))

    ordered_kinds: list[Any] = []
    seen_keys: set[Any] = set()
    for kind in kinds:
        try:
            key = ('h', kind)
            hash(key)
        except Exception:
            key = ('r', repr(kind))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        ordered_kinds.append(kind)

    cmap = cm.get_cmap('tab20', max(len(ordered_kinds), 1))
    base_colors = list(getattr(cmap, 'colors', []))
    if not base_colors:
        steps = max(len(ordered_kinds), 1)
        base_colors = [cmap(i / max(steps - 1, 1)) for i in range(steps)]

    colors: Dict[Any, str] = {}
    n = len(base_colors)
    for idx, kind in enumerate(ordered_kinds):
        rgba = base_colors[idx % n]
        colors[kind] = to_hex(rgba)
    return colors


def plot_atoms_preview(
    ax,
    atoms: Optional[Any],
    *,
    canvas=None,
    clear_axes: bool = True,
    axis_on: bool = True,
    fallback_lattice=None,
    hovered_atom_indices: Optional[Sequence[int] | int] = None,
    site_colors: Optional[Dict[Any, str]] = None,
    base_style: Optional[Dict[str, Any]] = None,
    hovered_style: Optional[Dict[str, Any]] = None,
    default_color: str = '#1f77b4',
    extra_draw: Optional[Callable[[Any, Optional[Any], Optional[np.ndarray]], None]] = None,
    fit_to_atoms: bool = False,
    fit_to_cell: bool = False,
) -> Dict[Any, str]:
    if clear_axes:
        ax.clear()
    try:
        ax.set_position([0.03, 0.03, 0.94, 0.94])
    except Exception:
        pass
    if axis_on:
        ax.set_axis_on()

    lattice = None
    if atoms is not None:
        lattice = np.asarray(atoms.get_cell(), dtype=float)
    elif fallback_lattice is not None:
        lattice = np.asarray(fallback_lattice, dtype=float)

    if lattice is not None:
        plot_lattice(ax, lattice)

    if atoms is None:
        if extra_draw is not None:
            extra_draw(ax, None, lattice)
        if canvas is not None:
            canvas.draw_idle()
        return site_colors or {}

    scaled = np.asarray(atoms.get_scaled_positions(wrap=False), dtype=float)
    if scaled.size == 0:
        if extra_draw is not None:
            extra_draw(ax, atoms, lattice)
        if canvas is not None:
            canvas.draw_idle()
        return site_colors or {}

    kinds = _spacegroup_kinds_from_atoms(atoms, len(scaled))
    color_map = site_colors if site_colors is not None else compute_site_colors(atoms)

    if hovered_atom_indices is None:
        hovered_set: set[int] = set()
    elif isinstance(hovered_atom_indices, int):
        hovered_set = {hovered_atom_indices}
    else:
        hovered_set = {int(idx) for idx in hovered_atom_indices}
    hovered_set = {idx for idx in hovered_set if 0 <= idx < len(scaled)}

    style = dict(PREVIEW_SITE_STYLE)
    if base_style:
        style.update(base_style)

    ordered_kinds: list[Any] = []
    seen_keys: set[Any] = set()
    for kind in kinds:
        try:
            key = ('h', kind)
            hash(key)
        except Exception:
            key = ('r', repr(kind))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        ordered_kinds.append(kind)

    for kind in ordered_kinds:
        selected_indices = [
            idx for idx, this_kind in enumerate(kinds)
            if this_kind == kind and idx not in hovered_set
        ]
        if not selected_indices:
            continue
        kind_style = dict(style)
        kind_style['color'] = color_map.get(kind, default_color)
        plot_sites_in_lattice(ax, lattice, scaled[selected_indices], **kind_style)

    focus_style = dict(style)
    focus_style.setdefault('color', 'black')
    focus_style['color'] = 'black'
    focus_style['s'] = int(float(focus_style.get('s', 40)) * 1.5)
    if hovered_style:
        focus_style.update(hovered_style)

    for idx in sorted(hovered_set):
        plot_sites_in_lattice(ax, lattice, scaled[idx], **focus_style)

    if fit_to_atoms:
        cart = np.asarray(atoms.get_positions(), dtype=float)
        if len(cart) >= 20:
            mins = np.percentile(cart, 2.0, axis=0)
            maxs = np.percentile(cart, 98.0, axis=0)
        else:
            mins = cart.min(axis=0)
            maxs = cart.max(axis=0)
        center = (mins + maxs) / 2.0
        spans = np.maximum(maxs - mins, 1e-6)
        padding = 0.10 * spans
        half = (spans + 2.0 * padding) / 2.0
        ax.set_xlim(center[0] - half[0], center[0] + half[0])
        ax.set_ylim(center[1] - half[1], center[1] + half[1])
        ax.set_zlim(center[2] - half[2], center[2] + half[2])
        ax.set_autoscale_on(False)

    elif fit_to_cell and lattice is not None:
        corners = corner_indices.T @ lattice
        mins = corners.min(axis=0)
        maxs = corners.max(axis=0)
        spans = np.maximum(maxs - mins, 1e-6)
        padding = 0.05 * spans
        mins = mins - padding
        maxs = maxs + padding
        ax.set_xlim(mins[0], maxs[0])
        ax.set_ylim(mins[1], maxs[1])
        ax.set_zlim(mins[2], maxs[2])
        try:
            ax.set_box_aspect(tuple(spans.tolist()))
        except Exception:
            pass
        ax.set_autoscale_on(False)

    if extra_draw is not None:
        extra_draw(ax, atoms, lattice)

    if canvas is not None:
        canvas.draw_idle()

    return color_map


def scale_lattice_to_lengths(lattice, lengths):
    lattice_array = np.asarray(lattice, dtype=float)
    if lattice_array.shape != (3, 3):
        raise ValueError("Lattice must be a 3x3 matrix of row vectors.")

    target_lengths = np.asarray(lengths, dtype=float)
    if target_lengths.shape != (3,):
        raise ValueError("Lengths must contain exactly three values: a, b, c.")
    if (target_lengths <= 0).any():
        raise ValueError("Lattice constants must be positive numbers.")

    original_lengths = np.linalg.norm(lattice_array, axis=1)
    if np.isclose(original_lengths, 0.0).any():
        raise ValueError("Cannot scale structure with zero lattice constant.")

    factors = target_lengths / original_lengths
    scaled_lattice = lattice_array.copy()
    for axis in range(3):
        scaled_lattice[axis] = lattice_array[axis] * factors[axis]
    return scaled_lattice

def bounding_box_corners(corners, preserve_ratio=True, padding=0.05):
    """
    Compute bounding box corners of a hexahedron.

    Parameters:
        corners: np.array of shape [8,3] - 3D coordinates of the hexahedron
        preserve_ratio: bool - if True, scales the box to preserve ratios (cube)

    Returns:
        min_corner: np.array of shape [3] - one corner of the bounding box
        max_corner: np.array of shape [3] - opposite corner of the bounding box
    """
    corners = np.asarray(corners)
    assert corners.shape == (8,3), "Input must be [8,3] array"

    min_corner = corners.min(axis=0)
    max_corner = corners.max(axis=0)

    padding += 0.5
    if preserve_ratio:
        # make it cube-like, take max side length
        max_side = (max_corner - min_corner).max()
        center = (max_corner + min_corner) / 2
        min_corner = center - padding * max_side
        max_corner = center + padding * max_side
    elif padding > 0:
        diff = max_corner - min_corner
        min_corner -= padding * diff
        max_corner += padding * diff

    return min_corner, max_corner

corner_indices = np.array(list(product((0,1), repeat=3))).T
edge_indices =np.array([(0,1),(0,2),(0,4),(7,6),(7,5),(7,3),(1,3),(1,5),(2,3),(2,6),(4,5),(4,6)])


def plot_lattice(ax, lattice):
    """
    Plot a lattice defined by its vectors on a given 3D axis.

    Parameters:
        ax: matplotlib 3D axis
        lattice: np.array of shape [3,3] - lattice vectors as rows
    """

    ax.figure.suptitle("")

    # draw cell
    corners = corner_indices.T @ lattice

    edges = corners[edge_indices]
    for edge in edges:
            ax.plot(edge[:, 0], edge[:, 1], edge[:, 2], color='black', linewidth=0.8)

    ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])
    mn,mx = bounding_box_corners(corners)
    ax.set_xlim(mn[0], mx[0])
    ax.set_ylim(mn[1], mx[1])
    ax.set_zlim(mn[2], mx[2])

def plot_sites_in_lattice(ax, lattice, points, *, role: str | None = None, **kwargs):
    """Plot atomic sites inside a lattice using role-based styling.

    Parameters
    ----------
    ax
        Matplotlib 3D axis to draw on.
    lattice
        ``(3, 3)`` array (rows are lattice vectors) or ``False``/``None`` to skip conversion.
    points
        Fractional coordinates ``(N, 3)`` or an iterable of such arrays.
    role
        Optional semantic role: ``'inactive'``, ``'focused'``, or ``'active'`` to apply
        consistent coloring with the Qt space-group selector.
    kwargs
        Forwarded to ``ax.scatter`` and override role defaults when provided.
    """
    if isinstance(points, (list, tuple)):
        if not points:
            return
        points = np.vstack(points)

    points = np.asarray(points, dtype=float)
    if points.size == 0:
        return
    if points.ndim == 1:
        if points.shape[0] != 3:
            return
        points = points.reshape(1, 3)

    config = {
        's': 25,
        'depthshade': False,
    }

    if role:
        style = _SITE_ROLE_STYLES.get(role)
        if style:
            for key, value in style.items():
                config.setdefault(key, value)

    config.update(kwargs)

    if 'color' not in config:
        config['color'] = 'red'

    if lattice is not False and lattice is not None:
        points = np.dot(points, lattice)

    ax.scatter(*points.T, **config)
