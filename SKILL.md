---
name: mobile-release-expert
description: End-to-end iOS and Android release execution for React Native CLI and Flutter apps with Fastlane-first automation, direct-console fallback, preflight audit, submission documentation generation, test-account packaging, rejection triage, and resubmission planning. Use when preparing a mobile app release, diagnosing App Store or Google Play rejections, generating release-ready reviewer artifacts, or reducing approval cycles with policy-aware best practices.
---

# Mobile Release Expert

Execute release work with one objective: reduce approval loops and ship safely.

## Core behavior

- Treat Fastlane as primary path and direct App Store Connect / Play Console as fallback.
- Support React Native CLI (non-Expo), Flutter, and mixed/hybrid repositories.
- Run preflight audit before every submission or resubmission.
- Generate a complete release kit, not only checklists.
- If rejection text is provided, generate root-cause triage plus a resubmission response draft.
- Block only for critical/high findings (P0/P1); keep lower severities advisory.

## Resource map

- Audit/prepare/triage CLI: `scripts/mobile_release_expert.py`
- Apple workflow reference: `references/apple-review-playbook.md`
- Google workflow reference: `references/google-play-playbook.md`
- Rejection pattern catalog: `references/rejection-catalog.json`
- MCP/tooling guidance: `references/mcp-and-tooling.md`
- Submission templates: `assets/templates/*`

## Required workflow

1. Identify project root and run audit.
2. Review P0/P1 findings and propose concrete fixes with file-level actions.
3. Generate release kit artifacts.
4. Validate Fastlane path; provide direct-console fallback checklist if lanes are missing.
5. If rejection exists, run triage and produce remediation + reviewer response.

Run commands from repository root:

```bash
python3 scripts/mobile_release_expert.py audit --project-root .
python3 scripts/mobile_release_expert.py prepare --project-root .
python3 scripts/mobile_release_expert.py triage --rejection-file path/to/rejection.txt --project-root .
```

## Output contract

Write outputs under:

`release-kit/<app-id>/<YYYY-MM-DD>/`

Minimum artifacts:

- `readiness-report.md`
- `blocking-issues.md`
- `ios-review-notes.md`
- `play-submission-notes.md`
- `test-accounts.csv`
- `release-checklist.md`
- `resubmission-response.md` (when triaging rejection)
- `readiness-report.json`

## Project detection

Detect all apps in the repository and run checks per app profile:

- React Native CLI app: `package.json` has `react-native`; `ios/` and `android/` exist.
- Flutter app: `pubspec.yaml` with flutter dependency; `android/` and `ios/` exist.

For monorepos, run per detected app directory and produce one release kit folder per app.

## Config contract

Use a project-local config file when present:

- `.release/release.config.json` (preferred)
- `release.config.json` (fallback)

If missing, generate defaults from `assets/templates/release-config.example.json` and continue with safe assumptions.

Expected config fields:

- app metadata (`app_id`, `app_name`, `platforms`)
- reviewer contact data
- Fastlane lane names
- test account provisioning command and fallback credentials
- policy URLs (privacy policy, terms, support)

## Test account automation

When test account hooks are available, run them automatically:

- If `test_account.provision_command` is set, execute it and parse JSON output.
- If command fails, downgrade to provided fallback credentials and raise P1.
- If no command and no fallback credentials, raise P1 with exact remediation steps.

Never submit without a reviewer login path when app requires authentication.

## Rejection triage behavior

When rejection text is supplied:

1. Classify by matching `references/rejection-catalog.json` patterns.
2. Produce likely root causes with confidence.
3. Produce fix checklist split by code/config/store-metadata.
4. Draft concise reviewer response focused on reproducible fixes and retest path.

If multiple patterns match, sort by confidence and severity.

## Fastlane and fallback behavior

- Validate Fastlane file presence and lane coverage for iOS and Android.
- If lanes are partial/missing, generate fallback direct-console run steps without blocking release prep.
- Keep Fastlane lane recommendations aligned with:
  - iOS: `build_app`, `deliver`
  - Android: `supply` / `upload_to_play_store`

## MCP and source hygiene

For policy interpretation or edge-case decisions:

1. Prefer official sources first (Apple, Google, Fastlane docs).
2. Use Context7 MCP when available for fresh API/docs references.
3. Treat community MCP servers as optional accelerators, not required dependencies.

## Skill interoperability

Invoke related skills only when needed:

- `security-best-practices`: when finding security/privacy risk likely to cause rejection.
- `spreadsheet`: when credentials/compliance tracking needs structured sheets.
- `playwright`: for console automation evidence capture.
- `screenshot` or `pdf`: when reviewer evidence packets are required.

## Escalation rules

- Do not run release upload commands automatically unless explicitly requested.
- Default to dry-run audit and artifact generation.
- Always show blockers first, then recommended fixes, then optional improvements.
