"""Audit details are metadata, never an arbitrary stored JSON passthrough."""

import pytest

from budbot.services.audit_service import audit_details_for_read, record_audit_event


@pytest.mark.parametrize("value", [None, [], "private marker", 123, {"nested": {"secret": "private marker"}},
                                        {"location_id": "private marker"}, {"enabled": "private marker"}])
def test_unknown_or_malformed_details_are_not_serialized(value):
    assert audit_details_for_read(value) == {}


def test_known_branding_field_names_are_visible_without_their_values():
    assert audit_details_for_read({
        "changed_fields": "business_logo,assistant_display_name,primary_brand_color,private marker",
        "business_logo": "private marker",
    }) == {"changed_fields": "assistant_display_name,business_logo,primary_brand_color"}


async def test_audit_writer_also_redacts_csrf_and_request_material(db_session):
    event = await record_audit_event(db_session, "test.redaction", details={
        "csrf": "private marker", "CSRF_HEADER": "private marker", "password": "private marker",
        "cookie": "private marker", "authorization": "private marker", "request_body": "private marker",
        "payload": "private marker", "api_key_credential": "private marker", "enabled": False,
    })
    assert event.details == {"enabled": False}
