"""Min-cost bipartite assignment (Hungarian algorithm).

Used to assign faces to persons jointly: per-item greedy ownership cannot enforce
"at most one face per person" and picks locally-best pairs that strand the rest,
whereas the global minimum-cost matching resolves exactly the swap cases dense
scenes produce.
"""

import math
from collections.abc import Sequence

FORBIDDEN = math.inf


def min_cost_assignment(costs: Sequence[Sequence[float]]) -> list[int | None]:
    """For each row, the assigned column index, or None if left unassigned.

    costs is rectangular (rows x cols); FORBIDDEN marks impossible pairs. The
    matrix is padded square with dummy cells, so rows can stay unassigned and
    a row whose real options are all taken or FORBIDDEN comes back None.
    """
    n_rows = len(costs)
    n_cols = len(costs[0]) if n_rows else 0
    size = max(n_rows, n_cols)
    if size == 0:
        return []

    # Real FORBIDDEN cells get a finite sentinel bigger than any real total so the
    # algorithm terminates; dummy cells cost less than the sentinel, so forbidden
    # pairs always lose to "leave unassigned".
    finite = [c for row in costs for c in row if not math.isinf(c)]
    sentinel = (max(finite, default=0.0) + 1.0) * (size + 1)
    dummy = sentinel / 2

    matrix = [[dummy] * size for _ in range(size)]
    for r in range(n_rows):
        for c in range(n_cols):
            matrix[r][c] = sentinel if math.isinf(costs[r][c]) else costs[r][c]
    for r in range(n_rows, size):  # dummy rows absorb surplus columns
        for c in range(size):
            matrix[r][c] = 0.0

    # Standard O(n^3) Hungarian with row/column potentials (1-based internals).
    INF = math.inf
    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    match_col = [0] * (size + 1)  # match_col[c] = row assigned to column c

    for row in range(1, size + 1):
        match_col[0] = row
        j0 = 0
        minv = [INF] * (size + 1)
        way = [0] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[j0] = True
            i0 = match_col[j0]
            delta, j1 = INF, 0
            for j in range(1, size + 1):
                if used[j]:
                    continue
                cur = matrix[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(size + 1):
                if used[j]:
                    u[match_col[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if match_col[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            match_col[j0] = match_col[j1]
            j0 = j1

    assignment: list[int | None] = [None] * n_rows
    for col in range(1, size + 1):
        row = match_col[col]
        if (
            1 <= row <= n_rows
            and col <= n_cols
            and not math.isinf(costs[row - 1][col - 1])
        ):
            assignment[row - 1] = col - 1
    return assignment
