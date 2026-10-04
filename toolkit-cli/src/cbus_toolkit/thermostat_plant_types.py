"""Direct source plant output/fan assignments on one shared thermostat owner.

The component implements the twelve plant branches and the live Group
allocator. It does not open a panel, choose a template, schedule host messages,
catch error7327, migrate an Application, or save. The owning lifecycle supplies
its live getters and synchronous attribute observers. Values are already-loaded
model scalars: the owner must perform AfterLoad Boolean normalization before
calling this component; arbitrary raw Boolean PP bytes are not replayed here. Existing Group/Level
metadata and opaque Level values stay in the shared resolver.
"""
from __future__ import annotations

from collections.abc import MutableMapping
from copy import deepcopy

from .edlt_add_dialog import _upper
from .thermostat_post_load import OUTPUTS, DAMPERS, RELAYS, pp_name, virtual_plant_type
from .thermostat_remote_references import RemoteGroup, _GraphResolver
from .thermostat_templates import ThermostatTemplateError


class PlantGroupCapacityError(ThermostatTemplateError):
    """Source ECannotCreateGroupApplicationIsFull; prior changes are retained.

    The plant panel owner alone catches this as error7327. Other errors are
    not converted to that alert and no rollback belongs to this component.
    """


# Derived from the pinned source CFG, not a final-mask/installation snapshot.
# A test node makes its own live installation read at the original position.
_PARAMETERS = (
    (  # plant 0
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3af9', 1),
        ('set', 'CoolStage1OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b04', 2),
        ('set', 'CoolStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b0f', 3),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b1a', 4),
        ('set', 'CoolFanLowOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b25', 5),
        ('set', 'CoolFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b30', 6),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b3b', 7),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b46', 8),
        ('set', 'HeatStage1OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b51', 9),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b5c', 10),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b67', 11),
        ('set', 'HeatFanLowOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b72', 12),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b7d', 13),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3b88', 14),
        ('set', 'InternalRelay1Group', ('ref', 'UnusedGroup255'), '0xfe3b93', 15),
        ('set', 'InternalRelay2Group', ('ref', 'UnusedGroup255'), '0xfe3b9e', 16),
        ('set', 'InternalRelay3Group', ('ref', 'UnusedGroup255'), '0xfe3ba9', 17),
        ('set', 'InternalRelay4Group', ('ref', 'UnusedGroup255'), '0xfe3bb4', 18),
        ('set', 'InternalRelay5Group', ('ref', 'UnusedGroup255'), '0xfe3bbf', 19),
        ('set', 'DamperZone1OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3bca', 20),
        ('set', 'DamperZone2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3bd5', 21),
        ('set', 'DamperZone3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3be0', 22),
        ('set', 'DamperZone4OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3beb', -1),
    ),
    (  # plant 1
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3bfb', 1),
        ('set', 'CoolStage1OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3c06', 2),
        ('set', 'CoolStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3c11', 3),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3c1c', 4),
        ('set', 'CoolFanLowOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3c27', 5),
        ('set', 'CoolFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3c32', 6),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3c3d', 7),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3c48', 8),
        ('set', 'HeatStage1OutputGroup', ('get', 5, 'W (heat)', 'HeatStage1'), '0xfe3c79', 9),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3c84', 10),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3c8f', 11),
        ('set', 'HeatFanLowOutputGroup', ('get', 3, 'G (heat fan)', 'HeatFanLow'), '0xfe3cc0', 12),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3ccb', 13),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3cd6', 14),
        ('set', 'InternalRelay1Group', ('ref', 'UnusedGroup255'), '0xfe3ce1', 15),
        ('set', 'InternalRelay2Group', ('ref', 'UnusedGroup255'), '0xfe3cec', 16),
        ('set', 'InternalRelay3Group', ('ref', 'HeatFanLow'), '0xfe3cfe', 17),
        ('set', 'InternalRelay4Group', ('ref', 'UnusedGroup255'), '0xfe3d09', 18),
        ('set', 'InternalRelay5Group', ('ref', 'HeatStage1'), '0xfe3d1b', -1),
    ),
    (  # plant 2
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3d2b', 1),
        ('set', 'CoolStage1OutputGroup', ('get', 1, 'pump', 'CoolStage1'), '0xfe3d5c', 2),
        ('set', 'CoolStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3d67', 3),
        ('set', 'CoolStage3OutputGroup', ('get', 2, 'fill', 'CoolStage3'), '0xfe3d98', 4),
        ('set', 'CoolFanLowOutputGroup', ('get', 3, 'cool fan speed 1', 'CoolFanLow'), '0xfe3dc9', 5),
        ('set', 'CoolFanMediumOutputGroup', ('get', 4, 'cool fan speed 2', 'CoolFanMedium'), '0xfe3dfa', 6),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3e05', 7),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3e10', 8),
        ('set', 'HeatStage1OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3e1b', 9),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3e26', 10),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3e31', 11),
        ('set', 'HeatFanLowOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3e3c', 12),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3e47', 13),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3e52', 14),
        ('set', 'InternalRelay1Group', ('ref', 'CoolStage1'), '0xfe3e64', 15),
        ('set', 'InternalRelay2Group', ('ref', 'CoolStage3'), '0xfe3e76', 16),
        ('set', 'InternalRelay3Group', ('ref', 'CoolFanLow'), '0xfe3e88', 17),
        ('set', 'InternalRelay4Group', ('ref', 'CoolFanMedium'), '0xfe3e9a', 18),
        ('set', 'InternalRelay5Group', ('ref', 'UnusedGroup255'), '0xfe3ea5', -1),
    ),
    (  # plant 3
        ('test', 'current-installation-is-nil', '0xfe3ec4', 1, 20),
        ('set', 'CoolActivationOutputGroup', ('get', 2, 'B (cool activation)', 'CoolActivation'), '0xfe4104', 2),
        ('set', 'CoolStage1OutputGroup', ('get', 1, 'Y (heat/cool)', 'CoolStage1'), '0xfe4135', 3),
        ('set', 'CoolStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4140', 4),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe414b', 5),
        ('set', 'CoolFanLowOutputGroup', ('get', 3, 'G (fan)', 'CoolFanLow'), '0xfe417c', 6),
        ('set', 'CoolFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4187', 7),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4192', 8),
        ('set', 'HeatActivationOutputGroup', ('get', 4, 'B (heat activation)', 'HeatActivation'), '0xfe41c3', 9),
        ('set', 'HeatStage1OutputGroup', ('ref', 'CoolStage1'), '0xfe41d5', 10),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe41e0', 11),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe41eb', 12),
        ('set', 'HeatFanLowOutputGroup', ('ref', 'CoolFanLow'), '0xfe41fd', 13),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4208', 14),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4213', 15),
        ('set', 'InternalRelay1Group', ('ref', 'CoolStage1'), '0xfe4225', 16),
        ('set', 'InternalRelay2Group', ('ref', 'CoolActivation'), '0xfe4237', 17),
        ('set', 'InternalRelay3Group', ('ref', 'CoolFanLow'), '0xfe4249', 18),
        ('set', 'InternalRelay4Group', ('ref', 'HeatActivation'), '0xfe425b', 19),
        ('set', 'InternalRelay5Group', ('ref', 'UnusedGroup255'), '0xfe4266', -1),
        ('test', 'installation-name-equals:Zoned 2 Stage Reverse Cycle System', '0xfe3eff', 21, 1),
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3f0b', 22),
        ('set', 'CoolStage1OutputGroup', ('get', 1, 'Y1 (cool/heat)', 'CoolStage1'), '0xfe3f3c', 23),
        ('set', 'CoolStage2OutputGroup', ('get', 2, 'Y2 (cool/heat)', 'CoolStage2'), '0xfe3f6d', 24),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe3f78', 25),
        ('set', 'CoolFanLowOutputGroup', ('get', 3, 'G (fan)', 'CoolFanLow'), '0xfe3fa9', 26),
        ('set', 'CoolFanMediumOutputGroup', ('get', 5, 'Heat/cool fan speed', 'CoolFanMedium'), '0xfe3fda', 27),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe3fe5', 28),
        ('set', 'HeatActivationOutputGroup', ('get', 4, 'B (heat activation)', 'HeatActivation'), '0xfe4016', 29),
        ('set', 'HeatStage1OutputGroup', ('ref', 'CoolStage1'), '0xfe4028', 30),
        ('set', 'HeatStage2OutputGroup', ('ref', 'CoolStage2'), '0xfe403a', 31),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4045', 32),
        ('set', 'HeatFanLowOutputGroup', ('ref', 'CoolFanLow'), '0xfe4057', 33),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'CoolFanMedium'), '0xfe4069', 34),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4074', 35),
        ('set', 'InternalRelay1Group', ('ref', 'CoolStage1'), '0xfe4086', 36),
        ('set', 'InternalRelay2Group', ('ref', 'CoolStage2'), '0xfe4098', 37),
        ('set', 'InternalRelay3Group', ('ref', 'CoolFanLow'), '0xfe40aa', 38),
        ('set', 'InternalRelay4Group', ('ref', 'HeatActivation'), '0xfe40bc', 39),
        ('set', 'InternalRelay5Group', ('ref', 'CoolFanMedium'), '0xfe40ce', -1),
    ),
    (  # plant 4
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4276', 1),
        ('set', 'CoolStage1OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4281', 2),
        ('set', 'CoolStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe428c', 3),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4297', 4),
        ('set', 'CoolFanLowOutputGroup', ('ref', 'UnusedGroup255'), '0xfe42a2', 5),
        ('set', 'CoolFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe42ad', 6),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe42b8', 7),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe42c3', 8),
        ('set', 'HeatStage1OutputGroup', ('get', 1, 'W (heat)', 'HeatStage1'), '0xfe42f4', 9),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe42ff', 10),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe430a', 11),
        ('set', 'HeatFanLowOutputGroup', ('get', 3, 'G (heat fan)', 'HeatFanLow'), '0xfe433b', 12),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4346', 13),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4351', 14),
        ('set', 'InternalRelay1Group', ('ref', 'HeatStage1'), '0xfe4363', 15),
        ('set', 'InternalRelay2Group', ('ref', 'UnusedGroup255'), '0xfe436e', 16),
        ('set', 'InternalRelay3Group', ('ref', 'HeatFanLow'), '0xfe4380', 17),
        ('set', 'InternalRelay4Group', ('ref', 'UnusedGroup255'), '0xfe438b', 18),
        ('set', 'InternalRelay5Group', ('ref', 'UnusedGroup255'), '0xfe4396', -1),
    ),
    (  # plant 5
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe43a6', 1),
        ('set', 'CoolStage1OutputGroup', ('get', 1, 'Y (cool)', 'CoolStage1'), '0xfe43d7', 2),
        ('set', 'CoolStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe43e2', 3),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe43ed', 4),
        ('set', 'CoolFanLowOutputGroup', ('get', 3, 'G (cool fan)', 'CoolFanLow'), '0xfe441e', 5),
        ('set', 'CoolFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4429', 6),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4434', 7),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe443f', 8),
        ('set', 'HeatStage1OutputGroup', ('ref', 'UnusedGroup255'), '0xfe444a', 9),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4455', 10),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4460', 11),
        ('set', 'HeatFanLowOutputGroup', ('ref', 'UnusedGroup255'), '0xfe446b', 12),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4476', 13),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4481', 14),
        ('set', 'InternalRelay1Group', ('ref', 'CoolStage1'), '0xfe4493', 15),
        ('set', 'InternalRelay2Group', ('ref', 'UnusedGroup255'), '0xfe449e', 16),
        ('set', 'InternalRelay3Group', ('ref', 'CoolFanLow'), '0xfe44b0', 17),
        ('set', 'InternalRelay4Group', ('ref', 'UnusedGroup255'), '0xfe44bb', 18),
        ('set', 'InternalRelay5Group', ('ref', 'UnusedGroup255'), '0xfe44c6', -1),
    ),
    (  # plant 6
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe44d6', 1),
        ('set', 'CoolStage1OutputGroup', ('get', 10, 'pump', 'CoolStage1'), '0xfe4507', 2),
        ('set', 'CoolStage2OutputGroup', ('get', 11, 'dump', 'CoolStage2'), '0xfe4538', 3),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4543', 4),
        ('set', 'CoolFanLowOutputGroup', ('get', 12, 'cool fan speed 1', 'CoolFanLow'), '0xfe4574', 5),
        ('set', 'CoolFanMediumOutputGroup', ('get', 13, 'cool fan speed 2', 'CoolFanMedium'), '0xfe45a5', 6),
        ('set', 'CoolFanHighOutputGroup', ('get', 14, 'cool fan speed 3', 'CoolFanHigh'), '0xfe45d6', 7),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe45e1', 8),
        ('set', 'HeatStage1OutputGroup', ('get', 5, 'W (heat)', 'HeatStage1'), '0xfe4612', 9),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe461d', 10),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4628', 11),
        ('set', 'HeatFanLowOutputGroup', ('get', 3, 'G1 (heat fan speed 1)', 'HeatFanLow'), '0xfe4659', 12),
        ('set', 'HeatFanMediumOutputGroup', ('get', 4, 'G2 (heat fan speed 2)', 'HeatFanMedium'), '0xfe468a', 13),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4695', 14),
        ('set', 'InternalRelay1Group', ('ref', 'UnusedGroup255'), '0xfe46a0', 15),
        ('set', 'InternalRelay2Group', ('ref', 'UnusedGroup255'), '0xfe46ab', 16),
        ('set', 'InternalRelay3Group', ('ref', 'HeatFanLow'), '0xfe46bd', 17),
        ('set', 'InternalRelay4Group', ('ref', 'HeatFanMedium'), '0xfe46cf', 18),
        ('set', 'InternalRelay5Group', ('ref', 'HeatStage1'), '0xfe46e1', -1),
    ),
    (  # plant 7
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe46f1', 1),
        ('set', 'CoolStage1OutputGroup', ('get', 1, 'Y (cool)', 'CoolStage1'), '0xfe4722', 2),
        ('set', 'CoolStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe472d', 3),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4738', 4),
        ('set', 'CoolFanLowOutputGroup', ('get', 3, 'G (cool fan)', 'CoolFanLow'), '0xfe476f', 5),
        ('set', 'CoolFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe477a', 6),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4785', 7),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4790', 8),
        ('set', 'HeatStage1OutputGroup', ('get', 5, 'W (heat)', 'HeatStage1'), '0xfe47c7', 9),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe47d2', 10),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe47dd', 11),
        ('set', 'HeatFanLowOutputGroup', ('get', 4, 'G (heat fan)', 'HeatFanLow'), '0xfe4814', 12),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe481f', 13),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe482a', 14),
        ('set', 'InternalRelay1Group', ('ref', 'CoolStage1'), '0xfe483c', 15),
        ('set', 'InternalRelay2Group', ('ref', 'UnusedGroup255'), '0xfe4847', 16),
        ('set', 'InternalRelay3Group', ('ref', 'CoolFanLow'), '0xfe4859', 17),
        ('set', 'InternalRelay4Group', ('ref', 'HeatFanLow'), '0xfe486b', 18),
        ('set', 'InternalRelay5Group', ('ref', 'HeatStage1'), '0xfe487d', -1),
    ),
    (  # plant 8
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe488d', 1),
        ('set', 'CoolStage1OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4898', 2),
        ('set', 'CoolStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe48a3', 3),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe48ae', 4),
        ('set', 'CoolFanLowOutputGroup', ('ref', 'UnusedGroup255'), '0xfe48b9', 5),
        ('set', 'CoolFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe48c4', 6),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe48cf', 7),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe48da', 8),
        ('set', 'HeatStage1OutputGroup', ('get', 5, 'W (heat)', 'HeatStage1'), '0xfe4911', 9),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe491c', 10),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4927', 11),
        ('set', 'HeatFanLowOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4932', 12),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe493d', 13),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4948', 14),
        ('set', 'InternalRelay1Group', ('ref', 'UnusedGroup255'), '0xfe4953', 15),
        ('set', 'InternalRelay2Group', ('ref', 'UnusedGroup255'), '0xfe495e', 16),
        ('set', 'InternalRelay3Group', ('ref', 'UnusedGroup255'), '0xfe4969', 17),
        ('set', 'InternalRelay4Group', ('ref', 'UnusedGroup255'), '0xfe4974', 18),
        ('set', 'InternalRelay5Group', ('ref', 'HeatStage1'), '0xfe4986', 19),
        ('set', 'DamperZone1OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4991', 20),
        ('set', 'DamperZone2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe499c', 21),
        ('set', 'DamperZone3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe49a7', 22),
        ('set', 'DamperZone4OutputGroup', ('ref', 'UnusedGroup255'), '0xfe49b2', -1),
    ),
    (  # plant 9
        ('test', 'current-installation-is-nil', '0xfe49d1', 1, 41),
        ('test', 'current-installation-is-nil', '0xfe4c0f', 2, 21),
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4dd8', 3),
        ('set', 'CoolStage1OutputGroup', ('get', 1, 'Y (cool)', 'CoolStage1'), '0xfe4e0f', 4),
        ('set', 'CoolStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4e1a', 5),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4e25', 6),
        ('set', 'CoolFanLowOutputGroup', ('get', 3, 'G (fan)', 'CoolFanLow'), '0xfe4e5c', 7),
        ('set', 'CoolFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4e67', 8),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4e72', 9),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4e7d', 10),
        ('set', 'HeatStage1OutputGroup', ('get', 5, 'W (heat)', 'HeatStage1'), '0xfe4eb4', 11),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4ebf', 12),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4eca', 13),
        ('set', 'HeatFanLowOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4ed5', 14),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4ee0', 15),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4eeb', 16),
        ('set', 'InternalRelay1Group', ('ref', 'CoolStage1'), '0xfe4efd', 17),
        ('set', 'InternalRelay2Group', ('ref', 'UnusedGroup255'), '0xfe4f08', 18),
        ('set', 'InternalRelay3Group', ('ref', 'CoolFanLow'), '0xfe4f1a', 19),
        ('set', 'InternalRelay4Group', ('ref', 'UnusedGroup255'), '0xfe4f25', 20),
        ('set', 'InternalRelay5Group', ('ref', 'HeatStage1'), '0xfe4f37', -1),
        ('test', 'installation-name-equals:Conventional Single Stage Heat/Cool USA System', '0xfe4c56', 22, 2),
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4c62', 23),
        ('set', 'CoolStage1OutputGroup', ('get', 1, 'Y (cool)', 'CoolStage1'), '0xfe4c99', 24),
        ('set', 'CoolStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4ca4', 25),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4caf', 26),
        ('set', 'CoolFanLowOutputGroup', ('get', 3, 'G (fan)', 'CoolFanLow'), '0xfe4ce6', 27),
        ('set', 'CoolFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4cf1', 28),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4cfc', 29),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4d07', 30),
        ('set', 'HeatStage1OutputGroup', ('get', 5, 'W (heat)', 'HeatStage1'), '0xfe4d3e', 31),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4d49', 32),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4d54', 33),
        ('set', 'HeatFanLowOutputGroup', ('ref', 'CoolFanLow'), '0xfe4d66', 34),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4d71', 35),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4d7c', 36),
        ('set', 'InternalRelay1Group', ('ref', 'CoolStage1'), '0xfe4d8e', 37),
        ('set', 'InternalRelay2Group', ('ref', 'UnusedGroup255'), '0xfe4d99', 38),
        ('set', 'InternalRelay3Group', ('ref', 'CoolFanLow'), '0xfe4dab', 39),
        ('set', 'InternalRelay4Group', ('ref', 'UnusedGroup255'), '0xfe4db6', 40),
        ('set', 'InternalRelay5Group', ('ref', 'HeatStage1'), '0xfe4dc8', -1),
        ('test', 'installation-name-equals:Conventional 2 Stage Heat/Cool USA System', '0xfe4a18', 42, 1),
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4a24', 43),
        ('set', 'CoolStage1OutputGroup', ('get', 1, 'Y (cool)', 'CoolStage1'), '0xfe4a5b', 44),
        ('set', 'CoolStage2OutputGroup', ('get', 2, 'Y2 (cool)', 'CoolStage2'), '0xfe4a92', 45),
        ('set', 'CoolStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4a9d', 46),
        ('set', 'CoolFanLowOutputGroup', ('get', 3, 'G (fan)', 'CoolFanLow'), '0xfe4ad4', 47),
        ('set', 'CoolFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4adf', 48),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4aea', 49),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4af5', 50),
        ('set', 'HeatStage1OutputGroup', ('get', 4, 'W (heat)', 'HeatStage1'), '0xfe4b2c', 51),
        ('set', 'HeatStage2OutputGroup', ('get', 5, 'W2 (heat)', 'CoolStage2'), '0xfe4b63', 52),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4b6e', 53),
        ('set', 'HeatFanLowOutputGroup', ('ref', 'CoolFanLow'), '0xfe4b80', 54),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4b8b', 55),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4b96', 56),
        ('set', 'InternalRelay1Group', ('ref', 'CoolStage1'), '0xfe4ba8', 57),
        ('set', 'InternalRelay2Group', ('ref', 'CoolStage2'), '0xfe4bba', 58),
        ('set', 'InternalRelay3Group', ('ref', 'CoolFanLow'), '0xfe4bcc', 59),
        ('set', 'InternalRelay4Group', ('ref', 'HeatStage1'), '0xfe4bde', 60),
        ('set', 'InternalRelay5Group', ('ref', 'HeatStage2'), '0xfe4bf0', -1),
    ),
    (  # plant 10
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe4f47', 1),
        ('set', 'CoolStage1OutputGroup', ('get', 1, 'pump', 'CoolStage1'), '0xfe4f7e', 2),
        ('set', 'CoolStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe4f89', 3),
        ('set', 'CoolStage3OutputGroup', ('get', 2, 'fill', 'CoolStage3'), '0xfe4fc0', 4),
        ('set', 'CoolFanLowOutputGroup', ('get', 3, 'cool fan speed 1', 'CoolFanLow'), '0xfe4ff7', 5),
        ('set', 'CoolFanMediumOutputGroup', ('get', 4, 'cool fan speed 2', 'CoolFanMedium'), '0xfe502e', 6),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe5039', 7),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe5044', 8),
        ('set', 'HeatStage1OutputGroup', ('get', 5, 'W (heat)', 'HeatStage1'), '0xfe507b', 9),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe5086', 10),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe5091', 11),
        ('set', 'HeatFanLowOutputGroup', ('ref', 'UnusedGroup255'), '0xfe509c', 12),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe50a7', 13),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe50b2', 14),
        ('set', 'InternalRelay1Group', ('ref', 'CoolStage1'), '0xfe50c4', 15),
        ('set', 'InternalRelay2Group', ('ref', 'CoolStage3'), '0xfe50d6', 16),
        ('set', 'InternalRelay3Group', ('ref', 'CoolFanLow'), '0xfe50e8', 17),
        ('set', 'InternalRelay4Group', ('ref', 'CoolFanMedium'), '0xfe50fa', 18),
        ('set', 'InternalRelay5Group', ('ref', 'HeatStage1'), '0xfe510c', -1),
    ),
    (  # plant 11
        ('set', 'CoolActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe511c', 1),
        ('set', 'CoolStage1OutputGroup', ('get', 1, 'Y (cool)', 'CoolStage1'), '0xfe5153', 2),
        ('set', 'CoolStage2OutputGroup', ('get', 2, 'Open', 'CoolStage2'), '0xfe518a', 3),
        ('set', 'CoolStage3OutputGroup', ('get', 5, 'Close', 'CoolStage3'), '0xfe51c1', 4),
        ('set', 'CoolFanLowOutputGroup', ('get', 3, 'G1 (fan speed 1)', 'CoolFanLow'), '0xfe51f8', 5),
        ('set', 'CoolFanMediumOutputGroup', ('get', 4, 'G2 (fan speed 2)', 'CoolFanMedium'), '0xfe522f', 6),
        ('set', 'CoolFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe523a', 7),
        ('set', 'HeatActivationOutputGroup', ('ref', 'UnusedGroup255'), '0xfe5245', 8),
        ('set', 'HeatStage1OutputGroup', ('ref', 'UnusedGroup255'), '0xfe5250', 9),
        ('set', 'HeatStage2OutputGroup', ('ref', 'UnusedGroup255'), '0xfe525b', 10),
        ('set', 'HeatStage3OutputGroup', ('ref', 'UnusedGroup255'), '0xfe5266', 11),
        ('set', 'HeatFanLowOutputGroup', ('ref', 'UnusedGroup255'), '0xfe5271', 12),
        ('set', 'HeatFanMediumOutputGroup', ('ref', 'UnusedGroup255'), '0xfe527c', 13),
        ('set', 'HeatFanHighOutputGroup', ('ref', 'UnusedGroup255'), '0xfe5287', 14),
        ('set', 'InternalRelay1Group', ('ref', 'CoolStage1'), '0xfe5299', 15),
        ('set', 'InternalRelay2Group', ('ref', 'CoolStage2'), '0xfe52ab', 16),
        ('set', 'InternalRelay3Group', ('ref', 'CoolFanLow'), '0xfe52bd', 17),
        ('set', 'InternalRelay4Group', ('ref', 'CoolFanMedium'), '0xfe52cf', 18),
        ('set', 'InternalRelay5Group', ('ref', 'CoolStage3'), '0xfe52e1', -1),
    ),
)

_FAN = (
    (  # plant 0
        ('set', 'CoolingPlantFanEnable', ('scalar', 0), '0xfe5a0d', 1),
        ('set', 'HeatingPlantFanEnable', ('scalar', 0), '0xfe5a17', -1),
    ),
    (  # plant 1
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 0), '0xfe5a26', 1),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 1), '0xfe5a33', 2),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5a40', 3),
        ('set', 'CoolingPlantFanEnable', ('scalar', 0), '0xfe5a4a', 4),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5a54', 5),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 1), '0xfe5a61', 6),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5a6e', 7),
        ('set', 'HeatingPlantFanEnable', ('scalar', 1), '0xfe5a78', -1),
    ),
    (  # plant 2
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5a87', 1),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 2), '0xfe5a94', 2),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5aa1', 3),
        ('set', 'CoolingPlantFanEnable', ('scalar', 1), '0xfe5aab', 4),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 0), '0xfe5ab5', 5),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 2), '0xfe5ac2', 6),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5acf', 7),
        ('set', 'HeatingPlantFanEnable', ('scalar', 0), '0xfe5ad9', -1),
    ),
    (  # plant 3
        ('test', 'current-installation-is-nil', '0xfe5af8', 1, 9),
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 0), '0xfe5b9b', 2),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 1), '0xfe5ba8', 3),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5bb5', 4),
        ('set', 'CoolingPlantFanEnable', ('scalar', 1), '0xfe5bbf', 5),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 0), '0xfe5bc9', 6),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 1), '0xfe5bd6', 7),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5be3', 8),
        ('set', 'HeatingPlantFanEnable', ('scalar', 1), '0xfe5bed', -1),
        ('test', 'installation-name-equals:Zoned 2 Stage Reverse Cycle System', '0xfe5b33', 10, 1),
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5b3a', 11),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 2), '0xfe5b47', 12),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5b54', 13),
        ('set', 'CoolingPlantFanEnable', ('scalar', 1), '0xfe5b5e', 14),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5b68', 15),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 2), '0xfe5b75', 16),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5b82', 17),
        ('set', 'HeatingPlantFanEnable', ('scalar', 1), '0xfe5b8c', -1),
    ),
    (  # plant 4
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 0), '0xfe5bfc', 1),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 1), '0xfe5c09', 2),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5c16', 3),
        ('set', 'CoolingPlantFanEnable', ('scalar', 0), '0xfe5c20', 4),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5c2a', 5),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 1), '0xfe5c37', 6),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5c44', 7),
        ('set', 'HeatingPlantFanEnable', ('scalar', 1), '0xfe5c4e', -1),
    ),
    (  # plant 5
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5c5d', 1),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 1), '0xfe5c6a', 2),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5c77', 3),
        ('set', 'CoolingPlantFanEnable', ('scalar', 1), '0xfe5c81', 4),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 0), '0xfe5c8b', 5),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 1), '0xfe5c98', 6),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5ca5', 7),
        ('set', 'HeatingPlantFanEnable', ('scalar', 0), '0xfe5caf', -1),
    ),
    (  # plant 6
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5cbe', 1),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 3), '0xfe5ccb', 2),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5cd8', 3),
        ('set', 'CoolingPlantFanEnable', ('scalar', 1), '0xfe5ce2', 4),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5cec', 5),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 2), '0xfe5cf9', 6),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5d06', 7),
        ('set', 'HeatingPlantFanEnable', ('scalar', 1), '0xfe5d10', -1),
    ),
    (  # plant 7
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5d1f', 1),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 1), '0xfe5d2c', 2),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5d39', 3),
        ('set', 'CoolingPlantFanEnable', ('scalar', 1), '0xfe5d43', 4),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5d4d', 5),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 1), '0xfe5d5a', 6),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5d67', 7),
        ('set', 'HeatingPlantFanEnable', ('scalar', 1), '0xfe5d71', -1),
    ),
    (  # plant 8
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 0), '0xfe5d80', 1),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 1), '0xfe5d8d', 2),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5d9a', 3),
        ('set', 'CoolingPlantFanEnable', ('scalar', 0), '0xfe5da4', 4),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 0), '0xfe5dae', 5),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 1), '0xfe5dbb', 6),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5dc8', 7),
        ('set', 'HeatingPlantFanEnable', ('scalar', 1), '0xfe5dd2', -1),
    ),
    (  # plant 9
        ('test', 'current-installation-is-nil', '0xfe5df1', 1, 9),
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5ecb', 2),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 1), '0xfe5ed8', 3),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5ee5', 4),
        ('set', 'CoolingPlantFanEnable', ('scalar', 1), '0xfe5eef', 5),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 0), '0xfe5ef9', 6),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 1), '0xfe5f06', 7),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5f13', 8),
        ('set', 'HeatingPlantFanEnable', ('scalar', 0), '0xfe5f1d', -1),
        ('test', 'installation-name-equals:Conventional 2 Stage Heat/Cool USA System', '0xfe5e2c', 10, 18),
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5e6a', 11),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 1), '0xfe5e77', 12),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5e84', 13),
        ('set', 'CoolingPlantFanEnable', ('scalar', 1), '0xfe5e8e', 14),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5e98', 15),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 1), '0xfe5ea5', 16),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5eb2', 17),
        ('set', 'HeatingPlantFanEnable', ('scalar', 1), '0xfe5ebc', -1),
        ('test', 'installation-name-equals:Conventional Single Stage Heat/Cool USA System', '0xfe5e63', 10, 1),
    ),
    (  # plant 10
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5f2c', 1),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 2), '0xfe5f39', 2),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5f46', 3),
        ('set', 'CoolingPlantFanEnable', ('scalar', 1), '0xfe5f50', 4),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 0), '0xfe5f5a', 5),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 2), '0xfe5f67', 6),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5f74', 7),
        ('set', 'HeatingPlantFanEnable', ('scalar', 0), '0xfe5f7e', -1),
    ),
    (  # plant 11
        ('set', 'CoolingPlantFanSpeedControlEnable', ('scalar', 1), '0xfe5f8a', 1),
        ('set', 'CoolingPlantFanSpeeds', ('scalar', 2), '0xfe5f97', 2),
        ('set', 'CoolingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5fa4', 3),
        ('set', 'CoolingPlantFanEnable', ('scalar', 1), '0xfe5fae', 4),
        ('set', 'HeatingPlantFanSpeedControlEnable', ('scalar', 0), '0xfe5fb8', 5),
        ('set', 'HeatingPlantFanSpeeds', ('scalar', 2), '0xfe5fc5', 6),
        ('set', 'HeatingPlantFanDefaultSpeed', ('scalar', 1), '0xfe5fd2', 7),
        ('set', 'HeatingPlantFanEnable', ('scalar', 0), '0xfe5fdc', -1),
    ),
)

class PlantTypeModel:
    """Direct projection with retained references and actual owner callbacks.

    The settled manager uses explicit address ordering (255 first), and new
    objects insert in that order even while source Begin suppresses publication.
    Incoming XML order, pending address edits and locale-sensitive TagName
    ordering are not substituted for this profile. Hooks run only on a changed
    attribute, after updating the working PP and reference state.
    """

    def __init__(self, values, references, resolver, *, zone_group,
                 current_installation, plant_type=None, group_sort='address-ascending',
                 reference_assigned=None, scalar_assigned=None):
        if not isinstance(values, MutableMapping) or not isinstance(references, MutableMapping):
            raise ThermostatTemplateError('Plant types require shared mutable owner values and references')
        if type(resolver) is not _GraphResolver:
            raise ThermostatTemplateError('Plant types require the shared graph resolver')
        if group_sort != 'address-ascending':
            raise ThermostatTemplateError('Plant types require explicit address-ascending manager order')
        if set(references) != set(OUTPUTS + DAMPERS + RELAYS):
            raise ThermostatTemplateError('Plant types require all retained output, damper and relay references')
        for callback in (zone_group, current_installation):
            if not callable(callback):
                raise ThermostatTemplateError('Plant types require live zone and installation getters')
        for callback in (plant_type, reference_assigned, scalar_assigned):
            if callback is not None and not callable(callback):
                raise ThermostatTemplateError('Plant observer and manager getters must be callable')
        self.values, self.references, self.resolver = values, references, resolver
        self.zone_group, self.current_installation = zone_group, current_installation
        self.plant_type = plant_type or (lambda: virtual_plant_type(self.values))
        self.reference_assigned, self.scalar_assigned = reference_assigned, scalar_assigned
        self._attributes = {role: object() for role in OUTPUTS + DAMPERS}
        self.journal = []
        self._application()
        for group in references.values():
            self._live(group)

    def _application(self):
        app = self.values.get('ApplicationNumber')
        if type(app) is not int or not (48 <= app <= 95 or app == 203) or app not in self.resolver.apps:
            raise ThermostatTemplateError('Plant types require the retained selected output application')
        return app

    def _live(self, group):
        if group is None:
            return None
        if type(group) is not RemoteGroup or group.application != self._application():
            raise ThermostatTemplateError('Plant reference is not a Group of the selected application')
        try:
            current = self.resolver.current(group)
        except KeyError as error:
            raise ThermostatTemplateError('Plant Group no longer belongs to the shared resolver') from error
        if current.identity != group.identity:
            raise ThermostatTemplateError('Plant Group identity changed inside the shared resolver')
        return current

    def _prefix(self):
        zone = self.zone_group()
        if type(zone) is not RemoteGroup or zone.application != 172:
            raise ThermostatTemplateError('Plant prefix requires the live communication Group')
        try:
            current = self.resolver.current(zone)
        except KeyError as error:
            raise ThermostatTemplateError('Plant communication Group is stale') from error
        if current.identity != zone.identity:
            raise ThermostatTemplateError('Plant communication Group identity changed')
        return '[CG' + format(current.address, '02d') + ']'

    def _name(self, label):
        if type(label) is not str:
            raise ThermostatTemplateError('Plant generated label must be text')
        return self._prefix() + ' ' + label

    def _manager(self):
        app = self._application()
        inventory = [group for (a, _), group in self.resolver.live.items() if a == app]
        return sorted(inventory, key=lambda group: (group.address != 255, group.address))

    def attribute(self, role):
        """Exact per-owner attribute token; a foreign token excludes no role."""
        if role not in self._attributes:
            raise ThermostatTemplateError('Unknown plant usage attribute')
        return self._attributes[role]

    def group_used_excluding_attribute(self, group, excluded_attribute):
        group = self._live(group)
        if group is None:
            return False
        for role in OUTPUTS + DAMPERS:
            if self._attributes[role] is excluded_attribute:
                continue
            other = self._live(self.references[role])
            if other is not None and other.identity == group.identity:
                return True
        return False

    def _find(self, label):
        name = self._name(label)
        rows = self._manager()
        for group in rows:
            if _upper(group.name) == _upper(name):
                self.journal.append({'call': 'FindExistingGroup', 'name': name,
                    'identity': group.identity})
                return group
        self.journal.append({'call': 'FindExistingGroup', 'name': name, 'identity': None})
        return None

    def _create(self, address, label, reason):
        name = self._name(label)
        group = self.resolver.create(self._application(), address, name, 'plant_types:' + reason)
        self.journal.append({'call': 'CreateGroup', 'address': address, 'name': name,
            'identity': group.identity, 'assignments': ['Address', 'TagName', 'manager.AddObject'],
            'storage_intent': 'GroupSave', 'native_issued_oid': False})
        return group

    def _rename(self, group, label, *, fallback=False):
        group = self._live(group)
        name = self._name(label)
        current = self.resolver.rename(group, name, 'plant_types:GetGroup')
        # The source method requests StorageSave even if TagName saw equality;
        # the resolver adds no redundant native mutation for that intent.
        self.journal.append({'call': 'ChangeTagName', 'identity': current.identity,
            'previous_name': group.name, 'name': name, 'same_name': group.name == name,
            'explicit_fallback': fallback, 'storage_intent': 'empty change list'})
        return current

    def get_new_group(self, label):
        """Source allocator: backwards prefixed anchors, then lowest free0..254."""
        found = self._find(label)
        if found is not None:
            return found
        for anchor in reversed(self._manager()):
            if not anchor.name.startswith(self._prefix()):
                continue
            for address in range(anchor.address + 1, 255):
                if (self._application(), address) not in self.resolver.live:
                    return self._create(address, label, 'backward-prefixed-anchor')
        for address in range(255):
            if (self._application(), address) not in self.resolver.live:
                return self._create(address, label, 'lowest-free-fallback')
        return None

    def get_group(self, requested, label, excluded_attribute):
        """Resolve, reuse or allocate without transferring any Level children."""
        if type(requested) is not int or not 0 <= requested <= 255:
            raise ThermostatTemplateError('Requested plant Group address must be an integer byte')
        found = self._find(label)
        if found is not None:
            return found
        group = self.resolver.group(self._application(), requested, False,
            'plant_types:GetGroup', enable_application=False)
        if group is None:
            return self._create(requested, label, 'missing-requested-address')
        if group.name.startswith(self._prefix()) and not self.group_used_excluding_attribute(group, excluded_attribute):
            if _upper(group.name) != _upper(self._name(label)):
                return self._rename(group, label)
            return group
        group = self.get_new_group(label)
        if group is None:
            self.journal.append({'call': 'GetGroup', 'exception': 'ECannotCreateGroupApplicationIsFull'})
            raise PlantGroupCapacityError('Cannot create plant Group: selected application is full')
        return self._rename(group, label, fallback=True)

    def _assign(self, prop, value, at, unused):
        kind = value[0]
        if kind == 'scalar':
            new = value[1]
            old = self.values.get(prop)
            self.values[prop] = new
            changed = old != new
            self.journal.append({'call': 'assign', 'property': prop, 'before': old,
                'after': new, 'changed': changed, 'source_at': at})
            if changed and self.scalar_assigned is not None:
                self.scalar_assigned(prop, old, new)
            return
        if kind == 'get':
            group = self.get_group(value[1], value[2], self.attribute(value[3]))
        else:
            group = unused if value[1] == 'UnusedGroup255' else self._live(self.references[value[1]])
        if prop.endswith('OutputGroup'):
            role = prop[:-11]
        elif prop.startswith('InternalRelay') and prop.endswith('Group'):
            role = prop[:-5]
        else:
            raise ThermostatTemplateError('Unknown source plant reference setter')
        old = self._live(self.references[role])
        self.references[role] = group
        self.values[pp_name(role)] = 255 if group is None else group.address
        changed = (old.identity if old else None) != (group.identity if group else None)
        self.journal.append({'call': 'assign', 'property': prop,
            'before_identity': old.identity if old else None,
            'after_identity': group.identity if group else None, 'changed': changed, 'source_at': at})
        if changed and self.reference_assigned is not None:
            self.reference_assigned(role, old, group)

    def _walk(self, program, unused):
        index = 0
        while index >= 0:
            node = program[index]
            if node[0] == 'set':
                _, prop, value, at, index = node
                self._assign(prop, value, at, unused)
            else:
                _, predicate, at, yes, no = node
                installation = self.current_installation()
                if installation is not None and type(installation) is not str:
                    raise ThermostatTemplateError('Live installation getter must return its source name or nil')
                if predicate == 'current-installation-is-nil':
                    result = installation is None
                else:
                    if installation is None:
                        raise ThermostatTemplateError('Source installation name read encountered nil after a nonnil probe')
                    result = installation == predicate.split(':', 1)[1]
                self.journal.append({'call': 'installation probe', 'predicate': predicate,
                    'name': installation, 'result': result, 'source_at': at})
                index = yes if result else no

    def _type(self):
        value = self.plant_type()
        if type(value) is not int or not 0 <= value <= 255:
            raise ThermostatTemplateError('Live plant type must be an integer byte')
        return value

    def update_parameters(self):
        """Direct twelve-way assignments, then a separate live fan-type read."""
        unused = self.resolver.group(self._application(), 255, True,
            'plant_types:GetUnusedGroup', enable_application=False)
        value = self._type() & 0x7f
        self.journal.append({'call': 'UpdateParametersForPlantType', 'plant_type': value})
        if value < 12:
            self._walk(_PARAMETERS[value], unused)
        self.update_fan_speeds()
        return self.as_dict()

    def update_fan_speeds(self):
        """Source fan scalar setters; no parameter/reference replay."""
        value = self._type() & 0x7f
        self.journal.append({'call': 'UpdateFanSpeedsForPlantType', 'plant_type': value})
        if value < 12:
            self._walk(_FAN[value], None)
        return self.as_dict()

    def as_dict(self):
        return {'format': 'cbus-thermostat-direct-plant-types-v1',
            'references': {role: None if (group := self._live(self.references[role])) is None
                else group.as_dict() for role in OUTPUTS + DAMPERS + RELAYS},
            'journal': deepcopy(self.journal), 'full_quick_zone_lifecycle': False,
            'automatic_host_callbacks_established': False, 'save_executed': False}
