"""Pin the four refused tweaker directions from issue #43.

Three KEYM6 targets have no recovered static Toolkit unit factory/model;
RELDN4->RELDN8 would read eight elements from four-element source logic
fields. All four must refuse before any I/O on every public entry path
(admitted, plan_writes, constructor) with the exact receipt reason.
Admitting any of them requires original-factory evidence (KEYM6) or an
evidence-backed padding rule for the out-of-bounds read (RELDN4).
"""
import unittest

from cbus_toolkit import toolkit_conversion_dlt as dlt
from cbus_toolkit import toolkit_conversion_tweakers as tweakers


REFUSED = (
    ('KEYM6', 'KEYDL4', 'TTweakerDLT', dlt.MISSING_FACTORY),
    ('KEYM6', 'KEYML5', 'TTweakerDLT', dlt.MISSING_FACTORY),
    ('KEYM6', 'KEYBL5', 'TTweakerDLT', dlt.MISSING_FACTORY),
    ('RELDN4', 'RELDN8', 'TTweakerRELDNX_TO_8', tweakers.PAIR_REFUSALS[('RELDN4', 'RELDN8')]),
)


class NoIO:
    def command(self, *_args, **_kwargs):
        raise AssertionError('refusal must happen before any C-Gate I/O')

    command_document = command


class RefusedPairsTests(unittest.TestCase):
    def test_registry_registers_but_pair_refusals_block_all_four(self):
        self.assertEqual(len(tweakers.PAIR_REFUSALS), 4)
        for source, target, tweaker, _reason in REFUSED:
            with self.subTest(pair=(source, target)):
                self.assertEqual(tweakers.lookup(source, target), tweaker)
                self.assertIn((source, target), tweakers.PAIR_REFUSALS)

    def test_admitted_refuses_all_four_with_exact_receipt_reason(self):
        for source, target, tweaker, reason in REFUSED:
            with self.subTest(pair=(source, target)):
                with self.assertRaises(tweakers.TweakerRefused) as caught:
                    tweakers.admitted(source.lower(), target.lower())
                self.assertEqual(caught.exception.tweaker_class, tweaker)
                self.assertEqual(caught.exception.reason, reason)

    def test_plan_writes_refuses_all_four_before_io(self):
        source_values = {'GroupAddress': '0 ' * 16, 'LogicGA13Associations': '1 0 1 0'}
        for source, target, _tweaker, reason in REFUSED:
            with self.subTest(pair=(source, target)):
                with self.assertRaises(tweakers.TweakerRefused) as caught:
                    tweakers.plan_writes(source, target, dict(source_values), set(source_values))
                self.assertEqual(caught.exception.reason, reason)

    def test_constructor_refuses_all_four_before_io(self):
        for source, target, _tweaker, reason in REFUSED:
            with self.subTest(pair=(source, target)):
                with self.assertRaises(tweakers.TweakerRefused) as caught:
                    tweakers.ToolkitTweakerConversion(NoIO(), source, None, target, None)
                self.assertEqual(caught.exception.reason, reason)

    def test_keym6_reason_names_missing_factory_and_reldn4_names_short_array(self):
        self.assertIn('factory/model', tweakers.PAIR_REFUSALS[('KEYM6', 'KEYDL4')])
        self.assertIn('four elements', tweakers.PAIR_REFUSALS[('RELDN4', 'RELDN8')])


if __name__ == '__main__':
    unittest.main()
