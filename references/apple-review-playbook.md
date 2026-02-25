# Apple Review Playbook

## Goal

Lower rejection loops by validating reviewer access, metadata clarity, and policy alignment before upload.

## Pre-submission checklist

- Confirm bundle ID, version, and build are correct and incremented.
- Verify reviewer login path with either guest mode or stable credentials.
- Include concise App Review notes with deterministic test steps.
- Ensure privacy policy/support URLs are public and reachable.
- Validate account deletion path if account creation exists.
- Retest critical flows on at least one small and one large iPhone profile.

## Common rejection themes

- Incomplete reviewer access (missing credentials, OTP lock, broken guest path).
- Metadata mismatch (descriptions/screenshots not matching app behavior).
- Broken flows (crashes, dead-end navigation, blank screens).
- Compliance declarations missing or contradictory.

## Review notes best practice

- State exactly where reviewer should tap first.
- Provide credentials and role permissions.
- Include feature flags required for reviewer visibility.
- Mention temporary backend environments if not production.

## Resubmission best practice

- Acknowledge each rejection point explicitly.
- Describe what changed and where.
- Mention retest coverage (automation + manual spot checks).
- Keep response factual and concise.
