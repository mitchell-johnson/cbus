import json
from pathlib import Path
import unittest

from cbus_toolkit.toolkit_update_version import (VersionComparisonError, compare_versions, evaluate_file_version,
                                                 parse_version)

FIXTURE = Path(__file__).resolve().parents[1] / 'research/fixtures/toolkit-update-version-vectors.json'


def fixture():
    return json.loads(FIXTURE.read_text())


class VersionVectorTests(unittest.TestCase):
    def test_runtime_parse_vectors(self):
        rows = fixture()['runtime_parse']
        self.assertGreaterEqual(len(rows), 190)
        for row in rows:
            with self.subTest(text=row['text']):
                expected = None if row['parsed'] is None else tuple(row['parsed'])
                self.assertEqual(parse_version(row['text']), expected)

    def test_runtime_compare_vectors(self):
        rows = fixture()['runtime_compare']
        self.assertGreaterEqual(len(rows), 8000)
        mismatches = [row for row in rows
                      if compare_versions(parse_version(row[0]), parse_version(row[1])) != row[2]]
        self.assertEqual(mismatches, [])

    def test_original_file_version_method_vectors(self):
        data = fixture()
        files = {row['label']: row for row in data['files']}
        self.assertEqual(len(data['original_file_version']), 1800)
        for row in data['original_file_version']:
            source = files[row['file']]
            observed = source['observed_file_version'] if source['exists'] else None
            with self.subTest(file=row['file'], right=row['right'], how=row['how']):
                if 'error' in row:
                    with self.assertRaises(VersionComparisonError) as caught:
                        evaluate_file_version(row['how'], observed, row['right'], name='<name>')
                    self.assertEqual(str(caught.exception), row['message'])
                else:
                    self.assertIs(evaluate_file_version(row['how'], observed, row['right']), row['result'])

    def test_boundaries(self):
        self.assertEqual(parse_version('1.2\x00\x00'), (1, 2, -1, -1))
        self.assertIsNone(parse_version('1.2\x00 '))
        self.assertIsNone(parse_version(None))
        self.assertEqual(compare_versions(parse_version('1.2'), parse_version('1.2.0')), -1)
        with self.assertRaises(ValueError):
            evaluate_file_version(16, '1.é2', '1')


if __name__ == '__main__':
    unittest.main()
