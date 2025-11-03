import numpy as np
from itertools import product
import matplotlib.pyplot as plt

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

def plot_sites_in_lattice(ax, lattice, points):
    """
    Plot atomic sites within a lattice on a given 3D axis.
    Parameters:
        ax: matplotlib 3D axis
        lattice: np.array of shape [3,3] - lattice vectors as rows
        points: iterable of np.array of shape [N,3] - fractional coordinates of atomic sites by kinds
    """
    cmap = plt.get_cmap("Set1")
    i = 0

    for pos in points:
        color = cmap(i % 20)
        i += 1
        if lattice is not False:
            pos = np.dot(pos, lattice)
        ax.scatter(*pos.T, color=color, s=25, depthshade=False)
