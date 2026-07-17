from __future__ import annotations

import io
import logging
import os
from contextlib import suppress
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _configured_data_root() -> Path:
    configured = os.getenv("DDR_DATA_ROOT")
    root = Path(configured).expanduser() if configured else PROJECT_ROOT / "data"
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    return root.resolve()


DATA_ROOT = _configured_data_root()
SUPPORTED_IMAGE_EXTENSIONS = frozenset({".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})


class ImageTarget(Protocol):
    def image(self, image: bytes, *, caption: str, width: str) -> Any: ...

    def warning(self, body: str) -> Any: ...


def _reject(stored_path: str, reason: str, resolved_path: Path | None = None) -> None:
    LOGGER.warning(
        "Image asset unavailable: stored_path=%r resolved_path=%s reason=%s",
        stored_path,
        resolved_path,
        reason,
    )


def _relative_parts(stored_path: str) -> tuple[str, ...] | None:
    normalized = stored_path.replace("\\", "/")
    portable = PurePosixPath(normalized)
    windows = PureWindowsPath(stored_path)
    parts = portable.parts
    is_absolute = portable.is_absolute() or windows.is_absolute()

    if windows.drive and not windows.is_absolute():
        return None
    if any(part == ".." for part in parts):
        return None

    data_indexes = [index for index, part in enumerate(parts) if part.casefold() == "data"]
    if is_absolute:
        if not data_indexes:
            return None
        parts = parts[data_indexes[-1] + 1 :]
    elif parts and parts[0].casefold() == "data":
        parts = parts[1:]

    return tuple(part for part in parts if part not in {"", ".", "/"})


def _case_status(root: Path, parts: tuple[str, ...]) -> tuple[str, Path]:
    current = root
    for part in parts:
        try:
            children = list(current.iterdir())
        except OSError:
            return "missing", current / part
        exact = next((child for child in children if child.name == part), None)
        if exact is None:
            if any(child.name.casefold() == part.casefold() for child in children):
                return "case_mismatch", current / part
            return "missing", current / part
        current = exact
    return "exact", current


def resolve_asset_path(
    stored_path: str | Path | None,
    *,
    data_root: Path | None = None,
) -> Path | None:
    """Resolve a stored image path inside the configured data root without trusting the CWD."""
    raw = "" if stored_path is None else os.fspath(stored_path).strip()
    if not raw:
        _reject(raw, "empty path")
        return None

    try:
        root = (data_root or DATA_ROOT).resolve()
        native_path = Path(raw)
        native_relative: tuple[str, ...] | None = None
        if native_path.is_absolute():
            with suppress(ValueError):
                native_relative = native_path.resolve(strict=False).relative_to(root).parts
        parts = native_relative or _relative_parts(raw)
    except (OSError, RuntimeError, ValueError) as exc:
        _reject(raw, f"invalid path: {exc}")
        return None
    if not parts:
        _reject(raw, "absolute path has no portable data suffix or path is unsafe")
        return None

    try:
        unresolved = root.joinpath(*parts)
        resolved = unresolved.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        _reject(raw, f"path could not be normalized: {exc}")
        return None
    try:
        resolved.relative_to(root)
    except ValueError:
        _reject(raw, "path traversal outside the allowed data root", resolved)
        return None

    if unresolved.suffix.casefold() not in SUPPORTED_IMAGE_EXTENSIONS:
        _reject(raw, f"unsupported image extension {unresolved.suffix!r}", resolved)
        return None

    case_status, exact_path = _case_status(root, parts)
    if case_status != "exact":
        reason = "filename casing mismatch" if case_status == "case_mismatch" else "file does not exist"
        _reject(raw, reason, resolved)
        return None

    try:
        exact_resolved = exact_path.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        _reject(raw, f"resolved file is invalid: {exc}", exact_path)
        return None
    try:
        exact_resolved.relative_to(root)
    except ValueError:
        _reject(raw, "resolved file escapes the allowed data root", exact_resolved)
        return None
    if not exact_resolved.exists():
        _reject(raw, "file does not exist", exact_resolved)
        return None
    if not exact_resolved.is_file():
        _reject(raw, "path is not a file", exact_resolved)
        return None

    LOGGER.info("Resolved image asset: stored_path=%r resolved_path=%s", raw, exact_resolved)
    return exact_resolved


def portable_asset_path(path: str | Path, *, data_root: Path | None = None) -> str:
    """Return a platform-neutral database path for an image under the data root."""
    root = (data_root or DATA_ROOT).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Image asset must be inside the data root: {resolved}") from exc
    if resolved.suffix.casefold() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(f"Unsupported image extension: {resolved.suffix}")
    return (Path("data") / relative).as_posix()


def load_image_bytes(path: Path) -> bytes:
    """Decode an image with Pillow and return normalized PNG bytes for Streamlit."""
    with Image.open(path) as image:
        image.load()
        renderable = image if image.mode in {"L", "RGB", "RGBA"} else image.convert("RGBA")
        output = io.BytesIO()
        renderable.save(output, format="PNG")
        return output.getvalue()


def render_image_safely(
    target: ImageTarget,
    stored_path: str | Path | None,
    *,
    caption: str,
    asset_label: str,
    data_root: Path | None = None,
) -> bool:
    """Render a verified image as bytes, or show a non-fatal import/storage warning."""
    path = resolve_asset_path(stored_path, data_root=data_root)
    if path is None:
        target.warning(
            f"{asset_label} is unavailable in this deployment. "
            "Import and process the approved source dataset to make it available."
        )
        return False

    try:
        image_bytes = load_image_bytes(path)
        target.image(image_bytes, caption=caption, width="stretch")
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        LOGGER.warning(
            "Image asset could not be decoded: stored_path=%r resolved_path=%s reason=%s",
            os.fspath(stored_path) if stored_path is not None else None,
            path,
            exc,
            exc_info=True,
        )
        target.warning(
            f"{asset_label} could not be read safely. "
            "Re-import and process the approved source dataset."
        )
        return False
    except Exception as exc:
        LOGGER.warning(
            "Image asset could not be rendered: stored_path=%r resolved_path=%s reason=%s",
            os.fspath(stored_path) if stored_path is not None else None,
            path,
            exc,
            exc_info=True,
        )
        target.warning(f"{asset_label} could not be rendered safely.")
        return False

    LOGGER.info("Rendered image asset: resolved_path=%s bytes=%d", path, len(image_bytes))
    return True
