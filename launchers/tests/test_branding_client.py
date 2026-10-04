from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch
from urllib.request import HTTPCookieProcessor

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

    def test_dashboard_published_images_load_and_preview_in_control_center(self) -> None:
        business_id = "12345678-1234-4678-9234-567812345678"
        reference = f"/assets/branding/{business_id}/0123456789abcdef0123456789abcdef.png"
        self.assertEqual(validate_local_asset_reference(reference), reference)
        client = LocalBrandingClient()
        with patch.object(client, "_request", side_effect=[
            {"logo_reference": reference}, {"avatar_reference": reference},
        ]):
            self.assertEqual(client.load(business_id)["business"]["logo_reference"], reference)
        with patch.object(client.opener, "open") as opened:
            opened.return_value.__enter__.return_value.read.return_value = b"png preview"
            self.assertEqual(client.load_asset_preview(reference, business_id), b"png preview")
            self.assertIn(f"/businesses/{business_id}/assets/", opened.call_args.args[0].full_url)
        with self.assertRaisesRegex(BrandingClientError, "different business"):
            client.load_asset_preview(reference, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

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
        with patch.object(client.opener, "open", return_value=Response()) as open_request:
            self.assertEqual(client.load_asset_preview(reference, business_id), b"png preview")
        request = open_request.call_args.args[0]
        self.assertEqual(
            request.full_url,
            f"{client.base_url}/api/v1/local/businesses/{business_id}/assets/0123456789abcdef0123456789abcdef.png/preview",
        )
        self.assertNotIn("X-budbot-business-id", request.headers)
        with self.assertRaisesRegex(BrandingClientError, "different business"):
            client.load_asset_preview(reference, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

    def test_login_reuses_session_client_and_csrf_for_admin_writes(self) -> None:
        class Response:
            def __init__(self, payload: dict[str, object]) -> None:
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self) -> bytes:
                return json.dumps(self.payload).encode("utf-8")

        client = LocalBrandingClient()
        self.assertTrue(
            any(isinstance(handler, HTTPCookieProcessor) for handler in client.opener.handlers)
        )
        with patch.object(
            client.opener,
            "open",
            side_effect=[Response({"csrf_token": "csrf-session-token"}), Response({"saved": True})],
        ) as open_request:
            client.login("owner@example.test", "new private passphrase")
            self.assertEqual(client.save("1234", {"display_name": "Shop"}), {"saved": True})

        login_request, save_request = (call.args[0] for call in open_request.call_args_list)
        self.assertEqual(login_request.get_method(), "POST")
        self.assertNotIn("X-csrf-token", login_request.headers)
        self.assertIn(b"new private passphrase", login_request.data)
        self.assertEqual(save_request.headers["X-csrf-token"], "csrf-session-token")
        self.assertNotIn("X-budbot-business-id", save_request.headers)

    def test_invalid_login_is_reported_without_echoing_the_password(self) -> None:
        client = LocalBrandingClient()
        supplied_password = "private test password"
        error = HTTPError(
            f"{client.base_url}/api/v1/auth/login",
            401,
            "Unauthorized",
            {},
            None,
        )
        with patch.object(client.opener, "open", side_effect=error):
            with self.assertRaises(BrandingClientError) as raised:
                client.login("owner@example.test", supplied_password)
        self.assertIn("owner setup instructions", str(raised.exception))
        self.assertNotIn(supplied_password, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
