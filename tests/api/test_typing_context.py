import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dumbapi_core.common import APIError, Config
from dumbapi_core.typing_context import continuations, recent, _cache


class TypingContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.config = Config(base/'DumbAPI', base/'state')
        self.thread = '12345678-1234-4234-8234-123456789abc'

    def tearDown(self):
        self.temp.cleanup()

    def row(self, text):
        return {'thread': {'title': 'Fishing game'}, 'messages': [{'role': 'user', 'text': text, 'at': 'now'}]}

    def test_new_sentence_borrows_only_suffix_and_preserves_exact_typed_prefix(self):
        source = ['Fish should flop naturally when landing on the dock.']
        for typed in ['Make sure the fish should fl', '  Make sure the FISH should fl', 'Make sure the fish should flop ']:
            values = continuations(typed, source)
            self.assertTrue(values)
            self.assertTrue(all(value.startswith(typed) for value in values))
            self.assertTrue(values[0].endswith('naturally when landing on the dock'))
        self.assertIn('Can you test fish flopping smoothly after landing', continuations(
            'Can you test fish flo', ['Fish flopping smoothly after landing']))
        self.assertFalse(continuations('Add an axo', ['Axolotl recovery']))

    def test_no_suffix_for_urls_code_unrelated_or_generic_last_word(self):
        for typed in ['https://example.fi', 'Open ./fi', 'me@example.fi', 'Fix the ', 'Nothing related here']:
            self.assertEqual(continuations(typed, ['Fish should flop naturally on the dock.']), [])
        self.assertEqual(continuations('Fish should fl', ['```\nFish should flop unnaturally on the dock\n```']), [])
        self.assertTrue(all(len(v)<=500 for v in continuations('Fish should fl', ['Fish should flop '+('naturally '*100)])))

    def test_cache_is_bounded_fresh_and_exact_thread_with_failure_fallback(self):
        clock = [100.0]
        with patch('dumbapi_core.typing_context.time.monotonic', side_effect=lambda: clock[0]), patch('dumbapi_core.t3.T3.read') as read:
            read.return_value = self.row('Fish stops flopping after landing on the dock.')
            first = recent(self.config, self.thread)
            self.assertEqual(first['source'], 'live_thread')
            self.assertEqual(recent(self.config, self.thread), first)
            read.assert_called_once_with(self.thread)
            clock[0] += 16
            read.return_value = self.row('Fish now flops smoothly on the dock.')
            self.assertIn('smoothly', recent(self.config, self.thread)['messages'][0]['text'])
            read.side_effect = APIError('Disconnected')
            clock[0] += 16
            self.assertEqual(recent(self.config, self.thread)['messages'], [])
            count = read.call_count
            recent(self.config, self.thread)
            self.assertEqual(read.call_count, count)
        self.assertEqual(recent(self.config, 'not-a-thread')['messages'], [])
        self.assertLessEqual(len(_cache), 16)

    def test_recent_read_is_small_and_other_thread_has_separate_cache(self):
        with patch('dumbapi_core.t3.T3.read') as read:
            row = self.row('x'*5000)
            row['messages'] *= 8
            read.return_value = row
            result = recent(self.config, self.thread)
            self.assertEqual(len(result['messages']), 4)
            self.assertEqual(len(result['messages'][0]['text']), 1000)
            other = '22345678-1234-4234-8234-123456789abc'
            read.return_value = self.row('Only this other thread')
            self.assertEqual(recent(self.config, other)['messages'][0]['text'], 'Only this other thread')
            self.assertEqual(recent(self.config, self.thread), result)
