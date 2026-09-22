import os
import time
import unittest
from unittest.mock import Mock, patch

from bot import Bot, payload


class BotTests(unittest.TestCase):
    def setUp(self):
        self.bot = Bot.__new__(Bot)
        self.bot.allowed = {42}
        self.bot.pending = {}
        self.bot.send = Mock()
        self.bot.telegram = Mock()
        self.bot.arr = Mock(return_value=[])
        self.bot.apps = {"movie": {"profile": 1, "root": "/downloads/movies"}}
        self.item = {"title": "Example", "year": 2000, "tmdbId": 123}

    def selection(self):
        self.bot.pending["key"] = {
            "kind": "movie", "item": self.item, "user": 42, "chat": 42,
            "expires": time.monotonic() + 60, "label": "Example (2000)",
            "confirmed": False,
        }

    def query(self, action="pick", user=42):
        return {"id": "callback", "from": {"id": user}, "data": f"{action}:key",
                "message": {"chat": {"id": 42, "type": "private"}}}

    def test_movie_payload(self):
        data = payload("movie", self.item, 7, "/downloads/movies")
        self.assertEqual(data["qualityProfileId"], 7)
        self.assertEqual(data["tmdbId"], 123)
        self.assertTrue(data["addOptions"]["searchForMovie"])

    def test_anime_and_specials(self):
        item = {"title": "Anime", "tvdbId": 1, "titleSlug": "anime",
                "genres": ["Anime"], "seasons": [{"seasonNumber": 0}, {"seasonNumber": 1}]}
        data = payload("series", item, 1, "/downloads/series")
        self.assertEqual(data["seriesType"], "anime")
        self.assertFalse(data["seasons"][0]["monitored"])
        self.assertTrue(data["seasons"][1]["monitored"])
        self.assertEqual(data["addOptions"]["monitor"], "skip")
        self.assertEqual(data["monitorNewItems"], "none")

    def test_unauthorized_and_group_messages_ignored(self):
        for user, chat_type in [(7, "private"), (42, "group")]:
            self.bot.handle({"message": {"from": {"id": user}, "chat": {"id": 42, "type": chat_type}, "text": "Example"}})
        self.bot.arr.assert_not_called()
        self.bot.send.assert_not_called()

    def test_empty_allowlist_accepts_any_private_user(self):
        self.bot.allowed = set()
        self.bot.search = Mock()
        for user in (7, 42):
            self.bot.handle({"message": {"from": {"id": user}, "chat": {"id": user, "type": "private"}, "text": "Example"}})
        self.assertEqual(self.bot.search.call_count, 2)

    def test_empty_allowlist_still_rejects_groups_and_missing_user(self):
        self.bot.allowed = set()
        self.bot.search = Mock()
        for user, chat_type in [(7, "group"), (None, "private")]:
            self.bot.handle({"message": {"from": {"id": user}, "chat": {"id": 7, "type": chat_type}, "text": "Example"}})
        self.bot.search.assert_not_called()

    def test_allowlist_configuration(self):
        env = {"TELEGRAM_BOT_TOKEN": "test-token"}
        for prefix in ("RADARR", "SONARR"):
            env.update({f"{prefix}_API_KEY": "test-key", f"{prefix}_QUALITY_PROFILE_ID": "1",
                        f"{prefix}_URL": "http://example", f"{prefix}_ROOT": "/downloads"})
        for value, expected in [(None, set()), ("", set()), ("  ", set()), ("42, 7", {42, 7})]:
            with self.subTest(value=value), patch.dict(os.environ, env, clear=True), patch("bot.Path.exists", return_value=False):
                if value is not None:
                    os.environ["TELEGRAM_ALLOWED_USERS"] = value
                self.assertEqual(Bot().allowed, expected)
        with patch.dict(os.environ, {**env, "TELEGRAM_ALLOWED_USERS": "invalid"}, clear=True):
            with self.assertRaises(ValueError):
                Bot()
        with patch.dict(os.environ, {**env, "TELEGRAM_BOT_TOKEN": ""}, clear=True):
            with self.assertRaises(ValueError):
                Bot()

    def test_confirmation_required_and_no_replay(self):
        self.selection()
        self.bot.handle({"callback_query": self.query("add")})
        self.bot.arr.assert_not_called()
        self.bot.handle({"callback_query": self.query()})
        self.bot.arr.assert_not_called()
        self.bot.handle({"callback_query": self.query("add")})
        self.assertEqual(self.bot.arr.call_count, 2)
        self.assertEqual(self.bot.arr.call_args.kwargs["data"]["tmdbId"], 123)
        self.bot.handle({"callback_query": self.query("add")})
        self.assertEqual(self.bot.arr.call_count, 2)

    def test_existing_not_added(self):
        self.selection()
        self.bot.arr.return_value = [self.item]
        self.bot.handle({"callback_query": self.query()})
        self.bot.handle({"callback_query": self.query("add")})
        self.bot.arr.assert_called_once_with("movie")

    def test_expired_and_wrong_user_callbacks(self):
        self.selection()
        self.bot.allowed.add(7)
        self.bot.handle({"callback_query": self.query("pick", user=7)})
        self.assertFalse(self.bot.pending["key"]["confirmed"])
        self.bot.pending["key"]["expires"] = 0
        self.bot.handle({"callback_query": self.query()})
        self.bot.send.assert_not_called()

    def test_search_limits_matches_and_replaces_old_selection(self):
        self.selection()
        self.bot.arr.return_value = [self.item] * 10
        self.bot.search(42, 42, "/movie Example")
        self.assertEqual(len(self.bot.pending), 5)
        self.assertNotIn("key", self.bot.pending)
        self.bot.arr.assert_called_once_with("movie", "/lookup?term=Example")

    def test_selected_season_payload(self):
        item = {"title": "Series", "tvdbId": 1, "titleSlug": "series",
                "seasons": [{"seasonNumber": n} for n in range(4)]}
        data = payload("series", item, 1, "/downloads/series", season=2)
        self.assertEqual([s["seasonNumber"] for s in data["seasons"] if s["monitored"]], [2])
        with self.assertRaises(ValueError):
            payload("series", item, 1, "/downloads/series", season=7)

    def test_season_query_parsing(self):
        self.bot.arr.return_value = [self.item]
        for text, season in [("/series Example S02", 2), ("Example season 3", 3), ("/series Example", 1)]:
            self.bot.search(42, 42, text)
            self.bot.arr.assert_called_with("series", "/lookup?term=Example")
            self.assertEqual(next(iter(self.bot.pending.values()))["season"], season)

    def test_missing_season_cannot_be_confirmed(self):
        self.selection()
        self.bot.pending["key"].update(kind="series", season=9)
        self.bot.handle({"callback_query": self.query()})
        self.assertFalse(self.bot.pending["key"]["confirmed"])
        self.bot.handle({"callback_query": self.query("add")})
        self.bot.arr.assert_not_called()

    def test_existing_series_requests_only_selected_season(self):
        self.selection()
        item = {"title": "Series", "tvdbId": 123, "id": 5,
                "seasons": [{"seasonNumber": 1, "monitored": False}, {"seasonNumber": 2, "monitored": False}]}
        self.bot.pending["key"].update(kind="series", season=2, item=item)
        self.bot.arr.side_effect = [[item], {}, [{"id": 10, "seasonNumber": 1}, {"id": 20, "seasonNumber": 2}], {}, {}]
        self.bot.handle({"callback_query": self.query()})
        self.bot.handle({"callback_query": self.query("add")})
        calls = self.bot.arr.call_args_list
        self.assertFalse(calls[1].kwargs["data"]["seasons"][0]["monitored"])
        self.assertTrue(calls[1].kwargs["data"]["seasons"][1]["monitored"])
        self.assertEqual(calls[3].kwargs["data"]["episodeIds"], [20])
        self.assertEqual(calls[4].kwargs["data"], {"name": "SeasonSearch", "seriesId": 5, "seasonNumber": 2})

    def test_arr_endpoint_routing(self):
        self.bot.apps["series"] = {"url": "http://sonarr:8989", "key": "test", "resource": "series"}
        with patch("bot.request") as req:
            for path, endpoint in [("/episode?seriesId=5", "episode?seriesId=5"), ("/command", "command"), ("/5", "series/5"), ("/lookup?term=test", "series/lookup?term=test")]:
                Bot.arr(self.bot, "series", path)
                self.assertEqual(req.call_args.args[0], f"http://sonarr:8989/api/v3/{endpoint}")

    def test_cancel_does_not_add(self):
        self.selection()
        self.bot.handle({"callback_query": self.query("cancel")})
        self.assertNotIn("key", self.bot.pending)
        self.bot.arr.assert_not_called()


if __name__ == "__main__":
    unittest.main()
