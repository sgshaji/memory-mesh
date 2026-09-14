"""Explicit, opt-in personal-pilot commands. Legacy commands keep their defaults."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import packs, recall
from .config import Vault, VaultError, find_vault
from .experience import create_task, get_mode, get_task, revise_task, set_mode
from .experience_types import require_id
from .host_lifecycle import bind_session, capabilities
from .learning_flow import record_feedback, submit_proposal
from .reuse_evaluation import evaluate_runs
from .task_execution import execute_check

MAX_INPUT_BYTES = 1_048_576


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VaultError("JSON objects cannot contain duplicate fields")
        result[key] = value
    return result


def read_json(path: str | None) -> object:
    try:
        if path is None or path == "-":
            text = sys.stdin.read(MAX_INPUT_BYTES + 1)
        else:
            with Path(path).open(encoding="utf-8") as source:
                text = source.read(MAX_INPUT_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        raise VaultError("JSON input could not be read as UTF-8") from exc
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise VaultError("JSON input exceeds the 1 MiB limit")
    try:
        return json.loads(text, object_pairs_hook=_unique_fields)
    except (ValueError, RecursionError) as exc:
        raise VaultError("invalid JSON input") from exc


def output(data: object) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, allow_nan=False))


def cmd_evaluate(args) -> int:
    output(evaluate_runs(read_json(args.input)))
    return 0


def _vault(args) -> Vault:
    return Vault(Path(args.root)) if args.root else find_vault()


def cmd_profile(args) -> int:
    vault = _vault(args)
    if args.mode is not None:
        set_mode(vault, args.mode)
        packs.compile_all(vault)
    output({"mode": get_mode(vault), "capabilities": capabilities()})
    return 0


def cmd_capabilities(args) -> int:
    output(capabilities())
    return 0


def cmd_task_start(args) -> int:
    data = read_json(args.input)
    fields = {"task_id", "event_id", "project", "tool", "version", "goal", "checks", "facts"}
    if not isinstance(data, dict) or set(data) != fields:
        raise VaultError("task input has missing or unsupported fields")
    vault = _vault(args)
    task = create_task(vault, **data)
    if args.session:
        bind_session(vault, args.session, task.task_id)
    output(asdict(task))
    return 0


def cmd_task_show(args) -> int:
    output(asdict(get_task(_vault(args), require_id(args.task_id, "task_id"))))
    return 0


def cmd_task_revise(args) -> int:
    data = read_json(args.input)
    required = {"event_id", "expected_revision", "relation", "reason"}
    if not isinstance(data, dict) or not required <= data.keys() or set(data) - (required | {"goal", "facts"}):
        raise VaultError("task revision input has missing or unsupported fields")
    output(asdict(revise_task(_vault(args), args.task_id, **data)))
    return 0


def cmd_check(args) -> int:
    result = execute_check(
        _vault(args), args.task_id, event_id=args.event_id,
        expected_revision=args.revision, check_id=args.check_id,
        workspace=Path(args.workspace), artifacts=args.artifact,
        start=args.start, pattern=args.pattern, timeout=args.timeout,
    )
    output(asdict(result))
    return 0 if result.outcome == "passed" else 1


def cmd_propose(args) -> int:
    output(submit_proposal(_vault(args), args.task_id, read_json(args.input)))
    return 0


def cmd_recall(args) -> int:
    vault = _vault(args)
    task = get_task(vault, args.task_id)
    result = recall.recall(vault, args.query or task.goal, task_id=args.task_id, tool="v2-cli")
    if args.text:
        print(result.context_markdown())
    else:
        output(result.as_payload())
    return 0


def cmd_feedback(args) -> int:
    output(record_feedback(
        _vault(args), task_id=args.task_id, event_id=args.event_id,
        note_ref=args.note, lesson_revision=args.lesson_revision,
        outcome=args.outcome, reason=args.reason, evidence_ids=args.evidence,
    ))
    return 0


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("v2", help="experimental evidence-gated personal pilot")
    commands = parser.add_subparsers(dest="v2_command", required=True)
    evaluate = commands.add_parser("evaluate", help="summarize offline runs without claiming causality")
    evaluate.add_argument("input", nargs="?", help="JSON file; omit or use - for stdin")
    evaluate.set_defaults(fn=cmd_evaluate)
    profile = commands.add_parser("profile", help="explicitly select shadow, strict, or off")
    profile.add_argument("mode", nargs="?", choices=("shadow", "strict", "off"))
    profile.set_defaults(fn=cmd_profile)
    capability = commands.add_parser("capabilities", help="show verified versus assisted capabilities")
    capability.set_defaults(fn=cmd_capabilities)
    tasks = commands.add_parser("task", help="bounded task identities and revisions")
    actions = tasks.add_subparsers(dest="task_action", required=True)
    start = actions.add_parser("start", help="create a task from bounded JSON")
    start.add_argument("input", nargs="?")
    start.add_argument("--session", help="bind this explicit task to a host session")
    start.set_defaults(fn=cmd_task_start)
    show = actions.add_parser("show", help="inspect one task and its execution evidence")
    show.add_argument("task_id")
    show.set_defaults(fn=cmd_task_show)
    revise = actions.add_parser("revise", help="record a correction or changed requirement")
    revise.add_argument("task_id")
    revise.add_argument("input", nargs="?")
    revise.set_defaults(fn=cmd_task_revise)
    check = commands.add_parser("check", help="explicitly run a declared unittest check")
    check.add_argument("task_id")
    check.add_argument("--event-id", required=True)
    check.add_argument("--revision", type=int, required=True)
    check.add_argument("--check-id", required=True)
    check.add_argument("--workspace", required=True)
    check.add_argument("--artifact", action="append", required=True)
    check.add_argument("--start", default=".")
    check.add_argument("--pattern", default="test_*.py")
    check.add_argument("--timeout", type=float, default=120)
    check.set_defaults(fn=cmd_check)
    propose = commands.add_parser("propose", help="stage a supported proposal, or preview in shadow mode")
    propose.add_argument("task_id")
    propose.add_argument("input", nargs="?")
    propose.set_defaults(fn=cmd_propose)
    recall_command = commands.add_parser("recall", help="recall only reviewed lessons matching a task")
    recall_command.add_argument("task_id")
    recall_command.add_argument("--query", default="")
    recall_command.add_argument("--text", action="store_true")
    recall_command.set_defaults(fn=cmd_recall)
    feedback = commands.add_parser("feedback", help="record explicit use without claiming causal savings")
    feedback.add_argument("task_id")
    feedback.add_argument("--event-id", required=True)
    feedback.add_argument("--note", required=True)
    feedback.add_argument("--lesson-revision", required=True)
    feedback.add_argument("--outcome", choices=("held", "failed", "unclear", "not-applicable"), required=True)
    feedback.add_argument("--reason", required=True)
    feedback.add_argument("--evidence", action="append", default=[])
    feedback.set_defaults(fn=cmd_feedback)
