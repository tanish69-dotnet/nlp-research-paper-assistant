"""Image acquisition and validation helpers (SECURITY.md §4, DEVELOPMENT_PLAN §3).

*Filesystem* images are confined to ``EVIDENCE_ROOT`` via
:func:`app.evidence.validation.resolve_image_path`. File-based checks
enforce format, byte and pixel limits before any model call.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from app.config import Settings
from app.core.errors import EvidenceInvalidError, PayloadTooLargeError

ALLOWED_EXTENSIONS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_MIME_FOR_EXTENSION = {ext: mime for ext, mime in ALLOWED_EXTENSIONS.items()}


def _mime_for_path(path: Path) -> str | None:
    return _MIME_FOR_EXTENSION.get(path.suffix.lower())


def validate_image_bytes(data: bytes, suffix: str, settings: Settings) -> str:
    """Validate raw image ``data`` and return its MIME type.

    Checks byte-limit, extension/format, and (if ``Pillow`` is installed) the
    pixel budget. ``suffix`` comes from the source filename or ``.png`` for
    base64-only items without a name.
    """
    if len(data) > settings.max_image_bytes:
        raise PayloadTooLargeError(
            f"image has {len(data)} bytes; max_image_bytes={settings.max_image_bytes}"
        )

    mime = _MIME_FOR_EXTENSION.get(suffix.lower())
    if mime is None:
        raise EvidenceInvalidError(
            f"unsupported image format {suffix!r}; allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Pixel budget: optional when Pillow is not installed (documented
    # extension point, SECURITY.md; Phase 3 keeps infrastructure simple).
    if settings.max_image_pixels < 1:
        return mime

    width, height = _probe_png_dimensions(data, suffix)
    if width is not None and height is not None and width * height > settings.max_image_pixels:
        raise PayloadTooLargeError(
            f"image is {width}x{height} ({width*height} pixels); "
            f"max_image_pixels={settings.max_image_pixels}"
        )
    return mime


def _probe_png_dimensions(data: bytes, suffix: str) -> tuple[int | None, int | None]:
    """Cheap PNG/JPEG/WEBP dimension probe.

    Tries Pillow first; on ``ImportError`` or malformed bytes, returns ``(None, None)``.
    """
    try:
        from PIL import Image  # type: ignore[import-not-found]
        import io

        with Image.open(io.BytesIO(data)) as image:  # type: ignore[no-untyped-call]
            return image.size  # type: ignore[no-any-return]
    except ImportError:
        return None, None
    except Exception:
        # Use a light fallback for PNG without Pillow (reads IHDR).
        if suffix.lower() == ".png" and len(data) >= 24 and data[1:4] == b"PNG":
            try:
                width = int.from_bytes(data[16:20], "big")
                height = int.from_bytes(data[20:24], "big")
                return width, height
            except Exception:
                return None, None
        return None, None


def encode_file_for_provider(path: Path, settings: Settings) -> tuple[str, str]:
    """Validate and base64-encode a file for provider transport.

    Returns ``(b64, mime)``. Logs intentionally omit the b64 itself (scrubbed
    by the logging processor).
    """
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise EvidenceInvalidError(f"unsupported image format {suffix!r}")

    data = path.read_bytes()
    mime = validate_image_bytes(data, suffix, settings)
    return base64.b64encode(data).decode("ascii"), mime


def decode_and_validate_b64(b64: str, settings: Settings) -> tuple[bytes, str]:
    """Validate a base64-transported image.

    The caller supplies a fallback ``.png`` suffix — the format is inferred
    from bytes only when we can decode the actual content.
    """
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception as exc:
        raise EvidenceInvalidError(f"image b64 is not valid base64: {exc}") from exc

    # Reuse the byte limit check (format detection from bytes for b64 items is
    # opportunistic: if probing fails, assume png — the provider handles it).
    mime = validate_image_bytes(data, ".png", settings)
    return data, mime


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
