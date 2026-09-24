# BudBot Compliance Architecture

Status: V1 project contract  
Last updated: 2026-09-23

> This document is an engineering compliance specification, not legal advice. Cannabis rules can change. Production deployments should be reviewed against current law, OLCC and NM CCD guidance, and the business's legal/compliance requirements.

## Goal

Compliance is a first-class backend subsystem, not a prompt-only behavior.

BudBot must support versioned compliance profiles. The initial profiles are:

- `general_retail@1.0`;
- `oregon_cannabis@1.0`;
- `new_mexico_cannabis@1.0`.

Profiles declare a compliance domain and either global applicability or one
canonical jurisdiction. Domains are `general_retail` and `cannabis`; business
industry labels are descriptive and are never legal-policy identifiers.

Future jurisdictions/verticals should be added as separate versioned profiles rather than by forking the application.

## Mandatory design principles

1. Mandatory compliance controls are server enforced.
2. Slash commands do not bypass compliance.
3. Direct API calls do not bypass compliance.
4. The LLM is not the sole enforcement mechanism.
5. Businesses may configure optional behavior, but may not disable mandatory profile rules.
6. Compliance decisions should be testable without an external model.
7. A compliance profile records its version and source/update metadata.
8. The application must distinguish age-gating a website/chat session from legally sufficient proof of age for a retail transaction.

## Oregon cannabis baseline

### Recreational age

Oregon OLCC materials state that recreational marijuana consumers must be at least 21 years old.

An OLCC retailer may also serve qualifying OMMP registry identification cardholders between ages 18 and 21 when the applicable medical requirements are met.

Therefore BudBot must not encode "every lawful Oregon marijuana customer is always 21+" as a universal purchase rule.

For the initial recreational-dispensary website profile, BudBot may require a 21+ session attestation before exposing cannabis-specific browsing/chat functionality unless a future explicitly designed medical workflow is enabled.

### Age gate is not transaction ID verification

The website age gate is a session-access control.

It must not claim to be:

- government ID verification;
- legal proof of age;
- a replacement for retailer ID checks;
- authorization to purchase cannabis.

Actual purchase/acquisition verification remains the retailer/POS/store's responsibility.

### Advertising/informational restrictions

The Oregon cannabis profile should conservatively treat public customer-facing chatbot content as subject to applicable marijuana/hemp advertising and informational-material restrictions.

The compliance layer must prevent BudBot-generated promotional content from:

- being false, deceptive, or misleading;
- targeting people under 21;
- encouraging illegal activity or interstate transport of marijuana;
- claiming government endorsement or implying a product is safe because it is regulated/tested;
- making unsupported curative or therapeutic claims;
- depicting or encouraging marijuana/hemp consumption where prohibited;
- encouraging use because of intoxicating effects;
- encouraging excessive or rapid consumption.

The profile must also support required internet-advertising warning text where applicable.

Current OLCC rule text includes warnings concerning operating vehicles/machinery, adult-only use, and keeping products away from children. Do not paraphrase legally required warning language in the production profile unless counsel/current rules confirm that paraphrasing is permitted.

### Medical/health questions

BudBot may report authoritative structured product facts, for example:

- labeled THC/CBD values;
- serving/container information supplied by the product source;
- ingredients;
- category;
- price;
- availability.

BudBot must not independently prescribe personalized cannabis treatment or invent medical claims.

When a customer asks for diagnosis, treatment, or personalized dosing, the compliance response should redirect to factual product information and appropriate professional advice rather than fabricating a therapeutic recommendation.

This does not prohibit faithfully presenting legally permissible product-label information or business-provided factual information.

## Session age-gate model

Conceptual state:

```text
NOT_REQUIRED
REQUIRED_UNVERIFIED
VERIFIED
DENIED
EXPIRED
```

A cannabis session should contain, at minimum:

- session ID;
- tenant ID;
- selected location ID if known;
- active compliance-profile ID/version;
- age-gate status;
- verification/attestation timestamp;
- expiration metadata if used.

Do not store unnecessary identity documents merely to implement the website age gate.

## M3 implementation boundary

M3 persists an opaque UUID customer session scoped to the tenant, with an
optional active same-tenant location, a snapshot of the active profile ID and
version, an explicit age-gate state, an attestation timestamp when submitted,
and a bounded expiration timestamp. It stores no date of birth, government ID,
ID image, or customer legal name.

M3 initially stored one business-selected profile. M5.5 deliberately replaces
that business-wide jurisdiction assumption while preserving session snapshots
and `COMPLIANCE_PROFILE_MISMATCH` for stale bindings. See the M5.5 section below.

The session API accepts `confirmed_21_or_older` only for the website/session
attestation flow. A positive Oregon attestation moves a new session to
`VERIFIED`; a negative response moves it to `DENIED`. Denied and expired
sessions cannot be upgraded in place. The attestation is not transaction-level
ID verification or purchase authorization, and OMMP verification remains
deferred.

## M5.5 multi-jurisdiction resolution

`Business.compliance_domain` is the policy-domain selector. `Location.region`
remains display text; `country` plus an explicitly supplied, normalized
two-letter `region_code` determines a code such as `US-OR` or `US-NM`. Existing
locations are not guessed from free text: their new region code stays null until
configured. The Alembic M5.5 migration maps a legacy `oregon_cannabis` business
to `cannabis`; legacy business profile ID/version remain for M3 API and
configuration compatibility, but never select a cannabis location's policy.

One immutable, declarative profile catalog and `ComplianceResolver` select the
active profile by domain and jurisdiction. General retail resolves to its
global profile and has no cannabis age gate. Cannabis locations resolve as
`US-OR -> oregon_cannabis@1.0` and
`US-NM -> new_mexico_cannabis@1.0`. No selected cannabis location yields
`COMPLIANCE_LOCATION_REQUIRED`; a missing canonical code or unconfigured
jurisdiction yields `COMPLIANCE_PROFILE_UNAVAILABLE`. Neither case falls back
to Oregon. A small explicit set of public-information capabilities remains
available; regulated, unknown, and prohibited capabilities remain closed.

Sessions snapshot `(compliance_domain, jurisdiction_code, profile_id,
profile_version)` plus resolution status. A location change is serialized by
locking the session, business configuration, and selected location. If that
fingerprint changes, the binding is refreshed, the age gate is initialized for
the new resolution, and its attestation timestamp is cleared. A same-fingerprint
switch (for example Portland to Salem) preserves valid verification. An active
catalog version change makes old sessions stale; protected capabilities reject
them until a fresh session or explicit location rebind establishes the new
binding. Location-scoped profile overrides are not persisted in M5.5; the
resolver has a validated future override seam but user-supplied IDs cannot
choose profiles.

The New Mexico adult-use website flow requires a 21+ session attestation.
This is not a claim that every lawful New Mexico cannabis customer must be 21:
the CCD describes a separate medical pathway for qualifying patients from age
18, subject to program requirements and valid patient/government identification.
BudBot does not verify medical eligibility, registry cards, government ID, or
purchase eligibility. The profile records reviewed regulator sources and does
not implement the full New Mexico advertising rule engine.

Future profile distribution uses a trusted registry and signed/versioned,
schema-validated declarative packages: validate schema, signature/trust, and
compatibility; stage; then explicitly or policy-activate. Profile packages
cannot contain executable code. `/compliance status`, `/check`, `/update`, and
`/sources` are future informational/update operations. A tenant-submitted
regulator URL may become source metadata or a review request only; it must
never directly rewrite or activate live rules. Hosted and self-hosted
deployments may consume the same trusted packages; self-hosted installations
may use cached validated profiles offline. No network updater is included here.
The M5.5 downgrade intentionally refuses to run while cannabis tenants exist,
because M5 cannot safely represent jurisdiction-specific session bindings.

## Request enforcement

Conceptual request path:

```text
Request
  ↓
Resolve tenant
  ↓
Resolve compliance profile
  ↓
Resolve session
  ↓
Does capability require age gate?
  ├── no  -> continue
  └── yes
        ↓
      verified?
        ├── no  -> AGE_VERIFICATION_REQUIRED
        └── yes -> continue
  ↓
Command/tool-specific compliance policy
  ↓
Execute
```

A frontend modal is not sufficient enforcement.

## Capability policy

Each sensitive capability should be classifiable by the profile.

Examples:

```text
business_hours      -> public
locations           -> public
contact              -> public
age_information      -> public
cannabis_products    -> age-gated
cannabis_search      -> age-gated
cannabis_deals       -> age-gated + advertising policy
medical_advice       -> prohibited as an assistant-generated capability
```

M6 adds generic `catalog_products`, `catalog_search`, and `catalog_deals`
capabilities so command handlers remain industry-neutral. General-retail profile
rules allow these catalog reads without cannabis age gating. Oregon and New Mexico
cannabis profile rules age-gate them. `/categories` uses the product catalog
capability because category names can disclose regulated menu information. The
generic capabilities are not in `SAFE_PUBLIC_CAPABILITIES`; no-location and
unsupported-jurisdiction cannabis requests therefore retain M5.5 fail-closed
behavior.

The exact policy matrix should be explicit and tested.

M7 AI tools are not a separate compliance path. The tool bridge statically maps
normalized model calls to existing customer commands, and the command executor
repeats tenant, feature, selected-location, and capability checks at execution
time. Product/category/deal calls therefore continue through the M6 catalog
services and the active server-side compliance profile. Tool schemas are only
advertisements and do not authorize execution. An unselected or unsupported
cannabis location fails closed, and a stale session binding is rejected before
provider use.

The AI service may refuse detected medical-advice requests before advertising or
executing catalog tools; `medical_advice` remains prohibited by the compliance
engine. That lightweight intent check is an early refusal aid, not the safety
boundary for generated recommendations: public chat returns deterministic command
output after tool execution and never returns the model's free-form synthesis.
Thus a missed intent phrase cannot turn catalog facts into a generated treatment
recommendation. Prompts are additional guidance only and never replace
server-side policy. FAQ/catalog/tool text and user messages remain data in their
respective message roles, not trusted system instructions. If AI is disabled or
unavailable, existing slash commands and deterministic compliance behavior remain
available.

## Promotions and `/deals`

BudBot may display business-supplied promotions only when:

- the promotion is enabled;
- the promotion belongs to the correct tenant/location;
- the active compliance profile permits it;
- required warnings/disclosures are applied;
- the assistant does not embellish or invent terms.

## Compliance source tracking

Each compliance profile should record metadata similar to:

```text
profile_id
profile_version
jurisdiction
effective_from
reviewed_at
source_references[]
```

Rules must not silently change in production. Compliance updates should be versioned, reviewed, tested, and recorded in the audit log/release notes.

## Admin controls

Admins may:

- view the active compliance profile;
- view its version;
- view explanatory source metadata;
- configure options explicitly marked configurable.

Admins may not disable mandatory profile controls through normal configuration or slash commands.

## Testing requirements

At minimum, automated tests must prove:

- an unverified cannabis session cannot use gated product commands;
- a verified session can use permitted gated capabilities;
- `/help` does not expose inaccessible commands incorrectly;
- direct API calls cannot bypass the gate;
- `/clear` does not accidentally remove or forge compliance state;
- tenant A cannot reuse tenant B's session/compliance state;
- prohibited health-claim paths remain blocked;
- required warning content is present where the profile requires it;
- general-retail tenants are not incorrectly forced through the cannabis gate.

## Current Oregon source references

Reviewed 2026-09-19:

- Oregon Liquor and Cannabis Commission, Marijuana FAQ:  
  https://www.oregon.gov/olcc/marijuana/pages/frequently-asked-questions.aspx

- Oregon Secretary of State, OAR 845-025-2800, Retailer Privileges; Prohibitions:  
  https://secure.sos.state.or.us/oard/viewSingleRule.action?ruleVrsnRsn=255959

- OLCC, OAR 845-025-8040 advertising-rule amendment text:  
  https://www.oregon.gov/olcc/Docs/rules/MJ-Leg-Tech-Rules.pdf

- OLCC, Acceptable ID for Marijuana:  
  https://cms.oregon.gov/olcc/docs/publications/Acceptable_ID_Marijuana_English.pdf

Before a production release, re-check the current official rule text rather than assuming this draft remains current.

## New Mexico source references

Reviewed 2026-09-23:

- New Mexico Regulation and Licensing Department, Cannabis Control Division FAQs:
  https://www.rld.nm.gov/cannabis/cannabis-in-new-mexico/faqs/
- CCD Industry Bulletin 25-15:
  https://www.rld.nm.gov/wp-content/uploads/2025/10/25-15.pdf
- New Mexico Administrative Code 16.8.3, packaging, labeling, advertising, marketing, and display:
  https://www.srca.nm.gov/parts/title16/16.008.0003.html
