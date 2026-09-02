"""`memory` — the one coherent CLI (mandate §E).

    memory learn "observation..."      deliberate capture → 00-inbox/
    memory recall "task..."            bounded recall (router → index → notes)
    memory episode ...                 stub / checkpoint / finish / show
    memory session-start|session-end   deterministic lifecycle entry points
    memory session-prompt "text"       first-prompt domain recall (idempotent)
    memory compile                     curator compile (nightly)
    memory curate [--lint-only]        curator compile + lint (weekly)
    memory lint                        read-only schema/index validation
    memory pack <domain> | --all       regenerate context packs
    memory status                      vault state at a glance
    memory doctor [--fix]              environment checks / scaffold
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import capture, config, episodes, gitutil, packs, recall as recall_mod, redact, tokens
from .config import Vault, VaultError, find_vault
from .curator import engine
from .curator.review import pending_review_files
from .frontmatter import parse as fm_parse
from .indexes import list_domain_indexes, validate_index
from .notes import iter_notes, load_note
from .router import load_domains, router_token_estimate
from .schema import domain_names, validate_note


def _vault(args) -> Vault:
    if getattr(args, "root", None):
        return Vault(Path(args.root))
    return find_vault()


def _print(s: str = "") -> None:
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode("ascii", "replace").decode("ascii"))


# ------------------------------------------------------------- commands


def cmd_learn(args) -> int:
    vault = _vault(args)
    text = args.text if args.text else sys.stdin.read()
    res = capture.learn(vault, text, source_tool=args.tool, domain=args.domain, project=args.project, trust=args.trust)
    verb = "captured" if res.created else "already captured (identical content)"
    _print(f"{verb}: {vault.rel(res.path)}")
    if res.redacted:
        _print("note: sensitive content was redacted before writing (" + ", ".join(f.rule for f in res.findings) + ")")
    return 0


def cmd_recall(args) -> int:
    vault = _vault(args)
    res = recall_mod.recall(vault, args.task, tool=args.tool, log=not args.no_log, session_id=args.session)
    if args.json:
        _print(json.dumps({
            "domains": res.domains,
            "unclassified": res.unclassified,
            "notes": [{"ref": n.ref, "domain": n.domain, "section": n.section, "tokens": n.tokens} for n in res.notes],
            "skipped": res.skipped,
            "token_total": res.token_total,
        }, indent=2))
    else:
        _print(res.context_markdown())
        _print(f"\n<!-- recall: domains={','.join(res.domains)} notes={len(res.notes)} tokens≈{res.token_total} -->")
    return 0


def cmd_session_start(args) -> int:
    """Print the router and the project note matching the working directory
    (session-lifecycle.md SessionStart). Deterministic; no model."""
    vault = _vault(args)
    router_path = vault.path(config.ROUTER)
    if router_path.exists():
        _print(router_path.read_text(encoding="utf-8"))
    proj = _match_project(vault, Path(args.cwd or Path.cwd()))
    if proj is not None:
        _print("\n<!-- project note -->\n" + proj.read_text(encoding="utf-8"))
    if args.session:
        state = recall_mod.load_session_state(vault, args.session)
        state.setdefault("started", datetime.now().astimezone().isoformat(timespec="seconds"))
        state["tool"] = args.tool
        recall_mod.save_session_state(vault, args.session, state)
    return 0


def _match_project(vault: Vault, cwd: Path):
    base = vault.path(config.PROJECTS)
    if not base.is_dir():
        return None
    cwd_str = str(cwd).lower().replace("\\", "/")
    components = set(cwd_str.strip("/").split("/"))
    for p in sorted(base.glob("*.md")):
        note = load_note(p, vault)
        wd = str(note.meta.get("working_dir") or "").lower().replace("\\", "/").strip("/")
        if wd and (cwd_str.startswith(wd) or wd.split("/")[-1] in components):
            return p
        if p.stem.lower() == cwd.name.lower():
            return p
    return None


def cmd_session_prompt(args) -> int:
    """First meaningful prompt → domain recall, exactly once per session
    (automatic-memory budget: start, domain recall, end — never per message)."""
    vault = _vault(args)
    sid = args.session or "default"
    state = recall_mod.load_session_state(vault, sid)
    if state.get("recalled"):
        return 0  # silent: budget already spent
    res = recall_mod.recall(vault, args.text, tool=args.tool, session_id=sid)
    _print(res.context_markdown())
    if res.unclassified:
        _print("\n<!-- no domain matched; served _general.md; episode will record domains: [unclassified] -->")
    return 0


def cmd_session_end(args) -> int:
    """Write the episode stub with Knowledge retrieved pre-filled from the
    session's disposable state (never from canonical sources)."""
    vault = _vault(args)
    sid = args.session or "default"
    state = recall_mod.load_session_state(vault, sid)
    retrieved = state.get("retrieved", [])
    if not retrieved and not args.force:
        _print("session retrieved nothing; skipping the episode (episode.md: may skip)")
        return 0
    domains = [d for d in state.get("domains", []) if d] or ["unclassified"]
    path = episodes.create_stub(
        vault,
        tool=args.tool,
        slug=args.slug or "session",
        session_ref=args.session_ref or sid,
        retrieved=retrieved,
        domains=domains,
        project=args.project,
    )
    for cp in state.get("checkpoints", []):
        if isinstance(cp, dict):  # checkpoint keeps its original PreCompact time
            try:
                at = datetime.fromisoformat(cp.get("at", ""))
            except ValueError:
                at = None
            episodes.checkpoint(vault, path, cp.get("text", ""), now=at)
        else:
            episodes.checkpoint(vault, path, str(cp))
    _print(f"episode stub: {vault.rel(path)} (status: raw — fill it and run `memory episode finish`)")
    return 0


def cmd_episode(args) -> int:
    vault = _vault(args)
    if args.action == "create":
        path = episodes.create_stub(
            vault, tool=args.tool, slug=args.slug or "session", session_ref=args.session_ref or "",
            retrieved=args.retrieved or [], domains=args.domain or None, project=args.project,
            duration_min=args.duration,
        )
        _print(f"episode stub: {vault.rel(path)}")
        return 0
    if args.action == "checkpoint":
        sid = args.session or "default"
        if args.path:
            episodes.checkpoint(vault, vault.path(args.path), args.text or "")
        else:  # before the stub exists, checkpoints park in session state
            state = recall_mod.load_session_state(vault, sid)
            state.setdefault("checkpoints", []).append({
                "text": args.text or "",
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
            })
            recall_mod.save_session_state(vault, sid, state)
        _print("checkpoint recorded")
        return 0
    if args.action == "finish":
        path = vault.path(args.path) if args.path else _latest_raw_episode(vault)
        if path is None:
            _print("no raw episode to finish")
            return 1
        try:
            warnings = episodes.finish(vault, path)
        except episodes.EpisodeError as e:
            _print(str(e))
            return 1
        _print(f"summarised: {vault.rel(path)}")
        for w in warnings:
            _print(f"warning: {w}")
        return 0
    if args.action == "show":
        path = vault.path(args.path) if args.path else _latest_raw_episode(vault)
        if path is None:
            _print("no episode found")
            return 1
        _print(path.read_text(encoding="utf-8"))
        return 0
    return 2


def _latest_raw_episode(vault: Vault):
    latest = None
    for n in iter_notes(vault, config.EPISODES):
        if n.type == "episode" and n.status == "raw":
            if latest is None or n.path.name > latest.name:
                latest = n.path
    return latest


def cmd_compile(args) -> int:
    vault = _vault(args)
    report = engine.run_compile(vault)
    return _print_run(vault, report)


def cmd_curate(args) -> int:
    vault = _vault(args)
    rc = 0
    if not args.lint_only:
        rc |= _print_run(vault, engine.run_compile(vault))
    if not args.compile_only:
        rc |= _print_run(vault, engine.run_lint(vault))
    files = pending_review_files(vault)
    if files:
        _print(f"\nreview pending: {', '.join(vault.rel(f) for f in files)} — tick [x] approve and re-run")
    return rc


def _print_run(vault: Vault, report: engine.RunReport) -> int:
    _print(f"{report.run_id}: {len(report.log_lines)} action(s), {len([d for d in report.decisions if d.gated])} gated proposal(s)")
    for line in report.log_lines:
        _print(f"  {line}")
    for w in report.warnings:
        _print(f"  warning: {w}")
    if report.commit and report.commit.committed:
        _print(f"  committed {report.commit.sha}")
    elif report.commit:
        _print(f"  {report.commit.message}")
    return 0


def cmd_lint(args) -> int:
    """Read-only deterministic validation (Q5). Curator's weekly pass is
    `memory curate --lint-only`, which also writes."""
    vault = _vault(args)
    issues = []
    domains = domain_names(vault)
    for rel in (config.INBOX, config.EPISODES, config.KNOWLEDGE, config.PROJECTS):
        for note in iter_notes(vault, rel):
            if note.type == "index":
                continue
            issues.extend(validate_note(note, vault, domains))
    for di in list_domain_indexes(vault):
        issues.extend(validate_index(di, vault))
    from .schema import Issue

    # router hygiene: token budget, 5-8 domains, every declared domain has an index
    rt = router_token_estimate(vault)
    if rt > config.TOKEN_BUDGET_ROUTER:
        issues.append(Issue(config.ROUTER, "warning", f"router estimates {rt} tokens (budget {config.TOKEN_BUDGET_ROUTER})"))
    if domains and not (5 <= len(domains) <= 8):
        issues.append(Issue(config.ROUTER, "warning", f"{len(domains)} domains declared (spec: five to eight)"))
    for d in domains:
        if not vault.path(f"{config.INDEX_DIR}/{d}.md").exists():
            issues.append(Issue(config.ROUTER, "error", f"declared domain `{d}` has no index file — recall for it falls back to _general"))
    for problem in redact.lint_user_rules(vault):
        issues.append(Issue(config.REDACT_FILE, "warning", problem))
    errors = [i for i in issues if i.severity == "error"]
    for i in issues:
        _print(str(i))
    _print(f"\n{len(errors)} error(s), {len(issues) - len(errors)} warning(s)")
    return 1 if errors else 0


def cmd_pack(args) -> int:
    vault = _vault(args)
    if args.all or not args.domain:
        out = packs.compile_all(vault)
        for p in out:
            _print(f"pack: {vault.rel(p)}")
        return 0
    try:
        p = packs.compile_pack(vault, args.domain)
    except packs.PackError as e:
        _print(str(e))
        return 1
    meta, _ = fm_parse(p.read_text(encoding="utf-8"))
    _print(f"pack: {vault.rel(p)} (≈{meta.get('token_estimate')} tokens, valid until {meta.get('valid_until')})")
    return 0


def cmd_status(args) -> int:
    vault = _vault(args)
    inbox = list(iter_notes(vault, config.INBOX))
    unprocessed = [n for n in inbox if "processed" not in n.meta]
    eps = [n for n in iter_notes(vault, config.EPISODES) if n.type == "episode"]
    by_status: dict[str, int] = {}
    for e in eps:
        by_status[e.status or "?"] = by_status.get(e.status or "?", 0) + 1
    from .notes import knowledge_notes

    kn = knowledge_notes(vault)
    kn_status: dict[str, int] = {}
    for n in kn:
        kn_status[n.status or "?"] = kn_status.get(n.status or "?", 0) + 1
    _print(f"vault: {vault.root}")
    _print(f"inbox: {len(unprocessed)} unprocessed / {len(inbox)} total")
    _print(f"episodes: {len(eps)} ({', '.join(f'{k}: {v}' for k, v in sorted(by_status.items()))})")
    _print(f"knowledge: {len(kn)} ({', '.join(f'{k}: {v}' for k, v in sorted(kn_status.items()))})")
    _print(f"domains: {', '.join(domain_names(vault)) or '(router missing)'}")
    rt = router_token_estimate(vault)
    if rt > config.TOKEN_BUDGET_ROUTER:
        _print(f"warning: router ≈{rt} tokens (budget {config.TOKEN_BUDGET_ROUTER})")
    files = pending_review_files(vault)
    if files:
        _print(f"review pending: {', '.join(vault.rel(f) for f in files)}")
    for p in sorted(vault.path(config.CONTEXT_PACKS).glob("*-current.md")) if vault.path(config.CONTEXT_PACKS).is_dir() else []:
        meta, _ = fm_parse(p.read_text(encoding="utf-8"))
        _print(f"pack {p.stem}: {packs.freshness(meta)}")
    return 0


def cmd_doctor(args) -> int:
    problems: list[str] = []
    try:
        vault = _vault(args)
    except VaultError:
        if args.fix:
            vault = Vault(Path(args.root) if args.root else Path.cwd())
        else:
            _print("no vault found here (run with --fix to scaffold one)")
            return 1
    if args.fix:
        created = vault.scaffold()
        for c in created:
            _print(f"created {c}/")
        if not vault.path(config.ROUTER).exists():
            problems.append(f"{config.ROUTER} missing — the router is required for recall")
        if not vault.path(config.REDACT_FILE).exists():
            from . import fsutil

            fsutil.atomic_write(vault.path(config.REDACT_FILE), "# One redaction rule per line: literal, literal:Name, or regex:pattern\n# Optionally: rule => [replacement-token]\n")
            _print(f"created {config.REDACT_FILE}")
    for rel in config.SCAFFOLD_DIRS:
        if not vault.path(rel).is_dir():
            problems.append(f"missing directory: {rel}/")
    if not vault.path(config.ROUTER).exists():
        problems.append(f"missing router: {config.ROUTER}")
    if not vault.path(config.GENERAL_INDEX).exists():
        problems.append(f"missing general fallback index: {config.GENERAL_INDEX}")
    for d in domain_names(vault):
        if not vault.path(f"{config.INDEX_DIR}/{d}.md").exists():
            problems.append(f"declared domain `{d}` has no index file")
    if not gitutil.available(vault):
        problems.append("git unavailable or not a repository — history/rollback disabled; curator will require manual commits")
    if sys.version_info < (3, 10):
        problems.append(f"python {sys.version_info.major}.{sys.version_info.minor} < 3.10")
    for p in problems:
        _print(f"problem: {p}")
    if not problems:
        _print("ok: vault healthy")
    return 1 if problems else 0


# ---------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="memory", description="Memory Mesh — local-first AI memory")
    ap.add_argument("--root", help="vault root (default: $MEMORY_MESH_ROOT or auto-detect)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("learn", help="capture an observation into 00-inbox/")
    p.add_argument("text", nargs="?", help="observation (reads stdin when omitted)")
    p.add_argument("--tool", default="cli")
    p.add_argument("--domain")
    p.add_argument("--project")
    p.add_argument("--trust", default="first-party", choices=["first-party", "mixed", "third-party", "unknown"])
    p.set_defaults(fn=cmd_learn)

    p = sub.add_parser("recall", help="bounded recall for a task")
    p.add_argument("task")
    p.add_argument("--tool", default="cli")
    p.add_argument("--session")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-log", action="store_true")
    p.set_defaults(fn=cmd_recall)

    p = sub.add_parser("session-start", help="print router + project note (SessionStart hook)")
    p.add_argument("--tool", default="cli")
    p.add_argument("--session")
    p.add_argument("--cwd")
    p.set_defaults(fn=cmd_session_start)

    p = sub.add_parser("session-prompt", help="first-prompt domain recall (UserPromptSubmit hook)")
    p.add_argument("text")
    p.add_argument("--tool", default="cli")
    p.add_argument("--session")
    p.set_defaults(fn=cmd_session_prompt)

    p = sub.add_parser("session-end", help="write the episode stub (SessionEnd hook)")
    p.add_argument("--tool", default="cli")
    p.add_argument("--session")
    p.add_argument("--slug")
    p.add_argument("--session-ref")
    p.add_argument("--project")
    p.add_argument("--force", action="store_true", help="write a stub even when nothing was retrieved")
    p.set_defaults(fn=cmd_session_end)

    p = sub.add_parser("episode", help="episode lifecycle")
    p.add_argument("action", choices=["create", "checkpoint", "finish", "show"])
    p.add_argument("path", nargs="?")
    p.add_argument("--tool", default="cli")
    p.add_argument("--slug")
    p.add_argument("--session")
    p.add_argument("--session-ref")
    p.add_argument("--project")
    p.add_argument("--duration", type=int)
    p.add_argument("--text")
    p.add_argument("--retrieved", nargs="*")
    p.add_argument("--domain", nargs="*")
    p.set_defaults(fn=cmd_episode)

    p = sub.add_parser("compile", help="curator compile (nightly)")
    p.set_defaults(fn=cmd_compile)

    p = sub.add_parser("curate", help="curator compile + lint")
    p.add_argument("--lint-only", action="store_true")
    p.add_argument("--compile-only", action="store_true")
    p.set_defaults(fn=cmd_curate)

    p = sub.add_parser("lint", help="read-only schema/index validation")
    p.set_defaults(fn=cmd_lint)

    p = sub.add_parser("pack", help="regenerate context pack(s)")
    p.add_argument("domain", nargs="?")
    p.add_argument("--all", action="store_true")
    p.set_defaults(fn=cmd_pack)

    p = sub.add_parser("status", help="vault state at a glance")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("doctor", help="environment checks; --fix scaffolds")
    p.add_argument("--fix", action="store_true")
    p.set_defaults(fn=cmd_doctor)

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except VaultError as e:
        _print(f"error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
