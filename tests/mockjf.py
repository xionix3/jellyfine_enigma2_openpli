# Fake Jellyfin server for testing the Enigma2 client (implements the subset the plugin uses)
import io
import json
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image

TOKEN = "tok123"
USER_ID = "u1"


def jpeg(w=300, h=450, color=(40, 90, 160)):
	buf = io.BytesIO()
	Image.new("RGB", (w, h), color).save(buf, "JPEG")
	return buf.getvalue()


JPEG = jpeg()
NOW = time.time()


def ago(days):
	return time.strftime("%Y-%m-%dT%H:%M:%S.0000000Z", time.gmtime(NOW - days * 86400))


def media_source(item_id, vcodec="h264", acodecs=("ac3",), width=1920, subs=("ger", "eng"), container="mkv", bitrate=8000000):
	streams = [{"Type": "Video", "Index": 0, "Codec": vcodec, "Width": width, "Height": int(width * 9 / 16), "VideoRange": "SDR"}]
	idx = 1
	for i, ac in enumerate(acodecs):
		streams.append({"Type": "Audio", "Index": idx, "Codec": ac, "Language": "ger" if i == 0 else "eng", "Channels": 6, "IsDefault": i == 0})
		idx += 1
	for s in subs:
		streams.append({"Type": "Subtitle", "Index": idx, "Codec": "subrip", "Language": s, "DisplayTitle": s.upper(), "IsExternal": False})
		idx += 1
	return {"Id": "ms-" + item_id, "Name": "Version 1", "Container": container, "Protocol": "File", "Size": 4 * 1024 ** 3,
		"Bitrate": bitrate, "MediaStreams": streams, "DefaultAudioStreamIndex": 1, "SupportsDirectPlay": True, "SupportsTranscoding": True}


CAST = [("p1", "Anna Actor", "Heldin"), ("p3", "Bert Bühne", "Schurke"), ("p4", "Carla Casting", "Kommissarin"), ("p5", "Dirk Dreh", "Taxifahrer"),
	("p6", "Eva Engel", "Ärztin"), ("p7", "Fritz Film", "Barkeeper"), ("p8", "Gina Gage", "Pilotin"), ("p9", "Hans Held", "Vater"),
	("p10", "Ida Idol", "Tochter"), ("p11", "Jan Jury", "Richter")]
PEOPLE = [{"Id": pid, "Name": n, "Type": "Actor", "Role": r, "PrimaryImageTag": "ph-" + pid if pid != "p5" else None} for pid, n, r in CAST]
PEOPLE = [dict((k, v) for k, v in p.items() if v is not None) for p in PEOPLE] + [{"Id": "p2", "Name": "Rex Regie", "Type": "Director"}]

# fake GitHub release for the update check (served under /gh/)
GH_ASSET = "enigma2-plugin-extensions-jellyfine-enigma2-openpli_all.ipk"
GH_OLD_ASSET = "enigma2-plugin-extensions-jellyfine2_all.ipk"
GH_IPK = b"!<arch>\n" + b"debian-binary   0           0     0     100644  4         `\n2.0\n"


def gh_release(base, version="9.9.9"):
	return {"tag_name": "v" + version, "draft": False, "prerelease": False, "html_url": base + "/gh/page",
		"body": "## Änderungen\n\n- Neue Startseite mit **Titelbild**\n- Suche mit [Kategorien](https://x)\n\nInstallation: wget ...",
		# the old stable name comes first (as in real releases, sorted by name): the update must pick the new one
		"assets": [{"name": GH_OLD_ASSET, "browser_download_url": base + "/gh/dl/" + GH_OLD_ASSET},
			{"name": GH_ASSET, "browser_download_url": base + "/gh/dl/" + GH_ASSET},
			{"name": "SHA256SUMS", "browser_download_url": base + "/gh/dl/SHA256SUMS"}]}


GENRE_IDS = {"Action": "g1", "Komödie": "g2", "Drama": "g3"}


def genre_id(name):
	return GENRE_IDS.get(name) or "g-" + name


def genre_name(gid):
	for n, i in GENRE_IDS.items():
		if i == gid:
			return n
	return gid[2:] if gid.startswith("g-") else gid


class Library(object):
	def __init__(self):
		self.items = {}
		self.views = [
			{"Id": "lib-movies", "Name": "Filme", "Type": "CollectionFolder", "CollectionType": "movies", "ImageTags": {}},
			{"Id": "lib-tv", "Name": "Serien", "Type": "CollectionFolder", "CollectionType": "tvshows", "ImageTags": {}},
			{"Id": "lib-music", "Name": "Musik", "Type": "CollectionFolder", "CollectionType": "music", "ImageTags": {}},
			{"Id": "lib-photos", "Name": "Fotos", "Type": "CollectionFolder", "CollectionType": "photos", "ImageTags": {}},
			{"Id": "lib-home", "Name": "Heimvideos", "Type": "CollectionFolder", "CollectionType": "homevideos", "ImageTags": {}},
		]
		for v in self.views:
			self.items[v["Id"]] = dict(v)
		for i in range(1, 41):
			mid = "m%d" % i
			vcodec = "hevc" if i % 5 == 0 else "h264"
			acodecs = ("dts",) if i == 7 else ("ac3", "aac")
			width = 3840 if i % 5 == 0 else 1920
			it = {"Id": mid, "Name": "Film %02d" % i, "Type": "Movie", "MediaType": "Video", "ParentId": "lib-movies",
				"ProductionYear": 1990 + i, "RunTimeTicks": (90 + i) * 60 * 10000000, "OfficialRating": "FSK 12",
				"CommunityRating": 6.5 + (i % 30) / 10.0, "Genres": ["Action", "Drama"] if i % 2 else ["Komödie"],
				"Overview": "Beschreibung von Film %d. <br>Mit <b>HTML</b> &amp; Umbruch." % i,
				"ImageTags": {"Primary": "tag%d" % i} if i != 3 else {}, "BackdropImageTags": ["bd%d" % i],
				"UserData": {"Played": i in (1, 2), "IsFavorite": i == 4, "PlaybackPositionTicks": 0, "PlayedPercentage": 0},
				"MediaSources": [media_source(mid, vcodec, acodecs, width)],
				"People": PEOPLE,
				"Studios": [{"Name": "Studio X"}], "Taglines": ["Ein Film."] if i == 5 else [],
				"DateCreated": ago(i), "PremiereDate": ago(i * 20)}
			if i == 6:
				it["UserData"].update(PlaybackPositionTicks=30 * 60 * 10000000, PlayedPercentage=30)
			self.items[mid] = it
		# series
		self.items["s1"] = {"Id": "s1", "Name": "Serie Eins", "Type": "Series", "ParentId": "lib-tv", "ProductionYear": 2015, "Status": "Continuing",
			"ChildCount": 2, "ImageTags": {"Primary": "st"}, "BackdropImageTags": ["sbd"], "Overview": "Eine Serie.",
			"UserData": {"UnplayedItemCount": 4, "Played": False}, "Genres": ["Drama"], "People": [],
			"DateCreated": ago(400), "DateLastMediaAdded": ago(1), "PremiereDate": ago(3000)}
		self.items["s2"] = {"Id": "s2", "Name": "Serie Zwei", "Type": "Series", "ParentId": "lib-tv", "ProductionYear": 2020, "ChildCount": 1,
			"ImageTags": {"Primary": "s2t"}, "UserData": {"UnplayedItemCount": 1, "Played": False}, "Genres": ["Komödie"],
			"DateCreated": ago(200), "DateLastMediaAdded": ago(1), "PremiereDate": ago(2000)}
		self.items["s2-1"] = {"Id": "s2-1", "Name": "Staffel 1", "Type": "Season", "SeriesId": "s2", "SeriesName": "Serie Zwei", "IndexNumber": 1,
			"ParentId": "s2", "ImageTags": {}, "UserData": {}}
		self.items["e211"] = {"Id": "e211", "Name": "Pilot", "Type": "Episode", "MediaType": "Video", "SeriesId": "s2", "SeriesName": "Serie Zwei",
			"SeasonId": "s2-1", "ParentIndexNumber": 1, "IndexNumber": 1, "ParentId": "s2-1", "RunTimeTicks": 30 * 60 * 10000000,
			"ImageTags": {"Primary": "e211t"}, "SeriesPrimaryImageTag": "s2t", "UserData": {"Played": False}, "LocationType": "FileSystem",
			"MediaSources": [media_source("e211")], "DateCreated": ago(1.5), "PremiereDate": ago(2)}
		for s in (1, 2):
			sid = "s1-%d" % s
			self.items[sid] = {"Id": sid, "Name": "Staffel %d" % s, "Type": "Season", "SeriesId": "s1", "SeriesName": "Serie Eins",
				"IndexNumber": s, "ParentId": "s1", "ChildCount": 3, "ImageTags": {}, "SeriesPrimaryImageTag": "st",
				"UserData": {"Played": s == 1 and False}}
			for e in (1, 2, 3):
				eid = "e%d%d" % (s, e)
				self.items[eid] = {"Id": eid, "Name": "Episode %d" % e, "Type": "Episode", "MediaType": "Video", "SeriesId": "s1",
					"SeriesName": "Serie Eins", "SeasonId": sid, "SeasonName": "Staffel %d" % s, "ParentIndexNumber": s, "IndexNumber": e,
					"ParentId": sid, "RunTimeTicks": 45 * 60 * 10000000, "ImageTags": {"Primary": "et%d%d" % (s, e)},
					"SeriesPrimaryImageTag": "st", "ParentBackdropItemId": "s1", "ParentBackdropImageTags": ["sbd"],
					"PremiereDate": "2015-0%d-1%dT00:00:00.0000000Z" % (s, e), "Overview": "Folge %d der Staffel %d." % (e, s),
					"UserData": {"Played": s == 1 and e == 1, "PlaybackPositionTicks": 600000000 if (s, e) == (1, 2) else 0,
						"PlayedPercentage": 22 if (s, e) == (1, 2) else 0},
					"MediaSources": [media_source(eid)], "LocationType": "FileSystem",
					"DateCreated": ago({(2, 1): 3, (2, 2): 2, (2, 3): 1}.get((s, e), 100 + e))}
		# virtual (missing) episode should be ignored
		self.items["e24"] = {"Id": "e24", "Name": "Fehlt", "Type": "Episode", "SeriesId": "s1", "SeasonId": "s1-2", "ParentIndexNumber": 2,
			"IndexNumber": 4, "LocationType": "Virtual", "ParentId": "s1-2", "UserData": {}}
		# music
		self.items["al1"] = {"Id": "al1", "Name": "Album A", "Type": "MusicAlbum", "ParentId": "lib-music", "AlbumArtist": "Band B",
			"ProductionYear": 2001, "ImageTags": {"Primary": "alt"}, "UserData": {}, "ChildCount": 3}
		for t in (1, 2, 3):
			tid = "t%d" % t
			self.items[tid] = {"Id": tid, "Name": "Song %d" % t, "Type": "Audio", "MediaType": "Audio", "ParentId": "al1", "AlbumId": "al1",
				"AlbumPrimaryImageTag": "alt", "Artists": ["Band B"], "IndexNumber": t, "RunTimeTicks": 200 * 10000000, "UserData": {},
				"MediaSources": [{"Id": "ms-" + tid, "Container": "flac", "Protocol": "File", "MediaStreams": [{"Type": "Audio", "Index": 0, "Codec": "flac"}]}]}
		# home videos folder
		self.items["f1"] = {"Id": "f1", "Name": "Urlaub", "Type": "Folder", "IsFolder": True, "ParentId": "lib-home", "ImageTags": {}, "UserData": {}}
		self.items["v1"] = {"Id": "v1", "Name": "Strand", "Type": "Video", "MediaType": "Video", "ParentId": "f1", "ImageTags": {},
			"UserData": {}, "MediaSources": [media_source("v1", container="mp4", subs=())]}

	def children(self, parent):
		return [it for it in self.items.values() if it.get("ParentId") == parent]

	def descendants(self, parent):
		out = []
		stack = [parent]
		while stack:
			p = stack.pop()
			for it in self.children(p):
				out.append(it)
				stack.append(it["Id"])
		return out


class State(object):
	def __init__(self, version="10.10.3", demo=False):
		self.version = version
		self.demo = demo
		if demo:
			from demo_data import DemoLibrary
			self.lib = DemoLibrary(media_source)
		else:
			self.lib = Library()
		self.reports = []
		self.requests = []
		self.qc_polls = 0
		self.deleted_encodings = []
		self.playback_infos = []
		self.item_queries = []
		self.connections = set()


def new_api(state):
	parts = [int(x) for x in state.version.split(".")[:2]]
	return parts >= [10, 9]


class Handler(BaseHTTPRequestHandler):
	state = None
	protocol_version = "HTTP/1.1"

	def log_message(self, *args):
		pass

	def send_json(self, obj, code=200):
		body = json.dumps(obj).encode()
		self.send_response(code)
		self.send_header("Content-Type", "application/json")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def send_empty(self, code=204):
		self.send_response(code)
		self.send_header("Content-Length", "0")
		self.end_headers()

	def body(self):
		n = int(self.headers.get("Content-Length") or 0)
		if not n:
			return None
		raw = self.rfile.read(n)
		return json.loads(raw) if raw else None

	def authed(self):
		auth = self.headers.get("Authorization", "")
		return self.headers.get("X-Emby-Token") == TOKEN or ('Token="%s"' % TOKEN) in auth

	def do_GET(self):
		self.route("GET")

	def do_POST(self):
		self.route("POST")

	def do_DELETE(self):
		self.route("DELETE")

	def route(self, method):
		st = self.state
		st.connections.add(self.client_address)
		u = urlparse(self.path)
		q = dict((k.lower(), v[0]) for k, v in parse_qs(u.query).items())
		path = u.path
		body = self.body() if method in ("POST", "DELETE") else None
		st.requests.append((method, path, q, body, dict(self.headers)))
		NEW = new_api(st)
		lib = st.lib

		if path == "/System/Info/Public":
			return self.send_json({"ServerName": "Mein Jellyfin" if st.demo else "TestServer", "Version": st.version, "Id": "srv1", "LocalAddress": "http://127.0.0.1"})
		if path == "/Users/AuthenticateByName" and method == "POST":
			if body and body.get("Username") == "demo" and body.get("Pw") == "geheim":
				return self.send_json({"AccessToken": TOKEN, "User": {"Id": USER_ID, "Name": "demo"}})
			return self.send_json({"error": "bad"}, 401)
		if path == "/QuickConnect/Enabled":
			return self.send_json(True)
		if path == "/QuickConnect/Initiate":
			if (NEW and method != "POST") or (not NEW and method != "GET"):
				return self.send_empty(405)
			if 'DeviceId="' not in self.headers.get("Authorization", ""):
				return self.send_json({}, 401)
			st.qc_polls = 0
			return self.send_json({"Secret": "sec1", "Code": "123456", "Authenticated": False})
		if path == "/QuickConnect/Connect":
			st.qc_polls += 1
			return self.send_json({"Secret": q.get("secret"), "Authenticated": st.qc_polls >= 2})
		if path == "/Users/AuthenticateWithQuickConnect" and method == "POST":
			if body and body.get("Secret") == "sec1" and st.qc_polls >= 2:
				return self.send_json({"AccessToken": TOKEN, "User": {"Id": USER_ID, "Name": "demo"}})
			return self.send_json({}, 401)
		if path.startswith("/Items/") and "/Images/" in path:
			return self.send_image(path, q)
		if path.startswith("/gh/"):
			return self.github(path)

		if not self.authed():
			return self.send_json({"error": "unauthorized"}, 401)

		if path.startswith("/MediaSegments/"):
			# 10.10+: intro 60-150 s and credits in the last 90 s of every episode; older servers: 404
			if [int(x) for x in st.version.split(".")[:2]] < [10, 10]:
				return self.send_json({}, 404)
			it = lib.items.get(path.split("/")[2]) or {}
			if it.get("Type") != "Episode":
				return self.send_json({"Items": [], "TotalRecordCount": 0, "StartIndex": 0})
			run = it.get("RunTimeTicks") or 0
			segs = [{"Id": "s1", "ItemId": it["Id"], "Type": "Intro", "StartTicks": 60 * 10000000, "EndTicks": 150 * 10000000},
				{"Id": "s2", "ItemId": it["Id"], "Type": 4, "StartTicks": run - 90 * 10000000, "EndTicks": run}]
			return self.send_json({"Items": segs, "TotalRecordCount": 2, "StartIndex": 0})
		if path.startswith("/Episode/") and path.endswith("/IntroTimestamps/v1"):
			it = lib.items.get(path.split("/")[2]) or {}
			if it.get("Type") != "Episode":
				return self.send_json({}, 404)
			return self.send_json({"EpisodeId": it["Id"], "Valid": True, "IntroStart": 60.0, "IntroEnd": 150.0, "ShowSkipPromptAt": 55.0, "HideSkipPromptAt": 70.0})
		if path == "/Users/Me":
			return self.send_json({"Id": USER_ID, "Name": "demo"})
		if path == "/Persons":
			term = (q.get("searchterm") or "").lower()
			persons = {}
			for it in lib.items.values():
				for p in it.get("People") or []:
					persons.setdefault(p["Id"], {"Id": p["Id"], "Name": p["Name"], "Type": "Person",
						"ImageTags": {"Primary": p["PrimaryImageTag"]} if p.get("PrimaryImageTag") else {}})
			people = [p for p in persons.values() if term in p["Name"].lower()]
			people.sort(key=lambda p: (not p["Name"].lower().startswith(term), p["Name"]))
			return self.send_json({"Items": people[:int(q.get("limit", 100))], "TotalRecordCount": len(people)})
		if path == "/Sessions/Capabilities/Full":
			return self.send_empty()
		if path == "/Sessions/Logout":
			return self.send_empty()
		if path in ("/Sessions/Playing", "/Sessions/Playing/Progress", "/Sessions/Playing/Stopped"):
			st.reports.append((path, body))
			if path == "/Sessions/Playing/Stopped" and body:
				it = lib.items.get(body.get("ItemId"))
				if it:
					run = it.get("RunTimeTicks") or 1
					pos = body.get("PositionTicks") or 0
					if pos >= run * 0.9:
						it["UserData"].update(Played=True, PlaybackPositionTicks=0, PlayedPercentage=0)
					else:
						it["UserData"].update(PlaybackPositionTicks=pos, PlayedPercentage=pos * 100.0 / run)
			return self.send_empty()
		if path == "/Videos/ActiveEncodings" and method == "DELETE":
			st.deleted_encodings.append(q.get("playsessionid"))
			return self.send_empty()

		m = re.match(r"^/Users/([^/]+)/(.*)$", path)
		if m:
			if NEW:
				return self.send_json({"error": "old route not supported in this test"}, 404)
			if m.group(1) != USER_ID:
				return self.send_json({}, 404)
			path = "/" + m.group(2)
		elif path.startswith(("/UserViews", "/UserItems", "/UserPlayedItems", "/UserFavoriteItems")) and not NEW:
			return self.send_json({}, 404)

		if path in ("/Views", "/UserViews"):
			return self.send_json({"Items": lib.views, "TotalRecordCount": len(lib.views)})
		if path in ("/Items/Resume", "/UserItems/Resume"):
			items = [it for it in lib.items.values() if (it.get("UserData") or {}).get("PlaybackPositionTicks") and not it["UserData"].get("Played")]
			return self.send_json({"Items": items, "TotalRecordCount": len(items)})
		if path == "/Shows/NextUp":
			out = []
			series_ids = [q["seriesid"]] if q.get("seriesid") else sorted(set(it["SeriesId"] for it in lib.items.values() if it.get("Type") == "Episode"))
			for sid in series_ids:
				eps = sorted([it for it in lib.items.values() if it.get("Type") == "Episode" and it.get("LocationType") != "Virtual"
					and it["SeriesId"] == sid], key=lambda e: (e["ParentIndexNumber"], e["IndexNumber"]))
				started = any(e["UserData"].get("Played") for e in eps)
				if not started and (q.get("disablefirstepisode") == "true" or not q.get("seriesid")):
					continue
				nxt = [e for e in eps if not e["UserData"].get("Played")][:1]
				out += nxt
			return self.send_json({"Items": out, "TotalRecordCount": len(out)})
		if path == "/Items/Latest":
			parent = q.get("parentid")
			items = [it for it in lib.items.values() if it.get("Type") in ("Movie", "Series", "MusicAlbum")]
			if parent:
				items = [it for it in items if it.get("ParentId") == parent]
			return self.send_json(items[: int(q.get("limit", 20))])
		m = re.match(r"^/Items/([^/]+)/PlaybackInfo$", path)
		if m and method == "POST":
			return self.playback_info(m.group(1), body, q)
		m = re.match(r"^/Items/([^/]+)/Similar$", path)
		if m:
			items = [it for it in lib.items.values() if it.get("Type") == "Movie" and it["Id"] != m.group(1)][:5]
			return self.send_json({"Items": items, "TotalRecordCount": len(items)})
		if path == "/Items":
			return self.items_query(q)
		m = re.match(r"^/Items/([^/]+)$", path)
		if m:
			it = lib.items.get(m.group(1))
			return self.send_json(it) if it else self.send_json({}, 404)
		m = re.match(r"^/Shows/([^/]+)/Seasons$", path)
		if m:
			items = sorted([it for it in lib.items.values() if it.get("Type") == "Season" and it.get("SeriesId") == m.group(1)], key=lambda s: s["IndexNumber"])
			return self.send_json({"Items": items, "TotalRecordCount": len(items)})
		m = re.match(r"^/Shows/([^/]+)/Episodes$", path)
		if m:
			items = [it for it in lib.items.values() if it.get("Type") == "Episode" and it.get("SeriesId") == m.group(1)
				and (not q.get("seasonid") or it.get("SeasonId") == q["seasonid"])]
			items.sort(key=lambda e: (e["ParentIndexNumber"], e["IndexNumber"]))
			return self.send_json({"Items": items, "TotalRecordCount": len(items)})
		if path == "/Genres":
			types = (q.get("includeitemtypes") or "").split(",") if q.get("includeitemtypes") else None
			names = sorted(set(g for it in lib.items.values() if not types or it.get("Type") in types for g in (it.get("Genres") or [])))
			return self.send_json({"Items": [{"Id": genre_id(n), "Name": n} for n in names]})
		m = re.match(r"^/(?:UserPlayedItems|PlayedItems)/([^/]+)$", path)
		if m:
			it = lib.items.get(m.group(1))
			if not it:
				return self.send_json({}, 404)
			it.setdefault("UserData", {})["Played"] = method == "POST"
			return self.send_json(it["UserData"])
		m = re.match(r"^/(?:UserFavoriteItems|FavoriteItems)/([^/]+)$", path)
		if m:
			it = lib.items.get(m.group(1))
			if not it:
				return self.send_json({}, 404)
			it.setdefault("UserData", {})["IsFavorite"] = method == "POST"
			return self.send_json(it["UserData"])
		return self.send_json({"error": "no route %s %s" % (method, self.path)}, 404)

	def github(self, path):
		import hashlib
		st = self.state
		base = "http://%s:%d" % self.server.server_address[:2]
		if path == "/gh/releases/latest":
			return self.send_json(gh_release(base, getattr(st, "gh_version", "9.9.9")))
		if path == "/gh/dl/" + GH_ASSET:
			st.gh_downloads = getattr(st, "gh_downloads", 0) + 1
			data = GH_IPK
		elif path == "/gh/dl/SHA256SUMS":
			digest = getattr(st, "gh_sum", None) or hashlib.sha256(GH_IPK).hexdigest()
			data = ("%s  %s\n" % (digest, GH_ASSET)).encode("ascii")
		else:
			return self.send_json({}, 404)
		self.send_response(200)
		self.send_header("Content-Type", "application/octet-stream")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)

	def send_image(self, path="", q=None):
		data = JPEG
		if self.state.demo:
			from demo_data import artwork
			parts = path.split("/")
			item = self.state.lib.items.get(parts[2], {"Id": parts[2]})
			itype = parts[4] if len(parts) > 4 else "Primary"
			mw, mh = int((q or {}).get("maxwidth", 400)), int((q or {}).get("maxheight", 600))
			if itype == "Primary" and parts[2].startswith("dp"):
				w = min(mw, mh * 2 // 3)
				data = artwork(item, "person", w, w * 3 // 2)
			elif itype == "Primary" and item.get("Type") in ("Movie", "Series", "Season", "BoxSet"):
				w = min(mw, mh * 2 // 3)
				data = artwork(item, "poster", w, w * 3 // 2)
			else:
				w = min(mw, mh * 16 // 9)
				data = artwork(item, "episode" if item.get("Type") == "Episode" else "backdrop", w, w * 9 // 16)
		self.send_response(200)
		self.send_header("Content-Type", "image/jpeg")
		self.send_header("Content-Length", str(len(data)))
		self.end_headers()
		self.wfile.write(data)

	def items_query(self, q):
		lib = self.state.lib
		if q.get("ids"):
			ids = q["ids"].split(",")
			items = [lib.items[i] for i in ids if i in lib.items]
			return self.send_json({"Items": items, "TotalRecordCount": len(items)})
		parent = q.get("parentid")
		recursive = q.get("recursive") == "true"
		if q.get("searchterm"):
			term = q["searchterm"].lower()
			fuzzy = getattr(self.state, "fuzzy_search", False)  # like servers that also return "similar" titles
			items = [it for it in lib.items.values() if (fuzzy or term in it.get("Name", "").lower()) and it.get("Type") not in ("CollectionFolder", "Season")]
		elif q.get("namestartswith"):
			term = q["namestartswith"].lower()
			items = [it for it in lib.items.values() if it.get("Name", "").lower().startswith(term) and it.get("Type") not in ("CollectionFolder", "Season")]
		elif parent:
			items = lib.descendants(parent) if recursive else lib.children(parent)
		elif q.get("personids") or q.get("artistids"):
			items = [it for it in lib.items.values() if it.get("Type") == "Movie"][:3]
		else:
			items = [it for it in lib.items.values() if it.get("Type") not in ("CollectionFolder",)]
		types = q.get("includeitemtypes")
		if types:
			allowed = types.split(",")
			items = [it for it in items if it.get("Type") in allowed]
		f = q.get("filters")
		if f == "IsFavorite":
			items = [it for it in items if (it.get("UserData") or {}).get("IsFavorite")]
		elif f == "IsPlayed":
			items = [it for it in items if (it.get("UserData") or {}).get("Played")]
		elif f == "IsUnplayed":
			items = [it for it in items if not (it.get("UserData") or {}).get("Played")]
		if q.get("genreids"):
			gname = genre_name(q["genreids"])
			items = [it for it in items if gname in (it.get("Genres") or [])]
		if q.get("genres"):
			wanted = q["genres"].split("|")
			items = [it for it in items if set(wanted) & set(it.get("Genres") or [])]
		if q.get("minpremieredate"):
			items = [it for it in items if (it.get("PremiereDate") or "") >= q["minpremieredate"][:19]]
		if q.get("mincommunityrating"):
			items = [it for it in items if (it.get("CommunityRating") or 0) >= float(q["mincommunityrating"])]
		self.state.item_queries.append(q)
		if q.get("searchterm") and not q.get("sortby"):
			# like Jellyfin: relevance (title starts with the term first) when no sort order is given
			term = q["searchterm"].lower()
			items.sort(key=lambda i: (not i.get("Name", "").lower().startswith(term), i.get("Name", "")))
		sort = q.get("sortby") or ("" if q.get("searchterm") else "SortName")
		first = sort.split(",")[0]
		desc = q.get("sortorder") == "Descending"
		if "IndexNumber" in sort:
			items.sort(key=lambda i: (i.get("ParentIndexNumber") or 0, i.get("IndexNumber") or 0))
		elif first == "Random":
			random.shuffle(items)
		elif first in ("DateCreated", "PremiereDate", "CommunityRating"):
			items.sort(key=lambda i: i.get(first) or ("" if first != "CommunityRating" else 0), reverse=desc)
		elif first == "DateLastContentAdded":
			items.sort(key=lambda i: i.get("DateLastMediaAdded") or "", reverse=desc)
		elif first:
			items.sort(key=lambda i: i.get("Name", ""), reverse=desc)
		total = len(items)
		start = int(q.get("startindex", 0))
		limit = int(q.get("limit", 100000))
		return self.send_json({"Items": items[start:start + limit], "TotalRecordCount": total, "StartIndex": start})

	def playback_info(self, item_id, body, q):
		st = self.state
		it = st.lib.items.get(item_id)
		if not it:
			return self.send_json({}, 404)
		st.playback_infos.append(body)
		prof = (body or {}).get("DeviceProfile") or {}
		sources = []
		for ms in it.get("MediaSources") or []:
			ms = json.loads(json.dumps(ms))
			v = [s for s in ms["MediaStreams"] if s["Type"] == "Video"]
			a = [s for s in ms["MediaStreams"] if s["Type"] == "Audio"]
			ok = body.get("EnableDirectPlay", True)
			dp = [p for p in prof.get("DirectPlayProfiles", []) if p["Type"] == ("Audio" if it.get("MediaType") == "Audio" else "Video")]
			if not dp:
				ok = False
			else:
				p = dp[0]
				if v and v[0]["Codec"] not in p.get("VideoCodec", "").split(","):
					ok = False
				ai = body.get("AudioStreamIndex")
				sel = [s for s in a if s["Index"] == ai] or a[:1]
				if sel and p.get("AudioCodec") and sel[0]["Codec"] not in p["AudioCodec"].split(","):
					ok = False
				for cp in prof.get("CodecProfiles", []):
					if v and cp.get("Codec") == v[0]["Codec"]:
						for c in cp["Conditions"]:
							if c["Property"] == "Width" and v[0]["Width"] > int(c["Value"]):
								ok = False
			ms["SupportsDirectPlay"] = ok
			ms["SupportsDirectStream"] = ok
			if not ok:
				tp = [t for t in prof.get("TranscodingProfiles", []) if t["Context"] == "Streaming" and t["Type"] == "Video"][0]
				if tp["Protocol"] == "hls":
					ms["TranscodingUrl"] = "/videos/%s/master.m3u8?DeviceId=dev&MediaSourceId=%s&VideoCodec=h264&AudioCodec=ac3&PlaySessionId=ps-%s&ApiKey=%s" % (item_id, ms["Id"], item_id, TOKEN)
				else:
					ms["TranscodingUrl"] = "/videos/%s/stream.ts?DeviceId=dev&MediaSourceId=%s&VideoCodec=h264&AudioCodec=ac3&PlaySessionId=ps-%s&StartTimeTicks=%s&ApiKey=%s" % (item_id, ms["Id"], item_id, body.get("StartTimeTicks", 0), TOKEN)
				ms["TranscodingSubProtocol"] = tp["Protocol"]
				ms["TranscodingContainer"] = "ts"
			sources.append(ms)
		return self.send_json({"MediaSources": sources, "PlaySessionId": "ps-%s" % item_id})


def start_server(version="10.10.3", demo=False):
	state = State(version, demo)
	handler = type("H", (Handler,), {"state": state})
	srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
	t = threading.Thread(target=srv.serve_forever, daemon=True)
	t.start()
	return srv, state, "http://127.0.0.1:%d" % srv.server_address[1]
