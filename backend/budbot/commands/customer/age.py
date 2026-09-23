"""Public age/compliance information rendered from the effective location."""

from budbot.compliance.age_gate import AgeGateStatus
from budbot.compliance.resolver import ComplianceResolutionStatus
from budbot.commands.customer.common import command_result
from budbot.commands.types import CommandExecutionContext, CommandResult, ParsedCommand
from budbot.services.session_service import SessionService


async def age(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    customer_session = context.customer_session
    assert customer_session is not None
    resolution = await SessionService(context.session, context.tenant).resolve_current(
        customer_session, require_match=False
    )
    lines: list[str] = []

    if resolution.status is ComplianceResolutionStatus.LOCATION_REQUIRED:
        lines.extend(
            (
                "No active location is selected for this cannabis business.",
                "Choose a location with /locations, then /location <name>, before age attestation or regulated cannabis access.",
            )
        )
        return command_result(parsed, "\n".join(lines))

    if resolution.profile is None:
        jurisdiction = resolution.jurisdiction_code or "the selected location"
        lines.extend(
            (
                f"BudBot does not have an active cannabis compliance profile for {jurisdiction}.",
                "Regulated cannabis access is unavailable here; no other jurisdiction's rules are being applied.",
                "Public business information remains available where appropriate.",
            )
        )
        return command_result(parsed, "\n".join(lines))

    profile = resolution.profile
    applicability = (
        f" for {resolution.jurisdiction_code}"
        if resolution.jurisdiction_code is not None
        else " (jurisdiction-neutral)"
    )
    lines.append(
        f"Effective compliance profile{applicability}: {profile.profile_id}@{profile.version}."
    )
    if profile.requires_age_gate and profile.minimum_age is not None:
        lines.append(
            f"This profile requires a {profile.minimum_age}+ website/session attestation "
            "for cannabis-specific access."
        )
    lines.append(profile.website_attestation_notice)
    if profile.medical_eligibility_notice:
        lines.append(profile.medical_eligibility_notice)

    if not resolution.matches_session(customer_session):
        lines.append(
            "This session's compliance binding is stale, so its previous age attestation "
            "does not authorize regulated access. Select a location again or create a new session."
        )
    else:
        status = customer_session.age_gate_status
        status_text = {
            AgeGateStatus.NOT_REQUIRED: "no age attestation is required",
            AgeGateStatus.REQUIRED_UNVERIFIED: "the age attestation has not been completed",
            AgeGateStatus.VERIFIED: "website/session attestation recorded",
            AgeGateStatus.DENIED: "the session was denied by the attestation",
            AgeGateStatus.EXPIRED: "the session has expired",
        }
        lines.append(f"Session status: {status_text.get(status, 'status unavailable')}.")
    return command_result(parsed, "\n".join(lines))
