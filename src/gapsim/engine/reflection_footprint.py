"""Prune unchanged model6 receiving-footprint sums, without a new transport law."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import math


class ReflectionFootprintIndex:
    def __init__(self, points, normals, arc_coordinates, areas, center_x):
        self.arc = arc_coordinates
        self.areas = areas
        self.indices = {-1: [], 1: []}
        self.receiver_arc = {-1: [], 1: []}
        for idx, (x, _y) in enumerate(points):
            if idx >= len(arc_coordinates):
                continue
            if idx < len(normals) and abs(float(normals[idx][0])) < .12:
                continue
            side = -1 if float(x) < center_x else 1
            self.indices[side].append(idx)
            self.receiver_arc[side].append(arc_coordinates[idx])

    def weights(self, *, hit_side, hit_arc, sigma, radius):
        receiver_arc = self.receiver_arc[hit_side]
        indices = self.indices[hit_side]
        left = bisect_left(receiver_arc, hit_arc-radius)
        right = bisect_right(receiver_arc, hit_arc+radius)
        denominator = max(sigma, 1e-9)
        weights = []
        for idx in indices[left:right]:
            ds = abs(float(self.arc[idx])-hit_arc)
            if ds > radius:
                continue
            # Keep scalar exp, operator order and ascending summation order:
            # vector exp would introduce a separate rounding/convergence change.
            weight = self.areas[idx]*math.exp(-.5*(ds/denominator)**2)
            if weight > 0.:
                weights.append((idx, weight))
        return weights
