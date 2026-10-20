"""P5.06 wave-12 narrow offline pin for #43 (PAIR_REFUSALS narrowness).

Pins only the ``PAIR_REFUSALS`` boundary in
``toolkit_conversion_tweakers``: exactly four refused pairs, sibling pairs
under the same tweaker classes stay admitted, the refusal receipt message
format is exact, and unregistered pairs use the distinct NO_TWEAKER reason.
Pure-offline: no spec fixture, PP session, hardware, C-Gate server, or I/O.
#43 stays OPEN; KEYM6 factory evidence and the RELDN4 padding rule remain
future work.
"""
from __future__ import annotations

import unittest

from cbus_toolkit import toolkit_conversion_tweakers as tweakers


class PairRefusalsNarrownessWave12Tests(unittest.TestCase):
    def test_pair_refusals_exactly_four_and_immutable(self):
        self.assertEqual(set(tweakers.PAIR_REFUSALS), {
            ('KEYM6', 'KEYDL4'), ('KEYM6', 'KEYML5'),
            ('KEYM6', 'KEYBL5'), ('RELDN4', 'RELDN8'),
        })
        with self.assertRaises(TypeError):
            tweakers.PAIR_REFUSALS[('KEYM6', 'KEYDL4')] = 'x'

    def test_sibling_pairs_under_same_tweakers_stay_admitted(self):
        # Narrowness: the refusal is per-pair, not per-class (REFUSALS is None).
        self.assertEqual(tweakers.admitted('KEYM2', 'KEYDL4'), 'TTweakerDLT')
        self.assertEqual(
            tweakers.admitted('RELDN8', 'RELDN12'), 'TTweakerRELDN8_TO_X')
        self.assertIsNone(tweakers.REFUSALS['TTweakerDLT'])
        self.assertIsNone(tweakers.REFUSALS['TTweakerRELDNX_TO_8'])

    def test_refusal_receipt_message_format_exact(self):
        for source, target in (('KEYM6', 'KEYBL5'), ('RELDN4', 'RELDN8')):
            with self.subTest(pair=(source, target)):
                reason = tweakers.PAIR_REFUSALS[(source, target)]
                with self.assertRaises(tweakers.TweakerRefused) as caught:
                    tweakers.admitted(source, target)
                self.assertEqual(
                    str(caught.exception),
                    f"Toolkit conversion {source} -> {target} is refused: {reason}")

    def test_unregistered_pair_uses_distinct_no_tweaker_reason(self):
        # Contrast: unknown pairs refuse with NO_TWEAKER, never a pair reason.
        self.assertIsNone(tweakers.lookup('DIMDN4', 'RELDN8'))
        with self.assertRaises(tweakers.TweakerRefused) as caught:
            tweakers.admitted('DIMDN4', 'RELDN8')
        self.assertIsNone(caught.exception.tweaker_class)
        self.assertEqual(caught.exception.reason, tweakers.NO_TWEAKER)
        for pair_reason in tweakers.PAIR_REFUSALS.values():
            self.assertNotEqual(caught.exception.reason, pair_reason)
        # Refusals are case-insensitive on lookup/admission.
        with self.assertRaises(tweakers.TweakerRefused) as lower:
            tweakers.admitted('keym6', 'keydl4')
        self.assertEqual(
            lower.exception.reason, tweakers.PAIR_REFUSALS[('KEYM6', 'KEYDL4')])


if __name__ == '__main__':
    unittest.main()
