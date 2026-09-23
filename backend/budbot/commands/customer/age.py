"""Public age/compliance information rendered from the active M3 profile."""

from budbot.compliance.age_gate import AgeGateStatus
from budbot.compliance.registry import get_profile
from budbot.commands.customer.common import command_result
from budbot.commands.types import CommandExecutionContext, CommandResult, ParsedCommand


async def age(
    context: CommandExecutionContext, parsed: ParsedCommand
) -> CommandResult:
    customer_session = context.customer_session
    assert customer_session is not None
    profile = get_profile(
        customer_session.compliance_profile_id,
        customer_session.compliance_profile_version,
    )
    lines = [f"Active compliance profile: {profile.profile_id}@{profile.version}."]
    if profile.requires_age_gate and profile.minimum_age is not None:
        lines.append(
            f"This profile requires a {profile.minimum_age}+ website/session attestation "
            "for cannabis-specific access."
        )
        lines.append(profile.website_attestation_notice)
    else:
        lines.append(profile.website_attestation_notice)
    if profile.medical_eligibility_notice:
        lines.append(profile.medical_eligibility_notice)
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
