from __future__ import annotations

import base64
from dataclasses import dataclass

import cv2
import numpy as np


class ImageDetectionError(ValueError):
    pass


@dataclass(frozen=True)
class FaceDetection:
    corners: list[list[float]]
    confidence: int
    method: str
    score: float


def decode_data_url(data_url: str) -> np.ndarray:
    if not isinstance(data_url, str) or "," not in data_url:
        raise ImageDetectionError("图片数据格式不正确")
    header, encoded = data_url.split(",", 1)
    if not header.startswith("data:image/"):
        raise ImageDetectionError("只支持图片数据")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ImageDetectionError("图片数据无法解码") from exc
    if not raw or len(raw) > 18 * 1024 * 1024:
        raise ImageDetectionError("图片为空或超过 18 MB")
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ImageDetectionError("图片无法读取")
    return image


def detect_face_data_url(data_url: str, grid_size: int = 3) -> FaceDetection | None:
    return detect_cube_face(decode_data_url(data_url), grid_size=grid_size)


def detect_cube_face(image: np.ndarray, grid_size: int = 3) -> FaceDetection | None:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ImageDetectionError("图片必须是彩色图像")
    if grid_size not in (2, 3):
        raise ImageDetectionError("只支持二阶或三阶魔方")

    original_height, original_width = image.shape[:2]
    scale = min(1.0, 1100.0 / max(original_width, original_height))
    if scale < 1:
        working = cv2.resize(
            image,
            (round(original_width * scale), round(original_height * scale)),
            interpolation=cv2.INTER_AREA,
        )
    else:
        working = image.copy()

    height, width = working.shape[:2]
    image_area = float(width * height)
    minimum_side = min(width, height)
    gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    hsv = cv2.cvtColor(working, cv2.COLOR_BGR2HSV)

    saturated = ((hsv[:, :, 1] > 38) & (hsv[:, :, 2] > 42)).astype(np.uint8) * 255
    white = ((hsv[:, :, 1] < 58) & (hsv[:, :, 2] > 145)).astype(np.uint8) * 255
    white = _remove_border_component(white)
    sticker_mask = cv2.bitwise_or(saturated, white)
    sticker_mask = cv2.morphologyEx(sticker_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    close_sizes = sorted(
        {
            max(3, _odd(round(minimum_side * 0.012))),
            max(5, _odd(round(minimum_side * 0.025))),
            max(7, _odd(round(minimum_side * 0.042))),
        }
    )
    contour_maps: list[tuple[str, np.ndarray]] = [("color", sticker_mask)]
    for kernel_size in close_sizes:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
        contour_maps.append(
            (f"color-close-{kernel_size}", cv2.morphologyEx(sticker_mask, cv2.MORPH_CLOSE, kernel))
        )

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    for low, high in ((28, 82), (55, 145), (90, 210)):
        edges = cv2.Canny(blurred, low, high)
        edge_kernel_size = max(3, _odd(round(minimum_side * 0.009)))
        edge_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (edge_kernel_size, edge_kernel_size))
        contour_maps.append((f"edge-{low}", cv2.morphologyEx(edges, cv2.MORPH_CLOSE, edge_kernel)))

    adaptive_block = max(21, _odd(round(minimum_side * 0.09)))
    adaptive = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        adaptive_block,
        5,
    )
    contour_maps.append(("adaptive", adaptive))

    candidates: list[tuple[np.ndarray, str]] = []
    cell_candidates: list[tuple[np.ndarray, float]] = []
    for method, binary in contour_maps:
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = abs(cv2.contourArea(contour))
            area_ratio = area / image_area
            if area_ratio < 0.00035 or area_ratio > 0.88:
                continue
            quad = _quad_from_contour(contour)
            if quad is None:
                continue
            quad_area = abs(cv2.contourArea(quad.astype(np.float32)))
            if quad_area <= 1:
                continue
            side_ratio = _side_ratio(quad)
            rectangularity = min(1.0, area / quad_area)
            if 0.008 <= quad_area / image_area <= 0.82 and side_ratio >= 0.28:
                candidates.append((quad, method))
            if (
                0.00045 <= quad_area / image_area <= 0.12
                and side_ratio >= 0.42
                and rectangularity >= 0.42
            ):
                cell_candidates.append((quad, rectangularity * side_ratio))

    cells = _deduplicate_cells(cell_candidates)
    candidates.extend(_fit_grid_candidates(cells, width, height, grid_size))
    if grid_size == 2:
        candidates.extend(_fit_2x2_pair_candidates(cells, width, height))
        candidates.extend(_expand_2x2_cell_candidates(cells, width, height))
    candidates.extend(_cluster_cell_candidates(cells, width, height))
    candidates = _deduplicate_candidates(candidates, width, height)

    scored_candidates: list[tuple[float, np.ndarray, str]] = []
    for quad, method in candidates[:160]:
        candidate_area_ratio = abs(cv2.contourArea(quad)) / image_area
        if grid_size == 2 and candidate_area_ratio < 0.055:
            continue
        if candidate_area_ratio < 0.035 and not method.startswith("grid-fit"):
            continue
        candidate_best_score = -1.0
        candidate_best_quad: np.ndarray | None = None
        for expansion in (0.96, 1.0, 1.04, 1.09):
            expanded = _expand_quad(quad, expansion, width, height)
            score = _score_face_candidate(working, expanded, grid_size)
            aligned_cells = 0
            if grid_size == 2:
                aligned_cells, alignment_score = _2x2_cell_alignment(cells, expanded)
                score += alignment_score * 0.24
            if method.startswith("grid-fit"):
                score += 0.065 if grid_size == 3 else 0.018
            elif method in {"cell-pair-2x2", "cell-2x2"}:
                score += 0.025
                if aligned_cells < 2:
                    score -= 0.16
            if score > candidate_best_score:
                candidate_best_score = score
                candidate_best_quad = expanded
        if candidate_best_quad is not None:
            scored_candidates.append((candidate_best_score, candidate_best_quad, method))

    scored_candidates.sort(key=lambda item: item[0], reverse=True)
    if not scored_candidates:
        return None
    best_score, best_quad, best_method = scored_candidates[0]

    if best_score < 0.50:
        return None

    normalized = [[float(point[0] / width), float(point[1] / height)] for point in best_quad]
    distinct_score = None
    for candidate_score, candidate_quad, _ in scored_candidates[1:]:
        if _quad_iou(best_quad, candidate_quad) < 0.62:
            distinct_score = candidate_score
            break
    score_floor, score_ceiling = ((0.72, 1.25) if grid_size == 2 else (0.62, 1.08))
    quality_score = float(
        np.clip((best_score - score_floor) / (score_ceiling - score_floor), 0.0, 1.0)
    )
    if distinct_score is None:
        margin_score = 1.0
    else:
        margin_score = float(np.clip((best_score - distinct_score) / 0.12, 0.0, 1.0))
    area_ratio = abs(cv2.contourArea(best_quad)) / image_area
    area_floor, area_ceiling = ((0.055, 0.18) if grid_size == 2 else (0.045, 0.24))
    area_score = float(np.clip((area_ratio - area_floor) / (area_ceiling - area_floor), 0.0, 1.0))
    confidence = round((quality_score * 0.55 + margin_score * 0.25 + area_score * 0.20) * 100)
    return FaceDetection(
        corners=normalized,
        confidence=int(confidence),
        method=best_method,
        score=round(quality_score, 4),
    )


def _remove_border_component(mask: np.ndarray) -> np.ndarray:
    padded = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    flood = padded.copy()
    flood_mask = np.zeros((flood.shape[0] + 2, flood.shape[1] + 2), np.uint8)
    height, width = mask.shape
    for x in range(1, width + 1):
        if flood[1, x]:
            cv2.floodFill(flood, flood_mask, (x, 1), 0)
        if flood[height, x]:
            cv2.floodFill(flood, flood_mask, (x, height), 0)
    for y in range(1, height + 1):
        if flood[y, 1]:
            cv2.floodFill(flood, flood_mask, (1, y), 0)
        if flood[y, width]:
            cv2.floodFill(flood, flood_mask, (width, y), 0)
    return flood[1:-1, 1:-1]


def _odd(value: int) -> int:
    return value if value % 2 else value + 1


def _quad_from_contour(contour: np.ndarray) -> np.ndarray | None:
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    if perimeter <= 0:
        return None
    for epsilon in (0.012, 0.018, 0.025, 0.035, 0.05, 0.075):
        polygon = cv2.approxPolyDP(hull, epsilon * perimeter, True)
        if len(polygon) == 4 and cv2.isContourConvex(polygon):
            return _order_quad(polygon.reshape(4, 2).astype(np.float32))
        if len(polygon) < 4:
            break
    rectangle = cv2.boxPoints(cv2.minAreaRect(hull)).astype(np.float32)
    return _order_quad(rectangle)


def _order_quad(points: np.ndarray) -> np.ndarray:
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]
    start = int(np.argmin(ordered[:, 0] + ordered[:, 1]))
    ordered = np.roll(ordered, -start, axis=0)
    if cv2.contourArea(ordered.astype(np.float32), oriented=True) < 0:
        ordered = ordered[[0, 3, 2, 1]]
    return ordered.astype(np.float32)


def _side_ratio(quad: np.ndarray) -> float:
    lengths = [np.linalg.norm(quad[(index + 1) % 4] - quad[index]) for index in range(4)]
    return float(min(lengths) / max(max(lengths), 1e-6))


def _deduplicate_cells(cells: list[tuple[np.ndarray, float]]) -> list[np.ndarray]:
    result: list[np.ndarray] = []
    for quad, quality in sorted(cells, key=lambda item: item[1], reverse=True):
        center = quad.mean(axis=0)
        size = np.sqrt(abs(cv2.contourArea(quad)))
        duplicate = False
        for existing in result:
            existing_center = existing.mean(axis=0)
            existing_size = np.sqrt(abs(cv2.contourArea(existing)))
            if np.linalg.norm(center - existing_center) < min(size, existing_size) * 0.32:
                duplicate = True
                break
        if not duplicate:
            result.append(quad)
    return result[:120]


def _fit_grid_candidates(
    cells: list[np.ndarray], width: int, height: int, grid_size: int = 3
) -> list[tuple[np.ndarray, str]]:
    candidates: list[tuple[np.ndarray, str]] = []
    if len(cells) < grid_size * 2:
        return candidates

    centers = np.array([quad.mean(axis=0) for quad in cells], dtype=np.float32)
    areas = np.array([max(abs(cv2.contourArea(quad)), 1.0) for quad in cells])
    side_ratios = np.array([_side_ratio(quad) for quad in cells])

    for seed_index, seed in enumerate(cells):
        if side_ratios[seed_index] < 0.64:
            continue
        top = seed[1] - seed[0]
        bottom = seed[2] - seed[3]
        left = seed[3] - seed[0]
        right = seed[2] - seed[1]
        axis_x = top + bottom
        axis_y = left + right
        spacing_x = (np.linalg.norm(top) + np.linalg.norm(bottom)) / 2
        spacing_y = (np.linalg.norm(left) + np.linalg.norm(right)) / 2
        if spacing_x < 3 or spacing_y < 3:
            continue
        axis_x /= max(np.linalg.norm(axis_x), 1e-6)
        axis_y /= max(np.linalg.norm(axis_y), 1e-6)
        spacing_x *= 1.045
        spacing_y *= 1.045

        relative = centers - centers[seed_index]
        projected_x = relative @ axis_x / spacing_x
        projected_y = relative @ axis_y / spacing_y
        grid_x = np.rint(projected_x).astype(int)
        grid_y = np.rint(projected_y).astype(int)
        residuals = np.hypot(projected_x - grid_x, projected_y - grid_y)
        area_ratios = areas / areas[seed_index]
        eligible = np.where(
            (area_ratios >= 0.48)
            & (area_ratios <= 2.05)
            & (side_ratios >= 0.62)
            & (residuals <= 0.36)
            & (np.abs(grid_x) <= 4)
            & (np.abs(grid_y) <= 4)
        )[0]
        if len(eligible) < 6:
            continue

        best_for_position: dict[tuple[int, int], int] = {}
        for index in eligible:
            key = (int(grid_x[index]), int(grid_y[index]))
            existing = best_for_position.get(key)
            if existing is None or residuals[index] < residuals[existing]:
                best_for_position[key] = int(index)

        xs = [position[0] for position in best_for_position]
        ys = [position[1] for position in best_for_position]
        for start_x in range(min(xs), max(xs) - grid_size + 2):
            for start_y in range(min(ys), max(ys) - grid_size + 2):
                selected_positions = [
                    position
                    for position in best_for_position
                    if start_x <= position[0] < start_x + grid_size
                    and start_y <= position[1] < start_y + grid_size
                ]
                if len(selected_positions) < grid_size * 2:
                    continue
                row_counts = [sum(position[1] == start_y + row for position in selected_positions) for row in range(grid_size)]
                column_counts = [sum(position[0] == start_x + column for position in selected_positions) for column in range(grid_size)]
                if min(row_counts) < 1 or min(column_counts) < 1:
                    continue
                if sum(count >= 2 for count in row_counts) < 2 or sum(count >= 2 for count in column_counts) < 2:
                    continue

                image_points = np.array(
                    [centers[best_for_position[position]] for position in selected_positions],
                    dtype=np.float32,
                )
                grid_points = np.array(
                    [
                        [position[0] - start_x + 0.5, position[1] - start_y + 0.5]
                        for position in selected_positions
                    ],
                    dtype=np.float32,
                )
                transform, inlier_mask = cv2.findHomography(
                    grid_points,
                    image_points,
                    cv2.RANSAC,
                    max(spacing_x, spacing_y) * 0.20,
                )
                if transform is None:
                    continue
                inlier_count = int(inlier_mask.sum()) if inlier_mask is not None else len(selected_positions)
                if inlier_count < grid_size * 2:
                    continue
                outer_grid = np.array(
                    [[[0, 0], [grid_size, 0], [grid_size, grid_size], [0, grid_size]]],
                    dtype=np.float32,
                )
                outer = cv2.perspectiveTransform(outer_grid, transform)[0]
                outer = _order_quad(outer)
                area_ratio = abs(cv2.contourArea(outer)) / (width * height)
                if area_ratio < 0.006 or area_ratio > 0.82 or _side_ratio(outer) < 0.30:
                    continue
                outer[:, 0] = np.clip(outer[:, 0], 0, width - 1)
                outer[:, 1] = np.clip(outer[:, 1], 0, height - 1)
                candidates.append((outer.astype(np.float32), f"grid-fit-{inlier_count}"))
    return candidates


def _cluster_cell_candidates(
    cells: list[np.ndarray], width: int, height: int
) -> list[tuple[np.ndarray, str]]:
    if len(cells) < 4:
        return []
    centers = np.array([quad.mean(axis=0) for quad in cells])
    areas = np.array([abs(cv2.contourArea(quad)) for quad in cells])
    candidates: list[tuple[np.ndarray, str]] = []
    for index, quad in enumerate(cells):
        base_size = np.sqrt(max(areas[index], 1.0))
        ratios = areas / max(areas[index], 1.0)
        distances = np.linalg.norm(centers - centers[index], axis=1)
        for radius in (4.2, 5.8):
            selected = np.where(
                (ratios >= 0.30) & (ratios <= 3.2) & (distances <= base_size * radius)
            )[0]
            if len(selected) < 4 or len(selected) > 16:
                continue
            points = np.concatenate([cells[item] for item in selected]).reshape(-1, 1, 2)
            outer = _quad_from_contour(points.astype(np.float32))
            if outer is not None:
                outer = _expand_quad(outer, 1.025, width, height)
                candidates.append((outer, f"cell-cluster-{len(selected)}"))
    return candidates


def _expand_2x2_cell_candidates(
    cells: list[np.ndarray], width: int, height: int
) -> list[tuple[np.ndarray, str]]:
    """Infer a complete 2x2 face from any one large sticker quadrilateral.

    Real phone photos often clip one side of a 2x2 cube or merge a dark-blue
    sticker into the background, leaving only two or three detectable cells.
    A keyboard in the background produces many quads too, but those cells are
    much smaller. Extrapolating only large, square-ish cells gives the scorer
    accurate face candidates without requiring all four stickers to contour.
    """
    image_area = float(width * height)
    result: list[tuple[np.ndarray, str]] = []
    for quad in cells:
        cell_area_ratio = abs(cv2.contourArea(quad)) / image_area
        if cell_area_ratio < 0.018 or _side_ratio(quad) < 0.62:
            continue
        top = quad[1] - quad[0]
        bottom = quad[2] - quad[3]
        left = quad[3] - quad[0]
        right = quad[2] - quad[1]
        axis_x = (top + bottom) / 2
        axis_y = (left + right) / 2
        center = quad.mean(axis=0)
        if np.linalg.norm(axis_x) < 4 or np.linalg.norm(axis_y) < 4:
            continue

        for row in range(2):
            for column in range(2):
                top_left = center - (column + 0.5) * axis_x - (row + 0.5) * axis_y
                outer = np.array(
                    [
                        top_left,
                        top_left + axis_x * 2,
                        top_left + axis_x * 2 + axis_y * 2,
                        top_left + axis_y * 2,
                    ],
                    dtype=np.float32,
                )
                area_ratio = abs(cv2.contourArea(outer)) / image_area
                if not 0.075 <= area_ratio <= 0.88 or _side_ratio(outer) < 0.34:
                    continue
                # A slightly clipped cube is valid; clamp only after its full
                # geometry has been checked so border cells can still vote.
                outer[:, 0] = np.clip(outer[:, 0], 0, width - 1)
                outer[:, 1] = np.clip(outer[:, 1], 0, height - 1)
                if abs(cv2.contourArea(outer)) / image_area >= 0.06:
                    result.append((_order_quad(outer), "cell-2x2"))
    return result


def _fit_2x2_pair_candidates(
    cells: list[np.ndarray], width: int, height: int
) -> list[tuple[np.ndarray, str]]:
    """Fit a 2x2 face from a detected horizontal or vertical sticker pair."""
    image_area = float(width * height)
    large = [
        quad
        for quad in cells
        if abs(cv2.contourArea(quad)) / image_area >= 0.014 and _side_ratio(quad) >= 0.58
    ]
    result: list[tuple[np.ndarray, str]] = []
    for left_index, first in enumerate(large):
        first_area = abs(cv2.contourArea(first))
        first_center = first.mean(axis=0)
        for second in large[left_index + 1 :]:
            second_area = abs(cv2.contourArea(second))
            area_ratio = min(first_area, second_area) / max(first_area, second_area, 1.0)
            if area_ratio < 0.48:
                continue
            second_center = second.mean(axis=0)
            delta = second_center - first_center
            horizontal = abs(delta[0]) > abs(delta[1]) * 1.35
            vertical = abs(delta[1]) > abs(delta[0]) * 1.35
            if not horizontal and not vertical:
                continue

            if horizontal:
                left, right = (first, second) if first_center[0] < second_center[0] else (second, first)
                left_center, right_center = left.mean(axis=0), right.mean(axis=0)
                axis_x = right_center - left_center
                axis_y = (
                    (left[3] - left[0]) + (left[2] - left[1])
                    + (right[3] - right[0]) + (right[2] - right[1])
                ) / 4
                if axis_y[1] < 0:
                    axis_y = -axis_y
                if not 0.50 <= np.linalg.norm(axis_y) / max(np.linalg.norm(axis_x), 1e-6) <= 1.7:
                    continue
                row_options = (0, 1)
                for row in row_options:
                    face_center = (left_center + right_center) / 2 + (0.5 - row) * axis_y
                    result.append((_face_quad_from_axes(face_center, axis_x, axis_y), "cell-pair-2x2"))
            else:
                top, bottom = (first, second) if first_center[1] < second_center[1] else (second, first)
                top_center, bottom_center = top.mean(axis=0), bottom.mean(axis=0)
                axis_y = bottom_center - top_center
                axis_x = (
                    (top[1] - top[0]) + (top[2] - top[3])
                    + (bottom[1] - bottom[0]) + (bottom[2] - bottom[3])
                ) / 4
                if axis_x[0] < 0:
                    axis_x = -axis_x
                if not 0.50 <= np.linalg.norm(axis_x) / max(np.linalg.norm(axis_y), 1e-6) <= 1.7:
                    continue
                for column in (0, 1):
                    face_center = (top_center + bottom_center) / 2 + (0.5 - column) * axis_x
                    result.append((_face_quad_from_axes(face_center, axis_x, axis_y), "cell-pair-2x2"))

    clipped: list[tuple[np.ndarray, str]] = []
    for quad, method in result:
        area_ratio = abs(cv2.contourArea(quad)) / image_area
        if not 0.07 <= area_ratio <= 0.88 or _side_ratio(quad) < 0.34:
            continue
        quad[:, 0] = np.clip(quad[:, 0], 0, width - 1)
        quad[:, 1] = np.clip(quad[:, 1], 0, height - 1)
        if abs(cv2.contourArea(quad)) / image_area >= 0.055:
            clipped.append((_order_quad(quad), method))
    return clipped


def _face_quad_from_axes(center: np.ndarray, axis_x: np.ndarray, axis_y: np.ndarray) -> np.ndarray:
    return np.array(
        [
            center - axis_x - axis_y,
            center + axis_x - axis_y,
            center + axis_x + axis_y,
            center - axis_x + axis_y,
        ],
        dtype=np.float32,
    )


def _2x2_cell_alignment(cells: list[np.ndarray], face_quad: np.ndarray) -> tuple[int, float]:
    face_area = abs(cv2.contourArea(face_quad))
    if face_area < 1:
        return 0, 0.0
    target = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(face_quad.astype(np.float32), target)
    slots = np.array([[0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]])
    matches: list[tuple[float, int]] = []
    for cell in cells:
        area_ratio = abs(cv2.contourArea(cell)) / face_area
        if not 0.10 <= area_ratio <= 0.40 or _side_ratio(cell) < 0.56:
            continue
        point = cv2.perspectiveTransform(cell.mean(axis=0).reshape(1, 1, 2), transform)[0, 0]
        if not -0.1 <= point[0] <= 1.1 or not -0.1 <= point[1] <= 1.1:
            continue
        distances = np.linalg.norm(slots - point, axis=1)
        slot = int(np.argmin(distances))
        if distances[slot] <= 0.24:
            matches.append((float(distances[slot]), slot))

    used: set[int] = set()
    quality = 0.0
    for distance, slot in sorted(matches):
        if slot in used:
            continue
        used.add(slot)
        quality += max(0.0, 1 - distance / 0.24)
    return len(used), quality / 4


def _deduplicate_candidates(
    candidates: list[tuple[np.ndarray, str]], width: int, height: int
) -> list[tuple[np.ndarray, str]]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            item[1].startswith("grid-fit"),
            abs(cv2.contourArea(item[0])),
        ),
        reverse=True,
    )
    result: list[tuple[np.ndarray, str]] = []
    diagonal = np.hypot(width, height)
    for quad, method in ordered:
        center = quad.mean(axis=0)
        area = abs(cv2.contourArea(quad))
        duplicate = False
        for existing, _ in result:
            existing_area = abs(cv2.contourArea(existing))
            if (
                np.linalg.norm(center - existing.mean(axis=0)) < diagonal * 0.018
                and min(area, existing_area) / max(area, existing_area) > 0.72
            ):
                duplicate = True
                break
        if not duplicate:
            result.append((quad, method))
    return result


def _quad_iou(first: np.ndarray, second: np.ndarray) -> float:
    first_area = abs(float(cv2.contourArea(first.astype(np.float32))))
    second_area = abs(float(cv2.contourArea(second.astype(np.float32))))
    if first_area <= 1 or second_area <= 1:
        return 0.0
    intersection_area, _ = cv2.intersectConvexConvex(
        first.astype(np.float32),
        second.astype(np.float32),
    )
    union = first_area + second_area - float(intersection_area)
    return float(intersection_area / max(union, 1e-6))


def _expand_quad(quad: np.ndarray, factor: float, width: int, height: int) -> np.ndarray:
    center = quad.mean(axis=0)
    expanded = center + (quad - center) * factor
    expanded[:, 0] = np.clip(expanded[:, 0], 0, width - 1)
    expanded[:, 1] = np.clip(expanded[:, 1], 0, height - 1)
    return expanded.astype(np.float32)


def _score_face_candidate(image: np.ndarray, quad: np.ndarray, grid_size: int = 3) -> float:
    if abs(cv2.contourArea(quad)) < 64:
        return 0.0
    size = 300
    target = np.array([[0, 0], [size - 1, 0], [size - 1, size - 1], [0, size - 1]], np.float32)
    transform = cv2.getPerspectiveTransform(quad.astype(np.float32), target)
    warped = cv2.warpPerspective(image, transform, (size, size), flags=cv2.INTER_LINEAR)
    gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB)

    gradient_x = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    gradient_y = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    vertical_profile = gradient_x[18:-18, :].mean(axis=0)
    horizontal_profile = gradient_y[:, 18:-18].mean(axis=1)
    grid_lines = [size * index / grid_size for index in range(1, grid_size)]
    edge_score = sum(
        _profile_grid_score(profile, position)
        for profile in (vertical_profile, horizontal_profile)
        for position in grid_lines
    ) / (2 * len(grid_lines))

    cell_means = []
    uniformities = []
    plausible = []
    for row in range(grid_size):
        for column in range(grid_size):
            center_x = round((column + 0.5) * size / grid_size)
            center_y = round((row + 0.5) * size / grid_size)
            radius = 24 if grid_size == 3 else 34
            patch_gray = gray[center_y - radius : center_y + radius, center_x - radius : center_x + radius]
            patch_hsv = hsv[center_y - radius : center_y + radius, center_x - radius : center_x + radius]
            patch_lab = lab[center_y - radius : center_y + radius, center_x - radius : center_x + radius]
            cell_means.append(float(np.median(patch_gray)))
            medians = np.median(patch_lab.reshape(-1, 3), axis=0)
            deviations = np.median(np.abs(patch_lab.reshape(-1, 3) - medians), axis=0)
            uniformities.append(float(np.mean(deviations)))
            saturation_75 = float(np.percentile(patch_hsv[:, :, 1], 75))
            value_median = float(np.median(patch_hsv[:, :, 2]))
            plausible.append(value_median > 48 and (saturation_75 > 25 or value_median > 125))

    center_brightness = float(np.mean(cell_means))
    vertical_darkness = np.mean([_darkest_strip(gray, round(position), vertical=True) for position in grid_lines])
    horizontal_darkness = np.mean([_darkest_strip(gray, round(position), vertical=False) for position in grid_lines])
    line_brightness = float((vertical_darkness + horizontal_darkness) / 2)
    dark_grid_score = float(np.clip((center_brightness - line_brightness + 6) / 55, 0, 1))
    uniformity_score = float(np.clip(1 - np.median(uniformities) / 28, 0, 1))
    plausibility_score = float(np.mean(plausible))
    geometry_score = float(np.clip((_side_ratio(quad) - 0.30) / 0.70, 0, 1))

    if grid_size == 2:
        worst_uniformities = sorted(uniformities, reverse=True)[:2]
        cell_uniformity_score = float(
            np.clip(1 - np.mean(worst_uniformities) / 24, 0, 1)
        )
        sticker_scores = []
        for row in range(2):
            for column in range(2):
                y0 = round((row + 0.16) * size / 2)
                y1 = round((row + 0.84) * size / 2)
                x0 = round((column + 0.16) * size / 2)
                x1 = round((column + 0.84) * size / 2)
                patch = hsv[y0:y1, x0:x1]
                saturation = patch[:, :, 1]
                value = patch[:, :, 2]
                sticker_pixels = ((saturation > 38) & (value > 45)) | (
                    (saturation < 62) & (value > 132)
                )
                coverage = float(np.mean(sticker_pixels))
                sticker_scores.append(float(np.clip((coverage - 0.30) / 0.58, 0, 1)))
        sticker_scores.sort()
        # Requiring three convincing quadrants rejects keyboard crops while
        # tolerating one dark-blue sticker, shadow, logo, or clipped edge.
        sticker_score = float(np.mean(sticker_scores[1:]))
        return float(
            edge_score * 0.15
            + dark_grid_score * 0.11
            + uniformity_score * 0.12
            + plausibility_score * 0.08
            + geometry_score * 0.09
            + sticker_score * 0.27
            + cell_uniformity_score * 0.18
        )

    return float(
        edge_score * 0.38
        + dark_grid_score * 0.24
        + uniformity_score * 0.17
        + plausibility_score * 0.11
        + geometry_score * 0.10
    )


def _profile_grid_score(profile: np.ndarray, expected: float) -> float:
    center = round(expected)
    window = profile[max(0, center - 16) : min(len(profile), center + 17)]
    if window.size == 0:
        return 0.0
    strength = float(np.max(window))
    baseline = float(np.median(profile))
    upper = float(np.percentile(profile, 92))
    return float(np.clip((strength - baseline) / max(upper - baseline, 5.0), 0, 1))


def _darkest_strip(gray: np.ndarray, expected: int, *, vertical: bool) -> float:
    values = []
    for offset in range(-13, 14):
        position = expected + offset
        if vertical:
            strip = gray[18:-18, max(0, position - 2) : min(gray.shape[1], position + 3)]
        else:
            strip = gray[max(0, position - 2) : min(gray.shape[0], position + 3), 18:-18]
        if strip.size:
            values.append(float(np.mean(strip)))
    return min(values) if values else 255.0
