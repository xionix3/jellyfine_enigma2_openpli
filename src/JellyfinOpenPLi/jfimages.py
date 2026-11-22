# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 xionix
# Jellyfin for Enigma2 - image pipeline: download (worker threads) -> file cache -> decode with ePicLoad
# (own thread, exact widget size, no scaling while painting) -> LRU cache of decoded pixmaps.
from __future__ import absolute_import

import os
import re
import threading
from collections import OrderedDict

try:
	from hashlib import md5 as _md5
except ImportError:  # pragma: no cover
	_md5 = None

from .jfasync import runner
from .jflog import log


def cache_location():
	try:
		from .jfconfig import cache_dir
		return cache_dir()
	except Exception:
		return "/tmp/jellyfine2", 80 * 1024 * 1024


def _ensure_dir():
	d = cache_location()[0]
	if not os.path.isdir(d):
		try:
			os.makedirs(d)
		except OSError:
			pass
	return d


def cleanup(max_bytes=None):
	"""Drop oldest files when the cache grows too large (runs in a worker)."""
	d, limit = cache_location()
	max_bytes = max_bytes or limit
	try:
		files = []
		total = 0
		for name in os.listdir(d):
			p = os.path.join(d, name)
			try:
				st = os.stat(p)
			except OSError:
				continue
			files.append((st.st_mtime, st.st_size, p))
			total += st.st_size
		if total <= max_bytes:
			return
		files.sort()
		for _mtime, size, p in files:
			try:
				os.remove(p)
			except OSError:
				pass
			total -= size
			if total <= max_bytes * 0.7:
				break
	except OSError:
		pass


def clear():
	d = cache_location()[0]
	try:
		for name in os.listdir(d):
			try:
				os.remove(os.path.join(d, name))
			except OSError:
				pass
	except OSError:
		pass


def image_ref(item, kind="poster"):
	"""Return (item_id, image_type, tag) for the best image of an item or None.

	kind: poster (2:3), thumb (16:9, falls back to the poster), landscape (16:9 only),
	backdrop (16:9 large), person (actor photo of a People entry or Person item)
	"""
	tags = item.get("ImageTags") or {}
	t = item.get("Type")
	if kind == "poster":
		if t == "Episode":
			if item.get("SeriesPrimaryImageTag") and item.get("SeriesId"):
				return (item["SeriesId"], "Primary", item["SeriesPrimaryImageTag"])
		if t == "Season" and not tags.get("Primary") and item.get("SeriesPrimaryImageTag") and item.get("SeriesId"):
			return (item["SeriesId"], "Primary", item["SeriesPrimaryImageTag"])
		if tags.get("Primary"):
			return (item["Id"], "Primary", tags["Primary"])
		if t == "Audio" and item.get("AlbumId") and item.get("AlbumPrimaryImageTag"):
			return (item["AlbumId"], "Primary", item["AlbumPrimaryImageTag"])
		return None
	if kind == "thumb":
		if tags.get("Primary") and t in ("Episode", "Video", "MusicVideo", "Audio"):
			return (item["Id"], "Primary", tags["Primary"])
		if tags.get("Thumb"):
			return (item["Id"], "Thumb", tags["Thumb"])
		if item.get("ParentThumbItemId") and item.get("ParentThumbImageTag"):
			return (item["ParentThumbItemId"], "Thumb", item["ParentThumbImageTag"])
		bd = item.get("BackdropImageTags") or []
		if bd:
			return (item["Id"], "Backdrop", bd[0])
		pb = item.get("ParentBackdropImageTags") or []
		if pb and item.get("ParentBackdropItemId"):
			return (item["ParentBackdropItemId"], "Backdrop", pb[0])
		if tags.get("Primary"):
			return (item["Id"], "Primary", tags["Primary"])
		return None
	if kind == "card":
		return image_ref(item, "landscape") or image_ref(item, "poster")
	if kind == "landscape":
		ref = image_ref(item, "thumb")
		if ref and ref[1] == "Primary" and t not in ("Episode", "Video", "MusicVideo"):
			return None
		return ref
	if kind == "person":
		tag = item.get("PrimaryImageTag") or tags.get("Primary")
		if tag and item.get("Id"):
			return (item["Id"], "Primary", tag)
		return None
	if kind == "backdrop":
		bd = item.get("BackdropImageTags") or []
		if bd:
			return (item["Id"], "Backdrop", bd[0])
		pb = item.get("ParentBackdropImageTags") or []
		if pb and item.get("ParentBackdropItemId"):
			return (item["ParentBackdropItemId"], "Backdrop", pb[0])
		if tags.get("Thumb"):
			return (item["Id"], "Thumb", tags["Thumb"])
		return None
	return None


BG_ARGB = "#FF0b0b10"  # letterbox colour when the picture has another aspect ratio


class PixCache(object):
	"""Decoded pictures by (file, w, h); bounded by pixel memory. Big pictures (backdrops) are limited separately."""

	def __init__(self, budget=40 * 1024 * 1024, big_limit=3):
		self.items = OrderedDict()
		self.used = 0
		self.budget = budget
		self.big_limit = big_limit

	def get(self, key):
		ptr = self.items.get(key)
		if ptr is not None:
			self.items.pop(key)
			self.items[key] = ptr
		return ptr

	def put(self, key, ptr):
		if ptr is None or key in self.items:
			return
		self.items[key] = ptr
		self.used += key[1] * key[2] * 4
		big = [k for k in self.items if k[1] * k[2] > 1000000]
		while len(big) > self.big_limit:
			self._drop(big.pop(0))
		while self.used > self.budget and len(self.items) > 1:
			self._drop(next(iter(self.items)))

	def _drop(self, key):
		if key in self.items:
			del self.items[key]
			self.used -= key[1] * key[2] * 4

	def clear(self):
		self.items.clear()
		self.used = 0


class Decoder(object):
	"""A few ePicLoad instances: JPEG/PNG decoding runs in their threads, results arrive on the GUI thread.

	ePicLoad cancels the callback of a running decode when it is started again, so every instance only
	gets a new file once it reported back."""

	def __init__(self, workers=3):
		self.idle = []
		self.busy = {}
		self.urgent = []  # LIFO: the picture asked for last is on screen now
		self.background = []  # FIFO: prefetch
		self.waiting = {}
		self.loaders = []
		try:
			from enigma import ePicLoad
		except ImportError:  # pragma: no cover
			ePicLoad = None
		for _i in range(workers if ePicLoad is not None else 0):
			pl = ePicLoad()
			pl.setPara((1, 1, 1, 1, 0, 1, BG_ARGB))  # keep aspect ratio, no ePicLoad cache, better resize
			pl.PictureData.get().append(lambda info, pl=pl: self._finished(pl))
			self.loaders.append(pl)
			self.idle.append(pl)

	def decode(self, path, w, h, callback, urgent=True):
		key = (path, w, h)
		waiters = self.waiting.get(key)
		if waiters is not None:
			waiters.append(callback)
			if urgent and key in self.background:
				self.background.remove(key)
				self.urgent.append(key)
			return
		self.waiting[key] = [callback]
		(self.urgent if urgent else self.background).append(key)
		self._pump()

	def _pump(self):
		while self.idle and (self.urgent or self.background):
			key = self.urgent.pop() if self.urgent else self.background.pop(0)
			pl = self.idle.pop()
			path, w, h = key
			self.busy[id(pl)] = key
			try:
				failed = pl.startDecode(path, w, h, True)
			except Exception as e:
				log("decode failed for %s: %s" % (path, e))
				failed = True
			if failed:
				self.busy.pop(id(pl), None)
				self.idle.append(pl)
				self._deliver(key, None)

	def _finished(self, pl):
		key = self.busy.pop(id(pl), None)
		ptr = None
		try:
			ptr = pl.getData()
		except Exception as e:
			log("getData failed: %s" % e)
		self.idle.append(pl)
		if key is not None:
			self._deliver(key, ptr)
		self._pump()

	def _deliver(self, key, ptr):
		for cb in self.waiting.pop(key, []):
			try:
				cb(ptr)
			except Exception as e:
				log("picture callback failed: %s" % e)


_pixcache = PixCache()
_decoder = None


def decoder():
	global _decoder
	if _decoder is None:
		_decoder = Decoder()
	return _decoder


def drop_pixmaps():
	"""Free decoded pictures (plugin closed)."""
	_pixcache.clear()


class ImageLoader(object):
	"""Downloads images (resized server side) and calls back with a local path."""

	def __init__(self, client):
		self.client = client
		self.inflight = {}
		self.lock = threading.Lock()
		self.counter = 0
		self.group = runner().group()  # never cancelled: in-flight downloads always finish
		_ensure_dir()

	def path_for(self, ref, w, h):
		item_id, image_type, tag = ref
		key = "%s_%s_%s_%dx%d" % (item_id, image_type, tag or "", int(w), int(h))
		if _md5 is not None:
			name = _md5(key.encode("utf-8")).hexdigest()
		else:
			name = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:200]
		return os.path.join(cache_location()[0], name)

	def cached(self, ref, w, h):
		base = self.path_for(ref, w, h)
		for ext in (".jpg", ".png"):
			if os.path.exists(base + ext):
				return base + ext
		return None

	def get(self, ref, w, h, callback, urgent=True):
		"""callback(path or None) on the GUI thread. Returns path immediately if cached.

		urgent: the picture is on screen now (downloaded before any prefetch)."""
		if not ref:
			return None
		hit = self.cached(ref, w, h)
		if hit:
			return hit
		base = self.path_for(ref, w, h)
		with self.lock:
			entry = self.inflight.get(base)
			if entry is not None:
				entry[0].append(callback)
				if urgent:
					runner().promote(entry[1])
				return None
			entry = self.inflight[base] = [[callback], None]
		url = self.client.image_url(ref[0], ref[1], ref[2], max_width=w, max_height=h)
		entry[1] = self.group.run(self._fetch, url, base, pool="image", urgent=urgent,
			callback=lambda p: self._done(base, p), errback=lambda e: self._done(base, None))
		return None

	def _fetch(self, url, base):
		data = self.client.download(url)
		if not data or len(data) < 64:
			return None
		if data[:3] == b"\xff\xd8\xff":
			ext = ".jpg"
		elif data[:8] == b"\x89PNG\r\n\x1a\n":
			ext = ".png"
		else:
			return None  # webp/gif/svg cannot be shown by LoadPixmap
		if not os.path.isdir(os.path.dirname(base)):
			_ensure_dir()
		tmp = base + ".part"
		with open(tmp, "wb") as f:
			f.write(data)
		os.rename(tmp, base + ext)
		self.counter += 1
		if self.counter % 150 == 0:
			cleanup()
		return base + ext

	def _done(self, base, path):
		with self.lock:
			waiters = self.inflight.pop(base, [[], None])[0]
		for cb in waiters:
			try:
				cb(path)
			except Exception as e:
				log("image callback failed: %s" % e)

	# ------------------------------------------------------------- decoded pictures
	def pixmap(self, ref, w, h, callback=None, urgent=True):
		"""Decoded picture of exactly w x h pixels (screen pixels).

		Returns it at once when it is in the memory cache, otherwise None and callback(ptr or None) later."""
		if not ref:
			return None
		key = ("%s/%s/%s" % ref, int(w), int(h))
		ptr = _pixcache.get(key)
		if ptr is not None:
			return ptr

		def decoded(ptr):
			if ptr is not None:
				_pixcache.put(key, ptr)
			if callback:
				callback(ptr)

		def have_file(path):
			if not path:
				if callback:
					callback(None)
				return
			decoder().decode(path, int(w), int(h), decoded, urgent)
		path = self.get(ref, w, h, have_file, urgent)
		if path:
			have_file(path)
		return None

	def has_pixmap(self, ref, w, h):
		return ref is not None and ("%s/%s/%s" % ref, int(w), int(h)) in _pixcache.items

	def prefetch(self, ref, w, h, decode=True):
		"""Warm the caches without a widget (next cards, next page ...)."""
		if not ref:
			return
		if decode:
			self.pixmap(ref, w, h, None, urgent=False)
		else:
			self.get(ref, w, h, lambda path: None, urgent=False)


_loader = None


def loader(client):
	global _loader
	if _loader is None or _loader.client is not client:
		_loader = ImageLoader(client)
	return _loader
