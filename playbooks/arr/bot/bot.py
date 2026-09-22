"""Private title-search bot. No LLM, public webhook, or third-party dependencies."""
import json
import logging
import os
import re
from pathlib import Path
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

LOG = logging.getLogger("arr-bot")


class APIError(Exception):
    pass


def request(url, data=None, headers=None, method=None):
    body = None if data is None else json.dumps(data).encode()
    req = Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})}, method=method)
    try:
        with urlopen(req, timeout=40) as response:
            return json.load(response)
    except HTTPError as exc:
        # Do not log URLs or response bodies: Telegram URLs contain the bot token.
        raise APIError(f"HTTP {exc.code}") from None
    except (URLError, TimeoutError, ValueError, OSError):
        raise APIError("Connection failed or invalid response") from None


def payload(kind, item, profile, root, season=1):
    common = {
        "title": item["title"],
        "qualityProfileId": profile,
        "rootFolderPath": root,
        "monitored": True,
    }
    if kind == "movie":
        return {
            **common,
            "tmdbId": item["tmdbId"],
            "minimumAvailability": "released",
            "addOptions": {"searchForMovie": True},
        }
    if season not in {s["seasonNumber"] for s in item.get("seasons", [])}:
        raise ValueError("Season not found")
    return {
        **common,
        "monitorNewItems": "none",
        "tvdbId": item["tvdbId"],
        "titleSlug": item["titleSlug"],
        "seasonFolder": True,
        "seriesType": "anime" if "anime" in {genre.lower() for genre in item.get("genres", [])} else "standard",
        "seasons": [
            {"seasonNumber": s["seasonNumber"], "monitored": s["seasonNumber"] == season}
            for s in item.get("seasons", [])
        ],
        "addOptions": {"monitor": "skip", "searchForMissingEpisodes": True},
    }


class Bot:
    def __init__(self):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
        self.allowed = {int(value.strip()) for value in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",") if value.strip()}
        if not self.token:
            raise ValueError("Bot token is required")
        self.apps = {}
        for kind, prefix, resource in [("movie", "RADARR", "movie"), ("series", "SONARR", "series")]:
            key = os.environ[f"{prefix}_API_KEY"].strip()
            profile = int(os.environ[f"{prefix}_QUALITY_PROFILE_ID"])
            if not key or profile < 1:
                raise ValueError("API keys and positive quality profile IDs are required")
            self.apps[kind] = {
                "url": os.environ[f"{prefix}_URL"].rstrip("/"),
                "key": key, "profile": profile,
                "root": os.environ[f"{prefix}_ROOT"], "resource": resource,
            }
        self.pending = {}
        self.offset_file = Path("/state/offset")
        self.offset = int(self.offset_file.read_text()) if self.offset_file.exists() else 0

    def telegram(self, method, data):
        result = request(f"https://api.telegram.org/bot{self.token}/{method}", data)
        if not result.get("ok"):
            raise APIError("Telegram request failed")
        return result["result"]

    def send(self, chat, text, buttons=None):
        data = {"chat_id": chat, "text": text}
        if buttons:
            data["reply_markup"] = {"inline_keyboard": buttons}
        self.telegram("sendMessage", data)

    def arr(self, kind, path="", data=None, method=None):
        app = self.apps[kind]
        resource = path[1:] if path.startswith("/") and path.partition("?")[0].split("/")[1] in {"command", "episode"} else app['resource'] + path
        return request(f"{app['url']}/api/v3/{resource}", data, {"X-Api-Key": app["key"]}, method)

    def search(self, chat, user, text):
        kind = None
        if text.startswith(("/movie ", "/series ")):
            command, text = text.split(" ", 1)
            kind = command[1:]
        text = text.strip()
        season = 1
        match = re.search(r"\s+(?:s|season\s+)(\d{1,3})$", text, re.IGNORECASE)
        if match and kind != "movie":
            season = int(match[1])
            text = text[:match.start()].strip()
            kind = "series"
        if not text or text.startswith("/"):
            self.send(chat, "Send a title, /movie TITLE, or /series TITLE S02. Series default to season 1; only the requested season is monitored. Choose a match, then confirm. Plot descriptions are not supported yet.")
            return
        if len(text) > 200:
            self.send(chat, "Please use a title of at most 200 characters.")
            return
        # In-memory selections expire after 15 minutes; restart requires a new search.
        self.pending = {key: value for key, value in self.pending.items() if value["expires"] > time.monotonic() and value["user"] != user}
        buttons = []
        failed = False
        for match_kind in ([kind] if kind else ["movie", "series"]):
            try:
                matches = self.arr(match_kind, "/lookup?" + urlencode({"term": text}))[:5]
            except APIError:
                failed = True
                continue
            for item in matches:
                key = secrets.token_hex(8)
                label = f"{item['title']} ({item.get('year', '?')}) — {match_kind}"
                self.pending[key] = {"kind": match_kind, "item": item, "user": user, "chat": chat, "expires": time.monotonic() + 900, "label": label, "season": season, "confirmed": False}
                buttons.append([{"text": label[:120], "callback_data": f"pick:{key}"}])
        if buttons:
            self.send(chat, "Choose a title:" if not failed else "Partial results (one service unavailable):", buttons)
        else:
            self.send(chat, "Search service unavailable; try again later." if failed else "No matches. Try another title or spelling.")

    def callback(self, query):
        user = query["from"]["id"]
        message = query.get("message", {})
        chat = message.get("chat", {}).get("id")
        action, _, key = query.get("data", "").partition(":")
        selected = self.pending.get(key)
        if not selected or selected["user"] != user or selected["chat"] != chat or selected["expires"] <= time.monotonic():
            self.telegram("answerCallbackQuery", {"callback_query_id": query["id"], "text": "Selection expired. Search again."})
            return
        self.telegram("answerCallbackQuery", {"callback_query_id": query["id"]})
        if action == "cancel":
            self.pending.pop(key)
            self.send(chat, "Cancelled.")
        elif action == "pick":
            if selected["kind"] == "series" and selected["season"] not in {s["seasonNumber"] for s in selected["item"].get("seasons", [])}:
                self.send(chat, "That season is not listed. Search again with /series TITLE S02 (or the desired season number).")
                return
            selected["confirmed"] = True
            scope = f"Season {selected['season']} only. Previously requested seasons are left unchanged." if selected["kind"] == "series" else "One movie."
            self.send(chat, f"Request {selected['label']}?\n{scope}\nUses the configured quality/language profile.", [[{"text": "Confirm request", "callback_data": f"add:{key}"}, {"text": "Cancel", "callback_data": f"cancel:{key}"}]])
        elif action == "add" and selected["confirmed"]:
            self.pending.pop(key)
            kind, item = selected["kind"], selected["item"]
            identity = "tmdbId" if kind == "movie" else "tvdbId"
            existing = next((entry for entry in self.arr(kind) if entry[identity] == item[identity]), None)
            if existing and kind == "movie":
                self.send(chat, "Already in the library manager; monitoring and search settings were left unchanged.")
                return
            if existing:
                season = selected["season"]
                target = next((s for s in existing["seasons"] if s["seasonNumber"] == season), None)
                if target is None:
                    self.send(chat, "Season not present in Sonarr yet. Refresh the series and try again.")
                    return
                target["monitored"] = True
                existing["monitored"] = True
                existing["monitorNewItems"] = "none"
                self.arr(kind, f"/{existing['id']}", data=existing, method="PUT")
                episodes = self.arr(kind, "/episode?" + urlencode({"seriesId": existing["id"]}))
                ids = [e["id"] for e in episodes if e["seasonNumber"] == season]
                if ids:
                    self.arr(kind, "/episode/monitor", data={"episodeIds": ids, "monitored": True}, method="PUT")
                self.arr(kind, "/command", data={"name": "SeasonSearch", "seriesId": existing["id"], "seasonNumber": season})
            else:
                app = self.apps[kind]
                self.arr(kind, data=payload(kind, item, app["profile"], app["root"], selected.get("season", 1)))
            self.send(chat, f"Requested {selected['label']}. Search queued; availability depends on your indexers. Jellyfin can see it after download and import.")

    def handle(self, update):
        query = update.get("callback_query")
        message = query.get("message", {}) if query else update.get("message", {})
        user = (query or message).get("from", {}).get("id")
        chat = message.get("chat", {})
        # Private chats only, even when an allowed user sends commands in a group.
        if user is None or (self.allowed and user not in self.allowed) or chat.get("type") != "private":
            return
        try:
            if query:
                self.callback(query)
            elif "text" in message:
                self.search(chat["id"], user, message["text"])
        except (APIError, KeyError, TypeError, ValueError):
            LOG.warning("Request could not be completed")
            self.send(chat["id"], "Request failed. Check Radarr/Sonarr before retrying: a timed-out request may already have been added.")

    def run(self):
        # Single synchronous worker: suitable for a private bot; use queued workers for higher traffic.
        while True:
            try:
                updates = self.telegram("getUpdates", {"offset": self.offset, "timeout": 25, "allowed_updates": ["message", "callback_query"]})
                for update in updates:
                    # At-most-once handling: checkpoint before side effects. A crash can lose a request,
                    # but cannot replay a confirmed download; search again after checking the manager.
                    offset = update["update_id"] + 1
                    temporary = self.offset_file.with_suffix(".tmp")
                    temporary.write_text(str(offset))
                    temporary.replace(self.offset_file)
                    self.offset = offset
                    self.handle(update)
            except (APIError, OSError):
                LOG.warning("Polling or state write failed; retrying in 5 seconds")
                time.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        bot = Bot()
    except (KeyError, ValueError):
        raise SystemExit("Invalid bot configuration: check token, allowed user IDs, API keys, profile IDs and state file") from None
    bot.run()
