"""Helpers for on-the-fly transparent background rendering."""

from __future__ import annotations

import asyncio
import io
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image

from yoink.api.storage import BUCKET_NAME

SOURCE_KIND_SUPABASE: Literal["supabase"] = "supabase"
SOURCE_KIND_GUEST: Literal["guest"] = "guest"
MAX_SOURCE_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
START_FADE = 215
PURE_WHITE = 250

_SUPABASE_PUBLIC_PREFIX = f"/storage/v1/object/public/{BUCKET_NAME}/"
_GUEST_STATIC_PREFIX = "/static/guest/"


@dataclass(slots=True)
class SourceRef:
    """Validated source reference for transparent rendering."""

    kind: Literal["supabase", "guest"]
    path: str


def parse_and_validate_source_url(src: str, supabase_url: str, api_url: str) -> SourceRef:
    """Validate source URL and normalize to an internal source reference."""
    parsed_src = urllib.parse.urlparse(src)
    if parsed_src.scheme not in {"http", "https"} or not parsed_src.netloc:
        raise ValueError("Unsupported source URL")

    source_host = parsed_src.netloc.lower()
    supabase_host = urllib.parse.urlparse(supabase_url).netloc.lower() if supabase_url else ""
    api_host = urllib.parse.urlparse(api_url).netloc.lower() if api_url else ""

    if supabase_host and source_host == supabase_host:
        if not parsed_src.path.startswith(_SUPABASE_PUBLIC_PREFIX):
            raise ValueError("Unsupported Supabase source path")
        rel_path = urllib.parse.unquote(parsed_src.path.removeprefix(_SUPABASE_PUBLIC_PREFIX))
        if not rel_path or rel_path.startswith("/") or "/../" in f"/{rel_path}":
            raise ValueError("Invalid source path")
        return SourceRef(kind=SOURCE_KIND_SUPABASE, path=rel_path)

    if api_host and source_host == api_host:
        if not parsed_src.path.startswith(_GUEST_STATIC_PREFIX):
            raise ValueError("Unsupported API source path")
        rel_path = urllib.parse.unquote(parsed_src.path.removeprefix(_GUEST_STATIC_PREFIX))
        if not rel_path:
            raise ValueError("Invalid source path")
        return SourceRef(kind=SOURCE_KIND_GUEST, path=rel_path)

    raise ValueError("Unsupported source host")


def _resolve_guest_path(source_path: str, static_dir: Path) -> Path:
    """Resolve guest image path safely under static/guest."""
    guest_root = (static_dir / "guest").resolve()
    candidate = (guest_root / source_path).resolve()
    try:
        candidate.relative_to(guest_root)
    except ValueError as exc:
        raise ValueError("Invalid guest source path") from exc
    return candidate


def _extract_download_bytes(download_result: object) -> bytes:
    """Normalize Supabase download result to bytes."""
    if isinstance(download_result, bytes):
        return download_result
    if isinstance(download_result, bytearray):
        return bytes(download_result)
    if hasattr(download_result, "content"):
        content = getattr(download_result, "content")
        if isinstance(content, bytes):
            return content
    raise ValueError("Unsupported download payload")


async def load_source_bytes(source: SourceRef, supabase, static_dir: Path) -> bytes:
    """Load source image bytes from Supabase storage or guest static files."""
    loop = asyncio.get_running_loop()

    if source.kind == SOURCE_KIND_SUPABASE:
        if supabase is None:
            raise RuntimeError("Supabase is not configured")
        download_result = await loop.run_in_executor(
            None,
            lambda: supabase.storage.from_(BUCKET_NAME).download(source.path),
        )
        return _extract_download_bytes(download_result)

    guest_file = _resolve_guest_path(source.path, static_dir)
    if not guest_file.is_file():
        raise FileNotFoundError("Guest source not found")
    return await loop.run_in_executor(None, guest_file.read_bytes)


def make_background_transparent(image_bytes: bytes) -> bytes:
    """Convert near-white background pixels to transparent PNG bytes."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    except Exception as exc:
        raise ValueError("Unsupported image data") from exc

    rgba = np.asarray(img, dtype=np.uint8).copy()
    rgb = rgba[..., :3].astype(np.float32)
    alpha = rgba[..., 3].astype(np.float32)
    brightness = rgb.mean(axis=2)

    white_mask = brightness > PURE_WHITE
    fade_mask = (brightness > START_FADE) & ~white_mask

    rgb_u8 = rgba[..., :3]
    alpha_u8 = rgba[..., 3]

    rgb_u8[white_mask] = 255
    alpha_u8[white_mask] = 0

    if np.any(fade_mask):
        norm = (brightness[fade_mask] - START_FADE) / (PURE_WHITE - START_FADE)
        factor = norm ** 5
        new_alpha = np.rint(alpha[fade_mask] * (1 - factor)).clip(0, 255).astype(np.uint8)
        alpha_u8[fade_mask] = new_alpha

    img = Image.fromarray(rgba, mode="RGBA")

    output = io.BytesIO()
    img.save(output, format="PNG")
    return output.getvalue()
