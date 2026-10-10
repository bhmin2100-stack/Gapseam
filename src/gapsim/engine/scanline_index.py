"""Exact candidate pruning for horizontal intersections of one static profile.

The interval tree is rebuilt for each changed profile. It only selects segment
indices; the caller retains its existing intersection arithmetic and tolerances.
"""
from __future__ import annotations

import math


class ScanlineIndex:
    def __init__(self, points, *, epsilon=1e-9):
        self.intervals = []
        for i, (a, b) in enumerate(zip(points, points[1:])):
            ay, by = float(a[1]), float(b[1])
            if math.isclose(ay, by, rel_tol=0., abs_tol=epsilon):
                continue
            self.intervals.append((min(ay, by)-epsilon, max(ay, by)+epsilon, i))
        self.root = self._build(self.intervals)

    @classmethod
    def _build(cls, intervals):
        if not intervals:
            return None
        centers = sorted((low+high)*.5 for low, high, _ in intervals)
        center = centers[len(centers)//2]
        left, right, crossing = [], [], []
        for item in intervals:
            low, high, _ = item
            if high < center:
                left.append(item)
            elif low > center:
                right.append(item)
            else:
                crossing.append(item)
        return (center, sorted(crossing, key=lambda item: item[0]),
                sorted(crossing, key=lambda item: item[1], reverse=True),
                cls._build(left), cls._build(right))

    def candidates(self, y):
        result = []
        node = self.root
        while node is not None:
            center, lower, upper, left, right = node
            if y < center:
                for low, _high, index in lower:
                    if low > y:
                        break
                    result.append(index)
                node = left
            else:
                for _low, high, index in upper:
                    if high < y:
                        break
                    result.append(index)
                node = right
        return sorted(result)
