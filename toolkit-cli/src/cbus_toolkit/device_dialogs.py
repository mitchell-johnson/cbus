"""Device-dialog mapping registry (issue #11 box1, bead cbus-h22).

PURE offline starter slice. Maps the 118 device-dialog candidates from the
documentation census (``toolkit-cli/docs/toolkit-surface.md`` section
"Device dialog candidates" / ``toolkit-surface.json``
``device_dialog_candidates``) to feature-ledger area IDs
(``src/cbus_toolkit/capabilities.json``) plus differential workflow slots.

This module makes NO parity claims: every dialog starts RED
(``differential_status="pending"``, all workflow/negative slots
``"unassessed"``, no evidence paths). No endpoints, credentials, or vendor
specifications are invented or read here. Only short topic titles, IDs,
paths, and counts from the committed census are recorded.

Ledger routing is triage only (nearest in-progress/pending area, fallback
``toolkit-differential-acceptance``); it does not assert that any dialog
works.
"""
from __future__ import annotations

from cbus_toolkit import differential

EXPECTED_DIALOG_COUNT = 118

DIALOG_PENDING = differential.DIFFERENTIAL_STATUSES[0]
DIALOG_UNASSESSED = differential.DIFFERENTIAL_STATUSES[1]

WORKFLOW_SLOTS = differential.WORKFLOW_SLOTS
NEGATIVE_SLOTS = differential.NEGATIVE_SLOTS

# (dialog_id, title, parent_context, subtree_topics, ledger_id)
# Titles/paths/counts transcribed from the committed census
# (toolkit-surface.json device_dialog_candidates); ledger routing is triage
# only, see module docstring.
_DIALOG_ROWS: tuple[tuple[str, str, str, int, str], ...] = (
    ("dialog:11068.htm", "4 channel auxiliary input unit configuration dialog box", "C-Bus wired input units / C-Bus auxiliary input units / 4 channel auxiliary input unit", 7, "toolkit-differential-acceptance"),
    ("dialog:11057.htm", "4 channel DIN rail auxiliary input unit (DINAUX4) configuration dialog box", "C-Bus wired input units / C-Bus auxiliary input units / 4 channel DIN rail auxiliary input unit (DINAUX4)", 7, "toolkit-differential-acceptance"),
    ("dialog:11037.htm", "4 channel DIN rail auxiliary input unit (BCI4A) configuration dialog box", "C-Bus wired input units / C-Bus auxiliary input units / 4 channel DIN rail auxiliary input unit (BCI4A)", 11, "toolkit-differential-acceptance"),
    ("dialog:9286.htm", "Decorator style 1 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / C-Bus Decorator input units / Decorator style 1 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9287.htm", "Decorator style 2 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / C-Bus Decorator input units / Decorator style 2 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9289.htm", "Decorator style 3 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / C-Bus Decorator input units / Decorator style 3 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9290.htm", "Decorator style 4 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / C-Bus Decorator input units / Decorator style 4 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9205.htm", "Saturn style 5 key DLT input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Dynamic Labelling Technology (DLT) key input units / Saturn style 5 key DLT input unit", 11, "dlt-edlt-widgets-and-labels"),
    ("dialog:9209.htm", "Neo style 5 key DLT input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Dynamic Labelling Technology (DLT) key input units / Neo style 5 key DLT input unit", 11, "dlt-edlt-widgets-and-labels"),
    ("dialog:9210.htm", "Decorator style 4 key DLT input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Dynamic Labelling Technology (DLT) key input units / Decorator style 4 key DLT input unit", 11, "dlt-edlt-widgets-and-labels"),
    ("dialog:18865.htm", "eDLT configuration dialog box", "C-Bus wired input units / Wired key input units / eDLT key input unit", 8, "dlt-edlt-widgets-and-labels"),
    ("dialog:19973.htm", "Saturn Zen key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Saturn Zen series / 1 Key Saturn Zen key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:19973_1.htm", "Saturn Zen key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Saturn Zen series / 2 Key Saturn Zen key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:19973_2.htm", "Saturn Zen key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Saturn Zen series / 3 Key Saturn Zen key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:19973_3.htm", "Saturn Zen key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Saturn Zen series / 4 Key Saturn Zen key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:40007.htm", "Saturn Zen NCC key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Saturn Zen series / Saturn Zen NCC key input unit", 3, "toolkit-differential-acceptance"),
    ("dialog:9294.htm", "Avanti style 1 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Avanti style key input units / Avanti style 1 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9300.htm", "Avanti style 2 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Avanti style key input units / Avanti style 2 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9301.htm", "Avanti style 3 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Avanti style key input units / Avanti style 3 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:8449.htm", "2 key Modena style key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Modena style key input unit / 2 key Modena style key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:8463.htm", "4 key Modena style key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Modena style key input unit / 4 key Modena style key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:8476.htm", "6 key Modena style key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Modena style key input unit / 6 key Modena style key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9302.htm", "Neo style 2 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Neo style key input units / Neo style 2 key input unit", 11, "neo-core-key-presets"),
    ("dialog:9303.htm", "Neo style 4 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Neo style key input units / Neo style 4 key input unit", 11, "neo-core-key-presets"),
    ("dialog:9304.htm", "Neo style 8 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Neo style key input units / Neo style 8 key input unit", 11, "neo-core-key-presets"),
    ("dialog:9305.htm", "Reflection style 1 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Reflection style key input units / Reflection style 1 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9311.htm", "Reflection style 3 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Reflection style key input units / Reflection style 3 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9312.htm", "Reflection style 6 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Reflection style key input units / Reflection style 6 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9313.htm", "Reflection style 8 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Reflection style key input units / Reflection style 8 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9314.htm", "Reflection style 2 key vertical input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Reflection style key input units / Reflection style 2 key vertical input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9315.htm", "Reflection style 4 key vertical input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Reflection style key input units / Reflection style 4 key vertical input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9318.htm", "Saturn style 2 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Saturn style key input units / Saturn style 2 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9319.htm", "Saturn style 4 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Saturn style key input units / Saturn style 4 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9320.htm", "Saturn style 6 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Saturn style key input units / Saturn style 6 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:40001.htm", "Saturn style NCC key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Saturn style key input units / Saturn style NCC key input unit", 3, "toolkit-differential-acceptance"),
    ("dialog:8113.htm", "1 key Standard input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Standard range of input key units / Standard KEYC series / 1 key Standard input unit", 9, "classic-key-presets"),
    ("dialog:8122.htm", "2 key Standard input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Standard range of input key units / Standard KEYC series / 2 key Standard input unit", 9, "classic-key-presets"),
    ("dialog:8132.htm", "4 key Standard input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Standard range of input key units / Standard KEYC series / 4 key Standard input unit", 9, "classic-key-presets"),
    ("dialog:8142.htm", "1 key Infra Red Standard input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Standard range of input key units / Standard KEYC series / 1 key Infra Red Standard input unit", 8, "classic-key-presets"),
    ("dialog:8151.htm", "4 key Infra Red Standard input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Standard range of input key units / Standard KEYC series / 4 key Infra Red Standard input unit", 9, "classic-key-presets"),
    ("dialog:9905.htm", "Vieo style 1 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Vieo key input unit / Vieo style 1 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9926.htm", "Vieo style 2 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Vieo key input unit / Vieo style 2 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9938.htm", "Vieo style 3 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / Vieo key input unit / Vieo style 3 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9967.htm", "30M 1 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 30M series key input units / 30M 1 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:9990.htm", "30M 2 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 30M series key input units / 30M 2 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:10004.htm", "30M 3 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 30M series key input units / 30M 3 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:10018.htm", "30M 4 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 30M series key input units / 30M 4 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:10032.htm", "30M infra red 1 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 30M series key input units / 30M infra red 1 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:10046.htm", "30M infra red 2 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 30M series key input units / 30M infra red 2 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:10059.htm", "30M infra red 3 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 30M series key input units / 30M infra red 3 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:10072.htm", "30M infra red 4 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 30M series key input units / 30M infra red 4 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:30004.htm", "40M 1 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 40M series key input units / 40M 1 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:30016.htm", "40M 2 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 40M series key input units / 40M 2 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:30028.htm", "40M 3 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 40M series key input units / 40M 3 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:30040.htm", "40M 4 key input unit configuration dialog box", "C-Bus wired input units / Wired key input units / 40M series key input units / 40M 4 key input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:4455.htm", "Two channel bus coupler configuration dialog box", "C-Bus wired input units / Wired key input units / C-Bus bus coupler input units / Two channel bus coupler", 11, "toolkit-differential-acceptance"),
    ("dialog:4457.htm", "Four channel bus coupler configuration dialog box", "C-Bus wired input units / Wired key input units / C-Bus bus coupler input units / Four channel bus coupler", 11, "toolkit-differential-acceptance"),
    ("dialog:11068_1.htm", "4 channel auxiliary input unit configuration dialog box", "C-Bus wired input units / Wired key input units / C-Bus auxiliary input units / 4 channel auxiliary input unit", 7, "toolkit-differential-acceptance"),
    ("dialog:11057_1.htm", "4 channel DIN rail auxiliary input unit (DINAUX4) configuration dialog box", "C-Bus wired input units / Wired key input units / C-Bus auxiliary input units / 4 channel DIN rail auxiliary input unit (DINAUX4)", 7, "toolkit-differential-acceptance"),
    ("dialog:11037_1.htm", "4 channel DIN rail auxiliary input unit (BCI4A) configuration dialog box", "C-Bus wired input units / Wired key input units / C-Bus auxiliary input units / 4 channel DIN rail auxiliary input unit (BCI4A)", 11, "toolkit-differential-acceptance"),
    ("dialog:10112.htm", "Passive infra red Occupancy Detector (1.2.67) configuration dialog box", "C-Bus wired input units / Wired C-Bus sensors and detectors / Passive infra red Occupancy Detectors / Passive infra red Occupancy Detector (1.2.67)", 7, "sensors-wizard-semantics"),
    ("dialog:19832.htm", "Passive infra red Occupancy Detector (2.4.00) configuration dialog box", "C-Bus wired input units / Wired C-Bus sensors and detectors / Passive infra red Occupancy Detectors / Passive infra red Occupancy Detector (2.4.00)", 9, "sensors-wizard-semantics"),
    ("dialog:11087.htm", "Multi Sensor configuration dialog box", "C-Bus wired input units / Wired C-Bus sensors and detectors / Multi Sensor", 13, "sensors-wizard-semantics"),
    ("dialog:15007.htm", "Configuration dialog box", "C-Bus wired input units / Wired C-Bus sensors and detectors / Light level sensor", 9, "sensors-wizard-semantics"),
    ("dialog:9722.htm", "Configuration dialog box", "C-Bus wired input units / Wired C-Bus sensors and detectors / Light level sensor / Light level sensor (firmware 1.00)", 5, "sensors-wizard-semantics"),
    ("dialog:5239.htm", "5031RDTSL Temperature Sensor configuration dialog box", "C-Bus wired input units / Wired C-Bus sensors and detectors / Remote Digital Temperature Sensor (5031RDTSL)", 8, "sensors-wizard-semantics"),
    ("dialog:14934.htm", "Current Measurement Unit configuration dialog box", "C-Bus wired input units / Wired C-Bus sensors and detectors / Current Measurement Unit", 9, "sensors-wizard-semantics"),
    ("dialog:17704.htm", "Detector configuration dialog box", "C-Bus wired input units / Wired C-Bus sensors and detectors / Light Level Detector (5754PE)", 14, "sensors-wizard-semantics"),
    ("dialog:17742.htm", "Occupancy/Light Level Detector configuration dialog box", "C-Bus wired input units / Wired C-Bus sensors and detectors / Occupancy/Light Level Detector (5754ODPE)", 14, "sensors-wizard-semantics"),
    ("dialog:17544.htm", "Occupancy/Light Level Detector with IR configuration dialog box", "C-Bus wired input units / Wired C-Bus sensors and detectors / Occupancy/Light Level Detector with IR (5754ODPEIR)", 14, "sensors-wizard-semantics"),
    ("dialog:8321.htm", "General input unit configuration dialog box", "C-Bus wired input units / General input unit", 11, "toolkit-differential-acceptance"),
    ("dialog:5116.htm", "Single channel shutter relay configuration dialog box", "C-Bus wired output units / Relays / Single channel shutter relay", 7, "all-unit-parameter-encoding"),
    ("dialog:9728.htm", "DIN rail four channel change over voltage free relay unit configuration dialog box", "C-Bus wired output units / Relays / DIN rail four channel change over voltage free relay unit", 10, "all-unit-parameter-encoding"),
    ("dialog:9792.htm", "DIN rail four (4) channel relay configuration dialog box", "C-Bus wired output units / Relays / DIN rail four (4) channel relay", 10, "all-unit-parameter-encoding"),
    ("dialog:9808.htm", "DIN rail 8 channel voltage free relay configuration dialog box", "C-Bus wired output units / Relays / DIN rail 8 channel voltage free relay (RELDN8)", 10, "all-unit-parameter-encoding"),
    ("dialog:9824.htm", "DIN rail 8 channel voltage free relay configuration dialog box", "C-Bus wired output units / Relays / DIN rail 8 channel voltage free relay (RELDN8B)", 10, "all-unit-parameter-encoding"),
    ("dialog:9838.htm", "DIN rail 12 channel voltage free relay unit configuration dialog box", "C-Bus wired output units / Relays / DIN rail 12 channel voltage free relay unit", 10, "all-unit-parameter-encoding"),
    ("dialog:10157.htm", "8 channel ELV relay configuration dialog box", "C-Bus wired output units / Relays / 8 channel ELV relay", 7, "all-unit-parameter-encoding"),
    ("dialog:12403.htm", "C-Bus ceiling sweep fan controller configuration dialog box", "C-Bus wired output units / Relays / C-Bus ceiling sweep fan controller", 8, "all-unit-parameter-encoding"),
    ("dialog:9688.htm", "4 channel standard dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 4 channel standard dimmer", 7, "all-unit-parameter-encoding"),
    ("dialog:9702.htm", "4 channel DIN rail dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 4 channel DIN rail dimmer", 9, "all-unit-parameter-encoding"),
    ("dialog:9646.htm", "8 channel DIN rail dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 8 channel DIN rail dimmer", 9, "all-unit-parameter-encoding"),
    ("dialog:5199.htm", "C-Bus Universal dimmer configuration dialog box", "C-Bus wired output units / Dimmers / C-Bus Universal dimmer", 11, "all-unit-parameter-encoding"),
    ("dialog:8064.htm", "3 channel architectural dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 3 channel architectural dimmer", 18, "all-unit-parameter-encoding"),
    ("dialog:8081.htm", "6 channel architectural dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 6 channel architectural dimmer", 18, "all-unit-parameter-encoding"),
    ("dialog:12053.htm", "1 channel professional dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 1 channel professional dimmer", 8, "all-unit-parameter-encoding"),
    ("dialog:12064.htm", "2 channel professional dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 2 channel professional dimmer", 8, "all-unit-parameter-encoding"),
    ("dialog:12074.htm", "4 channel professional dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 4 channel professional dimmer", 8, "all-unit-parameter-encoding"),
    ("dialog:7887.htm", "12 channel architectural dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 12 channel architectural dimmer", 18, "all-unit-parameter-encoding"),
    ("dialog:5213.htm", "3 channel professional dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 3 channel professional dimmer", 11, "all-unit-parameter-encoding"),
    ("dialog:5321.htm", "6 channel professional dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 6 channel professional dimmer", 11, "all-unit-parameter-encoding"),
    ("dialog:5296.htm", "12 channel professional dimmer configuration dialog box", "C-Bus wired output units / Dimmers / 12 channel professional dimmer", 11, "all-unit-parameter-encoding"),
    ("dialog:12090.htm", "DIN rail four channel analog output unit configuration dialog box", "C-Bus wired output units / DIN rail four channel analog output unit", 7, "all-unit-parameter-encoding"),
    ("dialog:9617.htm", "8 channel DSI Gateway configuration dialog box", "C-Bus wired output units / 8 channel DSI Gateway", 9, "all-unit-parameter-encoding"),
    ("dialog:11739.htm", "C-Bus to DMX One Way Gateway configuration dialog box", "C-Bus wired output units / C-Bus to DMX One Way Gateway", 7, "all-unit-parameter-encoding"),
    ("dialog:14052.htm", "Occupancy Controller (1 sensor, 1 relay) configuration dialog box", "C-Bus wired input/output units / Occupancy Controller (1 sensor, 1 relay)", 23, "sensors-wizard-semantics"),
    ("dialog:14054.htm", "Occupancy Controller (2 sensors, 2 relays) configuration dialog box", "C-Bus wired input/output units / Occupancy Controller (2 sensors, 2 relays)", 23, "sensors-wizard-semantics"),
    ("dialog:14053.htm", "Occupancy Controller (2 sensors, 2 relays, 2 dimmers) configuration dialog box", "C-Bus wired input/output units / Occupancy Controller (2 sensors, 2 relays, 2 dimmers)", 23, "sensors-wizard-semantics"),
    ("dialog:3850.htm", "C-Bus programmable thermostat configuration dialog box", "Wired C-Bus thermostat units / Introduction to the C-Bus thermostat / C-Bus thermostat configuration", 1, "thermostat-configuration"),
    ("dialog:3851.htm", "C-Bus single zone thermostat configuration dialog box", "Wired C-Bus thermostat units / Introduction to the C-Bus thermostat / C-Bus thermostat configuration", 1, "thermostat-configuration"),
    ("dialog:5392.htm", "MK2 Black and White Touch Screen configuration dialog box", "C-Bus controller units / MK2 Black and White Touch Screen", 4, "toolkit-differential-acceptance"),
    ("dialog:5414.htm", "MK2 Black and White Touch Screen with logic engine configuration dialog box", "C-Bus controller units / MK2 Black and White Touch Screen with logic engine", 4, "toolkit-differential-acceptance"),
    ("dialog:13447.htm", "Colour C-Touch Screen configuration dialog box", "C-Bus controller units / Colour C-Touch Screen", 4, "toolkit-differential-acceptance"),
    ("dialog:13617.htm", "Spectrum colour touch screen configuration dialog box", "C-Bus controller units / Spectrum colour touch screen", 4, "toolkit-differential-acceptance"),
    ("dialog:13623.htm", "Spectrum colour touch screen with logic engine configuration dialog box", "C-Bus controller units / Spectrum colour touch screen with logic engine", 4, "toolkit-differential-acceptance"),
    ("dialog:15488.htm", "Pascal Automation Controller configuration dialog box", "C-Bus controller units / Pascal Automation Controller", 4, "toolkit-differential-acceptance"),
    ("dialog:16301.htm", "C-Bus automation controller configuration dialog box", "C-Bus automation controller units", 4, "toolkit-differential-acceptance"),
    ("dialog:10747.htm", "PC interface configuration dialog box", "Wired support units / Wired network units / PC interface units", 4, "interface-discovery-and-setup"),
    ("dialog:10383.htm", "Inline CNI interface (5100CN2) configuration dialog box", "Wired support units / Wired network units / Inline CNI interface (5100CN2)", 4, "interface-discovery-and-setup"),
    ("dialog:10751.htm", "C-Bus bridges configuration dialog box", "Wired support units / Wired network units / C-Bus bridges", 5, "interface-discovery-and-setup"),
    ("dialog:1403.htm", "DALI Gateway configuration dialog box", "Wired support units / C-Bus DALI Gateway", 5, "toolkit-differential-acceptance"),
    ("dialog:15426.htm", "C-Bus 7 Day Clock configuration dialog box", "Wired support units / C-Bus 7 Day Clock", 8, "toolkit-differential-acceptance"),
    ("dialog:2215.htm", "C-Bus infrared transmitter configuration dialog box", "Wired support units / C-Bus infrared transmitter", 3, "toolkit-differential-acceptance"),
    ("dialog:5532.htm", "C-Bus telephone interface configuration dialog box", "Wired support units / C-Bus telephone interface", 3, "toolkit-differential-acceptance"),
    ("dialog:12558.htm", "Decorator wireless input/output unit configuration dialog box", "Wireless C-Bus units / Decorator wireless input/output units", 15, "toolkit-differential-acceptance"),
    ("dialog:13872.htm", "C-Bus wireless to wired gateway configuration dialog box", "Wireless C-Bus units / C-Bus wireless to wired gateway", 5, "toolkit-differential-acceptance"),
    ("dialog:13876.htm", "C-Bus Wireless to wired gateway (2.x) configuration dialog box", "Wireless C-Bus units / C-Bus Wireless to wired gateway (2.x)", 10, "toolkit-differential-acceptance"),
    ("dialog:1613.htm", "MRA amplifier configuration dialog box", "Wired Multi Room Audio units / The MRA amplifier", 11, "toolkit-differential-acceptance"),
)


def _index() -> dict[str, tuple[str, str, int, str]]:
    index: dict[str, tuple[str, str, int, str]] = {}
    for dialog_id, title, parent_context, subtree_topics, ledger_id in _DIALOG_ROWS:
        if dialog_id in index:
            raise ValueError(f"Duplicate device dialog id: {dialog_id}")
        index[dialog_id] = (title, parent_context, subtree_topics, ledger_id)
    return index


_INDEX = _index()


def _known_ledger_ids() -> set[str]:
    return set(differential.ledger_area_ids(differential.load_ledger()))


def _validate_ledger_id(ledger_id: str) -> None:
    if ledger_id not in _known_ledger_ids():
        raise KeyError(f"Unknown ledger area: {ledger_id}")


def _red_entry(dialog_id: str, title: str, parent_context: str, subtree_topics: int, ledger_id: str) -> dict:
    return {
        "dialog_id": dialog_id,
        "title": title,
        "parent_context": parent_context,
        "subtree_topics": subtree_topics,
        "ledger_id": ledger_id,
        "differential_status": DIALOG_PENDING,
        "workflows": {slot: DIALOG_UNASSESSED for slot in WORKFLOW_SLOTS},
        "negative_paths": {slot: DIALOG_UNASSESSED for slot in NEGATIVE_SLOTS},
        "evidence_paths": [],
    }


def list_dialogs() -> list[dict]:
    """Return all device-dialog registry entries (RED: all unassessed).

    Validates every mapped ledger ID against the authoritative ledger
    (``capabilities.json``); raises ``KeyError`` on drift.
    """
    known = _known_ledger_ids()
    entries = []
    for dialog_id, (title, parent_context, subtree_topics, ledger_id) in _INDEX.items():
        if ledger_id not in known:
            raise KeyError(f"Unknown ledger area: {ledger_id}")
        entries.append(
            _red_entry(dialog_id, title, parent_context, subtree_topics, ledger_id)
        )
    return entries


def dialog_status(dialog_id: str) -> dict:
    """Return the RED status entry for one dialog; reject unknown IDs.

    Validates the mapped ledger ID against the authoritative ledger
    (``capabilities.json``); raises ``KeyError`` on drift.
    """
    try:
        title, parent_context, subtree_topics, ledger_id = _INDEX[dialog_id]
    except KeyError as exc:
        raise KeyError(f"Unknown device dialog: {dialog_id}") from exc
    _validate_ledger_id(ledger_id)
    return _red_entry(dialog_id, title, parent_context, subtree_topics, ledger_id)


def matrix_by_ledger() -> dict[str, list[str]]:
    """Group dialog IDs by ledger area ID.

    Validates every mapped ledger ID against the authoritative ledger
    (``capabilities.json``); raises ``KeyError`` on drift.
    """
    known = _known_ledger_ids()
    matrix: dict[str, list[str]] = {}
    for dialog_id, (_, _, _, ledger_id) in _INDEX.items():
        if ledger_id not in known:
            raise KeyError(f"Unknown ledger area: {ledger_id}")
        matrix.setdefault(ledger_id, []).append(dialog_id)
    for dialog_ids in matrix.values():
        dialog_ids.sort()
    return matrix
