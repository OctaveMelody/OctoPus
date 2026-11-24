"""Small connected components for black notation marks on a white page."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

Box = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class Component:
    box: Box
    area: int

    @property
    def width(self) -> int:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> int:
        return self.box[3] - self.box[1]

    @property
    def center_y(self) -> float:
        return (self.box[1] + self.box[3]) / 2


def _percentile_bin(histogram: list[int], population: int, percentile: float) -> int:
    target = population * percentile
    running = 0
    for value, count in enumerate(histogram):
        running += count
        if running >= target:
            return value
    return 255


def normalize_recognition_contrast(gray: Image.Image) -> Image.Image:
    """Expand compressed print and paper levels when both form distinct modes."""
    histogram = gray.histogram()
    population = gray.width * gray.height
    # Ignore sparse extrema, but skip weak spans and broad upper levels from gradients.
    low = _percentile_bin(histogram, population, 0.005)
    high = _percentile_bin(histogram, population, 0.995)
    # Preserve pages with real black print and white paper; sparse specks still normalize.
    if (sum(histogram[:2]) >= population * 0.001
            and sum(histogram[254:]) >= population * 0.005):
        return gray
    span = high - low
    if span < 48 or _percentile_bin(histogram, population, 0.99) \
            - _percentile_bin(histogram, population, 0.5) > 28:
        return gray

    dark_radius = max(1, round(span * 0.2))
    middle_start = low + round(span * 0.25)
    middle_end = low + round(span * 0.75)
    background_start = high - max(16, round(span * 0.15))
    ink_bins = range(max(0, low - dark_radius), low + dark_radius + 1)
    ink_mode = max(ink_bins, key=histogram.__getitem__)
    dark_peak = histogram[ink_mode]
    middle = histogram[middle_start:middle_end + 1]
    middle_level = sum(middle) / max(1, len(middle))
    background_peak = max(histogram[background_start:high + 1], default=0)
    if (dark_peak < population * 0.001 or dark_peak < middle_level * 2
            or background_peak < population * 0.02):
        return gray
    # The darkest ink peak can fall just below the percentile on sparse printed pages.
    low = min(low, ink_mode)
    # Map interior gray levels from the center of each quantization bin. Mapping the
    # lower edge biases antialiased note boundaries toward ink after contrast compression.
    scale = 255 / (high - low)
    return gray.point([
        0 if value <= low else 255 if value >= high else int((value - low + 0.5) * scale)
        for value in range(256)
    ])


def connected_components(gray: Image.Image, threshold: int = 160) -> list[Component]:
    """Find eight-connected dark marks, with a dependency-free fallback."""
    width, height = gray.size
    data = gray.tobytes()
    try:
        import cv2
        import numpy as np
    except ImportError:
        pass
    else:
        label_components = getattr(cv2, "connectedComponentsWithStatsWithAlgorithm", None)
        algorithm = getattr(cv2, "CCL_SAUF", None)
        if label_components is not None and algorithm is not None and len(data) == width * height:
            # SAUF keeps the original raster-scan component order.
            foreground = np.frombuffer(data, dtype=np.uint8).reshape(height, width) < threshold
            count, _, stats, _ = label_components(
                np.ascontiguousarray(foreground, dtype=np.uint8),
                8, cv2.CV_32S, algorithm,
            )
            return [
                Component((int(left), int(top), int(left + box_width), int(top + box_height)),
                          int(area))
                for left, top, box_width, box_height, area in stats[1:count]
            ]

    seen = bytearray(len(data))
    found: list[Component] = []
    for y in range(height):
        for x in range(width):
            start = y * width + x
            if data[start] >= threshold or seen[start]:
                continue
            seen[start] = 1
            pending = [start]
            area = 0
            left = right = x
            top = bottom = y
            while pending:
                index = pending.pop()
                px, py = index % width, index // width
                area += 1
                left, right = min(left, px), max(right, px)
                top, bottom = min(top, py), max(bottom, py)
                for dy in (-1, 0, 1):
                    ny = py + dy
                    if not 0 <= ny < height:
                        continue
                    for dx in (-1, 0, 1):
                        nx = px + dx
                        if not 0 <= nx < width:
                            continue
                        neighbor = ny * width + nx
                        if data[neighbor] < threshold and not seen[neighbor]:
                            seen[neighbor] = 1
                            pending.append(neighbor)
            found.append(Component((left, top, right + 1, bottom + 1), area))
    return found
