"""Small HTTP client for the loopback-only M8 branding editor."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8000"
MAX_IMAGE_BYTES = 4 * 1024 * 1024
_ASSET_REFERENCE = re.compile(
    r"^/local-assets/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/[0-9a-f]{32}\.(?:png|jpg|webp)$"
)
_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class BrandingClientError(RuntimeError):
    """An actionable error from local branding operations."""


def validate_local_asset_reference(reference: str | None) -> str | None:
    """Allow only generated same-origin app assets, never arbitrary image URLs."""

    if not reference:
        return None
    if not _ASSET_REFERENCE.fullmatch(reference):
        raise BrandingClientError("This image is not a BudBot local asset.")
    return reference


def encode_image_file(path: Path) -> dict[str, str]:
    """Read an allowed bounded image and encode it for the local upload API."""

    image_path = Path(path)
    if image_path.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise BrandingClientError("Choose a PNG, JPG, or WebP image.")
    try:
        size = image_path.stat().st_size
        if size < 1 or size > MAX_IMAGE_BYTES:
            raise BrandingClientError("Choose an image no larger than 4 MB.")
        payload = image_path.read_bytes()
    except OSError as exc:
        raise BrandingClientError(f"Could not read the selected image: {exc}") from None
    if len(payload) != size:
        raise BrandingClientError("The selected image changed while it was being read.")
    return {"content_base64": base64.b64encode(payload).decode("ascii")}


class LocalBrandingClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 8.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, business_id: str | None = None, payload: object = None):
        headers = {"Accept": "application/json"}
        if business_id:
            headers["X-BudBot-Business-ID"] = business_id
        data = None
        method = "GET"
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
            method = "PUT"
        request = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = ""
            try:
                body = json.loads(exc.read().decode("utf-8"))
                detail = body.get("detail", "")
            except (OSError, ValueError, AttributeError):
                pass
            if isinstance(detail, list):
                detail = "; ".join(
                    str(item.get("msg", "Invalid value"))
                    for item in detail
                    if isinstance(item, dict)
                )
            raise BrandingClientError(
                str(detail) or f"Branding request failed ({exc.code})."
            ) from None
        except (OSError, URLError, TimeoutError, ValueError) as exc:
            raise BrandingClientError(
                f"BudBot could not load branding settings. Make sure the service is running. ({exc})"
            ) from None

    def list_businesses(self) -> list[dict[str, str]]:
        result = self._request("/api/v1/local/businesses")
        if not isinstance(result, list):
            raise BrandingClientError("BudBot returned an invalid business list.")
        return result

    def load(self, business_id: str) -> dict[str, dict[str, object]]:
        business = self._request(f"/api/v1/businesses/{business_id}", business_id)
        assistant = self._request(
            f"/api/v1/businesses/{business_id}/assistant", business_id
        )
        validate_local_asset_reference(business.get("logo_reference"))
        validate_local_asset_reference(assistant.get("avatar_reference"))
        return {"business": business, "assistant": assistant}

    def save(self, business_id: str, changes: dict[str, object]) -> dict[str, dict[str, object]]:
        return self._request(
            f"/api/v1/local/businesses/{business_id}/branding",
            business_id,
            changes,
        )

    def load_asset(self, reference: str) -> bytes:
        safe_reference = validate_local_asset_reference(reference)
        if safe_reference is None:
            return b""
        return self._read_asset(safe_reference)

    def load_asset_preview(self, reference: str, business_id: str) -> bytes:
        safe_reference = validate_local_asset_reference(reference)
        if safe_reference is None:
            return b""
        reference_business_id, filename = safe_reference.removeprefix(
            "/local-assets/"
        ).split("/", 1)
        if reference_business_id != business_id:
            raise BrandingClientError("This image belongs to a different business.")
        request = Request(
            f"{self.base_url}/api/v1/local/businesses/{business_id}/assets/{filename}/preview",
            headers={
                "Accept": "image/png",
                "X-BudBot-Business-ID": business_id,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read(MAX_IMAGE_BYTES + 1)
            if len(payload) > MAX_IMAGE_BYTES:
                raise BrandingClientError("This local image preview is larger than expected.")
            return payload
        except HTTPError as exc:
            raise BrandingClientError(
                f"Could not render the saved local image preview ({exc.code})."
            ) from None
        except (OSError, URLError, TimeoutError) as exc:
            raise BrandingClientError(f"Could not load the saved local image preview: {exc}") from None

    def _read_asset(self, safe_reference: str) -> bytes:
        request = Request(self.base_url + safe_reference, headers={"Accept": "image/*"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read(MAX_IMAGE_BYTES + 1)
            if len(payload) > MAX_IMAGE_BYTES:
                raise BrandingClientError("This local image is larger than expected.")
            return payload
        except (OSError, URLError, TimeoutError) as exc:
            raise BrandingClientError(f"Could not load the saved local image: {exc}") from None
