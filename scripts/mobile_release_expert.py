#!/usr/bin/env python3
"""Mobile Release Expert CLI.

Audit and prepare mobile releases for React Native CLI and Flutter projects.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
SEVERITY_WEIGHTS = {"P0": 35, "P1": 15, "P2": 5, "P3": 2}
SKIP_DIRS = {
    ".git",
    "node_modules",
    "Pods",
    ".dart_tool",
    ".gradle",
    ".idea",
    ".vscode",
    "build",
    "dist",
    "release-kit",
}
PLACEHOLDER_PATTERNS = (
    "com.example",
    "your.package",
    "changeme",
    "todo",
    "sample",
)
DATE_FMT = "%Y-%m-%d"


@dataclass
class AppProfile:
    root: Path
    frameworks: List[str]


@dataclass
class Finding:
    finding_id: str
    severity: str
    title: str
    description: str
    remediation: str
    file: Optional[str] = None
    tags: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "id": self.finding_id,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "remediation": self.remediation,
        }
        if self.file:
            payload["file"] = self.file
        if self.tags:
            payload["tags"] = self.tags
        return payload


def is_placeholder(value: str) -> bool:
    lower = value.lower()
    return any(token in lower for token in PLACEHOLDER_PATTERNS)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "app"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(read_text(path))


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def discover_apps(project_root: Path) -> List[AppProfile]:
    candidates: Dict[Path, List[str]] = {}

    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        current = Path(dirpath)

        frameworks: List[str] = []
        has_android = (current / "android").is_dir()
        has_ios = (current / "ios").is_dir()

        if "package.json" in filenames:
            try:
                package_data = load_json(current / "package.json")
            except Exception:
                package_data = {}
            deps = package_data.get("dependencies", {})
            dev_deps = package_data.get("devDependencies", {})
            if "react-native" in deps or "react-native" in dev_deps:
                frameworks.append("react-native-cli")

        if "pubspec.yaml" in filenames:
            pubspec = read_text(current / "pubspec.yaml")
            if re.search(r"^\s*flutter\s*:\s*$", pubspec, flags=re.MULTILINE):
                frameworks.append("flutter")

        if frameworks and has_android and has_ios:
            candidates[current] = sorted(set(frameworks))
        elif has_android and has_ios and current == project_root:
            candidates[current] = ["hybrid-unknown"]

    apps = [AppProfile(root=path, frameworks=fw) for path, fw in sorted(candidates.items())]
    return apps


def find_release_config(app_root: Path) -> Tuple[Dict[str, Any], Optional[Path], Optional[Finding]]:
    paths = [
        app_root / ".release" / "release.config.json",
        app_root / "release.config.json",
    ]
    for path in paths:
        if not path.exists():
            continue
        try:
            return load_json(path), path, None
        except Exception as exc:
            finding = Finding(
                finding_id="CONFIG-001",
                severity="P1",
                title="Invalid release config JSON",
                description=f"Failed to parse {path}: {exc}",
                remediation="Fix JSON formatting and required fields in release config.",
                file=str(path),
                tags=["config"],
            )
            return {}, path, finding

    finding = Finding(
        finding_id="CONFIG-000",
        severity="P2",
        title="Release config not found",
        description="No .release/release.config.json or release.config.json file found.",
        remediation="Create release config from assets/templates/release-config.example.json.",
        tags=["config"],
    )
    return {}, None, finding


def _search_regex(text: str, patterns: Iterable[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


def check_android(app_root: Path, findings: List[Finding], facts: Dict[str, Any]) -> None:
    build_gradle = app_root / "android" / "app" / "build.gradle"
    build_gradle_kts = app_root / "android" / "app" / "build.gradle.kts"
    build_file = build_gradle if build_gradle.exists() else build_gradle_kts

    if not build_file.exists():
        findings.append(
            Finding(
                finding_id="AND-000",
                severity="P0",
                title="Android app module build file missing",
                description="Expected android/app/build.gradle(.kts) was not found.",
                remediation="Restore Android app module and ensure Gradle files exist.",
                file=str(build_file),
                tags=["android", "build"],
            )
        )
        return

    text = read_text(build_file)
    app_id = _search_regex(
        text,
        [
            r"applicationId\s*=\s*[\"']([^\"']+)[\"']",
            r"applicationId\s+[\"']([^\"']+)[\"']",
        ],
    )
    version_code = _search_regex(text, [r"versionCode\s*=\s*(\d+)", r"versionCode\s+(\d+)"])
    version_name = _search_regex(
        text,
        [
            r"versionName\s*=\s*[\"']([^\"']+)[\"']",
            r"versionName\s+[\"']([^\"']+)[\"']",
        ],
    )
    target_sdk = _search_regex(
        text,
        [r"targetSdk\s*=\s*(\d+)", r"targetSdkVersion\s+(\d+)", r"targetSdk\s+(\d+)"],
    )

    facts["android_build_file"] = str(build_file)
    facts["android_application_id"] = app_id or ""
    facts["android_version_code"] = version_code or ""
    facts["android_version_name"] = version_name or ""
    facts["android_target_sdk"] = target_sdk or ""

    if not app_id:
        findings.append(
            Finding(
                finding_id="AND-001",
                severity="P0",
                title="Android applicationId missing",
                description="Unable to detect applicationId in Gradle config.",
                remediation="Set applicationId in android/app/build.gradle(.kts).",
                file=str(build_file),
                tags=["android", "identity"],
            )
        )
    elif is_placeholder(app_id):
        findings.append(
            Finding(
                finding_id="AND-002",
                severity="P0",
                title="Android applicationId is placeholder",
                description=f"Detected placeholder applicationId: {app_id}",
                remediation="Use your production package name before submission.",
                file=str(build_file),
                tags=["android", "identity"],
            )
        )

    if not version_code:
        findings.append(
            Finding(
                finding_id="AND-003",
                severity="P1",
                title="Android versionCode missing",
                description="versionCode is required for Play Store submissions.",
                remediation="Set and increment versionCode in Gradle config.",
                file=str(build_file),
                tags=["android", "versioning"],
            )
        )

    if not version_name:
        findings.append(
            Finding(
                finding_id="AND-004",
                severity="P1",
                title="Android versionName missing",
                description="versionName is required for clear release metadata.",
                remediation="Set semantic versionName (for example 1.3.0).",
                file=str(build_file),
                tags=["android", "versioning"],
            )
        )

    if not target_sdk:
        findings.append(
            Finding(
                finding_id="AND-005",
                severity="P2",
                title="Android targetSdk not detected",
                description="Could not detect targetSdk/targetSdkVersion in Gradle config.",
                remediation="Set targetSdk to current Play policy requirement.",
                file=str(build_file),
                tags=["android", "policy"],
            )
        )
    elif target_sdk.isdigit() and int(target_sdk) < 34:
        findings.append(
            Finding(
                finding_id="AND-006",
                severity="P2",
                title="Android targetSdk may be outdated",
                description=f"Detected targetSdk={target_sdk}. Verify this satisfies current Play policy.",
                remediation="Upgrade compileSdk/targetSdk and retest.",
                file=str(build_file),
                tags=["android", "policy"],
            )
        )

    signing_release_detected = bool(
        re.search(r"signingConfigs\s*\{", text)
        and re.search(r"\brelease\b", text)
        and re.search(r"signingConfig", text)
    )
    if not signing_release_detected:
        findings.append(
            Finding(
                finding_id="AND-007",
                severity="P1",
                title="Android release signing config unclear",
                description="No clear release signing configuration detected in Gradle config.",
                remediation="Verify release signing config and Play App Signing setup.",
                file=str(build_file),
                tags=["android", "signing"],
            )
        )

    manifest = app_root / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    if manifest.exists():
        manifest_text = read_text(manifest)
        manifest_pkg = _search_regex(manifest_text, [r"<manifest[^>]*\spackage=[\"']([^\"']+)[\"']"])
        if manifest_pkg and is_placeholder(manifest_pkg):
            findings.append(
                Finding(
                    finding_id="AND-008",
                    severity="P1",
                    title="Android manifest package is placeholder",
                    description=f"Detected placeholder manifest package: {manifest_pkg}",
                    remediation="Update manifest package and Gradle namespace/applicationId consistency.",
                    file=str(manifest),
                    tags=["android", "identity"],
                )
            )


def find_info_plist(app_root: Path) -> Optional[Path]:
    preferred = app_root / "ios" / "Runner" / "Info.plist"
    if preferred.exists():
        return preferred

    ios_root = app_root / "ios"
    if not ios_root.exists():
        return None

    for plist_path in ios_root.rglob("Info.plist"):
        plist_str = str(plist_path)
        if "/Pods/" in plist_str or "/build/" in plist_str:
            continue
        return plist_path
    return None


def parse_pbxproj_values(app_root: Path) -> Dict[str, str]:
    pbxproj_files = list((app_root / "ios").glob("*.xcodeproj/project.pbxproj"))
    if not pbxproj_files:
        return {}

    text = read_text(pbxproj_files[0])
    bundle = _search_regex(text, [r"PRODUCT_BUNDLE_IDENTIFIER\s*=\s*([^;]+);"])
    marketing = _search_regex(text, [r"MARKETING_VERSION\s*=\s*([^;]+);"])
    current = _search_regex(text, [r"CURRENT_PROJECT_VERSION\s*=\s*([^;]+);"])
    values = {}
    if bundle:
        values["PRODUCT_BUNDLE_IDENTIFIER"] = bundle.strip().strip('"')
    if marketing:
        values["MARKETING_VERSION"] = marketing.strip().strip('"')
    if current:
        values["CURRENT_PROJECT_VERSION"] = current.strip().strip('"')
    return values


def check_ios(app_root: Path, findings: List[Finding], facts: Dict[str, Any]) -> None:
    info_plist = find_info_plist(app_root)
    if not info_plist:
        findings.append(
            Finding(
                finding_id="IOS-000",
                severity="P0",
                title="iOS Info.plist missing",
                description="Could not locate a primary iOS Info.plist file.",
                remediation="Ensure ios/<target>/Info.plist exists and is tracked.",
                tags=["ios", "build"],
            )
        )
        return

    pbx_values = parse_pbxproj_values(app_root)

    try:
        with info_plist.open("rb") as handle:
            plist_data = plistlib.load(handle)
    except Exception as exc:
        findings.append(
            Finding(
                finding_id="IOS-001",
                severity="P0",
                title="Unable to parse Info.plist",
                description=f"Parsing failed for {info_plist}: {exc}",
                remediation="Fix Info.plist format before submitting.",
                file=str(info_plist),
                tags=["ios", "build"],
            )
        )
        return

    bundle_id = str(plist_data.get("CFBundleIdentifier", "")).strip()
    short_version = str(plist_data.get("CFBundleShortVersionString", "")).strip()
    build_version = str(plist_data.get("CFBundleVersion", "")).strip()

    if bundle_id in {"$(PRODUCT_BUNDLE_IDENTIFIER)", "${PRODUCT_BUNDLE_IDENTIFIER}"}:
        bundle_id = pbx_values.get("PRODUCT_BUNDLE_IDENTIFIER", bundle_id)
    if short_version in {"$(MARKETING_VERSION)", "${MARKETING_VERSION}"}:
        short_version = pbx_values.get("MARKETING_VERSION", short_version)
    if build_version in {"$(CURRENT_PROJECT_VERSION)", "${CURRENT_PROJECT_VERSION}"}:
        build_version = pbx_values.get("CURRENT_PROJECT_VERSION", build_version)

    facts["ios_info_plist"] = str(info_plist)
    facts["ios_bundle_id"] = bundle_id
    facts["ios_version"] = short_version
    facts["ios_build"] = build_version

    if not bundle_id:
        findings.append(
            Finding(
                finding_id="IOS-002",
                severity="P0",
                title="iOS bundle identifier missing",
                description="CFBundleIdentifier is missing.",
                remediation="Set a valid bundle identifier in target settings.",
                file=str(info_plist),
                tags=["ios", "identity"],
            )
        )
    elif is_placeholder(bundle_id):
        findings.append(
            Finding(
                finding_id="IOS-003",
                severity="P0",
                title="iOS bundle identifier is placeholder",
                description=f"Detected placeholder bundle identifier: {bundle_id}",
                remediation="Use production bundle identifier before archive upload.",
                file=str(info_plist),
                tags=["ios", "identity"],
            )
        )

    if not short_version:
        findings.append(
            Finding(
                finding_id="IOS-004",
                severity="P1",
                title="iOS marketing version missing",
                description="CFBundleShortVersionString is missing.",
                remediation="Set semantic version string in target build settings.",
                file=str(info_plist),
                tags=["ios", "versioning"],
            )
        )

    if not build_version:
        findings.append(
            Finding(
                finding_id="IOS-005",
                severity="P1",
                title="iOS build number missing",
                description="CFBundleVersion is missing.",
                remediation="Set and increment build number for each upload.",
                file=str(info_plist),
                tags=["ios", "versioning"],
            )
        )

    if "ITSAppUsesNonExemptEncryption" not in plist_data:
        findings.append(
            Finding(
                finding_id="IOS-006",
                severity="P3",
                title="Encryption usage flag not declared",
                description="ITSAppUsesNonExemptEncryption key is not explicitly declared.",
                remediation="Set the key explicitly to avoid review clarification delays.",
                file=str(info_plist),
                tags=["ios", "compliance"],
            )
        )


def check_fastlane(app_root: Path, findings: List[Finding], facts: Dict[str, Any]) -> None:
    candidates = [
        app_root / "fastlane" / "Fastfile",
        app_root / "ios" / "fastlane" / "Fastfile",
        app_root / "android" / "fastlane" / "Fastfile",
    ]
    fastfiles = [path for path in candidates if path.exists()]

    facts["fastlane_fastfiles"] = [str(path) for path in fastfiles]
    if not fastfiles:
        findings.append(
            Finding(
                finding_id="FL-000",
                severity="P2",
                title="Fastlane not configured",
                description="No Fastfile found. Fastlane-first flow cannot run.",
                remediation="Add Fastlane lanes for iOS and Android or use direct-console fallback.",
                tags=["fastlane"],
            )
        )
        facts["fastlane_mode"] = "none"
        return

    joined = "\n".join(read_text(path).lower() for path in fastfiles)
    has_ios_lane = any(token in joined for token in ("deliver", "upload_to_app_store", "pilot"))
    has_android_lane = any(token in joined for token in ("upload_to_play_store", "supply"))

    facts["fastlane_has_ios_lane"] = has_ios_lane
    facts["fastlane_has_android_lane"] = has_android_lane

    if has_ios_lane and has_android_lane:
        facts["fastlane_mode"] = "full"
    elif has_ios_lane or has_android_lane:
        facts["fastlane_mode"] = "partial"
    else:
        facts["fastlane_mode"] = "metadata-only"

    if not has_ios_lane:
        findings.append(
            Finding(
                finding_id="FL-001",
                severity="P2",
                title="iOS publish lane not detected",
                description="No deliver/upload_to_app_store usage found in Fastfiles.",
                remediation="Add iOS lane using build_app + deliver.",
                tags=["fastlane", "ios"],
            )
        )

    if not has_android_lane:
        findings.append(
            Finding(
                finding_id="FL-002",
                severity="P2",
                title="Android publish lane not detected",
                description="No upload_to_play_store/supply usage found in Fastfiles.",
                remediation="Add Android lane using upload_to_play_store.",
                tags=["fastlane", "android"],
            )
        )


def check_maestro(app_root: Path, findings: List[Finding], facts: Dict[str, Any]) -> None:
    candidates = [app_root / "maestro", app_root / ".maestro", app_root / "tests" / "maestro"]
    flow_files: List[Path] = []

    for directory in candidates:
        if directory.exists():
            flow_files.extend(sorted(directory.rglob("*.yml")))
            flow_files.extend(sorted(directory.rglob("*.yaml")))

    flow_files = [path for path in flow_files if path.is_file()]
    facts["maestro_flows"] = [str(path) for path in flow_files]

    if not flow_files:
        findings.append(
            Finding(
                finding_id="TEST-001",
                severity="P2",
                title="No Maestro flows detected",
                description="No automated release smoke flows found in maestro/.maestro folders.",
                remediation="Add launch/login/core-navigation Maestro flows and run pre-submission.",
                tags=["testing", "maestro"],
            )
        )


def check_store_compliance(config: Dict[str, Any], findings: List[Finding]) -> None:
    policy = config.get("policy", {}) if isinstance(config, dict) else {}
    contact = config.get("contact", {}) if isinstance(config, dict) else {}

    privacy_url = str(policy.get("privacy_policy_url", "")).strip()
    support_url = str(policy.get("support_url", "")).strip()
    email = str(contact.get("email", "")).strip()

    if not privacy_url:
        findings.append(
            Finding(
                finding_id="POL-001",
                severity="P1",
                title="Privacy policy URL missing",
                description="Reviewer-facing privacy policy URL is not configured.",
                remediation="Add public privacy policy URL in release config and store listing.",
                tags=["policy"],
            )
        )

    if not support_url:
        findings.append(
            Finding(
                finding_id="POL-002",
                severity="P2",
                title="Support URL missing",
                description="Support URL is absent; this often delays metadata approval.",
                remediation="Provide support URL in release config and store metadata.",
                tags=["policy"],
            )
        )

    if not email:
        findings.append(
            Finding(
                finding_id="POL-003",
                severity="P1",
                title="Release contact email missing",
                description="Contact email is required for reviewer clarifications.",
                remediation="Add contact.email in release config.",
                tags=["policy", "contact"],
            )
        )


def check_test_accounts(config: Dict[str, Any], findings: List[Finding]) -> None:
    auth = config.get("authentication", {}) if isinstance(config, dict) else {}
    requires_login = bool(auth.get("requires_login", True))
    test_account = config.get("test_account", {}) if isinstance(config, dict) else {}

    provision_command = str(test_account.get("provision_command", "")).strip()
    fallback_accounts = test_account.get("fallback_accounts", [])

    if not requires_login:
        return

    if not provision_command and not fallback_accounts:
        findings.append(
            Finding(
                finding_id="ACC-001",
                severity="P1",
                title="No reviewer test account path configured",
                description="App requires login but no provisioning command or fallback credentials were supplied.",
                remediation="Configure test_account.provision_command or fallback_accounts in release config.",
                tags=["accounts", "review"],
            )
        )
    elif provision_command and not fallback_accounts:
        findings.append(
            Finding(
                finding_id="ACC-002",
                severity="P2",
                title="No fallback reviewer credentials",
                description="Provision command exists but fallback credentials are absent if automation fails.",
                remediation="Add at least one fallback account entry for manual submission notes.",
                tags=["accounts", "review"],
            )
        )


def check_device_matrix(config: Dict[str, Any], findings: List[Finding]) -> None:
    testing = config.get("testing", {}) if isinstance(config, dict) else {}
    matrix = testing.get("device_matrix", [])
    if not isinstance(matrix, list) or len(matrix) < 4:
        findings.append(
            Finding(
                finding_id="TEST-002",
                severity="P2",
                title="Screen-size/device matrix coverage is thin",
                description="Configured device matrix has fewer than four target profiles.",
                remediation="Test on small, medium, and large phones plus one tablet profile for each platform.",
                tags=["testing", "screens"],
            )
        )


def severity_counts(findings: List[Finding]) -> Dict[str, int]:
    counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    return counts


def compute_score(findings: List[Finding]) -> int:
    score = 100
    for finding in findings:
        score -= SEVERITY_WEIGHTS.get(finding.severity, 0)
    return max(score, 0)


def sort_findings(findings: List[Finding]) -> List[Finding]:
    return sorted(findings, key=lambda x: (SEVERITY_ORDER.get(x.severity, 99), x.finding_id))


def build_recommendations(findings: List[Finding]) -> List[str]:
    recs: List[str] = []
    by_severity = severity_counts(findings)
    if by_severity["P0"] > 0:
        recs.append("Resolve all P0 blockers before creating submission artifacts.")
    if by_severity["P1"] > 0:
        recs.append("Resolve P1 issues before uploading binaries to avoid predictable review loops.")
    if any(f.finding_id.startswith("FL-") for f in findings):
        recs.append("Complete Fastlane lane coverage to keep release execution deterministic.")
    if any(f.finding_id.startswith("ACC-") for f in findings):
        recs.append("Guarantee reviewer login access via provisioning command and fallback credentials.")
    if not recs:
        recs.append("No critical blockers detected. Proceed with staged rollout and post-upload verification.")
    return recs


def audit_app(app: AppProfile, project_root: Path) -> Dict[str, Any]:
    findings: List[Finding] = []
    facts: Dict[str, Any] = {
        "project_root": str(project_root),
        "app_root": str(app.root),
        "frameworks": app.frameworks,
    }

    config, config_path, config_issue = find_release_config(app.root)
    if config_issue:
        findings.append(config_issue)
    facts["release_config_path"] = str(config_path) if config_path else ""
    facts["release_config_present"] = bool(config_path)

    check_android(app.root, findings, facts)
    check_ios(app.root, findings, facts)
    check_fastlane(app.root, findings, facts)
    check_maestro(app.root, findings, facts)
    check_store_compliance(config, findings)
    check_test_accounts(config, findings)
    check_device_matrix(config, findings)

    app_id = (
        config.get("app", {}).get("app_id")
        if isinstance(config, dict)
        else None
    ) or facts.get("android_application_id") or facts.get("ios_bundle_id") or app.root.name
    app_slug = slugify(str(app_id))

    sorted_findings = sort_findings(findings)
    counts = severity_counts(sorted_findings)
    score = compute_score(sorted_findings)

    if counts["P0"] > 0 or counts["P1"] > 0:
        gate = "blocked"
    else:
        gate = "go"

    result = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "app_id": app_id,
        "app_slug": app_slug,
        "app_root": str(app.root),
        "frameworks": app.frameworks,
        "facts": facts,
        "gate": gate,
        "readiness_score": score,
        "severity_counts": counts,
        "findings": [item.to_dict() for item in sorted_findings],
        "recommendations": build_recommendations(sorted_findings),
    }

    return result


def to_markdown_report(result: Dict[str, Any]) -> str:
    counts = result["severity_counts"]
    findings = result["findings"]
    recs = result["recommendations"]

    lines = [
        f"# Mobile Release Readiness Report: {result['app_id']}",
        "",
        f"- Generated: {result['generated_at']}",
        f"- App root: `{result['app_root']}`",
        f"- Frameworks: {', '.join(result['frameworks'])}",
        f"- Gate: **{result['gate'].upper()}**",
        f"- Readiness score: **{result['readiness_score']} / 100**",
        "",
        "## Severity Summary",
        "",
        "| P0 | P1 | P2 | P3 |",
        "|---:|---:|---:|---:|",
        f"| {counts['P0']} | {counts['P1']} | {counts['P2']} | {counts['P3']} |",
        "",
        "## Findings",
        "",
    ]

    if not findings:
        lines.append("No findings detected.")
    else:
        for idx, finding in enumerate(findings, start=1):
            location = f" ({finding['file']})" if finding.get("file") else ""
            lines.append(f"{idx}. [{finding['severity']}] {finding['title']}{location}")
            lines.append(f"   - {finding['description']}")
            lines.append(f"   - Fix: {finding['remediation']}")

    lines.extend(["", "## Recommended Next Actions", ""])
    for rec in recs:
        lines.append(f"- {rec}")

    return "\n".join(lines).strip() + "\n"


def blocking_issues_markdown(result: Dict[str, Any]) -> str:
    findings = [item for item in result["findings"] if item["severity"] in {"P0", "P1"}]

    lines = [
        f"# Blocking Issues: {result['app_id']}",
        "",
        "These issues should be fixed before submission.",
        "",
    ]

    if not findings:
        lines.append("No P0/P1 blockers detected.")
    else:
        for idx, item in enumerate(findings, start=1):
            lines.append(f"{idx}. [{item['severity']}] {item['title']}")
            lines.append(f"   - {item['description']}")
            lines.append(f"   - Fix: {item['remediation']}")
    return "\n".join(lines).strip() + "\n"


def template_context(result: Dict[str, Any], config: Dict[str, Any], accounts: List[Dict[str, str]]) -> Dict[str, str]:
    app = config.get("app", {}) if isinstance(config, dict) else {}
    contact = config.get("contact", {}) if isinstance(config, dict) else {}
    policy = config.get("policy", {}) if isinstance(config, dict) else {}
    fastlane = config.get("fastlane", {}) if isinstance(config, dict) else {}

    facts = result.get("facts", {})
    context = {
        "APP_ID": str(result.get("app_id", "")),
        "APP_NAME": str(app.get("app_name", result.get("app_id", ""))),
        "APP_ROOT": str(result.get("app_root", "")),
        "DATE": dt.datetime.now().strftime(DATE_FMT),
        "FRAMEWORKS": ", ".join(result.get("frameworks", [])),
        "READINESS_SCORE": str(result.get("readiness_score", "")),
        "GATE": str(result.get("gate", "")).upper(),
        "P0_COUNT": str(result.get("severity_counts", {}).get("P0", 0)),
        "P1_COUNT": str(result.get("severity_counts", {}).get("P1", 0)),
        "P2_COUNT": str(result.get("severity_counts", {}).get("P2", 0)),
        "P3_COUNT": str(result.get("severity_counts", {}).get("P3", 0)),
        "IOS_BUNDLE_ID": str(facts.get("ios_bundle_id", "")),
        "IOS_VERSION": str(facts.get("ios_version", "")),
        "IOS_BUILD": str(facts.get("ios_build", "")),
        "ANDROID_APPLICATION_ID": str(facts.get("android_application_id", "")),
        "ANDROID_VERSION_NAME": str(facts.get("android_version_name", "")),
        "ANDROID_VERSION_CODE": str(facts.get("android_version_code", "")),
        "CONTACT_NAME": str(contact.get("name", "")),
        "CONTACT_EMAIL": str(contact.get("email", "")),
        "CONTACT_PHONE": str(contact.get("phone", "")),
        "PRIVACY_POLICY_URL": str(policy.get("privacy_policy_url", "")),
        "SUPPORT_URL": str(policy.get("support_url", "")),
        "ACCOUNT_DELETION_URL": str(policy.get("account_deletion_url", "")),
        "FASTLANE_IOS_LANE": str(fastlane.get("ios_lane", "release_ios")),
        "FASTLANE_ANDROID_LANE": str(fastlane.get("android_lane", "release_android")),
        "TEST_ACCOUNT_COUNT": str(len(accounts)),
    }
    return context


def render_template(text: str, context: Dict[str, str]) -> str:
    output = text
    for key, value in context.items():
        output = output.replace("{{" + key + "}}", value)
    return output


def load_template(name: str, script_path: Path) -> str:
    template_path = script_path.parent.parent / "assets" / "templates" / name
    if not template_path.exists():
        raise FileNotFoundError(f"Template missing: {template_path}")
    return read_text(template_path)


def attempt_provision_accounts(config: Dict[str, Any], app_root: Path) -> Tuple[List[Dict[str, str]], Optional[str]]:
    test_account = config.get("test_account", {}) if isinstance(config, dict) else {}
    fallback_accounts = test_account.get("fallback_accounts", [])
    provision_command = str(test_account.get("provision_command", "")).strip()

    if not provision_command:
        normalized = normalize_accounts(fallback_accounts)
        return normalized, None

    try:
        completed = subprocess.run(
            shlex.split(provision_command),
            cwd=str(app_root),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except Exception as exc:
        return normalize_accounts(fallback_accounts), f"Provision command failed to execute: {exc}"

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        return normalize_accounts(fallback_accounts), f"Provision command exited with {completed.returncode}: {stderr}"

    stdout = completed.stdout.strip()
    if not stdout:
        return normalize_accounts(fallback_accounts), "Provision command returned empty output; using fallback accounts."

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return normalize_accounts(fallback_accounts), "Provision output was not JSON; using fallback accounts."

    accounts = payload.get("accounts", []) if isinstance(payload, dict) else []
    normalized = normalize_accounts(accounts)
    if normalized:
        return normalized, None

    return normalize_accounts(fallback_accounts), "Provision output did not include valid account entries."


def normalize_accounts(items: Any) -> List[Dict[str, str]]:
    if not isinstance(items, list):
        return []

    normalized: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        username = str(item.get("username", "")).strip()
        password = str(item.get("password", "")).strip()
        notes = str(item.get("notes", "")).strip()
        role = str(item.get("role", "reviewer")).strip() or "reviewer"
        if username and password:
            normalized.append(
                {
                    "username": username,
                    "password": password,
                    "role": role,
                    "notes": notes,
                }
            )
    return normalized


def write_accounts_csv(path: Path, accounts: List[Dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["username", "password", "role", "notes"])
        writer.writeheader()
        for row in accounts:
            writer.writerow(row)


def load_rejection_catalog(script_path: Path) -> List[Dict[str, Any]]:
    catalog_path = script_path.parent.parent / "references" / "rejection-catalog.json"
    payload = load_json(catalog_path)
    if isinstance(payload, list):
        return payload
    raise ValueError(f"Invalid rejection catalog format: {catalog_path}")


def triage_rejection_text(text: str, catalog: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    lower = text.lower()
    matches: List[Dict[str, Any]] = []

    for rule in catalog:
        patterns = rule.get("patterns", [])
        if not isinstance(patterns, list) or not patterns:
            continue

        hit_count = 0
        for pattern in patterns:
            if not isinstance(pattern, str):
                continue
            if re.search(pattern, lower):
                hit_count += 1

        if hit_count == 0:
            continue

        score = hit_count / max(len(patterns), 1)
        item = dict(rule)
        item["confidence"] = round(score, 2)
        matches.append(item)

    matches.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(item.get("severity", "P3"), 99),
            -float(item.get("confidence", 0.0)),
        )
    )
    return matches


def triage_markdown(text: str, matches: List[Dict[str, Any]]) -> str:
    lines = [
        "# Rejection Triage Report",
        "",
        "## Source Excerpt",
        "",
        "```text",
        text[:3000].strip(),
        "```",
        "",
        "## Matched Patterns",
        "",
    ]

    if not matches:
        lines.append("No known rejection patterns matched. Perform manual review.")
    else:
        lines.append("| Rule | Platform | Severity | Confidence |")
        lines.append("|---|---|---|---:|")
        for item in matches:
            lines.append(
                f"| {item.get('id', '')} | {item.get('platform', 'both')} | {item.get('severity', 'P2')} | {item.get('confidence', 0)} |"
            )

        lines.extend(["", "## Recommended Remediation", ""])
        for idx, item in enumerate(matches, start=1):
            lines.append(f"{idx}. [{item.get('severity', 'P2')}] {item.get('title', item.get('id', 'Rule'))}")
            for fix in item.get("fixes", []):
                lines.append(f"   - {fix}")
            evidence = item.get("evidence", [])
            if evidence:
                lines.append("   - Evidence to include:")
                for piece in evidence:
                    lines.append(f"     - {piece}")

    return "\n".join(lines).strip() + "\n"


def build_resubmission_response(app_id: str, matches: List[Dict[str, Any]]) -> str:
    lines = [
        f"# Resubmission Response Draft ({app_id})",
        "",
        "Dear App Review Team,",
        "",
        "Thank you for the review and feedback. We have completed fixes for the reported issues.",
        "",
        "## What We Changed",
        "",
    ]

    if not matches:
        lines.append("- We reviewed the reported concerns and applied targeted fixes in authentication, metadata, and submission notes.")
    else:
        for item in matches:
            lines.append(f"- {item.get('title', item.get('id', 'Issue'))}: implemented remediation and verified expected behavior.")

    lines.extend(
        [
            "",
            "## Verification",
            "",
            "- Retested critical user flows with pre-release automation.",
            "- Verified reviewer access path and test credentials.",
            "- Updated submission notes with explicit reproduction steps.",
            "",
            "Please let us know if additional evidence or build notes are needed.",
            "",
            "Best regards,",
            "Release Engineering",
        ]
    )

    return "\n".join(lines).strip() + "\n"


def determine_release_dir(project_root: Path, app_slug: str, date_str: str, output_root: Optional[Path] = None) -> Path:
    base = output_root if output_root else project_root / "release-kit"
    target = base / app_slug / date_str
    ensure_dir(target)
    return target


def write_audit_outputs(result: Dict[str, Any], release_dir: Path) -> None:
    json_path = release_dir / "readiness-report.json"
    md_path = release_dir / "readiness-report.md"
    blockers_path = release_dir / "blocking-issues.md"

    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    md_path.write_text(to_markdown_report(result), encoding="utf-8")
    blockers_path.write_text(blocking_issues_markdown(result), encoding="utf-8")


def prepare_release_kit(
    result: Dict[str, Any],
    app_root: Path,
    script_path: Path,
    run_provision_command: bool,
    output_root: Optional[Path],
) -> Dict[str, Any]:
    config, _, _ = find_release_config(app_root)
    date_str = dt.datetime.now().strftime(DATE_FMT)
    release_dir = determine_release_dir(Path(result["facts"]["project_root"]), result["app_slug"], date_str, output_root)

    accounts: List[Dict[str, str]] = []
    account_warning: Optional[str] = None

    if run_provision_command:
        accounts, account_warning = attempt_provision_accounts(config, app_root)
    else:
        test_account = config.get("test_account", {}) if isinstance(config, dict) else {}
        accounts = normalize_accounts(test_account.get("fallback_accounts", []))

    context = template_context(result, config, accounts)

    template_targets = {
        "app-review-notes.md": "ios-review-notes.md",
        "play-submission-notes.md": "play-submission-notes.md",
        "release-checklist.md": "release-checklist.md",
        "direct-console-fallback.md": "direct-console-fallback.md",
    }

    for template_name, out_name in template_targets.items():
        rendered = render_template(load_template(template_name, script_path), context)
        (release_dir / out_name).write_text(rendered, encoding="utf-8")

    write_accounts_csv(release_dir / "test-accounts.csv", accounts)

    if account_warning:
        warning_path = release_dir / "account-provision-warning.txt"
        warning_path.write_text(account_warning + "\n", encoding="utf-8")

    write_audit_outputs(result, release_dir)
    return {
        "release_dir": str(release_dir),
        "accounts_written": len(accounts),
        "account_warning": account_warning or "",
    }


def cmd_audit(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    apps = discover_apps(project_root)

    if not apps:
        print("No mobile apps detected (React Native CLI / Flutter).", file=sys.stderr)
        return 2

    selected_apps = [app for app in apps if not args.app_root or str(app.root) == str(Path(args.app_root).resolve())]
    if not selected_apps:
        print("No matching app for --app-root filter.", file=sys.stderr)
        return 2

    date_str = dt.datetime.now().strftime(DATE_FMT)
    output_root = Path(args.output_root).resolve() if args.output_root else None

    overall: List[Dict[str, Any]] = []
    for app in selected_apps:
        result = audit_app(app, project_root)
        release_dir = determine_release_dir(project_root, result["app_slug"], date_str, output_root)
        write_audit_outputs(result, release_dir)
        overall.append(result)
        print(f"[audit] {result['app_id']} -> {release_dir}")
        print(f"        gate={result['gate']} score={result['readiness_score']} P0={result['severity_counts']['P0']} P1={result['severity_counts']['P1']}")

    summary_path = (output_root or (project_root / "release-kit")) / f"audit-summary-{date_str}.json"
    summary_path.write_text(json.dumps(overall, indent=2), encoding="utf-8")
    print(f"[audit] summary -> {summary_path}")
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root).resolve()
    apps = discover_apps(project_root)

    if not apps:
        print("No mobile apps detected (React Native CLI / Flutter).", file=sys.stderr)
        return 2

    selected_apps = [app for app in apps if not args.app_root or str(app.root) == str(Path(args.app_root).resolve())]
    if not selected_apps:
        print("No matching app for --app-root filter.", file=sys.stderr)
        return 2

    output_root = Path(args.output_root).resolve() if args.output_root else None

    for app in selected_apps:
        result = audit_app(app, project_root)
        artifact = prepare_release_kit(
            result=result,
            app_root=app.root,
            script_path=Path(__file__).resolve(),
            run_provision_command=not args.skip_provision,
            output_root=output_root,
        )
        print(f"[prepare] {result['app_id']} -> {artifact['release_dir']}")
        if artifact["account_warning"]:
            print(f"          account warning: {artifact['account_warning']}")
    return 0


def cmd_triage(args: argparse.Namespace) -> int:
    rejection_text = ""
    if args.rejection_file:
        rejection_text = Path(args.rejection_file).read_text(encoding="utf-8", errors="ignore")
    elif args.rejection_text:
        rejection_text = args.rejection_text

    rejection_text = rejection_text.strip()
    if not rejection_text:
        print("Provide --rejection-file or --rejection-text.", file=sys.stderr)
        return 2

    project_root = Path(args.project_root).resolve()
    apps = discover_apps(project_root)
    if not apps:
        print("No mobile apps detected (React Native CLI / Flutter).", file=sys.stderr)
        return 2

    app = apps[0] if not args.app_root else next((item for item in apps if str(item.root) == str(Path(args.app_root).resolve())), None)
    if app is None:
        print("No matching app for --app-root filter.", file=sys.stderr)
        return 2

    result = audit_app(app, project_root)
    date_str = dt.datetime.now().strftime(DATE_FMT)
    output_root = Path(args.output_root).resolve() if args.output_root else None
    release_dir = determine_release_dir(project_root, result["app_slug"], date_str, output_root)

    catalog = load_rejection_catalog(Path(__file__).resolve())
    matches = triage_rejection_text(rejection_text, catalog)

    triage_md = triage_markdown(rejection_text, matches)
    response_md = build_resubmission_response(str(result["app_id"]), matches)

    (release_dir / "rejection-triage.md").write_text(triage_md, encoding="utf-8")
    (release_dir / "resubmission-response.md").write_text(response_md, encoding="utf-8")
    write_audit_outputs(result, release_dir)

    print(f"[triage] {result['app_id']} -> {release_dir}")
    print(f"         matches={len(matches)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mobile Release Expert CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--project-root", default=".", help="Project root directory")
        sub.add_argument("--app-root", help="Optional specific app root path")
        sub.add_argument("--output-root", help="Optional override for release-kit output root")

    audit_parser = subparsers.add_parser("audit", help="Run release preflight audit")
    add_common(audit_parser)
    audit_parser.set_defaults(func=cmd_audit)

    prepare_parser = subparsers.add_parser("prepare", help="Run audit and generate full release kit")
    add_common(prepare_parser)
    prepare_parser.add_argument(
        "--skip-provision",
        action="store_true",
        help="Do not execute automated test account provisioning command",
    )
    prepare_parser.set_defaults(func=cmd_prepare)

    triage_parser = subparsers.add_parser("triage", help="Analyze rejection text and draft resubmission response")
    add_common(triage_parser)
    triage_parser.add_argument("--rejection-file", help="Path to rejection text file")
    triage_parser.add_argument("--rejection-text", help="Inline rejection text")
    triage_parser.set_defaults(func=cmd_triage)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
