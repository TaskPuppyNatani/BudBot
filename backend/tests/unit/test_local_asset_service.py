"""Image validation and business-scoped local asset storage tests."""

from __future__ import annotations

from io import BytesIO
import zlib
from uuid import uuid4

from PIL import Image
import pytest

from budbot.services.local_asset_service import (
    MAX_IMAGE_BYTES,
    LocalAssetError,
    LocalAssetStore,
    normalize_image,
)


def _image_bytes(image_format: str = "PNG") -> bytes:
    stream = BytesIO()
    mode = "RGB" if image_format == "JPEG" else "RGBA"
    color = (35, 150, 80) if mode == "RGB" else (35, 150, 80, 120)
    Image.new(mode, (20, 10), color).save(stream, format=image_format)
    return stream.getvalue()


@pytest.mark.parametrize("image_format,extension", [("PNG", "png"), ("JPEG", "jpg"), ("WEBP", "webp")])
def test_normalizes_supported_formats(image_format: str, extension: str) -> None:
    payload, actual_extension = normalize_image(_image_bytes(image_format))
    assert actual_extension == extension
    assert payload


def test_rejects_oversize_unsupported_and_oversized_dimensions() -> None:
    with pytest.raises(LocalAssetError, match="4 MB"):
        normalize_image(b"x" * (MAX_IMAGE_BYTES + 1))

    stream = BytesIO()
    Image.new("RGB", (2, 2)).save(stream, format="GIF")
    with pytest.raises(LocalAssetError, match="PNG, JPG, or WebP"):
        normalize_image(stream.getvalue())

    png = bytearray(_image_bytes())
    png[16:20] = (5000).to_bytes(4, "big")
    png[20:24] = (4000).to_bytes(4, "big")
    png[29:33] = zlib.crc32(png[12:29]).to_bytes(4, "big")
    with pytest.raises(LocalAssetError, match="16 megapixels"):
        normalize_image(bytes(png))


def test_asset_paths_are_tenant_scoped_and_removal_ignores_unowned_refs(tmp_path) -> None:
    store = LocalAssetStore(tmp_path)
    business_id = uuid4()
    other_business_id = uuid4()
    reference, path = store.save(business_id, _image_bytes())
    assert path.is_file()
    assert reference.startswith(f"/local-assets/{business_id}/")
    assert list(path.parent.iterdir()) == [path]
    preview = store.render_preview(business_id, reference)
    assert preview.startswith(b"\x89PNG\r\n\x1a\n")
    assert list(path.parent.iterdir()) == [path]

    store.remove(other_business_id, reference)
    assert path.is_file()
    store.remove(business_id, reference)
    assert not path.exists()


def test_png_logo_preview_keeps_transparency_and_aspect_ratio(tmp_path) -> None:
    store = LocalAssetStore(tmp_path)
    business_id = uuid4()
    stream = BytesIO()
    Image.new("RGBA", (640, 320), (35, 150, 80, 120)).save(stream, format="PNG")

    reference, path = store.save(business_id, stream.getvalue())

    preview_bytes = store.render_preview(business_id, reference)
    with Image.open(path) as original, Image.open(BytesIO(preview_bytes)) as preview:
        assert original.size == (640, 320)
        assert original.getpixel((0, 0))[3] == 120
        assert preview.size == (320, 160)
        assert preview.getpixel((0, 0))[3] == 120
