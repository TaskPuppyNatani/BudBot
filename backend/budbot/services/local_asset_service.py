"""Validated, business-scoped image storage for authenticated editors."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from uuid import UUID, uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGE_DIMENSION = 8192
MAX_IMAGE_PIXELS = 16_000_000
SUPPORTED_FORMATS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
_ASSET_NAME = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg|webp)$")


class LocalAssetError(ValueError):
    """An image cannot be safely used as a local brand asset."""


def normalize_image(payload: bytes) -> tuple[bytes, str]:
    """Decode and re-encode an allowed image, stripping metadata and bad payloads."""

    if not payload or len(payload) > MAX_IMAGE_BYTES:
        raise LocalAssetError("Choose an image no larger than 4 MB.")
    try:
        with Image.open(BytesIO(payload)) as opened:
            image_format = (opened.format or "").upper()
            if image_format not in SUPPORTED_FORMATS:
                raise LocalAssetError("Use a PNG, JPG, or WebP image.")
            if getattr(opened, "n_frames", 1) != 1:
                raise LocalAssetError("Animated images are not supported.")
            width, height = opened.size
            if (
                width < 1
                or height < 1
                or width > MAX_IMAGE_DIMENSION
                or height > MAX_IMAGE_DIMENSION
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise LocalAssetError(
                    "Image dimensions must be at most 8192 by 8192 and 16 megapixels."
                )
            opened.verify()

        with Image.open(BytesIO(payload)) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()
            output = BytesIO()
            if image_format == "JPEG":
                image.convert("RGB").save(
                    output, format="JPEG", quality=92, optimize=True
                )
            elif image_format == "WEBP":
                image.save(output, format="WEBP", quality=92, method=6)
            else:
                image.save(output, format="PNG", optimize=True)
        normalized = output.getvalue()
    except LocalAssetError:
        raise
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise LocalAssetError("The selected file is not a valid PNG, JPG, or WebP image.") from exc
    if len(normalized) > MAX_IMAGE_BYTES:
        raise LocalAssetError("The optimized image is larger than 4 MB.")
    return normalized, SUPPORTED_FORMATS[image_format]


class LocalAssetStore:
    """Store sanitized files beneath a persistent application-owned directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def save(self, business_id: UUID, payload: bytes) -> tuple[str, Path]:
        normalized, extension = normalize_image(payload)
        directory = self.root / str(business_id)
        directory.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4().hex}.{extension}"
        path = directory / filename
        try:
            path.write_bytes(normalized)
        except OSError as exc:
            path.unlink(missing_ok=True)
            raise LocalAssetError("BudBot could not save this image.") from exc
        return f"/local-assets/{business_id}/{filename}", path

    def render_preview(self, business_id: UUID, reference: str) -> bytes:
        """Render a small PNG for Tk in memory without storing a second image."""

        reference = reference.replace("/assets/branding/", "/local-assets/", 1)
        prefix = f"/local-assets/{business_id}/"
        if not reference.startswith(prefix):
            raise LocalAssetError("This image does not belong to the selected business.")
        filename = reference[len(prefix) :]
        if not _ASSET_NAME.fullmatch(filename):
            raise LocalAssetError("This is not a BudBot image asset.")
        tenant_root = (self.root / str(business_id)).resolve()
        path = (tenant_root / filename).resolve()
        if path.parent != tenant_root or not path.is_file():
            raise LocalAssetError("This local image is no longer available.")
        try:
            with Image.open(path) as opened:
                image = ImageOps.exif_transpose(opened)
                image.thumbnail((320, 320), Image.Resampling.LANCZOS)
                has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
                preview = image.convert("RGBA" if has_alpha else "RGB")
                output = BytesIO()
                preview.save(output, format="PNG", optimize=True)
                return output.getvalue()
        except (
            Image.DecompressionBombError,
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            ValueError,
        ) as exc:
            raise LocalAssetError("BudBot could not render this image preview.") from exc

    def remove(self, business_id: UUID, reference: str | None) -> None:
        """Remove only generated assets within the specified tenant directory."""

        if not reference:
            return
        reference = reference.replace("/assets/branding/", "/local-assets/", 1)
        prefix = f"/local-assets/{business_id}/"
        if not reference.startswith(prefix):
            return
        filename = reference[len(prefix) :]
        if not _ASSET_NAME.fullmatch(filename):
            return
        tenant_root = (self.root / str(business_id)).resolve()
        path = (tenant_root / filename).resolve()
        if path.parent == tenant_root:
            path.unlink(missing_ok=True)

    def read_published(self, business_id: UUID, filename: str) -> bytes:
        """Read generated images only; publication is checked by the API first."""
        if not _ASSET_NAME.fullmatch(filename):
            raise LocalAssetError("This image is unavailable.")
        root = self.root.resolve()
        directory = (root / str(business_id)).resolve()
        path = (directory / filename).resolve()
        if not directory.is_relative_to(root) or path.parent != directory:
            raise LocalAssetError("This image is unavailable.")
        try:
            if path.stat().st_size > MAX_IMAGE_BYTES:
                raise LocalAssetError("This image is unavailable.")
            return path.read_bytes()
        except OSError:
            raise LocalAssetError("This image is unavailable.") from None
