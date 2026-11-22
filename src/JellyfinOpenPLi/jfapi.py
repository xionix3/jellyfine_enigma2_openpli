# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Jellyfin for Enigma2 - REST client (pure python, no enigma imports)
#
# Supports Jellyfin 10.8 ... 10.11+.  Routes that moved in 10.9
# (/Users/{id}/... -> /UserItems, /UserViews, ...) are chosen by server version.
from __future__ import absolute_import

from .jfi18n import _

import json
import socket
import time

try:
	import ssl
except ImportError:  # pragma: no cover - minimal images without python3-ssl
	ssl = None

import threading

try:
	import http.client as httplib
	from urllib.parse import urlencode, urljoin, urlsplit
except ImportError:  # pragma: no cover - python 2 fallback
	import httplib
	from urllib import urlencode
	from urlparse import urljoin, urlsplit

CLIENT_NAME = "Jellyfin Enigma2"
CLIENT_VERSION = "1.5.0"

SEARCH_TYPES = "Movie,Series,Episode,BoxSet,MusicAlbum,MusicVideo,Video,MusicArtist,Audio"
LIST_FIELDS = "Overview,Genres,PrimaryImageAspectRatio,ChildCount,DateCreated,DateLastMediaAdded,MediaSourceCount,SeriesPrimaryImage"
# only real ItemFields values (ProductionYear, ratings ... are always returned)
DETAIL_FIELDS = ("Overview,Genres,People,Studios,Taglines,MediaSources,MediaStreams,ProviderIds,OriginalTitle,"
	"ChildCount,RecursiveItemCount,DateCreated,RemoteTrailers,Chapters,SeriesPrimaryImage")
EPISODE_FIELDS = "Overview,PrimaryImageAspectRatio,MediaSources,MediaStreams,DateCreated,SeriesPrimaryImage"

HIDDEN_COLLECTION_TYPES = ("books", "photos", "livetv", "folders_hidden")


class JellyfinError(Exception):
	def __init__(self, message, status=None):
		from .jflog import redact
		message = redact(message)  # messages end up in dialogs and logs that users share
		Exception.__init__(self, message)
		self.message = message
		self.status = status

	def __str__(self):
		return self.message


def normalize_server(url):
	url = (url or "").strip()
	if not url:
		return ""
	if "://" not in url:
		url = "http://" + url
	# users often paste the web-ui address
	for marker in ("/web/", "/web#", "/#"):
		pos = url.find(marker)
		if pos > 0:
			url = url[:pos]
	if url.endswith("/web"):
		url = url[:-4]
	return url.rstrip("/")


def parse_version(text):
	parts = []
	for p in (text or "").split("."):
		digits = "".join(ch for ch in p if ch.isdigit())
		parts.append(int(digits) if digits else 0)
	while len(parts) < 3:
		parts.append(0)
	return tuple(parts[:3])


def discover_servers(timeout=2.0):
	"""Jellyfin LAN auto discovery (UDP broadcast on port 7359)."""
	found = {}
	sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	try:
		sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
		sock.settimeout(0.5)
		msg = b"Who is JellyfinServer?"
		for target in ("255.255.255.255", "<broadcast>"):
			try:
				sock.sendto(msg, (target, 7359))
			except Exception:
				pass
		end = time.time() + timeout
		while time.time() < end:
			try:
				data, addr = sock.recvfrom(4096)
			except socket.timeout:
				continue
			except Exception:
				break
			try:
				info = json.loads(data.decode("utf-8", "replace"))
			except ValueError:
				continue
			address = info.get("Address") or "http://%s:8096" % addr[0]
			key = info.get("Id") or address
			found[key] = {"Name": info.get("Name") or address, "Address": normalize_server(address), "Id": info.get("Id")}
	finally:
		sock.close()
	return list(found.values())


class JellyfinClient(object):
	def __init__(self, server="", device_id="", device_name="Enigma2", token="", user_id="", user_name="", verify_ssl=True, timeout=20):
		self.server = normalize_server(server)
		self.device_id = device_id or "enigma2"
		self.device_name = device_name or "Enigma2"
		self.token = token or ""
		self.user_id = user_id or ""
		self.user_name = user_name or ""
		self.verify_ssl = verify_ssl
		self.timeout = timeout
		self.server_version = (0, 0, 0)
		self.server_name = ""
		self.server_id = ""
		self._local = threading.local()

	# ------------------------------------------------------------------ http
	def auth_header(self):
		def esc(v):
			return (v or "").replace('"', "'").replace(",", " ")
		parts = [
			'Client="%s"' % esc(CLIENT_NAME),
			'Device="%s"' % esc(self.device_name),
			'DeviceId="%s"' % esc(self.device_id),
			'Version="%s"' % CLIENT_VERSION,
		]
		if self.token:
			parts.append('Token="%s"' % self.token)
		return "MediaBrowser " + ", ".join(parts)

	def _ssl_context(self):
		if self.verify_ssl or ssl is None:
			return None
		try:
			return ssl._create_unverified_context()
		except Exception:
			return None

	def build_url(self, path, params=None):
		url = self.server + path
		if params:
			clean = []
			for k, v in params.items():
				if v is None:
					continue
				if isinstance(v, bool):
					v = "true" if v else "false"
				elif isinstance(v, (list, tuple)):
					v = ",".join(str(x) for x in v)
				clean.append((k, v))
			if clean:
				url += ("&" if "?" in url else "?") + urlencode(clean)
		return url

	# keep-alive connections, one set per worker thread (saves TCP/TLS handshakes)
	def _connection(self, scheme, host, port, timeout):
		conns = self._local.__dict__.setdefault("conns", {})
		key = (scheme, host, port, bool(self.verify_ssl))
		conn = conns.get(key)
		if conn is not None:
			return conn, False
		if scheme == "https":
			ctx = None
			if ssl is not None:
				ctx = ssl.create_default_context() if self.verify_ssl else ssl._create_unverified_context()
			conn = httplib.HTTPSConnection(host, port, timeout=timeout, context=ctx)
		else:
			conn = httplib.HTTPConnection(host, port, timeout=timeout)
		conns[key] = conn
		return conn, True

	def _drop_connection(self, scheme, host, port):
		conns = self._local.__dict__.setdefault("conns", {})
		conn = conns.pop((scheme, host, port, bool(self.verify_ssl)), None)
		if conn is not None:
			try:
				conn.close()
			except Exception:
				pass

	def _http(self, method, url, data, headers, timeout, redirects=3):
		"""Returns (status, payload, final_url). Follows redirects, reuses connections."""
		for hop in range(redirects + 1):
			parts = urlsplit(url)
			scheme = (parts.scheme or "http").lower()
			host = parts.hostname
			port = parts.port or (443 if scheme == "https" else 80)
			path = parts.path or "/"
			if parts.query:
				path += "?" + parts.query
			for attempt in (0, 1):
				conn, fresh = self._connection(scheme, host, port, timeout)
				try:
					if conn.sock is not None:
						conn.sock.settimeout(timeout)
					else:
						conn.timeout = timeout
					conn.request(method, path, body=data, headers=headers)
					resp = conn.getresponse()
					payload = resp.read()
					status = resp.status
					location = resp.getheader("Location")
					if resp.will_close:
						self._drop_connection(scheme, host, port)
					break
				except socket.timeout:
					self._drop_connection(scheme, host, port)
					raise
				except (httplib.HTTPException, OSError):
					self._drop_connection(scheme, host, port)
					if attempt == 0 and not fresh:
						continue  # stale keep-alive connection, retry once on a new one
					raise
			if status in (301, 302, 303, 307, 308) and location and hop < redirects:
				url = urljoin(url, location)
				if status == 303 or (status in (301, 302) and method == "POST"):
					method, data = "GET", None
				continue
			return status, payload, url
		return status, payload, url

	def _base_headers(self, accept="application/json"):
		auth = self.auth_header()
		hdrs = {
			"Accept": accept,
			"Accept-Encoding": "identity",
			"Authorization": auth,
			"X-Emby-Authorization": auth,
			"User-Agent": "%s/%s" % (CLIENT_NAME.replace(" ", ""), CLIENT_VERSION),
		}
		if self.token:
			hdrs["X-Emby-Token"] = self.token
		return hdrs

	def request(self, method, path, params=None, body=None, timeout=None, headers=None, raw=False, want_url=False):
		if not self.server:
			raise JellyfinError(_("Kein Server konfiguriert"))
		url = self.build_url(path, params)
		data = None
		hdrs = self._base_headers()
		if body is not None:
			data = json.dumps(body).encode("utf-8")
			hdrs["Content-Type"] = "application/json"
		elif method == "POST":
			data = b""
		if headers:
			hdrs.update(headers)
		try:
			status, payload, final_url = self._http(method, url, data, hdrs, timeout or self.timeout)
		except socket.timeout:
			raise JellyfinError(_("Zeitüberschreitung bei der Verbindung zum Server"))
		except Exception as e:
			text = str(e)
			if (ssl is not None and isinstance(e, ssl.SSLError)) or "CERTIFICATE" in text.upper():
				raise JellyfinError(_("SSL-Fehler: %s (SSL-Prüfung in den Einstellungen deaktivierbar)") % text)
			if isinstance(e, (httplib.HTTPException, OSError)):
				raise JellyfinError(_("Server nicht erreichbar: %s") % (text or e.__class__.__name__))
			raise
		if status >= 400:
			detail = (payload or b"")[:300].decode("utf-8", "replace")
			if status == 401:
				raise JellyfinError(_("Nicht autorisiert (401) - bitte erneut anmelden"), 401)
			if status == 403:
				raise JellyfinError(_("Zugriff verweigert (403)"), 403)
			if status == 404:
				raise JellyfinError(_("Nicht gefunden (404): %s") % path, 404)
			raise JellyfinError(_("HTTP %s: %s") % (status, detail), status)
		if raw:
			return payload
		result = None
		if payload and status != 204:
			try:
				result = json.loads(payload.decode("utf-8"))
			except ValueError:
				result = None
		if want_url:
			return result, final_url
		return result

	def get(self, path, **params):
		return self.request("GET", path, params=params)

	def post(self, path, body=None, **params):
		return self.request("POST", path, params=params, body=body)

	def delete(self, path, **params):
		return self.request("DELETE", path, params=params)

	@property
	def new_api(self):
		return self.server_version >= (10, 9, 0)

	@property
	def logged_in(self):
		return bool(self.server and self.token and self.user_id)

	# ------------------------------------------------------------------ server/auth
	def public_info(self):
		info, final_url = self.request("GET", "/System/Info/Public", timeout=10, want_url=True)
		info = info or {}
		if not info.get("Id") and not info.get("Version"):
			raise JellyfinError(_("Unter dieser Adresse antwortet kein Jellyfin-Server"))
		# follow a permanent move (e.g. http -> https reverse proxy)
		suffix = "/System/Info/Public"
		if final_url and suffix in final_url:
			base = final_url[:final_url.index(suffix)]
			if base and base != self.server:
				self.server = normalize_server(base)
		self.server_version = parse_version(info.get("Version"))
		self.server_name = info.get("ServerName") or ""
		self.server_id = info.get("Id") or ""
		return info

	def _apply_auth(self, res):
		if not res or not res.get("AccessToken"):
			raise JellyfinError(_("Anmeldung fehlgeschlagen"))
		self.token = res["AccessToken"]
		user = res.get("User") or {}
		self.user_id = user.get("Id") or ""
		self.user_name = user.get("Name") or ""
		return res

	def authenticate(self, username, password):
		self.token = ""
		try:
			res = self.post("/Users/AuthenticateByName", {"Username": username, "Pw": password or ""})
		except JellyfinError as e:
			if e.status in (400, 401):
				raise JellyfinError(_("Benutzername oder Passwort falsch"), e.status)
			raise
		return self._apply_auth(res)

	def quickconnect_enabled(self):
		try:
			return bool(self.get("/QuickConnect/Enabled"))
		except JellyfinError:
			return False

	def quickconnect_initiate(self):
		self.token = ""
		try:
			res = self.post("/QuickConnect/Initiate")
		except JellyfinError as e:
			if e.status in (404, 405):  # 10.8 used GET
				res = self.get("/QuickConnect/Initiate")
			elif e.status == 401:
				raise JellyfinError(_("Quick Connect ist auf dem Server deaktiviert"), 401)
			else:
				raise
		if not res or not res.get("Secret"):
			raise JellyfinError(_("Quick Connect konnte nicht gestartet werden"))
		return res

	def quickconnect_check(self, secret):
		res = self.get("/QuickConnect/Connect", secret=secret) or {}
		return bool(res.get("Authenticated"))

	def quickconnect_authenticate(self, secret):
		res = self.post("/Users/AuthenticateWithQuickConnect", {"Secret": secret})
		return self._apply_auth(res)

	def validate_session(self):
		if self.server_version == (0, 0, 0):
			self.public_info()
		try:
			me = self.get("/Users/Me")
		except JellyfinError as e:
			if e.status == 404:
				me = self.get("/Users/%s" % self.user_id)
			else:
				raise
		if me:
			self.user_id = me.get("Id") or self.user_id
			self.user_name = me.get("Name") or self.user_name
		return me

	def report_capabilities(self):
		body = {
			"PlayableMediaTypes": ["Video", "Audio"],
			"SupportedCommands": [],
			"SupportsMediaControl": False,
			"SupportsPersistentIdentifier": True,
		}
		try:
			self.post("/Sessions/Capabilities/Full", body)
		except JellyfinError:
			pass

	def logout(self):
		try:
			self.post("/Sessions/Logout")
		except JellyfinError:
			pass
		self.token = ""
		self.user_id = ""

	# ------------------------------------------------------------------ library
	def _user_path(self, new_path, old_path):
		return new_path if self.new_api else old_path % self.user_id

	def views(self):
		path = self._user_path("/UserViews", "/Users/%s/Views")
		res = self.get(path, userId=self.user_id if self.new_api else None) or {}
		out = []
		for v in res.get("Items") or []:
			if (v.get("CollectionType") or "").lower() in HIDDEN_COLLECTION_TYPES:
				continue
			out.append(v)
		return out

	def items(self, **params):
		params.setdefault("fields", LIST_FIELDS)
		params.setdefault("enableImageTypes", "Primary,Backdrop,Thumb")
		params.setdefault("imageTypeLimit", 1)
		params.setdefault("enableTotalRecordCount", True)
		if self.new_api:
			params["userId"] = self.user_id
			res = self.get("/Items", **params)
		else:
			res = self.get("/Users/%s/Items" % self.user_id, **params)
		return res or {"Items": [], "TotalRecordCount": 0}

	def resume(self, limit=24, media_type="Video", **extra):
		params = dict(limit=limit, mediaTypes=media_type, fields=LIST_FIELDS, enableImageTypes="Primary,Backdrop,Thumb", imageTypeLimit=1, enableTotalRecordCount=False)
		params.update(extra)
		if self.new_api:
			res = self.get("/UserItems/Resume", userId=self.user_id, **params)
		else:
			res = self.get("/Users/%s/Items/Resume" % self.user_id, **params)
		return (res or {}).get("Items") or []

	def next_up(self, limit=24, series_id=None, **extra):
		params = dict(userId=self.user_id, limit=limit, seriesId=series_id, fields=LIST_FIELDS,
			enableImageTypes="Primary,Backdrop,Thumb", imageTypeLimit=1, enableTotalRecordCount=False)
		params.update(extra)
		res = self.get("/Shows/NextUp", **params) or {}
		return res.get("Items") or []

	def latest(self, parent_id=None, limit=24, **extra):
		params = dict(parentId=parent_id, limit=limit, fields=LIST_FIELDS, enableImageTypes="Primary,Backdrop,Thumb", imageTypeLimit=1)
		params.update(extra)
		if self.new_api:
			res = self.get("/Items/Latest", userId=self.user_id, **params)
		else:
			res = self.get("/Users/%s/Items/Latest" % self.user_id, **params)
		if isinstance(res, dict):
			return res.get("Items") or []
		return res or []

	def item(self, item_id, fields=DETAIL_FIELDS):
		if self.new_api:
			return self.get("/Items/%s" % item_id, userId=self.user_id, fields=fields)
		return self.get("/Users/%s/Items/%s" % (self.user_id, item_id), fields=fields)

	def seasons(self, series_id):
		res = self.get("/Shows/%s/Seasons" % series_id, userId=self.user_id, fields="Overview,PrimaryImageAspectRatio,ChildCount", enableImageTypes="Primary,Thumb", imageTypeLimit=1) or {}
		return res.get("Items") or []

	def episodes(self, series_id, season_id=None):
		res = self.get("/Shows/%s/Episodes" % series_id, userId=self.user_id, seasonId=season_id, fields=EPISODE_FIELDS,
			enableImageTypes="Primary,Thumb", imageTypeLimit=1) or {}
		return res.get("Items") or []

	def children(self, parent_id, **params):
		params.setdefault("sortBy", "SortName")
		params.setdefault("sortOrder", "Ascending")
		return self.items(parentId=parent_id, **params)

	def album_tracks(self, album_id):
		res = self.items(parentId=album_id, includeItemTypes="Audio", recursive=True, sortBy="ParentIndexNumber,IndexNumber,SortName", fields="MediaSources")
		return res.get("Items") or []

	def similar(self, item_id, limit=24):
		res = self.get("/Items/%s/Similar" % item_id, userId=self.user_id, limit=limit, fields=LIST_FIELDS) or {}
		return res.get("Items") or []

	def search(self, term, types=None, limit=100):
		"""Exact title search: only items whose title really contains the term.

		Two queries: the server's search (searchTerm) and titles starting with the term (nameStartsWith),
		so an exact title is found even when the server ranks fuzzy hits first. Everything that does
		not contain the term in its title is dropped."""
		from .jfutil import strict_matches
		if types == "Person":
			return self.search_people(term)
		types = types or SEARCH_TYPES
		found = []
		seen = set()
		queries = [dict(searchTerm=term, limit=limit), dict(nameStartsWith=term.strip().lower(), sortBy="SortName", limit=50)]
		for i, q in enumerate(queries):
			try:
				res = self.items(recursive=True, includeItemTypes=types, enableTotalRecordCount=False, **q)
			except JellyfinError:
				if i == 0:
					raise
				continue
			for it in res.get("Items") or []:
				if it.get("Id") and it["Id"] not in seen:
					seen.add(it["Id"])
					found.append(it)
		return strict_matches(term, found)

	def search_people(self, term, limit=60):
		from .jfutil import strict_matches
		params = dict(searchTerm=term, limit=limit, enableImageTypes="Primary", imageTypeLimit=1, fields="PrimaryImageAspectRatio")
		if self.user_id:
			params["userId"] = self.user_id
		res = self.get("/Persons", **params) or {}
		people = [p for p in (res.get("Items") or []) if p.get("Id")]
		for p in people:
			p.setdefault("Type", "Person")
		return strict_matches(term, people)

	def genres(self, parent_id=None, item_types=None):
		res = self.get("/Genres", userId=self.user_id, parentId=parent_id, includeItemTypes=item_types, sortBy="SortName", sortOrder="Ascending") or {}
		return res.get("Items") or []

	def set_played(self, item_id, played=True):
		if self.new_api:
			path, params = "/UserPlayedItems/%s" % item_id, {"userId": self.user_id}
		else:
			path, params = "/Users/%s/PlayedItems/%s" % (self.user_id, item_id), {}
		return self.request("POST" if played else "DELETE", path, params=params)

	def set_favorite(self, item_id, favorite=True):
		if self.new_api:
			path, params = "/UserFavoriteItems/%s" % item_id, {"userId": self.user_id}
		else:
			path, params = "/Users/%s/FavoriteItems/%s" % (self.user_id, item_id), {}
		return self.request("POST" if favorite else "DELETE", path, params=params)

	def image_url(self, item_id, image_type="Primary", tag=None, max_width=None, max_height=None, quality=85):
		params = {"quality": quality, "format": "Jpg"}
		if max_width:
			params["maxWidth"] = int(max_width)
		if max_height:
			params["maxHeight"] = int(max_height)
		if tag:
			params["tag"] = tag
		return self.build_url("/Items/%s/Images/%s" % (item_id, image_type), params)

	def download(self, url, timeout=20):
		status, payload, _url = self._http("GET", url, None, self._base_headers("image/jpeg,image/png;q=0.8"), timeout)
		if status >= 400:
			raise JellyfinError(_("Bild nicht geladen (HTTP %s)") % status, status)
		return payload

	# ------------------------------------------------------------------ playback
	def playback_info(self, item_id, opts, start_ticks=0, audio_index=None, sub_index=None, media_source_id=None, force_transcode=False):
		mode = opts.get("mode", "auto")
		bitrate = int(opts.get("max_bitrate") or 0) or 200000000
		body = {
			"UserId": self.user_id,
			"DeviceProfile": build_device_profile(opts),
			"MaxStreamingBitrate": bitrate,
			"StartTimeTicks": int(start_ticks or 0),
			"EnableDirectPlay": mode != "transcode" and not force_transcode,
			"EnableDirectStream": mode != "transcode" and not force_transcode,
			"EnableTranscoding": True,
			"AllowVideoStreamCopy": True,
			"AllowAudioStreamCopy": True,
			"AutoOpenLiveStream": True,
		}
		if audio_index is not None:
			body["AudioStreamIndex"] = int(audio_index)
		if sub_index is not None:
			body["SubtitleStreamIndex"] = int(sub_index)
		if media_source_id:
			body["MediaSourceId"] = media_source_id
		res = self.post("/Items/%s/PlaybackInfo" % item_id, body, userId=self.user_id)
		if not res:
			raise JellyfinError(_("Keine Wiedergabeinformationen erhalten"))
		if res.get("ErrorCode"):
			codes = {
				"NotAllowed": _("Wiedergabe für diesen Benutzer nicht erlaubt"),
				"NoCompatibleStream": _("Kein kompatibler Stream verfügbar"),
				"RateLimitExceeded": _("Zu viele gleichzeitige Streams"),
			}
			raise JellyfinError(codes.get(res["ErrorCode"], _("Wiedergabefehler: %s") % res["ErrorCode"]))
		return res

	def resolve_stream(self, item, pbinfo, opts, media_source_id=None, force_transcode=False):
		"""Pick the URL Enigma2 should play. Returns dict."""
		sources = pbinfo.get("MediaSources") or []
		if not sources:
			raise JellyfinError(_("Das Element hat keine abspielbare Quelle"))
		ms = sources[0]
		if media_source_id:
			for s in sources:
				if s.get("Id") == media_source_id:
					ms = s
					break
		mode = opts.get("mode", "auto")
		item_id = item.get("Id")
		session_id = pbinfo.get("PlaySessionId") or ""
		is_audio = item.get("MediaType") == "Audio" or item.get("Type") == "Audio"
		result = {
			"media_source_id": ms.get("Id"),
			"play_session_id": session_id,
			"media_source": ms,
			"is_hls": False,
			"can_seek": True,
		}
		want_direct = not force_transcode and mode != "transcode"
		direct_ok = ms.get("SupportsDirectPlay") or (ms.get("SupportsDirectStream") and not ms.get("TranscodingUrl"))
		turl = ms.get("TranscodingUrl")
		if (want_direct and (mode == "direct" or direct_ok)) or (not turl and direct_ok):
			result["url"] = self.static_url(item_id, ms, session_id, is_audio)
			result["play_method"] = "DirectPlay"
			return result
		if not turl:
			raise JellyfinError(_("Der Server kann dieses Element nicht für die Box aufbereiten (Transcoding für den Benutzer deaktiviert?)"))
		if turl.startswith("http"):
			url = turl
		else:
			url = self.server + (turl if turl.startswith("/") else "/" + turl)
		low = url.lower()
		if "apikey=" not in low and "api_key=" not in low:
			url += ("&" if "?" in url else "?") + "api_key=" + self.token
		result["url"] = url
		result["play_method"] = "Transcode"
		result["is_hls"] = "m3u8" in low or (ms.get("TranscodingSubProtocol") or "").lower() == "hls"
		result["can_seek"] = result["is_hls"]
		return result

	def static_url(self, item_id, ms, session_id="", is_audio=False):
		container = (ms.get("Container") or "").split(",")[0].strip()
		path = ("/Audio/%s/stream" if is_audio else "/Videos/%s/stream") % item_id
		if container and not is_audio:
			path += "." + container
		params = {"static": "true", "MediaSourceId": ms.get("Id"), "DeviceId": self.device_id, "api_key": self.token}
		if session_id:
			params["PlaySessionId"] = session_id
		if ms.get("ETag"):
			params["Tag"] = ms.get("ETag")
		return self.build_url(path, params)

	def _report(self, path, body):
		try:
			self.post(path, body)
		except JellyfinError:
			pass

	def report_start(self, info):
		self._report("/Sessions/Playing", info)

	def report_progress(self, info):
		self._report("/Sessions/Playing/Progress", info)

	def report_stop(self, info):
		self._report("/Sessions/Playing/Stopped", info)

	def stop_encoding(self, play_session_id):
		try:
			self.delete("/Videos/ActiveEncodings", deviceId=self.device_id, playSessionId=play_session_id)
		except JellyfinError:
			pass

	# MediaSegmentType as numbers (older JSON serializers)
	SEGMENT_NAMES = ("Unknown", "Commercial", "Preview", "Recap", "Outro", "Intro")

	def media_segments(self, item_id, item_type=None):
		"""Skippable parts of a video: [(type, start_ticks, end_ticks)], type Intro/Recap/Preview/Outro/Commercial.

		Jellyfin 10.10+ media segments (filled by e.g. the Intro Skipper plugin); servers without them
		answer 404 -> the older Intro Skipper endpoint for episodes; nothing found -> []."""
		if not getattr(self, "segments_unsupported", False):
			try:
				res = self.get("/MediaSegments/%s" % item_id) or {}
				out = []
				for seg in res.get("Items") or []:
					kind = seg.get("Type")
					if isinstance(kind, int):
						kind = self.SEGMENT_NAMES[kind] if 0 <= kind < len(self.SEGMENT_NAMES) else "Unknown"
					start, end = int(seg.get("StartTicks") or 0), int(seg.get("EndTicks") or 0)
					if end > start:
						out.append((kind, start, end))
				return sorted(out, key=lambda s: s[1])
			except JellyfinError as e:
				if e.status != 404:
					return []
				self.segments_unsupported = True
		if item_type != "Episode":
			return []
		try:
			res = self.get("/Episode/%s/IntroTimestamps/v1" % item_id) or {}
		except JellyfinError:
			return []
		start, end = float(res.get("IntroStart") or 0), float(res.get("IntroEnd") or 0)
		if not res.get("Valid", True) or end <= start:
			return []
		return [("Intro", int(start * 10000000), int(end * 10000000))]


def build_device_profile(opts):
	"""DeviceProfile describing what an Enigma2 box (gstreamer/exteplayer3) can play."""
	max_width = int(opts.get("max_width") or 1920)
	max_height = 2160 if max_width > 1920 else (1080 if max_width > 1280 else 720)
	bitrate = int(opts.get("max_bitrate") or 0) or 200000000
	channels = str(opts.get("audio_channels") or 6)

	vcodecs = ["h264"]
	if opts.get("hevc", True):
		vcodecs.append("hevc")
	vcodecs += ["mpeg2video", "mpeg4", "msmpeg4v3"]
	if opts.get("vc1"):
		vcodecs.append("vc1")
	if opts.get("vp9"):
		vcodecs.append("vp9")
	acodecs = ["aac", "ac3", "eac3", "mp3", "mp2", "flac", "vorbis", "opus", "pcm_s16le", "pcm_s24le", "pcm_bluray", "lpcm"]
	if opts.get("dts"):
		acodecs += ["dts", "dca"]
	if opts.get("truehd"):
		acodecs.append("truehd")

	video_containers = "mkv,mp4,m4v,mov,ts,mpegts,m2ts,mts,avi,mpeg,mpg,vob,flv,3gp,webm"
	audio_containers = "mp3,aac,m4a,m4b,flac,ogg,oga,opus,wav,webma,wma,mka"
	trans_v = "h264,hevc" if opts.get("hevc", True) else "h264"
	protocol = "hls" if opts.get("protocol", "hls") == "hls" else "http"

	profile = {
		"Name": "%s %s" % (CLIENT_NAME, CLIENT_VERSION),
		"MaxStreamingBitrate": bitrate,
		"MaxStaticBitrate": max(bitrate, 100000000),
		"MusicStreamingTranscodingBitrate": 320000,
		"MaxStaticMusicBitrate": 100000000,
		"DirectPlayProfiles": [
			{"Type": "Video", "Container": video_containers, "VideoCodec": ",".join(vcodecs), "AudioCodec": ",".join(acodecs)},
			{"Type": "Audio", "Container": audio_containers, "AudioCodec": "mp3,aac,flac,vorbis,opus,alac,pcm_s16le,pcm_s24le,ac3,eac3,wmav2"},
		],
		"TranscodingProfiles": [
			{"Type": "Video", "Container": "ts", "VideoCodec": trans_v, "AudioCodec": "ac3,aac,mp3",
				"Protocol": protocol, "Context": "Streaming", "MaxAudioChannels": channels,
				"MinSegments": 1, "BreakOnNonKeyFrames": True, "CopyTimestamps": False},
			{"Type": "Audio", "Container": "mp3", "AudioCodec": "mp3", "Protocol": "http", "Context": "Streaming", "MaxAudioChannels": "2"},
			{"Type": "Video", "Container": "ts", "VideoCodec": trans_v, "AudioCodec": "ac3,aac,mp3", "Protocol": "http", "Context": "Static", "MaxAudioChannels": channels},
		],
		"ContainerProfiles": [],
		"CodecProfiles": [
			{"Type": "Video", "Codec": "h264", "Conditions": [
				{"Condition": "LessThanEqual", "Property": "Width", "Value": str(max_width), "IsRequired": False},
				{"Condition": "LessThanEqual", "Property": "Height", "Value": str(max_height), "IsRequired": False},
				{"Condition": "LessThanEqual", "Property": "VideoBitDepth", "Value": "8", "IsRequired": False},
				{"Condition": "LessThanEqual", "Property": "VideoLevel", "Value": "52", "IsRequired": False},
			]},
			{"Type": "Video", "Codec": "hevc", "Conditions": [
				{"Condition": "LessThanEqual", "Property": "Width", "Value": str(max_width), "IsRequired": False},
				{"Condition": "LessThanEqual", "Property": "Height", "Value": str(max_height), "IsRequired": False},
				{"Condition": "LessThanEqual", "Property": "VideoBitDepth", "Value": "10", "IsRequired": False},
			]},
			{"Type": "VideoAudio", "Conditions": [
				{"Condition": "LessThanEqual", "Property": "AudioChannels", "Value": "8", "IsRequired": False},
			]},
		],
		"SubtitleProfiles": [
			{"Format": "srt", "Method": "Embed"},
			{"Format": "subrip", "Method": "Embed"},
			{"Format": "ass", "Method": "Embed"},
			{"Format": "ssa", "Method": "Embed"},
			{"Format": "pgssub", "Method": "Encode"},
			{"Format": "pgs", "Method": "Encode"},
			{"Format": "dvdsub", "Method": "Encode"},
			{"Format": "dvbsub", "Method": "Encode"},
			{"Format": "vobsub", "Method": "Encode"},
			{"Format": "srt", "Method": "Encode"},
			{"Format": "subrip", "Method": "Encode"},
			{"Format": "ass", "Method": "Encode"},
			{"Format": "ssa", "Method": "Encode"},
			{"Format": "vtt", "Method": "Encode"},
			{"Format": "webvtt", "Method": "Encode"},
			{"Format": "mov_text", "Method": "Encode"},
			{"Format": "ttml", "Method": "Encode"},
		],
	}
	return profile


def make_play_report(item_id, stream, position_ticks=0, paused=False, audio_index=None, sub_index=None, failed=False):
	body = {
		"ItemId": item_id,
		"MediaSourceId": stream.get("media_source_id"),
		"PlaySessionId": stream.get("play_session_id"),
		"PositionTicks": int(position_ticks or 0),
		"IsPaused": bool(paused),
		"IsMuted": False,
		"PlayMethod": stream.get("play_method", "DirectPlay"),
		"CanSeek": bool(stream.get("can_seek", True)),
		"RepeatMode": "RepeatNone",
	}
	if audio_index is not None:
		body["AudioStreamIndex"] = audio_index
	if sub_index is not None:
		body["SubtitleStreamIndex"] = sub_index
	if failed:
		body["Failed"] = True
	return body
