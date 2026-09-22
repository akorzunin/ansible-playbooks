"""Run on ws from the ARR deployment directory; never prints credentials.

Manages named ARR objects only. Requires host python3-yaml for Bazarr's config.
No media requests are created by this script.
"""
import copy
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import yaml

PORTS = {"radarr": 7878, "sonarr": 8989, "prowlarr": 9696, "bazarr": 6767}
KEYS = {}


def api(app, path, data=None, method=None, form=False):
    version = "" if app == "bazarr" else ("v1/" if app == "prowlarr" else "v3/")
    body = None if data is None else (urlencode(data, doseq=True) if form else json.dumps(data)).encode()
    req = Request(f"http://127.0.0.1:{PORTS[app]}/api/{version}{path}", data=body, method=method,
                  headers={"X-Api-Key": KEYS[app], "Content-Type": "application/x-www-form-urlencoded" if form else "application/json"})
    try:
        with urlopen(req, timeout=120) as response:
            content = response.read()
            return json.loads(content) if content else None
    except HTTPError as exc:
        # Validation responses can contain passwords/API keys. Report field names only.
        try:
            errors = json.loads(exc.read())
            fields = [e.get("propertyName", "") for e in errors] if isinstance(errors, list) else []
        except (ValueError, AttributeError):
            fields = []
        raise RuntimeError(f"{app} {path.split('?')[0]}: HTTP {exc.code}, fields={fields}") from None


def fields(obj, values):
    for name, value in values.items():
        field = next((f for f in obj["fields"] if f["name"] == name), None)
        if field is None:
            raise ValueError(f"Unsupported field: {name}")
        field["value"] = value
    return obj


def save(app, path, obj):
    existing = next((x for x in api(app, path) if x["name"] == obj["name"]), None)
    if existing:
        obj["id"] = existing["id"]
        return api(app, f"{path}/{existing['id']}", obj, "PUT")
    obj.pop("id", None)
    return api(app, path, obj)


def test(app, path, obj):
    existing = next((x for x in api(app, path) if x["name"] == obj["name"]), None)
    if existing:
        obj["id"] = existing["id"]
    return api(app, path + "/test", obj)


def set_env(values):
    path = Path("bot.env")
    text = path.read_text()
    for key, value in values.items():
        line = f"{key}={value}"
        if re.search(rf"^{key}=.*$", text, re.MULTILINE):
            text = re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.MULTILINE)
        else:
            text += line + "\n"
    tmp = path.with_suffix(".tmp")
    tmp.touch(mode=0o600)
    tmp.chmod(0o600)
    tmp.write_text(text)
    tmp.replace(path)


def configure_apps():
    for app in ("radarr", "sonarr", "prowlarr"):
        KEYS[app] = ET.parse(f"config/{app}/config.xml").findtext("ApiKey")
        for attempt in range(30):
            try:
                config = api(app, "config/host")
                break
            except (OSError, RuntimeError):
                if attempt == 29:
                    raise
                time.sleep(2)
        config.update(proxyEnabled=True, proxyType="http", proxyHostname="host.docker.internal", proxyPort=20171,
                      proxyBypassFilter="localhost,127.0.0.1,radarr,sonarr,prowlarr,bazarr,flaresolverr,host.docker.internal",
                      proxyBypassLocalAddresses=True)
        api(app, "config/host", config, "PUT")

    for app, root, prefix in [("radarr", "complete/films", "movie"), ("sonarr", "complete/shows", "tv")]:
        if not any(x["path"] == f"/downloads/{root}" for x in api(app, "rootfolder")):
            api(app, "rootfolder", {"path": f"/downloads/{root}"})
        client = next(x for x in api(app, "downloadclient/schema") if x["implementation"] == "Transmission")
        client.update(name="Transmission (ARR)", enable=True, removeCompletedDownloads=False)
        fields(client, {"host": "host.docker.internal", "port": 9092,
                        prefix + "Category": "", prefix + "Directory": f"/downloads/incoming/{app}"})
        test(app, "downloadclient", client)
        save(app, "downloadclient", client)
        config = api(app, "config/downloadclient")
        config["enableCompletedDownloadHandling"] = True
        api(app, "config/downloadclient", config, "PUT")
        config = api(app, "config/mediamanagement")
        config["copyUsingHardlinks"] = True
        api(app, "config/mediamanagement", config, "PUT")

        spec = next(x for x in api(app, "customformat/schema") if x["implementation"] == "LanguageSpecification")
        spec.pop("presets", None)
        spec["name"] = "Original language"
        fields(spec, {"value": -2, "exceptLanguage": False})
        custom = save(app, "customformat", {"name": "ARR Original Audio", "includeCustomFormatWhenRenaming": False, "specifications": [spec]})
        profile = copy.deepcopy(next(x for x in api(app, "qualityprofile") if x["name"] == "HD-1080p"))
        profile.pop("id", None)
        profile.update(name="ARR 1080p Original Preferred", upgradeAllowed=True,
                       minFormatScore=0, cutoffFormatScore=100, minUpgradeFormatScore=1)
        if app == "radarr":
            profile["language"] = {"id": -1, "name": "Any"}
        for fmt in profile["formatItems"]:
            fmt["score"] = 100 if fmt["format"] == custom["id"] else 0
        profile = save(app, "qualityprofile", profile)
        set_env({f"{app.upper()}_API_KEY": KEYS[app], f"{app.upper()}_QUALITY_PROFILE_ID": profile["id"]})
        print(f"{app}: root, Transmission test, hardlinks, 1080p and original-audio preference configured", flush=True)


def configure_indexers():
    tag = next((x for x in api("prowlarr", "tag") if x["label"] == "arr-cloudflare"), None)
    if tag is None:
        tag = api("prowlarr", "tag", {"label": "arr-cloudflare"})
    proxy = next(x for x in api("prowlarr", "indexerproxy/schema") if x["implementation"] == "FlareSolverr")
    proxy.update(name="ARR FlareSolverr", tags=[tag["id"]])
    fields(proxy, {"host": "http://flaresolverr:8191/", "requestTimeout": 60})
    test("prowlarr", "indexerproxy", proxy)
    save("prowlarr", "indexerproxy", proxy)
    api("prowlarr", "command", {"name": "IndexerDefinitionUpdate"})
    schemas = api("prowlarr", "indexer/schema")
    for name, url in [("Nyaa.si", "https://nyaa.si/"), ("1337x", "https://1337x.to/"), ("RuTracker.org", "https://rutracker.org/")]:
        try:
            indexer = copy.deepcopy(next(x for x in schemas if x["name"] == name))
            indexer.update(enable=True, appProfileId=1, priority=25,
                           tags=[] if name == "Nyaa.si" else [tag["id"]])
            values = {"baseUrl": url}
            if name == "Nyaa.si":
                values.update({"cat-id": "1_2", "prefer_magnet_links": True})
            if name == "RuTracker.org":
                if not os.environ.get("RUTRACKER_USER") or not os.environ.get("RUTRACKER_PASS"):
                    raise ValueError("RUTRACKER_USER and RUTRACKER_PASS are required")
                values.update(username=os.environ["RUTRACKER_USER"], password=os.environ["RUTRACKER_PASS"])
            fields(indexer, values)
            # Try only mirrors shipped by Prowlarr, not arbitrary third-party proxy sites.
            urls = list(dict.fromkeys([url] + indexer.get("indexerUrls", [])))
            for base_url in urls:
                fields(indexer, {"baseUrl": base_url})
                try:
                    test("prowlarr", "indexer", indexer)
                    break
                except RuntimeError:
                    if base_url == urls[-1]:
                        raise
            save("prowlarr", "indexer", indexer)
            print(f"{name}: configured and test passed", flush=True)
        except (RuntimeError, ValueError, StopIteration, OSError) as exc:
            print(f"{name}: NOT configured ({type(exc).__name__}); inspect Prowlarr test diagnostics", flush=True)
    for app in ("radarr", "sonarr"):
        obj = next(x for x in api("prowlarr", "applications/schema") if x["implementation"].lower() == app)
        obj.update(name=app.capitalize(), syncLevel="fullSync")
        fields(obj, {"prowlarrUrl": "http://prowlarr:9696", "baseUrl": f"http://{app}:{PORTS[app]}", "apiKey": KEYS[app]})
        if app == "radarr":
            # Nyaa uses TV/Anime even for anime films; Radarr filters the actual title.
            field = next(f for f in obj["fields"] if f["name"] == "syncCategories")
            field["value"] = sorted(set(field["value"] + [5070]))
        test("prowlarr", "applications", obj)
        save("prowlarr", "applications", obj)
    api("prowlarr", "command", {"name": "ApplicationIndexerSync"})
    print("Prowlarr: application connections tested and sync queued", flush=True)


def configure_bazarr():
    config = yaml.safe_load(Path("config/bazarr/config/config.yaml").read_text())
    KEYS["bazarr"] = config["auth"]["apikey"]
    profiles = api("bazarr", "system/languages/profiles")
    name = "ARR English"
    profile = next((p for p in profiles if p["name"] == name), None)
    if profile is None:
        profile = {"profileId": max([p["profileId"] for p in profiles] + [0]) + 1, "name": name,
                   "cutoff": 1, "items": [{"id": 1, "language": "en", "hi": "False", "forced": "False", "audio_exclude": "False"}],
                   "mustContain": [], "mustNotContain": [], "originalFormat": False}
        profiles.append(profile)
    # Russian is enabled for manual searches, not required for the automatic cutoff.
    enabled = [x["code2"] for x in api("bazarr", "system/languages") if x["enabled"]]
    data = {"languages-enabled": sorted(set(enabled + ["en", "ru"])), "languages-profiles": json.dumps(profiles),
            "settings-general-use_sonarr": "true", "settings-general-use_radarr": "true",
            "settings-sonarr-ip": "sonarr", "settings-sonarr-port": "8989", "settings-sonarr-apikey": KEYS["sonarr"],
            "settings-radarr-ip": "radarr", "settings-radarr-port": "7878", "settings-radarr-apikey": KEYS["radarr"],
            "settings-general-serie_default_enabled": "true", "settings-general-movie_default_enabled": "true",
            "settings-general-serie_default_profile": str(profile["profileId"]),
            "settings-general-movie_default_profile": str(profile["profileId"]),
            "settings-general-use_embedded_subs": "true", "settings-general-auto_update": "false",
            "settings-general-enabled_providers": sorted((set(config["general"]["enabled_providers"]) - {"podnapisi"}) | {"yifysubtitles", "supersubtitles"})}
    api("bazarr", "system/settings", data, form=True)
    print("Bazarr: linked to ARR; English default, Russian manual; YIFY Subtitles/SuperSubtitles enabled", flush=True)


if __name__ == "__main__":
    os.umask(0o077)
    try:
        configure_apps()
        configure_indexers()
        configure_bazarr()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
    except Exception as exc:
        # No traceback: exceptions from libraries may include secret-bearing URLs.
        raise SystemExit(f"Configuration stopped: {type(exc).__name__}. Inspect app diagnostics; no media was requested.") from None
