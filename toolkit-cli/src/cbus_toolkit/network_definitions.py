"""Explicit C-Gate runtime network catalogue commands; no interface opening."""
from __future__ import annotations

from dataclasses import dataclass

from .native import NativeProjects, _project, _token


def _plain_token(value, label):
    value = _token(value, label)
    if any(character in value for character in ('"', "\\")):
        raise ValueError(f"{label} must be an unquoted C-Gate token")
    return value


def _name(value):
    value = _plain_token(value, "network definition name")
    if "/" in value or len(value.encode("utf-8")) > 255:
        raise ValueError("Network definition names cannot contain paths or exceed 255 UTF-8 bytes")
    return value


@dataclass(frozen=True)
class NetworkDefinitionCommand:
    project: str
    operation: str
    command: str
    expected_codes: tuple[int, ...]


def definition_command(action, *, project, name=None, new_name=None,
                       interface_type=None, interface_address=None, options=(),
                       selector=None, fix_references=True):
    """Validate every input before project selection or any command is sent."""
    project = _project(project)
    if action not in ("list", "create", "delete", "rename", "load", "save", "flush"):
        raise ValueError("Unknown network definition operation")
    if type(fix_references) is not bool:
        raise ValueError("fix_references must be Boolean")
    if not isinstance(options, (tuple, list)):
        raise ValueError("Network options must be a list or tuple of tokens")
    if action != "create" and (interface_type is not None or interface_address is not None or options):
        raise ValueError("Interface and option arguments are supported only for create")
    if action != "rename" and (new_name is not None or not fix_references):
        raise ValueError("Rename arguments are supported only for rename")
    if action not in ("load", "save") and selector is not None:
        raise ValueError("DB or FILE is supported only for load and save")
    if action not in ("create", "delete", "rename", "flush") and name is not None:
        raise ValueError("This operation does not take a network definition name")
    command = "NET " + action.upper()
    if action == "list":
        command += " " + project
    elif action == "create":
        name = _name(name)
        interface_type = _plain_token(interface_type, "interface type").lower()
        if interface_type not in ("serial", "cni", "bridge", "etherlite", "socket", "modem", "wiser"):
            raise ValueError("Unsupported network interface type")
        interface_address = _plain_token(interface_address, "interface address")
        options = tuple(_plain_token(option, "network option") for option in options)
        command += " " + " ".join((name, interface_type, interface_address, *options))
    elif action in ("delete", "rename", "flush"):
        command += " " + _name(name)
        if action == "rename":
            command += " " + _name(new_name)
            if not fix_references:
                command += " nofixrefs"
    else:
        selector = _plain_token(selector, "network definition source or destination").upper()
        if selector not in ("DB", "FILE"):
            raise ValueError("Network definition source or destination must be DB or FILE")
        command += f" {selector} {project}"
    return NetworkDefinitionCommand(project, action, command, (131, 132) if action == "list" else (200,))


def _execute(plan, client):
    NativeProjects(client).operation("use", plan.project)
    response = client.command(plan.command)
    if response.code not in plan.expected_codes:
        raise RuntimeError("Network definition operation did not complete: " + response.final)
    return response


class NativeNetworkDefinitions:
    def __init__(self, client):
        self.client = client

    def execute(self, action, *, project, **arguments):
        plan = definition_command(action, project=project, **arguments)
        return _execute(plan, self.client)


def cli_command(args):
    return definition_command(
        args.definition_action, project=args.project,
        **{name: getattr(args, name) for name in (
            "name", "new_name", "interface_type", "interface_address", "options", "selector",
        ) if hasattr(args, name)},
        fix_references=not getattr(args, "no_fix_references", False),
    )


def cli_run(args, client):
    return _execute(cli_command(args), client)
