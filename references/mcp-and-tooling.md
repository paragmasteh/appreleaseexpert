# MCP and Tooling Guidance

## Core tooling stack

- Fastlane for release automation (`deliver`, `upload_to_play_store`).
- Maestro for deterministic mobile smoke tests.
- Bundletool for Android bundle validation.
- Platform-native build/release commands for final verification.

## MCP usage policy

- Prefer official sources (Apple, Google, Fastlane, framework docs).
- Use Context7 MCP for up-to-date documentation retrieval when available.
- Use community MCP servers as optional accelerators only.

## Recommended optional MCP servers

- Context7 MCP (documentation context retrieval).
- App Store Connect MCP (community-maintained; validate output manually).
- Play Store MCP (community-maintained; validate output manually).

## Practical rule

Do not block release prep on MCP availability. The skill must run fully with local project files and built-in references.
