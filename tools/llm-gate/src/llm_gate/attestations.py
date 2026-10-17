"""Release attestation predicates (docs/PLAN-v2.md Phase 18, ADR 0009). `release.yml` attests
both on the image digest with `actions/attest`:

- **vuln-scan**: what grype found in the pushed image, per platform, and which findings
  `.grype.yaml` ignores and why;
- **llm-review**: for every PR merged since the previous release, the LLM gate's verdicts on its
  merged head, from the audit log (ADR 0005), and which PRs weren't reviewed or can't be verified.

The predicates carry ids, SHAs, logins, verdicts and counts, plus the override and ignore reasons,
which are scrubbed like everything else in the audit log. They hold no PR titles or bodies.
"""

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .redact import clip, redact

VULN_SCAN_TYPE = "https://github.com/gergodrazsdik/calendar-gates/attestations/vuln-scan/v1"
LLM_REVIEW_TYPE = "https://github.com/gergodrazsdik/calendar-gates/attestations/llm-review/v1"

SEVERITIES = ("critical", "high", "medium", "low", "negligible", "unknown")
NOT_REVIEWED = frozenset({"skipped_no_key", "error"})


# --- vuln-scan ---------------------------------------------------------------------------------


def _counts(matches: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(SEVERITIES, 0)
    for match in matches:
        severity = str((match.get("vulnerability") or {}).get("severity") or "unknown").lower()
        counts[severity if severity in counts else "unknown"] += 1
    return counts


def vuln_scan(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One predicate from grype JSON reports (`-o json`), one report per platform of the image."""
    if not reports:
        raise ValueError("no grype reports")
    descriptor = reports[0].get("descriptor") or {}
    db = (descriptor.get("db") or {}).get("status") or {}
    results = []
    ignored: dict[tuple[str, str, str], dict[str, str]] = {}
    for report in reports:
        target = (report.get("source") or {}).get("target") or {}
        results.append(
            {
                "platform": f"{target.get('os', '?')}/{target.get('architecture', '?')}",
                "manifest_digest": target.get("manifestDigest"),
                "counts": _counts(report.get("matches") or []),
            }
        )
        for match in report.get("ignoredMatches") or []:
            vulnerability = str((match.get("vulnerability") or {}).get("id") or "?")
            artifact = match.get("artifact") or {}
            package = f"{artifact.get('name', '?')}@{artifact.get('version', '?')}"
            rules = match.get("appliedIgnoreRules") or [{}]
            reason = clip(redact(str(rules[0].get("reason") or "no reason given")), 300)
            ignored[(vulnerability, package, reason)] = {
                "id": vulnerability,
                "package": package,
                "reason": reason,
            }
    return {
        "scanner": {
            "name": descriptor.get("name", "grype"),
            "version": descriptor.get("version"),
            "db_schema": db.get("schemaVersion"),
            "db_built": db.get("built"),
        },
        "scanned_at": descriptor.get("timestamp"),
        "results": results,
        "ignored": sorted(ignored.values(), key=lambda i: (i["id"], i["package"])),
    }


# --- llm-review --------------------------------------------------------------------------------


def _records(audit_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(audit_dir.glob("events/**/*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _run_order(record: Mapping[str, Any]) -> tuple[int, int, str]:
    return (
        int(record.get("workflow_run_id") or 0),
        int(record.get("run_attempt") or 0),
        str(record.get("finished_at") or record.get("ts") or ""),
    )


def llm_review(
    commits: Sequence[Mapping[str, Any]],
    audit_dir: Path,
    *,
    range_from: str | None,
    range_to: str,
) -> dict[str, Any]:
    """`commits`: the release's commits on main, oldest first, each `{commit, pr, head_sha,
    merged_at}` (the PR that merged it, that PR's final head and merge time, or nulls for a commit
    without a PR)."""
    records = _records(audit_dir)
    log_start = min((str(r["ts"]) for r in records if r.get("ts")), default=None)
    prs: list[dict[str, Any]] = []
    unreviewed: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []
    for item in commits:
        number, head = item.get("pr"), item.get("head_sha")
        if not isinstance(number, int) or not head:
            unreviewed.append({"commit": item.get("commit"), "reason": "no pull request"})
            continue
        mine = [r for r in records if r.get("pr") == number and r.get("head_sha") == head]
        runs = [r for r in mine if r.get("type") == "gate_run"]
        latest: dict[str, Mapping[str, Any]] = {}
        for run in sorted(runs, key=_run_order):
            latest[str(run.get("check"))] = run
        triages = sorted((r for r in mine if r.get("type") == "triage"), key=_run_order)
        triage = triages[-1] if triages else None
        overrides = [
            {
                "by": r.get("by"),
                "checks": r.get("checks", []),
                "reason": clip(redact(str(r.get("reason") or "")), 300),
            }
            for r in mine
            if r.get("type") == "override"
        ]
        entry: dict[str, Any] = {
            "number": number,
            "head_sha": head,
            "risk": (triage or {}).get("final_risk")
            or next((r.get("risk") for r in latest.values() if r.get("risk")), None),
            "ai_assisted": (triage or {}).get("ai_assisted"),
            "checks": {
                check: "overridden" if run.get("override_honoured") else run.get("verdict")
                for check, run in sorted(latest.items())
            },
            "overrides": overrides,
        }
        prs.append(entry)

        if not latest:
            reason = "no review record for the merged head"
            merged = str(item.get("merged_at") or "")
            if log_start is None or (merged and _utc(merged) < _utc(log_start)):
                reason = "merged before the audit log existed"
            elif any(r.get("pr") == number and r.get("type") == "gate_run" for r in records):
                reason += " (earlier heads were reviewed)"
            unreviewed.append({"number": number, "reason": reason})
        else:
            skipped = sorted(
                f"{check}: {run.get('verdict')}"
                for check, run in latest.items()
                if run.get("blocking") and run.get("verdict") in NOT_REVIEWED
            )
            if skipped:
                unreviewed.append({"number": number, "reason": ", ".join(skipped)})
        problems = []
        if any(r.get("workflow_modified") for r in latest.values()):
            problems.append("workflow_modified")
        tampered = sum(1 for r in mine if r.get("type") == "tamper_suspected")
        if tampered:
            problems.append(f"tamper_suspected ({tampered})")
        if problems:
            unverified.append({"number": number, "reason": ", ".join(problems)})
    return {
        "range": {"from": range_from, "to": range_to},
        "prs": prs,
        "unreviewed": unreviewed,
        "unverified": unverified,
    }


def render_notes(predicate: Mapping[str, Any]) -> str:
    """The release notes' "LLM review" section."""
    prs = predicate["prs"]
    start = predicate["range"]["from"] or "the first commit"
    lines = [
        "## LLM review",
        "",
        f"{len(prs)} pull request(s) since {start}, from the audit log (attested on the image as "
        f"`{LLM_REVIEW_TYPE}`).",
        "",
    ]
    if prs:
        checks = sorted({c for pr in prs for c in pr["checks"]})
        lines += [
            "| PR | Risk | " + " | ".join(checks) + " |",
            "|---|---|" + "---|" * len(checks),
        ]
        for pr in prs:
            cells = [str(pr["checks"].get(c, "-")) for c in checks]
            lines.append(f"| #{pr['number']} | {pr['risk'] or '-'} | " + " | ".join(cells) + " |")
        lines.append("")
    overridden = [pr for pr in prs if pr["overrides"]]
    for pr in overridden:
        for o in pr["overrides"]:
            lines.append(f"- #{pr['number']} overridden by @{o['by']}: {o['reason']}")
    if overridden:
        lines.append("")
    for key, title in (("unreviewed", "Unreviewed"), ("unverified", "Unverified")):
        if predicate[key]:
            lines += [f"**{title}**", ""]
            for item in predicate[key]:
                what = f"#{item['number']}" if "number" in item else f"`{item['commit']}`"
                lines.append(f"- {what}: {item['reason']}")
            lines.append("")
    return "\n".join(lines)
