"""The single TOON help printer shared by every god-tier CLI tool.

Forty tools used to carry their own copy of this patch and thirty did not, so
`--help` spoke Typer/Rich, argparse or plain text depending on the tool. This
module is the one implementation:

- Click and Typer are patched through ``Command.format_help``.
- argparse is patched through ``ArgumentParser.format_help``, including the
  sub-command table.
- The description comes from :mod:`cli_common.tool_descriptions`, keyed by the
  command name. The tool's own ``help=`` string is only a fallback, because the
  routing model must judge the same text wherever it runs.

``run_tool`` exports ``GOD_TIER_CLI_COMMAND`` and ``GOD_TIER_CLI_SKILL`` to the
child process, so a tool invoked through the dispatcher prints the canonical
name and its linked usage skill without importing the dispatcher.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from .tool_descriptions import description_for


def _command_name(fallback: str = "") -> str:
    """Return the command this process is serving."""
    return (
        os.environ.get("GOD_TIER_CLI_COMMAND")
        or fallback
        or Path(sys.argv[0]).name
    )


def _base_dict(fallback_desc: str = "") -> dict[str, Any]:
    """Return the ``name``, ``description`` and optional ``skill`` header."""
    command = _command_name()
    document: dict[str, Any] = {
        "name": command,
        "description": description_for(command) or fallback_desc,
    }
    skill = os.environ.get("GOD_TIER_CLI_SKILL", "").strip()
    if skill:
        document["skill"] = skill
    return document


def _first_line(text: Any) -> str:
    return str(text or "").split("\n")[0].strip()


def install_toon_help_patch(default_name: str = "", default_desc: str = "") -> None:
    """Patch Click, Typer and argparse so ``--help`` renders TOON.

    *default_name* and *default_desc* are kept for the tools that already call
    this with two arguments. The registry wins over *default_desc*; the
    arguments only cover a tool whose command is not registered yet.
    """
    try:
        from toon import encode as toon_encode
    except ImportError:
        return

    command = _command_name(default_name)

    # ------------------------------------------------------------------
    # Click / Typer
    # ------------------------------------------------------------------
    try:
        try:
            import typer._click as click  # type: ignore[import]
        except ImportError:
            import click  # type: ignore[import]

        try:
            import typer.rich_utils as rich_utils  # type: ignore[import]
        except ImportError:
            rich_utils = None

        def _help_dict_for_obj(obj: Any, ctx: Any = None) -> dict[str, Any]:
            raw_help = getattr(obj, "help", "") or ""
            document = _base_dict(description_for(command) or default_desc or _first_line(raw_help))

            if hasattr(obj, "commands") or isinstance(obj, getattr(click, "Group", type(None))):
                commands = []
                for cmd_name, cmd_obj in (getattr(obj, "commands", {}) or {}).items():
                    if str(cmd_name).startswith("-"):
                        continue
                    commands.append({
                        "name": str(cmd_name),
                        "description": _first_line(getattr(cmd_obj, "help", "")),
                    })
                if commands:
                    document["commands"] = commands
            else:
                parameters = []
                for parameter in getattr(obj, "params", []):
                    name = getattr(parameter, "name", "") or "/".join(getattr(parameter, "opts", []))
                    entry: dict[str, Any] = {
                        "name": str(name),
                        "type": getattr(getattr(parameter, "type", None), "name", "text"),
                        "help": _first_line(getattr(parameter, "help", "")),
                        "required": bool(getattr(parameter, "required", False)),
                    }
                    default_value = getattr(parameter, "default", None)
                    if default_value is not None:
                        entry["default"] = str(default_value)
                    parameters.append(entry)
                if parameters:
                    document["parameters"] = parameters
            return document

        def _toon_rich_format_help(*, obj: Any, ctx: Any, markup_mode: Any = None) -> None:
            try:
                click.echo(toon_encode(_help_dict_for_obj(obj, ctx)))
            except Exception:
                click.echo(str(getattr(obj, "help", "") or ""))

        if rich_utils is not None:
            rich_utils.rich_format_help = _toon_rich_format_help  # type: ignore[attr-defined]

        def _toon_click_format_help(self: Any, ctx: Any, formatter: Any) -> None:
            try:
                click.echo(toon_encode(_help_dict_for_obj(self, ctx)))
            except Exception:
                formatter.write_text(self.help or "")

        click.Command.format_help = _toon_click_format_help  # type: ignore[method-assign]

        try:
            import typer.core as typer_core  # type: ignore[import]

            typer_core.TyperCommand.format_help = _toon_click_format_help  # type: ignore[attr-defined]
            typer_core.TyperGroup.format_help = _toon_click_format_help  # type: ignore[attr-defined]
        except Exception:
            pass
    except Exception:
        pass

    # ------------------------------------------------------------------
    # argparse
    # ------------------------------------------------------------------
    def _argparse_dict(parser: argparse.ArgumentParser) -> dict[str, Any]:
        document = _base_dict(description_for(command) or default_desc or _first_line(parser.description))
        usage = parser.format_usage().strip()
        document["usage"] = usage[len("usage: ") :] if usage.startswith("usage: ") else usage

        commands = []
        parameters = []
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, subparser in action.choices.items():
                    commands.append({
                        "name": str(name),
                        "description": _first_line(getattr(subparser, "description", "")),
                    })
                continue
            if not action.option_strings:
                continue
            parameters.append({
                "name": "/".join(action.option_strings),
                "type": getattr(action.type, "__name__", "text") if action.type else "text",
                "help": _first_line(action.help),
                "required": bool(action.required),
            })
        if commands:
            document["commands"] = commands
        if parameters:
            document["parameters"] = parameters
        return document

    _original_argparse_help = argparse.ArgumentParser.format_help

    def _toon_argparse_help(self: argparse.ArgumentParser) -> str:
        try:
            return toon_encode(_argparse_dict(self))
        except Exception:
            return _original_argparse_help(self)

    argparse.ArgumentParser.format_help = _toon_argparse_help  # type: ignore[method-assign]


# ----------------------------------------------------------------------
# Cyclopts
# ----------------------------------------------------------------------
try:
    from cyclopts import App as _CycloptsApp
except ImportError:  # argparse/typer tools do not ship cyclopts
    _CycloptsApp = None

try:
    from toon import encode as _toon_encode
except ImportError:
    _toon_encode = None


if _CycloptsApp is not None and _toon_encode is not None:

    class TOONApp(_CycloptsApp):  # type: ignore[misc, valid-type]
        """Cyclopts application whose ``--help`` prints the shared TOON document.

        Cyclopts does not subclass Click, so the Click patch never reaches it.
        Jira, KYSS and book-downloading each carried a private copy of this
        class; they now import this one, and the description comes from the
        same registry as every other tool.
        """

        def help_print(self, tokens=None, *, console=None) -> None:
            _chain, apps, _ = self.parse_commands(tokens or [])
            target = apps[-1]
            document = _base_dict(
                description_for(_command_name()) or _first_line(getattr(target, "help", ""))
            )
            subcommands = {
                name: command_obj
                for name, command_obj in target._commands.items()
                if not name.startswith("-") and name != "--version"
            }
            if subcommands:
                document["commands"] = [
                    {"name": name, "description": _first_line(getattr(obj, "help", ""))}
                    for name, obj in subcommands.items()
                ]
            else:
                document["parameters"] = [
                    {
                        "name": argument.name,
                        "required": argument.required,
                        "help": (
                            argument.parameter.help
                            if argument.parameter and argument.parameter.help
                            else ""
                        ),
                    }
                    for argument in target.assemble_argument_collection()
                ]
            (console or self.console).print(
                _toon_encode(document), soft_wrap=True, markup=False, highlight=False
            )
