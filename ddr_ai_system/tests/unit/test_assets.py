from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image

from ddr_ai.assets import portable_asset_path, render_image_safely, resolve_asset_path


class FakeImageTarget:
    def __init__(self, *, fail_render: bool = False) -> None:
        self.fail_render = fail_render
        self.images: list[dict[str, Any]] = []
        self.warnings: list[str] = []

    def image(self, image: bytes, *, caption: str, width: str) -> None:
        if self.fail_render:
            raise RuntimeError("simulated Streamlit media failure")
        with Image.open(io.BytesIO(image)) as decoded:
            decoded.verify()
        self.images.append({"image": image, "caption": caption, "width": width})

    def warning(self, body: str) -> None:
        self.warnings.append(body)


def make_png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 6), color=(12, 90, 120)).save(path)
    return path


def test_resolve_valid_relative_path(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    image = make_png(data_root / "raw" / "plots" / "Plot.png")

    assert resolve_asset_path("data/raw/plots/Plot.png", data_root=data_root) == image.resolve()


def test_missing_file_returns_none(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()

    assert resolve_asset_path("data/raw/plots/missing.png", data_root=data_root) is None


def test_stale_windows_absolute_path_uses_portable_data_suffix(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    image = make_png(data_root / "raw" / "plots" / "plot.png")
    stale = r"C:\old-workstation\repo\data\raw\plots\plot.png"

    assert resolve_asset_path(stale, data_root=data_root) == image.resolve()


def test_linux_case_sensitive_filename_mismatch_is_rejected_on_all_platforms(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    make_png(data_root / "raw" / "plots" / "Plot.png")

    assert resolve_asset_path("data/raw/plots/plot.png", data_root=data_root) is None


def test_traversal_attempt_is_rejected(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    make_png(tmp_path / "outside.png")

    assert resolve_asset_path("data/../outside.png", data_root=data_root) is None


def test_unsupported_image_type_is_rejected(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    text_file = data_root / "raw" / "plot.txt"
    text_file.parent.mkdir(parents=True)
    text_file.write_text("not an image", encoding="utf-8")

    assert resolve_asset_path("data/raw/plot.txt", data_root=data_root) is None


def test_portable_asset_path_uses_forward_slashes(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    image = make_png(data_root / "processed" / "overlays" / "plot.png")

    assert portable_asset_path(image, data_root=data_root) == "data/processed/overlays/plot.png"


def test_image_is_decoded_and_rendered_as_bytes(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    make_png(data_root / "raw" / "plots" / "plot.png")
    target = FakeImageTarget()

    rendered = render_image_safely(
        target,
        "data/raw/plots/plot.png",
        caption="Source",
        asset_label="Source image",
        data_root=data_root,
    )

    assert rendered is True
    assert len(target.images) == 1
    assert isinstance(target.images[0]["image"], bytes)
    assert target.images[0]["width"] == "stretch"
    assert not target.warnings


def test_missing_source_and_overlay_show_warnings_without_rendering(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    target = FakeImageTarget()

    source_rendered = render_image_safely(
        target,
        "data/raw/plots/missing.png",
        caption="Source",
        asset_label="Source image",
        data_root=data_root,
    )
    overlay_rendered = render_image_safely(
        target,
        None,
        caption="Overlay",
        asset_label="Debug overlay",
        data_root=data_root,
    )

    assert source_rendered is False
    assert overlay_rendered is False
    assert not target.images
    assert target.warnings == [
        "Source image is unavailable in this deployment. "
        "Import and process the approved source dataset to make it available.",
        "Debug overlay is unavailable in this deployment. "
        "Import and process the approved source dataset to make it available.",
    ]


def test_streamlit_render_failure_is_converted_to_warning(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    make_png(data_root / "raw" / "plots" / "plot.png")
    target = FakeImageTarget(fail_render=True)

    rendered = render_image_safely(
        target,
        "data/raw/plots/plot.png",
        caption="Source",
        asset_label="Source image",
        data_root=data_root,
    )

    assert rendered is False
    assert target.warnings == ["Source image could not be rendered safely."]
