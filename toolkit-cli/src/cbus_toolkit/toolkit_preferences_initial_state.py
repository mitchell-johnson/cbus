"""Exact observed preference registration state, without I/O.

Forty current values follow Toolkit 1.18.0.2754's selected registration routines.
The original constructor/type-initializer bodies were observed with a preallocated
object fixture, plus an independent original InitInstance zero-layout check. The
five display booleans are the original explicit pre-read fallback values. This
is not installer configuration or a whole-application startup snapshot.
"""
from __future__ import annotations

from .toolkit_preferences_store import validate_values, validate_display_values

# Original EXE SHA256: 9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab.
# Initialization-table order: Kipper388, global614, default languages682.
# Current booleans and registry default booleans are deliberately distinct.
_REGISTERED_VALUES = (
    ('LoadChangePortDisable', False),
    ('ApplicationLogDisable', False),
    ('TemperatureUnit', 0),
    ('DoNotPauseEventsWhileLoadingProject', False),
    ('ShowProjectManager', False),
    ('RememberProjectManagerVisibleState', False),
    ('Default Site', 'LOCAL'),
    ('Default COM Port', 'COM1'),
    ('Default Interface Type', 'Serial (PCI)'),
    ('Default CNI Address', ''),
    ('AutoInvokeMacroFunctionDialog', False),
    ('AutoInvokeDatabaseUnitDialog', False),
    ('SynchroniseFilters', True),
    ('CGateShutdownOnExit', False),
    ('CGateShutdownOnExitAsk', False),
    ('CloseProjectsOnExit', False),
    ('CGateShutdownDecision', 0),
    ('UnitDialogOverride', False),
    ('UnitDialogModeAdvanced', False),
    ('UnitDialogAlwaysClassic', False),
    ('FeedbackLog', False),
    ('FeedbackLogFile', ''),
    ('FeedbackLogSize', 0),
    ('JavaHeapMin', 0),
    ('JavaHeapMax', 0),
    ('IlluminanceMeasurementUnit', 0),
    ('ClipsalWebsiteURL', 'https://www.clipsal.com'),
    ('CISDownloadsURL', 'https://www.se.com/ww/en/product-range/2216-spacelogic-cbus-home-automation-system#software-and-firmware'),
    ('AllowLegacyApplicationCreation', False),
    ('AllowUserDefinedApplicationCreation', False),
    ('LegacyDuplicateUnitsDetection', True),
    ('ShowDatabaseLabelsOption', False),
    ('Default Language 1', 1),
    ('Default Language 2', -1),
    ('Default Language 3', -1),
    ('Default Language 4', -1),
    ('Default Language 5', -1),
    ('Default Language 6', -1),
    ('Default Language 7', -1),
    ('Default Language 8', -1),
)
_DISPLAY_FALLBACKS = (
    ('tag_hex', False),
    ('tag_override', False),
    ('sort_applications', False),
    ('sort_groups', False),
    ('sort_levels', False),
)


def constructor_state() -> dict[str, object]:
    """Return a detached existing-format state before any registry load.

    No host settings are read or changed. Values are the observed registration
    stage, including ShowProjectManager=False despite its registry default=True.
    Display values are the original missing-value load fallbacks, all False.
    """
    return {
        'format': 'cbus-toolkit-preferences-state-v1',
        'values': validate_values(dict(_REGISTERED_VALUES)),
        'display_values': validate_display_values(dict(_DISPLAY_FALLBACKS)),
    }
