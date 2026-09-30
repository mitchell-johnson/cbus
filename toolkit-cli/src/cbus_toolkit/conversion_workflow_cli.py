"""Public entry points for the bounded database conversion workflow."""
from __future__ import annotations

from pathlib import Path

from .conversion_workflow import ConversionWorkflow, read_journal, read_plan, write_plan


def prepare(args):
    """Reject local input mistakes before opening a server connection."""
    action = args.remote_action
    if action in ("plan-move", "apply-move"):
        if args.spec_dir is None:
            raise ValueError("Use --spec-dir or CBUS_UNITSPEC_DIR for private decoded specifications")
        if not args.exclusive_project:
            raise ValueError("Use --exclusive-project only while you exclusively own the closed project")
    if action == "plan-move":
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Conversion plan destination already exists")
        if not args.output.parent.is_dir():
            raise ValueError("Conversion plan directory must exist")
    elif action == "apply-move":
        args._conversion_plan = read_plan(args.plan)
        if args.journal.exists() or args.journal.is_symlink():
            raise ValueError("Existing conversion attempt refuses reapply; use recover")
        if not args.journal.parent.is_dir():
            raise ValueError("Conversion journal directory must exist")
    else:
        args._conversion_journal = read_journal(args.journal)


def execute(args, client):
    workflow = ConversionWorkflow(client, getattr(args, "spec_dir", None))
    if args.remote_action == "plan-move":
        plan = workflow.plan_move(args.source, args.destination,
                                  backup_project=args.backup_project,
                                  exclusive_project=args.exclusive_project)
        write_plan(args.output, plan)
        binding = plan["binding"]
        changes = [{"parameter": name,
                    "destination_before": binding["destination_pp"]["parameters"].get(name),
                    "expected_after": value,
                    "source": binding["source_pp"]["parameters"].get(name),
                    "stored_in_converted_unit": name in dict(binding["expected_pp"])}
                   for name, value in binding["expected_values"].items()
                   if binding["destination_pp"]["parameters"].get(name) != value]
        return {"planned": True, "plan_file": str(Path(args.output).absolute()),
                "plan_sha256": plan["plan_sha256"], "source": binding["source"],
                "destination": binding["destination"], "backup_project": binding["backup_project"],
                "expected_identity": binding["expected_identity"], "changes": changes,
                "project_saved": False, "hardware_programmed": False}, 0
    if args.remote_action == "apply-move":
        return workflow.apply_move(args._conversion_plan, journal=args.journal,
                                   exclusive_project=args.exclusive_project), 0
    result = workflow.recover(journal=args.journal)
    return result, int(result.get("disposition") in ("conflict", "read-unavailable")
                       or result.get("backup_verified_fresh") is not True
                       or "read_error" in result.get("observation", {}))
