"""Shared progressive-disclosure helpers for argparse-based god-tier CLI tools.

A tool with many subcommands suffers two problems that this module addresses,
both of which hurt LLM agents most:

1. argparse renders every subcommand as one flat brace dump, unreadable and
   useless for command selection. `GroupedHelpFormatter` + `build_grouped_epilog`
   group the commands by intent in --help (display only; invocation unchanged).
2. Near-synonym command families (scope twins, verb twins) cannot be told apart
   from the help. `suggest_commands` maps a natural-language goal to the few most
   relevant commands, with curated hints that disambiguate the colliding families.

Each tool supplies its own data (COMMAND_GROUPS, INTENT_HINTS, SEARCH_SYNONYMS);
this module holds only the generic mechanics so the ~200 lines are not copied per
tool.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .toon_help import install_toon_help_patch

CommandGroups = list[tuple[str, list[str]]]


class TOONArgumentParser(argparse.ArgumentParser):
    """argparse.ArgumentParser whose entire --help output is pure TOON.

    Version-stable alternative to introspecting HelpFormatter internals
    (they changed in Python 3.13): builds the help document straight from
    the parser's own ``_actions`` / ``description``. Subparsers created via
    ``add_subparsers().add_parser()`` inherit this class automatically.
    """

    def format_help(self) -> str:
        try:
            import toon

            return toon.encode(self._toon_dict()) + "\n"
        except Exception:  # never break --help because of encoding
            return argparse.ArgumentParser.format_help(self)

    def format_usage(self, *args, **kwargs):  # errors stay compact too
        try:
            import toon

            return toon.encode({"usage": f"{self.prog} <command> [options]"}) + "\n"
        except Exception:
            return argparse.ArgumentParser.format_usage(self, *args, **kwargs)

    def _toon_dict(self) -> dict:
        doc: dict = {"name": self.prog}
        description = (self.description or "").split("\n")[0].strip()

        usage_bits: list[str] = []
        commands: list[dict[str, str]] = []
        options: list[dict] = []

        for action in self._actions:
            if isinstance(action, argparse._SubParsersAction):
                usage_bits.append("<command>")
                choices_actions = {a.dest: (a.help or "") for a in action._choices_actions}
                for name in getattr(action, "choices", {}):
                    commands.append(
                        {"name": name, "desc": (choices_actions.get(name) or "").split("\n")[0]}
                    )
            elif isinstance(action, argparse._HelpAction):
                continue
            elif action.option_strings:
                flag = "/".join(action.option_strings)
                required = bool(getattr(getattr(action, "container", None), "required", False))
                options.append(
                    {
                        "flag": flag,
                        "req": required,
                        "default": action.default if action.default is not None else "",
                        "help": (action.help or "").split("\n")[0],
                    }
                )
                usage_bits.append(flag)
            else:
                usage_bits.append(action.dest.upper())

        if usage_bits:
            doc["usage"] = f"{self.prog} {' '.join(usage_bits)}"
        if description:
            doc["description"] = description
        first_step = getattr(self, "first_step", None)
        if first_step:
            doc["mandatory_first_step"] = first_step
        daemon_note = getattr(self, "daemon_note", None)
        if daemon_note:
            doc["daemon"] = daemon_note
        if commands:
            doc["commands"] = commands
        elif options:
            doc["options"] = options
        return doc


class ChunkProgress:
    """Token-efficient progress for chunked bulk operations.

    On a TTY: one static line refreshed in place with \\r. Piped/agent stdout:
    fully silent while running, single final summary line.
    """

    def __init__(self, prefix: str = "copy", unit: str = "lignes") -> None:
        self.prefix = prefix
        self.unit = unit
        self.rows = 0
        self.chunks = 0
        self._tty = sys.stdout.isatty()

    def update(self, n_rows: int) -> None:
        self.chunks += 1
        self.rows += n_rows
        if self._tty:
            print(
                f"\r{self.prefix}: {self.rows:,} {self.unit} ({self.chunks} chunks)",
                end="",
                flush=True,
                file=sys.stdout,
            )

    def close(self) -> None:
        line = f"{self.prefix}: {self.rows:,} {self.unit} au total ({self.chunks} chunks)"
        if self._tty:
            print(f"\r{line}" + " " * 10, flush=True)
        else:
            print(line, flush=True)


class GroupedHelpFormatter(argparse.RawTextHelpFormatter):
    """RawText formatter that hides argparse's flat subcommand dump.

    The grouped command listing is rendered through the parser epilog instead
    (see build_grouped_epilog). Suppressing the _SubParsersAction here removes
    the unreadable flat command block from --help without touching invocation.
    """

    def _format_action(self, action: argparse.Action) -> str:
        if isinstance(action, argparse._SubParsersAction):
            return ""
        return super()._format_action(action)


def _help_by_name(subparsers: argparse._SubParsersAction) -> dict[str, str]:
    return {action.dest: (action.help or "") for action in subparsers._choices_actions}


def build_grouped_epilog(
    subparsers: argparse._SubParsersAction,
    command_groups: CommandGroups,
    *,
    prog: str = "cli",
    suggest: bool = True,
) -> str:
    """Assemble the grouped command listing shown in --help.

    Reads each subcommand's help text from the registered choices and lays them
    out under *command_groups*. Any command not assigned to a group is listed
    under 'Other' so nothing is ever silently hidden.
    """
    help_by_name = _help_by_name(subparsers)
    grouped: set[str] = set()
    lines: list[str] = ["", "commands (grouped):"]

    for title, names in command_groups:
        present = [n for n in names if n in help_by_name]
        if not present:
            continue
        width = max(len(n) for n in present)
        lines.append("")
        lines.append(f"  {title}:")
        for n in present:
            grouped.add(n)
            lines.append(f"    {n.ljust(width)}  {help_by_name[n]}")

    leftover = [n for n in help_by_name if n not in grouped]
    if leftover:
        width = max(len(n) for n in leftover)
        lines.append("")
        lines.append("  Other:")
        for n in sorted(leftover):
            lines.append(f"    {n.ljust(width)}  {help_by_name[n]}")

    lines.append("")
    lines.append(f"Run '{prog} <command> --help' for a command's options")
    if suggest:
        lines.append(f"or '{prog} suggest \"<goal>\"' to find the right command from a goal.")
    return "\n".join(lines)


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2]


def suggest_commands(
    goal: str,
    subparsers: argparse._SubParsersAction,
    command_groups: CommandGroups,
    *,
    intent_hints: dict[str, str] | None = None,
    search_synonyms: dict[str, str] | None = None,
    limit: int = 6,
    fuzzy_threshold: int = 80,
) -> list[tuple[str, str]]:
    """Rank subcommands against a natural-language goal with fuzzy token matching.

    For each goal token we take its best fuzzy match (rapidfuzz ratio, 0-100)
    among the command's text tokens — name, help, group, synonyms, and curated
    hint. A token only scores if its best match clears *fuzzy_threshold*, which
    gives typo tolerance ("datasouce" still matches "datasource") without the
    long tail of weak partial overlaps that a raw substring count rewards. A
    hit on a token in the command *name* is boosted, since the name is the
    strongest intent signal.

    Returns up to *limit* (command, reason) pairs; the reason is the curated
    disambiguation hint when one exists, else the command's own help text.
    """
    from rapidfuzz import fuzz

    intent_hints = intent_hints or {}
    search_synonyms = search_synonyms or {}
    help_by_name = _help_by_name(subparsers)

    # Callers pass synonyms in two shapes: {command: "extra tokens"} (the
    # documented dict[str, str] contract) or {concept: [command, ...]}.
    # Normalise the second shape into the first so a command is enriched by
    # every concept that routes to it.
    synonym_text: dict[str, str] = {}
    for key, value in search_synonyms.items():
        if isinstance(value, (list, tuple, set)):
            for command in value:
                synonym_text.setdefault(str(command), f"{key} {synonym_text.get(str(command), '')}".strip())
        else:
            synonym_text[str(key)] = f"{value} {synonym_text.get(str(key), '')}".strip()

    group_of: dict[str, str] = {}
    for title, names in command_groups:
        for n in names:
            group_of[n] = title

    q_tokens = _tokenize(goal)
    if not q_tokens:
        return []

    scored: list[tuple[float, str]] = []
    for name, helptext in help_by_name.items():
        if name == "suggest":
            continue
        name_tokens = set(name.split("-"))
        doc_tokens = set(_tokenize(" ".join([
            name.replace("-", " "),
            helptext,
            group_of.get(name, ""),
            synonym_text.get(name, ""),
            intent_hints.get(name, ""),
        ])))
        if not doc_tokens:
            continue

        score = 0.0
        for qt in q_tokens:
            best = max((fuzz.ratio(qt, dt) for dt in doc_tokens), default=0)
            if best >= fuzzy_threshold:
                score += best
                if qt in name_tokens:
                    score += 50  # name hit is the strongest intent signal
        if score > 0:
            scored.append((score, name))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(name, intent_hints.get(name) or help_by_name[name]) for _, name in scored[:limit]]


def add_suggest_command(subparsers: argparse._SubParsersAction) -> None:
    """Register the standard `suggest <goal>` subcommand on a subparsers object."""
    p = subparsers.add_parser(
        "suggest",
        help="Find the right command from a natural-language goal",
        description="Map a plain-language goal to the few most relevant commands, "
                    "so you don't have to scan the full command list.",
    )
    p.add_argument(
        "goal", nargs="+",
        help='What you want to do, e.g. "change the SQL of a datasource"',
    )


def run_suggest(
    goal_parts: list[str],
    subparsers: argparse._SubParsersAction,
    command_groups: CommandGroups,
    *,
    prog: str = "cli",
    intent_hints: dict[str, str] | None = None,
    search_synonyms: dict[str, str] | None = None,
) -> int:
    """Handle the `suggest` subcommand: print ranked command suggestions."""
    goal = " ".join(goal_parts)
    matches = suggest_commands(
        goal, subparsers, command_groups,
        intent_hints=intent_hints, search_synonyms=search_synonyms,
    )
    if not matches:
        print(f"No command matched: {goal!r}.")
        print(f"Run '{prog} --help' for the grouped command list.")
        return 0
    print(f"Top commands for: {goal!r}\n")
    for name, why in matches:
        print(f"  {name}\n      {why}")
    print(f"\nRun '{prog} <command> --help' for its options.")
    return 0


def warn_deprecated(old: str, replacement: str) -> None:
    """Emit a non-fatal deprecation notice to stderr (the command still runs)."""
    print(f"[deprecated] '{old}' is deprecated; use '{replacement}'.", file=sys.stderr)


def build_inspect_meta(
    tool_name: str,
    tool_dir: Path | str,
    skill_path: str,
    *,
    entrypoint: str | None = None,
) -> dict[str, str]:
    """Build the standard ontological tool introspection metadata dict.

    Single source of truth shared by cli_common.print_tool_inspect and the
    god-tier-cli wrapper's `_handle_inspect` (which adds its own extra keys).
    """
    td = Path(tool_dir).resolve()
    repo_root = td.parent if (td.parent / "graphify-out").exists() else td
    graphify_dir = td / "graphify-out"
    if not graphify_dir.exists() and (repo_root / "graphify-out").exists():
        graphify_dir = repo_root / "graphify-out"
    graphify_exists = graphify_dir.is_dir() and (graphify_dir / "graph.json").is_file()

    meta = {
        "tool": tool_name,
        "package_dir": str(td),
        "skill": skill_path,
        "graphify_dir": str(graphify_dir) if graphify_exists else "(not indexed)",
        "graphify_cmd": (
            f"cd {td} && graphify explain <symbol>"
            if graphify_exists
            else f"cd {td} && graphify . --code-only"
        ),
        "runtime": "uv",
    }
    if entrypoint is not None:
        meta["entrypoint"] = entrypoint
    return meta


def print_tool_inspect(
    tool_name: str,
    tool_dir: Path | str,
    skill_path: str,
) -> int:
    """Print standard ontological tool introspection metadata (TOON)."""
    meta = build_inspect_meta(tool_name, tool_dir, skill_path)
    try:
        import toon

        print(toon.encode(meta))
    except ImportError:
        for k, v in meta.items():
            print(f"{k}: {v}")
    return 0



# Re-export Ontology Engine & Models for downstream tools
try:
    from .ontology_models import (
        EntityType,
        RelationType,
        EntityPayload,
        RelationPayload,
        BulkOntologyPayload,
        LineageHop,
        LineageResult,
    )
    from .ontology_normalizer import normalize_symbol, fuzzy_match_entities
    from .ontology_engine import OntologyEngine
    from .ontology_visualizer import render_ontology_3d, build_graph_data
except ImportError:
    pass


