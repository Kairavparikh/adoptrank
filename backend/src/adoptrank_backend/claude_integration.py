"""A bounded, auditable Claude Code launcher for AdoptRank context packs."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .context_pack import (
    build_context_pack,
    estimate_tokens,
    render_context_pack,
    search_external_code,
    search_external_repositories,
)
from .local_scan import scan_project
from .schemas import ContextPack


@dataclass(frozen=True)
class ClaudeLaunch:
    command: list[str]
    pack: ContextPack
    context_text: str
    audit_path: Path


def _external_evidence(query: str, root: Path, budget: int, api: str) -> tuple[list, list, str | None]:
    project = scan_project(root)
    try:
        excerpts = search_external_code(query, project, api, max(200, int(budget * 0.35)))
        return [], excerpts, None
    except httpx.HTTPError as error:
        if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in {404, 405}:
            try:
                repositories = search_external_repositories(query, project, api)
                return repositories, [], None
            except httpx.HTTPError as fallback_error:
                return [], [], f"External repository evidence unavailable: {fallback_error}"
        return [], [], f"External code evidence unavailable: {error}"


def build_claude_launch(
    query: str,
    root: Path,
    budget: int = 8000,
    *,
    api: str = "https://adoptrank.vercel.app",
    include_external: bool = True,
    print_mode: bool = False,
    permission_mode: str = "default",
    max_budget_usd: float | None = None,
    audit_path: Path | None = None,
) -> ClaudeLaunch:
    """Prepare, but do not execute, a Claude Code command with bounded evidence."""
    root = root.resolve()
    external_repositories: list = []
    external_code: list = []
    external_error = None
    if include_external:
        external_repositories, external_code, external_error = _external_evidence(query, root, budget, api)
    pack = build_context_pack(root, query, budget, external_repositories, external_code)
    if external_error:
        pack.warnings.append(external_error)
    context_text = render_context_pack(pack)
    command = ["claude"]
    if print_mode:
        command.extend(["--print", query, "--output-format", "stream-json", "--verbose"])
    else:
        command.append(query)
    if context_text:
        command.extend(["--append-system-prompt", context_text])
    command.extend(["--permission-mode", permission_mode])
    if max_budget_usd is not None:
        if not print_mode:
            raise ValueError("--max-budget-usd requires --print because Claude Code only supports it there")
        command.extend(["--max-budget-usd", str(max_budget_usd)])
    if audit_path is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        audit_path = root / ".adoptrank" / "claude-runs" / f"{stamp}.json"
    return ClaudeLaunch(command=command, pack=pack, context_text=context_text, audit_path=audit_path)


def _audit_payload(launch: ClaudeLaunch, *, status: str, returncode: int | None = None) -> dict:
    return {
        "schema_version": "adoptrank.claude-run.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "status": status,
        "command": [part if part != launch.context_text else "<bounded-context-pack>" for part in launch.command],
        "context_budget": launch.pack.budget,
        "context_estimated_tokens": estimate_tokens(launch.context_text),
        "context_sha256": hashlib.sha256(launch.context_text.encode()).hexdigest(),
        "route": launch.pack.route,
        "abstained": launch.pack.abstained,
        "local_paths": sorted({snippet.path for snippet in launch.pack.snippets if snippet.source == "local"}),
        "related_paths": launch.pack.related_paths,
        "external_repositories": [item.full_name for item in launch.pack.external_repositories],
        "warnings": launch.pack.warnings,
        "returncode": returncode,
    }


def write_audit(launch: ClaudeLaunch, *, status: str, returncode: int | None = None) -> None:
    launch.audit_path.parent.mkdir(parents=True, exist_ok=True)
    launch.audit_path.write_text(json.dumps(_audit_payload(launch, status=status, returncode=returncode), indent=2))


def run_claude_launch(launch: ClaudeLaunch, root: Path, *, dry_run: bool = False) -> int:
    """Start Claude Code. The audit records injected context, not source contents or secrets."""
    if dry_run:
        write_audit(launch, status="dry-run")
        return 0
    if shutil.which("claude") is None:
        raise RuntimeError("Claude Code is not installed or is not on PATH. Run `claude auth login` first.")
    write_audit(launch, status="started")
    started = time.perf_counter()
    completed = subprocess.run(launch.command, cwd=root)
    write_audit(launch, status=f"completed:{time.perf_counter() - started:.2f}s", returncode=completed.returncode)
    return completed.returncode
