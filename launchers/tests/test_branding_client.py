from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from branding_client import (
    BrandingClientError,
    LocalBrandingClient,
    encode_image_file,
    validate_local_asset_reference,
)


class BrandingClientTests(unittest.TestCase):
    def test_only_generated_local_asset_references_are_accepted(self) -> None:
        reference = "/local-assets/12345678-1234-4678-9234-567812345678/0123456789abcdef0123456789abcdef.png"
        self.assertEqual(validate_local_asset_reference(reference), reference)
        for unsafe in (
            "https://example.com/logo.png",
            "/local-assets/../../etc/passwd",
            reference + "?fetch=1",
        ):
            with self.subTest(reference=unsafe), self.assertRaises(BrandingClientError):
                validate_local_asset_reference(unsafe)

    def test_image_picker_upload_is_extension_and_size_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            png = Path(directory) / "mark.png"
            png.write_bytes(b"not decoded here")
            result = encode_image_file(png)
            self.assertTrue(result["content_base64"])
            unsupported = Path(directory) / "mark.svg"
            unsupported.write_text("<svg/>")
            with self.assertRaisesRegex(BrandingClientError, "PNG, JPG, or WebP"):
                encode_image_file(unsupported)

    def test_asset_preview_uses_the_selected_business_scoped_endpoint(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit: int) -> bytes:
                return b"png preview"

        business_id = "12345678-1234-4678-9234-567812345678"
        reference = f"/local-assets/{business_id}/0123456789abcdef0123456789abcdef.png"
        client = LocalBrandingClient()
        with patch("branding_client.urlopen", return_value=Response()) as urlopen:
            self.assertEqual(client.load_asset_preview(reference, business_id), b"png preview")
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            f"{client.base_url}/api/v1/local/businesses/{business_id}/assets/0123456789abcdef0123456789abcdef.png/preview",
        )
        self.assertEqual(request.headers["X-budbot-business-id"], business_id)
        with self.assertRaisesRegex(BrandingClientError, "different business"):
            client.load_asset_preview(reference, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


if __name__ == "__main__":
    unittest.main()
