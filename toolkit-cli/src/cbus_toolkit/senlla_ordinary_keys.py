"""SENLLA ordinary eight-key load and fresh recall-hook projection.

This component receives already loaded primary-group objects. Their identity,
including None, is significant; an owning unit loader must establish them.
It preserves custom raw nibbles while applying the source's locked template
defaults, followed by the fresh form's ascending-key recall conflict hooks.
Scene keys and the rest of the unit/form/save pipeline are separate stages.
"""
from dataclasses import dataclass
import json
from pathlib import Path

from .sensors import SensorError


STAGES = ('JPCommand', 'SRCommand', 'LPCommand', 'LRCommand')
_ROWS = json.loads(Path(__file__).with_name('senlla_ordinary_key_matches.json').read_text())['first_matches']
_MATCHES = {tuple(row['stages']): row['function_type'] for row in _ROWS}
_SURVIVING = frozenset((*range(14), 16, 21, 34))
_CATEGORIES = (frozenset((17,)), frozenset((18, 19)), frozenset((20, 21, 22)))


def _array(value, count, maximum, label):
    if (not isinstance(value, (list, tuple)) or len(value) != count
            or any(type(item) is not int or not 0 <= item <= maximum for item in value)):
        raise SensorError(f'{label} requires exactly {count} integers in 0..{maximum}')
    return tuple(value)


def primary_block_index(mask):
    """The native reference list loads block bits in ascending order."""
    mask, = _array((mask,), 1, 255, 'Block allocation')
    return (mask & -mask).bit_length() - 1 if mask else None


def loaded_template(stages, *, store1=None, store2=None):
    """Resolve a four-nibble key through the SENPILL override and subset."""
    stages = _array(stages, 4, 15, 'Ordinary key stages')
    for level in (store1, store2):
        if level is not None:
            _array((level,), 1, 255, 'Stored level')
    function = _MATCHES.get(stages, 26)
    if function == 14:
        return {249: 17, 252: 18, 255: 20}.get(store1, 26)
    if function == 15:
        return {2: 19, 5: 22}.get(store2, 26)
    return function if function in _SURVIVING else 26


@dataclass(frozen=True)
class OrdinaryKeys:
    stages: tuple
    templates: tuple
    block_masks: tuple
    timer_seconds: tuple
    expiry_commands: tuple
    timer_defaults: tuple
    recall_resets: tuple

    def parameters(self):
        """Return detached PP arrays for this component's write projection."""
        return {
            **{name: [row[index] for row in self.stages] for index, name in enumerate(STAGES)},
            'BlockAllocation': list(self.block_masks), 'SceneKeySelector': [0] * 8,
            'TimerHighByte': [seconds >> 8 for seconds in self.timer_seconds],
            'TimerLowByte': [seconds & 255 for seconds in self.timer_seconds],
            'TimerExpiryCommand': list(self.expiry_commands),
        }


def load_ordinary_keys(stages, block_masks, store1, store2, timer_seconds, expiry_commands, *,
                       primary_groups, block_references=None):
    """Project eight ordinary keys; no group lookup, form, session or I/O runs.

    ``primary_groups`` contains the exact eight source-loaded references.
    Multi-block and zero-block keys have None; singleton references must be
    supplied by the owning group loader, including its unused-group object.
    ``block_references`` optionally supplies the owning loader's ordered rows
    after allocation transfers; omitting it uses direct raw ascending order.
    """
    if not isinstance(stages, (list, tuple)) or len(stages) != 8:
        raise SensorError('Ordinary key stages require exactly eight rows')
    raw = tuple(_array(row, 4, 15, 'Ordinary key stages') for row in stages)
    masks = _array(block_masks, 8, 255, 'Block allocation')
    if block_references is None:
        references = tuple(tuple(index for index in range(8) if mask & (1 << index)) for mask in masks)
    else:
        if not isinstance(block_references, (list, tuple)) or len(block_references) != 8:
            raise SensorError('Block references require exactly eight ordered rows')
        references = tuple(_array(row, mask.bit_count(), 7, 'Ordered block references')
                           for row, mask in zip(block_references, masks))
        if any(len(set(row)) != len(row) or sum(1 << index for index in row) != mask
               for row, mask in zip(references, masks)):
            raise SensorError('Ordered block references must match their allocation mask without duplicates')
    first = _array(store1, 8, 255, 'LightLevelStore1')
    second = _array(store2, 8, 255, 'LightLevelStore2')
    timers = list(_array(timer_seconds, 8, 65535, 'Block timers'))
    expiry = list(_array(expiry_commands, 8, 15, 'Timer expiry commands'))
    if not isinstance(primary_groups, (list, tuple)) or len(primary_groups) != 8:
        raise SensorError('Primary groups require exactly eight loaded references')
    groups = tuple(primary_groups)
    if any(mask.bit_count() != 1 and group is not None for mask, group in zip(masks, groups)):
        raise SensorError('Zero-block and multi-block keys require a nil primary group')
    if any(mask.bit_count() == 1 and group is None for mask, group in zip(masks, groups)):
        raise SensorError('Singleton keys require their loaded primary group object')
    templates, defaults = [], []
    for key, (row, blocks) in enumerate(zip(raw, references)):
        block = blocks[0] if blocks else None
        function = loaded_template(row, store1=first[block] if block is not None else None,
                                   store2=second[block] if block is not None else None)
        templates.append(function)
        # The native callback executes under MacroFunctionPin. Loading the
        # template can default block timing without replacing the raw stages.
        if function in (6, 34) and block is not None:
            if timers[block] == 0:
                timers[block] = 300
                defaults.append((key, block, 'timer', 300))
            if expiry[block] == 0:
                expiry[block] = 15
                defaults.append((key, block, 'expiry', 15))
    final, resets = list(raw), []
    # SetupFlashHooks activates a general and a function-template hook for
    # each key in ascending order. A reset to16 does not belong to a recall
    # category, so its nested notifications cannot reset another sibling.
    for key in range(8):
        category = next((values for values in _CATEGORIES if templates[key] in values), None)
        if category is None:
            continue
        for sibling in range(8):
            other = templates[sibling]
            if (sibling != key and groups[sibling] is groups[key]
                    and other in (17, 18, 19, 20, 21, 22) and other not in category):
                templates[sibling] = 16
                final[sibling] = (0, 0, 0, 0)
                resets.append((key, sibling, other, 16))
    return OrdinaryKeys(tuple(final), tuple(templates), masks, tuple(timers), tuple(expiry),
                        tuple(defaults), tuple(resets))
