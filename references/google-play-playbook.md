# Google Play Review Playbook

## Goal

Prevent avoidable policy and metadata rejections through deterministic checks before rollout.

## Pre-submission checklist

- Validate `applicationId`, `versionCode`, `versionName`, and target SDK.
- Confirm Play Data safety and app behavior are consistent.
- Confirm account login path and test credentials (if auth required).
- Validate screenshots/listing assets against actual app UI.
- Check release notes, support URL, and privacy policy URL.
- Verify signing and upload path (Fastlane or Console).

## Common rejection themes

- Policy declarations inconsistent with in-app data usage.
- Broken auth flows or invalid test credentials.
- Package identity/versioning mistakes.
- Device compatibility/screen behavior issues.
- Misleading metadata.

## Internal testing best practice

- Run smoke suite on representative device matrix.
- Validate startup, login, purchase/subscription critical paths.
- Validate offline/error states and retry paths.
- Capture evidence artifacts for disputed rejections.

## Resubmission best practice

- Map each rejection reason to a concrete fix.
- Include exact tester steps and credentials.
- Mention changed build/version and impacted screens.
- Keep response direct; avoid speculative language.
