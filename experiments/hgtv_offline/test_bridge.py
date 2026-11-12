import json
import re
import unittest
from bridge import parse_rows, verify_signing_fixtures, run_jvm
from build import ROOT


class OfflineBridgeTests(unittest.TestCase):
    def test_upstream_parser_fixture_preserves_original_fields(self):
        source = (ROOT / 'vendor' / 'DanmakuTest.kt').read_text()
        rows = json.loads(re.search(r'private val window="""(.*?)"""', source, re.S).group(1))
        result = parse_rows(rows)
        self.assertEqual(result['rows_seen'], 6)
        self.assertEqual(result['rows_skipped'], 4)
        self.assertEqual([r['offset_ms'] for r in result['items']], [0, 478])
        self.assertEqual(result['items'][1]['text'], '前面高能')
        self.assertEqual(result['items'][1]['original_text'], '  前面高能  ')
        self.assertEqual(result['items'][1]['raw_row'], rows[1])
        self.assertFalse(result['live_verified'])

    def test_original_signing_vectors_through_python(self):
        self.assertEqual(verify_signing_fixtures(),
                         {'status': 'passed', 'fixture_vectors': 12, 'live_verified': False})

    def test_network_permission_is_denied_before_any_connection(self):
        self.assertEqual(json.loads(run_jvm('guard-check')), {'network_guard_blocked': True})

    def test_live_operation_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Unsupported operation'):
            run_jvm('bridge', {'operation': 'collect_live'})


if __name__ == '__main__':
    unittest.main()
