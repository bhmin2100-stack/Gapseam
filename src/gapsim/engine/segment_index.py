"""Static segment BVH rebuilt once per evolving surface, not once per ray."""
from __future__ import annotations


class SegmentIndex:
    def __init__(self, points):
        self.bounds = [(min(a[0], b[0]), min(a[1], b[1]),
                        max(a[0], b[0]), max(a[1], b[1]))
                       for a, b in zip(points, points[1:])]
        self.root = self._build(list(range(len(self.bounds)))) if self.bounds else None

    def _build(self, indices):
        boxes = [self.bounds[i] for i in indices]
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes))
        if len(indices) <= 8:
            return box, indices, None, None
        axis = 0 if box[2]-box[0] > box[3]-box[1] else 1
        indices.sort(key=lambda i: self.bounds[i][axis]+self.bounds[i][axis+2])
        mid = len(indices)//2
        return box, None, self._build(indices[:mid]), self._build(indices[mid:])

    @staticmethod
    def _intersects(box, origin, direction, distance):
        lo, hi = 0., distance
        for axis in (0, 1):
            lower, upper = box[axis]-1e-8, box[axis+2]+1e-8
            d, o = direction[axis], origin[axis]
            if abs(d) < 1e-15:
                if o < lower or o > upper:
                    return False
            else:
                a, b = (lower-o)/d, (upper-o)/d
                lo, hi = max(lo, min(a,b)), min(hi, max(a,b))
                if lo > hi:
                    return False
        return True

    def ray_candidates(self, origin, direction, distance):
        stack = [self.root] if self.root is not None else []
        result = []
        while stack:
            box, leaf, left, right = stack.pop()
            if not self._intersects(box, origin, direction, distance):
                continue
            if leaf is not None:
                result.extend(i for i in leaf if self._intersects(
                    self.bounds[i], origin, direction, distance))
            else:
                stack.extend((left, right))
        return sorted(result)  # Preserve tie-breaking at shared endpoints.
