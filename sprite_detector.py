from __future__ import annotations

import cv2
import numpy as np
from PIL import Image


def detect_sprites(
    rgba_image: Image.Image,
    min_area: int = 500,
    padding: int = 4,
) -> list[tuple[int, int, int, int]]:
    """Return bounding boxes (x1, y1, x2, y2) for each detected sprite.

    Detection is based on the alpha channel — any region of opaque pixels
    that forms a connected component larger than min_area is treated as one
    sprite. Results are sorted top-to-bottom, left-to-right (row-major).
    """
    arr = np.array(rgba_image.convert("RGBA"), dtype=np.uint8)
    alpha = arr[:, :, 3]
    h, w = alpha.shape

    binary = (alpha > 10).astype(np.uint8) * 255

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )

    bboxes: list[tuple[int, int, int, int]] = []
    for lbl in range(1, num_labels):
        area = int(stats[lbl, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        x = int(stats[lbl, cv2.CC_STAT_LEFT])
        y = int(stats[lbl, cv2.CC_STAT_TOP])
        bw = int(stats[lbl, cv2.CC_STAT_WIDTH])
        bh = int(stats[lbl, cv2.CC_STAT_HEIGHT])

        x1 = max(0, x - padding)
        y1 = max(0, y - padding)
        x2 = min(w, x + bw + padding)
        y2 = min(h, y + bh + padding)
        bboxes.append((x1, y1, x2, y2))

    bboxes.sort(key=lambda b: ((b[1] + b[3]) // 2, (b[0] + b[2]) // 2))
    return bboxes


def _bbox_sort(bboxes: list) -> list:
    return sorted(bboxes, key=lambda b: ((b[1] + b[3]) // 2, (b[0] + b[2]) // 2))


def _union_find_groups(n: int, pairs: list[tuple[int, int]]) -> dict[int, list[int]]:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        pa, pb = find(a), find(b)
        if pa != pb:
            parent[pa] = pb

    groups: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)
    return groups


def _merge_groups(bboxes: list, groups: dict) -> list:
    result = []
    for indices in groups.values():
        x1 = min(bboxes[i][0] for i in indices)
        y1 = min(bboxes[i][1] for i in indices)
        x2 = max(bboxes[i][2] for i in indices)
        y2 = max(bboxes[i][3] for i in indices)
        result.append((x1, y1, x2, y2))
    return _bbox_sort(result)


def merge_nearby_bboxes(
    bboxes: list[tuple[int, int, int, int]],
    distance: int,
) -> list[tuple[int, int, int, int]]:
    """Merge bounding boxes whose edges are within `distance` pixels of each other.

    Useful for grouping a main sprite with nearby sparkles / accessories that
    were detected as separate components.
    """
    if distance <= 0 or len(bboxes) < 2:
        return bboxes

    n = len(bboxes)
    pairs: list[tuple[int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            x1a, y1a, x2a, y2a = bboxes[i]
            x1b, y1b, x2b, y2b = bboxes[j]
            h_gap = max(0, max(x1a, x1b) - min(x2a, x2b))
            v_gap = max(0, max(y1a, y1b) - min(y2a, y2b))
            if h_gap <= distance and v_gap <= distance:
                pairs.append((i, j))

    return _merge_groups(bboxes, _union_find_groups(n, pairs))


def apply_manual_merges(
    bboxes: list[tuple[int, int, int, int]],
    merge_spec: str,
) -> list[tuple[int, int, int, int]]:
    """Merge bboxes by 1-based index groups specified as a string.

    Format: "1+3, 5+7+8"
      — comma-separated groups
      — sprites in a group joined by +
      — numbers match the labels shown in the preview
    """
    if not merge_spec.strip() or not bboxes:
        return bboxes

    n = len(bboxes)
    pairs: list[tuple[int, int]] = []

    for group_str in merge_spec.split(","):
        indices: list[int] = []
        for part in group_str.split("+"):
            try:
                idx = int(part.strip()) - 1   # 1-based → 0-based
                if 0 <= idx < n:
                    indices.append(idx)
            except ValueError:
                pass
        for k in range(1, len(indices)):
            pairs.append((indices[0], indices[k]))

    if not pairs:
        return bboxes

    return _merge_groups(bboxes, _union_find_groups(n, pairs))


def _make_checkerboard(w: int, h: int, square: int = 16) -> np.ndarray:
    xs = np.arange(w) // square
    ys = np.arange(h) // square
    pattern = (xs[np.newaxis, :] + ys[:, np.newaxis]) % 2  # 0 or 1
    light = np.array([220, 220, 220], dtype=np.uint8)
    dark  = np.array([160, 160, 160], dtype=np.uint8)
    board = np.where(pattern[:, :, np.newaxis] == 0, light, dark).astype(np.uint8)
    return board  # shape (h, w, 3)


def draw_bboxes(
    rgba_image: Image.Image,
    bboxes: list[tuple[int, int, int, int]],
    bg: str = "black",          # "black" | "white" | "checker"
) -> Image.Image:
    """Return a copy of the image composited onto bg, with red bounding boxes."""
    w, h = rgba_image.size
    alpha_np = np.array(rgba_image.split()[3], dtype=np.float32) / 255.0
    rgb_np   = np.array(rgba_image.convert("RGB"), dtype=np.float32)

    # Build background canvas
    if bg == "checker":
        canvas = _make_checkerboard(w, h).astype(np.float32)
    elif bg == "white":
        canvas = np.full((h, w, 3), 255.0, dtype=np.float32)
    else:  # black
        canvas = np.zeros((h, w, 3), dtype=np.float32)

    # Alpha-composite sprite over canvas
    a3 = alpha_np[:, :, np.newaxis]
    vis = (rgb_np * a3 + canvas * (1.0 - a3)).astype(np.uint8)

    # Draw red bounding boxes + index numbers
    for i, (x1, y1, x2, y2) in enumerate(bboxes):
        cv2.rectangle(vis, (x1, y1), (x2, y2), (220, 30, 30), 2)
        cv2.putText(
            vis, str(i + 1), (x1 + 2, y1 + 14),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220, 30, 30), 1,
            cv2.LINE_AA,
        )

    return Image.fromarray(vis, "RGB")
