"""Explicit customer-session age-gate states and transitions."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from budbot.core.exceptions import ComplianceError


class AgeGateStatus(StrEnum):
    """Persisted states for a session's website age gate."""

    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED_UNVERIFIED = "REQUIRED_UNVERIFIED"
    VERIFIED = "VERIFIED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


# A descriptive alias keeps the domain language usable in callers and tests.
AgeGateState = AgeGateStatus


@dataclass(frozen=True, slots=True)
class AgeAttestationTransition:
    """The only state changes permitted by the M3 attestation flow."""

    status: AgeGateStatus
    attested_at: datetime | None


def initial_age_gate_status(*, requires_age_gate: bool) -> AgeGateStatus:
    """Return the profile-specific state for a newly created session."""

    return (
        AgeGateStatus.REQUIRED_UNVERIFIED
        if requires_age_gate
        else AgeGateStatus.NOT_REQUIRED
    )


def transition_age_gate(
    current: AgeGateStatus,
    *,
    confirmed_21_or_older: bool,
    requires_age_gate: bool,
    now: datetime,
    previous_attested_at: datetime | None,
) -> AgeAttestationTransition:
    """Apply one explicit attestation transition.

    A denied or expired session cannot be upgraded in place. A verified session
    is idempotent only for another positive attestation; a negative response
    cannot silently downgrade it.
    """

    if current is AgeGateStatus.EXPIRED:
        raise ComplianceError(
            "SESSION_EXPIRED",
            "the customer session has expired; create a new session",
            status_code=410,
        )

    if not requires_age_gate:
        if current is not AgeGateStatus.NOT_REQUIRED:
            raise ComplianceError(
                "COMPLIANCE_STATE_INVALID",
                "the session has an invalid state for its active compliance profile",
            )
        return AgeAttestationTransition(
            status=AgeGateStatus.NOT_REQUIRED,
            attested_at=None,
        )

    if current is AgeGateStatus.DENIED:
        raise ComplianceError(
            "AGE_VERIFICATION_DENIED",
            "this session was denied by the age attestation; create a new session",
        )
    if current is AgeGateStatus.VERIFIED:
        if confirmed_21_or_older:
            return AgeAttestationTransition(
                status=AgeGateStatus.VERIFIED,
                attested_at=previous_attested_at or now,
            )
        raise ComplianceError(
            "AGE_VERIFICATION_DENIED",
            "a verified session cannot be downgraded through a negative attestation",
        )
    if current is not AgeGateStatus.REQUIRED_UNVERIFIED:
        raise ComplianceError(
            "COMPLIANCE_STATE_INVALID",
            "the session has an invalid state for its active compliance profile",
        )

    return AgeAttestationTransition(
        status=(
            AgeGateStatus.VERIFIED
            if confirmed_21_or_older
            else AgeGateStatus.DENIED
        ),
        attested_at=now,
    )
