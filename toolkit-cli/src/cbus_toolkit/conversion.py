"""Native database unit conversion with explicit move semantics and backups.

C-Gate's internal CONVERTUNIT modes 1 and 2 select a catalogue target or an
existing database unit. Mode 2 removes the source unit. Neither mode programs
hardware. Toolkit's additional client-side conversions are a separate path.
"""
from __future__ import annotations

import re

from .cgate import CGateError
from .native import NativeProjects, _project, _token
from .programming import Programmer


class ConversionError(RuntimeError):
    def __init__(self, message, *, backup_project=None):
        self.details = {"backup_project": backup_project}
        super().__init__(message)


def _unit_path(path):
    if not isinstance(path, str):
        raise ValueError("A fully qualified database unit path is required")
    match = re.fullmatch(r"//([A-Za-z0-9_]{1,8})/(\d{1,3})/p/(\d{1,3})", path)
    if not match or any(int(value) > 255 for value in match.groups()[1:]):
        raise ValueError("Use one unit path in the form //PROJECT/254/p/20")
    project, network, unit = match.groups()
    return f"//{project}/{int(network)}/p/{int(unit)}", project, int(network), int(unit)


class NativeConversions:
    def __init__(self, client):
        self.client = client
        self.projects = NativeProjects(client)

    def _arguments(self, source, *, unit_type=None, catalog_number=None, destination=None):
        source, project, network, unit = _unit_path(source)
        if destination is not None:
            if unit_type is not None or catalog_number is not None:
                raise ValueError("Choose a catalogue target or an existing destination unit")
            destination, other_project, _, _ = _unit_path(destination)
            if project.upper() != other_project.upper():
                raise ValueError("Native conversion moves require source and destination in the same project")
            if destination.upper() == source.upper():
                raise ValueError("Move source and destination must differ")
            arguments = f"2 {source} {destination}"
        else:
            unit_type = _token(unit_type, "target unit type")
            catalog_number = _token(catalog_number, "target catalogue number")
            destination = source
            arguments = f"1 {source} {unit_type} {catalog_number}"
        return arguments, source, destination, project

    def _check(self, arguments, source, destination, project):
        # The vendor conversion implementation uses relative network paths
        # internally even when its public arguments are fully qualified.
        self.projects.operation("use", project)
        reply = self.client.command("CONVERTUNIT CHECK " + arguments)
        if reply.code not in (200, 301):
            raise ConversionError("Unexpected native conversion check response: " + reply.final)
        return {"allowed": reply.code == 200, "source": source, "destination": destination,
                "removes_source": source != destination, "response": reply}

    def check_catalog(self, source, unit_type, catalog_number):
        return self._check(*self._arguments(source, unit_type=unit_type, catalog_number=catalog_number))

    def check_move(self, source, destination):
        return self._check(*self._arguments(source, destination=destination))

    def convert_catalog(self, source, unit_type, catalog_number, *, backup_project=None):
        return self._convert(self._arguments(source, unit_type=unit_type, catalog_number=catalog_number),
                             backup_project=backup_project, expected_type=unit_type, expected_catalog=catalog_number)

    def move(self, source, destination, *, backup_project=None):
        """Replace destination programming and remove source using native mode 2."""
        return self._convert(self._arguments(source, destination=destination), backup_project=backup_project)

    def align(self, source, destination, source_spec, target_spec, *, backup_project=None, dry_run=False):
        """Align evidenced classic settings while retaining destination identity."""
        from .offline_conversion import OfflineConversion
        source, _, _, _ = _unit_path(source)
        destination, project, _, _ = _unit_path(destination)
        if source.upper() == destination.upper():
            raise ValueError("Alignment source and destination must differ")
        if not isinstance(dry_run, bool):
            raise ValueError("dry_run must be a boolean")
        if backup_project is not None:
            backup_project = _project(backup_project)
            if backup_project.upper() == project.upper():
                raise ValueError("Backup project must differ from the destination project")
        converter = OfflineConversion(source_spec, target_spec)
        programmer = Programmer(self.client)
        with programmer.load(source.rsplit("/p/", 1)[0], "/db" + source) as session:
            converter._verify_session(session, source_spec)
            source_values = session.values()
        backup_created = None
        with programmer.load(destination.rsplit("/p/", 1)[0], "/db" + destination) as session:
            converter._verify_session(session, target_spec)
            plan = converter.plan(source_values, session.values())
            if backup_project and not dry_run:
                self.projects.operation("save", project)
                self.projects.operation("copy", project, backup_project)
                backup_created = backup_project
            try:
                result = converter.apply(session, plan)
                if not dry_run:
                    session.save_to_source()
            except (ValueError, RuntimeError, OSError) as error:
                raise ConversionError("Alignment or save failed: " + str(error), backup_project=backup_created) from error
        if not dry_run:
            try:
                restored = self._snapshot(destination)
                actual = converter._snapshot(target_spec, restored["parameters"], target_spec.parameters)
                if actual != {**plan.expected, **plan.changes}:
                    raise ConversionError("A fresh database load differs from the aligned settings")
            except (ValueError, RuntimeError, OSError) as error:
                raise ConversionError("Alignment persistence verification failed: " + str(error), backup_project=backup_created) from error
        return {**result, "source_address": source, "destination_address": destination,
                "backup_project": backup_created, "saved": not dry_run,
                "project_saved": False, "database_replaced": False, "hardware_programmed": False}

    def _snapshot(self, path):
        network = path.rsplit("/p/", 1)[0]
        with Programmer(self.client).load(network, "/db" + path) as session:
            return session.export_parameters()

    def _convert(self, prepared, *, backup_project, expected_type=None, expected_catalog=None):
        arguments, source, destination, project = prepared
        if backup_project is not None:
            backup_project = _project(backup_project)
            if backup_project.upper() == project.upper():
                raise ValueError("Backup project must differ from the conversion project")
        check = self._check(*prepared)
        if not check["allowed"]:
            raise ConversionError("Native C-Gate rejected this conversion: " + check["response"].final)
        before = self._snapshot(source)
        target = before if source == destination else self._snapshot(destination)
        expected_type = expected_type or target["unit_type"]
        expected_catalog = expected_catalog or target["catalog_number"]
        if backup_project:
            self.projects.operation("save", project)
            self.projects.operation("copy", project, backup_project)
        try:
            response = self.client.command("CONVERTUNIT CONVERT " + arguments)
            if response.code != 200:
                raise ConversionError("Native conversion did not complete: " + response.final)
            after = self._snapshot(destination)
            if after["unit_type"] != expected_type or after["catalog_number"] != expected_catalog:
                raise ConversionError("Converted unit identity differs from the requested destination")
            if source != destination:
                try:
                    self.client.command("DBGET " + source)
                except CGateError as error:
                    if error.response.code != 401:
                        raise
                else:
                    raise ConversionError("Native move did not remove the source unit")
        except (RuntimeError, OSError) as error:
            raise ConversionError("Conversion or verification failed: " + str(error), backup_project=backup_project) from error
        # Preserve and expose the native PP result. In mode 2 the vendor can
        # retain the source UnitAddress even though the DB address is different.
        raw_address = after["parameters"].get("UnitAddress")
        try:
            address_matches = int(raw_address, 0) == int(destination.rsplit("/", 1)[1]) if raw_address is not None else None
        except ValueError:
            address_matches = False
        return {"converted": True, "source": source, "destination": destination,
                "source_removed": source != destination, "backup_project": backup_project,
                "project_saved": False, "hardware_programmed": False,
                "parameter_address_matches_database": address_matches,
                "before": before, "after": after, "response": response}
