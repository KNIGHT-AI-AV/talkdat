"""Activity counts should survive malformed dates and calendar transitions."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from knight_flow.history import history_stats


class ActivityHistoryTests(unittest.TestCase):
    def test_more_than_twenty_thousand_entries_is_disclosed_and_bounded(self):
        requests=[]
        rows=[{'type':'dictation','text':'one','created_at':None}]*20001
        def recent(limit):requests.append(limit);return rows[:limit]
        with patch('knight_flow.history.create_history_store', return_value=SimpleNamespace(recent=recent)):
            stats=history_stats({})
        self.assertEqual(requests,[20001])
        self.assertTrue(stats['capped'])
        self.assertEqual(stats['entries'],20000)
        self.assertEqual(stats['words'],20000)

    def test_daily_chart_has_seven_calendar_dates_even_when_history_is_empty(self):
        with patch('knight_flow.history.create_history_store', return_value=SimpleNamespace(recent=lambda _: [])):
            stats=history_stats({})
        self.assertEqual(len(stats['daily']),7)
        self.assertTrue(all(row['entries']==0 for row in stats['daily']))
        self.assertEqual(len({row['date'] for row in stats['daily']}),7)
        self.assertFalse(stats['capped'])

    def test_non_text_payloads_do_not_count_as_spoken_words(self):
        rows=[{'type':'dictation','text':value} for value in (None,42,[],{})]
        with patch('knight_flow.history.create_history_store', return_value=SimpleNamespace(recent=lambda _:rows)):
            stats=history_stats({})
        self.assertEqual(stats['words'],0)
        self.assertEqual(stats['dictated_words'],0)

    def test_speech_daily_average_uses_days_with_dictation(self):
        now=datetime(2026,9,20,12).timestamp();yesterday=now-86400
        rows=[{'type':'dictation','text':'one','created_at':now},
              {'type':'translation','text':'another','created_at':yesterday}]
        with patch('knight_flow.history.create_history_store', return_value=SimpleNamespace(recent=lambda _:rows)):
            stats=history_stats({})
        self.assertEqual(stats['active_days'],2)
        self.assertEqual(stats['dictation_active_days'],1)

    def test_translations_and_rewrites_do_not_inflate_speech_time_saved(self):
        rows = [{'text': 'word '*150, 'type': 'dictation'},
                {'text': 'word '*150, 'type': 'translation'},
                {'text': 'word '*150, 'type': 'transform'}]
        with patch('knight_flow.history.create_history_store', return_value=SimpleNamespace(recent=lambda _limit: rows)):
            stats = history_stats({})
        self.assertEqual(stats['words'], 450)
        self.assertEqual(stats['minutes_saved'], 3)

    def test_invalid_dates_do_not_blank_the_whole_activity_page(self):
        values = [float('nan'), float('inf'), float('-inf'), 1e300, True, None, 'invalid']
        rows = [{'text': 'two words', 'type': 'dictation', 'created_at': value} for value in values]
        with patch('knight_flow.history.create_history_store', return_value=SimpleNamespace(recent=lambda _limit: rows)):
            stats = history_stats({})
        self.assertEqual(stats['entries'], 7)
        self.assertEqual(stats['words'], 14)
        self.assertEqual(stats['active_days'], 0)

    def test_a_twenty_five_hour_day_counts_once_in_the_streak(self):
        threshold = datetime(2026, 11, 1, 9, tzinfo=timezone.utc).timestamp()
        now = datetime(2026, 11, 2, 7, 30, tzinfo=timezone.utc).timestamp()
        earlier = datetime(2026, 10, 31, 20, tzinfo=timezone.utc).timestamp()
        def local_date(timestamp):
            return datetime.fromtimestamp(timestamp, timezone.utc).replace(tzinfo=None) + timedelta(hours=-7 if timestamp < threshold else -8)
        clock = SimpleNamespace(fromtimestamp=local_date)
        rows = [{'text': 'hello', 'created_at': stamp} for stamp in (now, earlier)]
        with patch('knight_flow.history.create_history_store', return_value=SimpleNamespace(recent=lambda _limit: rows)), \
             patch('knight_flow.history.time.time', return_value=now), \
             patch('knight_flow.history.time.localtime', side_effect=lambda stamp=None: local_date(now if stamp is None else stamp).timetuple()), \
             patch('knight_flow.history.datetime', clock, create=True):
            stats = history_stats({})
        self.assertEqual(stats['streak_days'], 2)


if __name__ == '__main__':
    unittest.main()
