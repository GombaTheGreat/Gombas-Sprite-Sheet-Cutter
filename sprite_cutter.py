from __future__ import annotations

import io
import zipfile

from PIL import Image


def cut_sprites(
    rgba_image: Image.Image,
    bboxes: list[tuple[int, int, int, int]],
    target_size: int | None = None,
) -> list[Image.Image]:
    """Crop each bounding box from rgba_image, optionally letterbox-resize to target_size×target_size."""
    sprites: list[Image.Image] = []
    for x1, y1, x2, y2 in bboxes:
        crop = rgba_image.crop((x1, y1, x2, y2))
        if target_size is not None:
            crop = _letterbox(crop, target_size)
        sprites.append(crop)
    return sprites


def _letterbox(img: Image.Image, size: int) -> Image.Image:
    """Fit img into a size×size canvas, preserving aspect ratio, transparent padding."""
    img_w, img_h = img.size
    scale = min(size / img_w, size / img_h)
    new_w = max(1, int(img_w * scale))
    new_h = max(1, int(img_h * scale))
    resized = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset_x = (size - new_w) // 2
    offset_y = (size - new_h) // 2
    canvas.paste(resized, (offset_x, offset_y), resized.split()[3])
    return canvas


def pack_to_zip(
    sprites: list[Image.Image],
    prefix: str = "sprite",
    start_index: int = 1,
) -> bytes:
    """Pack a list of RGBA PIL images into an in-memory ZIP of numbered PNGs.

    start_index lets callers produce sequential filenames across multiple sheets.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i, sprite in enumerate(sprites, start=start_index):
            png_buf = io.BytesIO()
            sprite.save(png_buf, format="PNG")
            zf.writestr(f"{prefix}_{i:03d}.png", png_buf.getvalue())
    return buf.getvalue()
