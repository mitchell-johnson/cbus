"""Ordered, caller-declared cache lists for explicit eDLT control phases.

This module does not bind controls, change parameters or resolve live metadata.
Names and formatted displays are supplied separately: Toolkit's address/hex
display preference can change the latter without changing the object's name.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping

from .edlt import EdltError, _int
from .edlt_lifecycle import LifecycleCache, LifecycleMetadataError

FORMAT = 'cbus-edlt-application-cache-v1'
MAX_LIST_GROUPS = 4096


@dataclass(frozen=True)
class CachedDisplay:
    address: int
    name: str
    formatted_display: str

    def __post_init__(self):
        _int(self.address, 'Cached display address')
        if any(not isinstance(value, str) or len(value) > 1024 for value in (self.name, self.formatted_display)):
            raise EdltError('Cached names and formatted displays must be strings of at most1024 characters')

    @classmethod
    def from_dict(cls, row):
        if not isinstance(row, Mapping) or set(row) != {'address', 'name', 'formatted_display'}:
            raise EdltError('Invalid cached display fields')
        return cls(row['address'], row['name'], row['formatted_display'])

    def as_dict(self):
        return dict(address=self.address, name=self.name, formatted_display=self.formatted_display)


def _records(rows, limit):
    if not isinstance(rows, tuple) or len(rows) > limit or any(type(row) is not CachedDisplay for row in rows):
        raise EdltError('Invalid ordered display list')
    if len({row.address for row in rows}) != len(rows):
        raise EdltError('Duplicate cache object address; distinct names do not disambiguate identity')


@dataclass(frozen=True)
class CachedGroupList:
    application: int
    complete: bool
    groups: tuple[CachedDisplay, ...]

    def __post_init__(self):
        _int(self.application, 'Cached group-list application')
        if type(self.complete) is not bool: raise EdltError('Group-list completeness must be boolean')
        _records(self.groups, 256)

    def as_dict(self):
        return dict(application=self.application, complete=self.complete, groups=[g.as_dict() for g in self.groups])


@dataclass(frozen=True)
class ApplicationCache:
    lifecycle: LifecycleCache
    applications_complete: bool
    applications: tuple[CachedDisplay, ...]
    group_lists: tuple[CachedGroupList, ...]

    def __post_init__(self):
        if type(self.lifecycle) is not LifecycleCache: raise EdltError('Application cache requires lifecycle facts')
        if type(self.applications_complete) is not bool: raise EdltError('Application-list completeness must be boolean')
        _records(self.applications, 256)
        applications = {a.address for a in self.applications}
        if not applications <= set(self.lifecycle.applications):
            raise EdltError('Named applications must be present in lifecycle facts')
        if self.applications_complete and applications != set(self.lifecycle.applications):
            raise EdltError('Complete application list disagrees with lifecycle facts')
        if not isinstance(self.group_lists, tuple) or len(self.group_lists) > 256 or any(type(row) is not CachedGroupList for row in self.group_lists):
            raise EdltError('Invalid application group lists')
        if len({row.application for row in self.group_lists}) != len(self.group_lists):
            raise EdltError('Duplicate group-list application')
        if sum(len(row.groups) for row in self.group_lists) > MAX_LIST_GROUPS:
            raise EdltError('Group lists exceed4096 cached objects')
        for row in self.group_lists:
            if row.application not in applications: raise EdltError('Group list requires a named application')
            listed = {g.address for g in row.groups}
            for fact in self.lifecycle.groups:
                if fact.application != row.application: continue
                if fact.group in listed and not fact.exists or row.complete and fact.exists and fact.group not in listed:
                    raise EdltError('Group list contradicts lifecycle presence facts')

    @classmethod
    def from_dict(cls, document):
        if not isinstance(document, Mapping) or set(document) != {
                'format', 'lifecycle', 'applications_complete', 'applications', 'group_lists'} or document['format'] != FORMAT:
            raise EdltError('Invalid application cache format or fields')
        def array(rows, limit):
            if not isinstance(rows, (list, tuple)) or len(rows) > limit:
                raise EdltError('Invalid application cache array')
            return rows
        applications = tuple(CachedDisplay.from_dict(row) for row in array(document['applications'], 256))
        groups = []
        for row in array(document['group_lists'], 256):
            if not isinstance(row, Mapping) or set(row) != {'application', 'complete', 'groups'}:
                raise EdltError('Invalid group-list fields')
            groups.append(CachedGroupList(row['application'], row['complete'],
                tuple(CachedDisplay.from_dict(g) for g in array(row['groups'], 256))))
        return cls(LifecycleCache.from_dict(document['lifecycle']), document['applications_complete'], applications, tuple(groups))

    def as_dict(self):
        return dict(format=FORMAT, lifecycle=self.lifecycle.as_dict(), applications_complete=self.applications_complete,
                    applications=[a.as_dict() for a in self.applications], group_lists=[g.as_dict() for g in self.group_lists])

    def find_application(self, address):
        _int(address, 'Application address')
        return next((row for row in self.applications if row.address == address), None)

    def find_group_list(self, application):
        _int(application, 'Application address')
        return next((row for row in self.group_lists if row.application == application), None)

    def group_presence(self, application, group):
        """True/False are supplied facts; None means the cache cannot answer."""
        _int(application, 'Application address'); _int(group, 'Group address')
        row = self.find_group_list(application)
        if row is not None:
            if any(g.address == group for g in row.groups): return True
            if row.complete: return False
        fact = self.lifecycle.find(application, group)
        return fact.exists if fact else None

    def application_choices(self, *, primary, secondary):
        _int(primary, 'Primary application'); _int(secondary, 'Secondary application')
        if not self.applications_complete:
            raise LifecycleMetadataError('Complete ordered application list is required', {'field': 'applications_complete'}, original_stage='lists')
        eligible = tuple(a for a in self.applications if 48 <= a.address <= 127 or a.address == 136)
        return {'primary': tuple(a for a in eligible if a.address != secondary),
                'secondary': (CachedDisplay(255, '<Unused>', '<Unused>'),) + tuple(a for a in eligible if a.address != primary)}

    def group_choices(self, application, *, exclude=(), placeholder='<Unused>'):
        _int(application, 'Application address')
        if not isinstance(exclude, (list, tuple)) or len(exclude) > 256:
            raise EdltError('Excluded groups must be a bounded address sequence')
        for group in exclude: _int(group, 'Excluded group')
        if not isinstance(placeholder, str) or len(placeholder) > 1024:
            raise EdltError('Invalid unused-group display name')
        row = self.find_group_list(application)
        if row is None or not row.complete:
            raise LifecycleMetadataError('Complete ordered group list is required',
                {'application': application, 'field': 'group_list_complete'}, original_stage='lists')
        return (CachedDisplay(255, placeholder, placeholder),) + tuple(g for g in row.groups if g.address != 255 and g.address not in exclude)
