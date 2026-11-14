"""Cluster subjects by face similarity for within-album bib propagation.

Uses cosine similarity and greedy single-link merging, subject to cannot-link
constraints. Embeddings use plain Python sequences to keep NumPy out of core.
"""

import math
from collections.abc import Hashable, Iterable, Sequence
from typing import NamedTuple

from startnummer.core.types import Embedding

DEFAULT_MIN_SIMILARITY = 0.45  # placeholder; calibrate against bib-labeled pairs


class FaceItem(NamedTuple):
    key: Hashable  # caller-defined identity, e.g. (record_index, subject_index)
    embeddings: Sequence[Embedding]  # one subject may carry several face reads


def cosine_similarity(a: Embedding, b: Embedding) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _best_similarity(a: FaceItem, b: FaceItem) -> float:
    # Single-link at subject level: the closest embedding pair decides.
    return max(
        (cosine_similarity(ea, eb) for ea in a.embeddings for eb in b.embeddings),
        default=0.0,
    )


def cluster_faces(
    items: Sequence[FaceItem],
    *,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    cannot_link: Iterable[tuple[Hashable, Hashable]] = (),
) -> list[list[Hashable]]:
    """Groups items by face similarity; singletons included.

    cannot_link pairs (by key) are never placed in the same cluster; unknown
    keys in a pair are ignored. Greedy merge by descending similarity, so when
    a face is similar to two mutually-exclusive identities it joins the closer.
    """
    index = {item.key: i for i, item in enumerate(items)}
    forbidden = {frozenset((index[a], index[b])) for a, b in cannot_link if a in index and b in index and a != b}

    parent = list(range(len(items)))
    members: dict[int, set[int]] = {i: {i} for i in range(len(items))}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    candidates = [
        (similarity, i, j)
        for i in range(len(items))
        for j in range(i + 1, len(items))
        if (similarity := _best_similarity(items[i], items[j])) >= min_similarity
    ]
    candidates.sort(reverse=True)

    for _, i, j in candidates:
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        if any(frozenset((a, b)) in forbidden for a in members[ri] for b in members[rj]):
            continue
        parent[rj] = ri
        members[ri] |= members.pop(rj)

    groups: dict[int, list[Hashable]] = {}
    for i, item in enumerate(items):
        groups.setdefault(find(i), []).append(item.key)
    return list(groups.values())
