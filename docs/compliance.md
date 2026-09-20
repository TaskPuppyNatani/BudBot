# BudBot Compliance Architecture

Status: V1 project contract  
Last updated: 2026-09-19

> This document is an engineering compliance specification, not legal advice. Cannabis rules can change. Production deployments should be reviewed against current law, OLCC guidance, and the business's legal/compliance requirements.

## Goal

Compliance is a first-class backend subsystem, not a prompt-only behavior.

BudBot must support versioned compliance profiles. The initial profiles are:

- `general_retail`;
- `oregon_cannabis`.

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

The exact policy matrix should be explicit and tested.

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
