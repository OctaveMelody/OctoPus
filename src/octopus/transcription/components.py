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


def connected_components(gray: Image.Image, threshold: int = 160) -> list[Component]:
    """Find eight-connected dark marks without a computer-vision dependency."""
    width, height = gray.size
    data = gray.tobytes()
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
