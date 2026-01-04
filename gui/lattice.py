from __future__ import annotations

import numpy as np
from itertools import product
import matplotlib.pyplot as plt

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
