"""Image processing and downscaling utilities for Laika uploads."""

import io
import logging
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

MAX_IMAGE_UPLOAD_BYTES = 15 * 1024 * 1024


def save_resized_webp(
    raw_bytes: bytes,
    dest_path: Path,
    max_dimension: int = 1080,
    quality: int = 82,
    square: bool = False,
) -> bool:
    """Validate, EXIF-orient, resize/crop, and save an image as compressed WebP.

    Args:
        raw_bytes: Raw uploaded image bytes.
        dest_path: Target file path on disk (parent directories are created).
        max_dimension: Maximum width/height (or square side length) in pixels.
        quality: WebP compression quality (1-100).
        square: When True, enforce an exact 1:1 square aspect ratio via center fit.

    Returns:
        True when the image was successfully processed and written, else False.
    """
    if not raw_bytes or len(raw_bytes) > MAX_IMAGE_UPLOAD_BYTES:
        return False

    try:
        with Image.open(io.BytesIO(raw_bytes)) as opened:
            processed: Image.Image = ImageOps.exif_transpose(opened)
            if processed.mode not in ("RGB", "RGBA"):
                processed = processed.convert("RGB")
            if square:
                side = min(max_dimension, min(processed.size))
                processed = ImageOps.fit(
                    processed,
                    (side, side),
                    method=Image.Resampling.LANCZOS,
                )
            else:
                processed.thumbnail(
                    (max_dimension, max_dimension),
                    Image.Resampling.LANCZOS,
                )
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            processed.save(dest_path, format="WEBP", quality=quality, method=6)
        return True
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.error("Falha ao processar imagem enviada: %s", exc)
        return False
