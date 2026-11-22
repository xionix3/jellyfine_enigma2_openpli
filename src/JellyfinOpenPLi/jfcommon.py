# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 xionix
# Jellyfin for Enigma2 - shared screen helpers
from __future__ import absolute_import

from .jfi18n import _, ngettext

from enigma import ePoint

from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.ProgressBar import ProgressBar
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Tools.LoadPixmap import LoadPixmap

from . import jfconfig
from .jfasync import runner
from .jfimages import image_ref, loader
from .jfskin import S
from .jfutil import child_count_text, display_title, is_new, is_played, played_percentage, unplayed_count
from .jflog import log


def load_pixmap(path):
	if not path:
		return None
	try:
		return LoadPixmap(path)
	except Exception as e:
		log("LoadPixmap failed for %s: %s" % (path, e))
		return None


class JFScreen(Screen):
	"""Base class: async tasks bound to the screen, status overlay, helpers."""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.cl = jfconfig.client()
		self.tasks = runner().group()
		self.images = loader(self.cl)
		self.jf_closed = False
		self.busy = 0
		self._jf_timers = []
		# pictures that are still loading appear together (one repaint) instead of one after the other
		self._reveal_waiting = 0
		self._reveal_queue = []
		self._reveal_timer = None
		# full screen gradients etc.: widget name -> PNG, decoded once per session (skin pixmaps are not cached)
		self.static_layers = {}
		self.onClose.append(self.__jf_on_close)
		self.onLayoutFinish.append(self.__jf_apply_item_heights)
		self.onLayoutFinish.append(self.__jf_static_layers)

	def __jf_static_layers(self):
		from .jfskin import img
		for name, png in self.static_layers.items():
			if name in self:
				set_widget_pixmap(self, name, img(png))

	def __jf_apply_item_heights(self):
		# the skin's itemHeight may differ from what a list needs (e.g. album vs. episode rows)
		for comp in list(self.values()):
			h = getattr(comp, "jf_item_height", None)
			if h:
				try:
					comp.l.setItemHeight(S(h))
				except Exception:
					pass

	def __jf_on_close(self):
		self.jf_closed = True
		self.tasks.cancel()
		for t in self._jf_timers:
			t.stop()
		self._jf_timers = []
		if self._reveal_timer is not None:
			self._reveal_timer.stop()
		self._reveal_queue = []

	# longest time a loaded picture waits for the others of the same screen
	REVEAL_HOLD_MS = 300

	def _reveal_expect(self):
		self._reveal_waiting = max(0, self._reveal_waiting) + 1

	def _reveal(self, fn):
		"""A picture arrived: show it together with the others that are still loading (at most REVEAL_HOLD_MS)."""
		self._reveal_queue.append(fn)
		self._reveal_waiting -= 1
		if self._reveal_waiting <= 0:
			self._reveal_flush()
		elif self._reveal_timer is None or not self._reveal_timer.isActive():
			if self._reveal_timer is None:
				from enigma import eTimer
				self._reveal_timer = eTimer()
				self._reveal_timer.callback.append(self._reveal_flush)
			self._reveal_timer.start(self.REVEAL_HOLD_MS, True)

	def _reveal_flush(self):
		if self._reveal_timer is not None:
			self._reveal_timer.stop()
		queue, self._reveal_queue = self._reveal_queue, []
		self._reveal_waiting = 0
		if self.jf_closed:
			return
		for fn in queue:
			fn()

	def add_keys(self, red="", green="", yellow="", blue="", hint=None):
		for name, text in (("key_red", red), ("key_green", green), ("key_yellow", yellow), ("key_blue", blue)):
			self[name] = Label(text)
		if hint is not None:
			self["key_hint"] = Label(hint)

	def run(self, fn, *args, **kwargs):
		"""Run fn in a worker; callbacks only fire while the screen is open."""
		callback = kwargs.pop("callback", None)
		errback = kwargs.pop("errback", None)
		status = kwargs.pop("status", None)
		if status:
			self.set_busy(True, status)

		def ok(res):
			if status:
				self.set_busy(False)
			if not self.jf_closed and callback:
				callback(res)

		def fail(err):
			if status:
				self.set_busy(False)
			if self.jf_closed:
				return
			if errback:
				errback(err)
			else:
				self.show_error(err)

		return self.tasks.run(fn, *args, callback=ok, errback=fail, **kwargs)

	def later(self, ms, fn):
		"""Run fn on the GUI thread after ms (e.g. give the server time to process a stop report)."""
		from enigma import eTimer
		t = eTimer()

		def fire():
			self._jf_timers.remove(t)
			if not self.jf_closed:
				fn()
		t.callback.append(fire)
		self._jf_timers.append(t)
		t.start(ms, True)

	def set_busy(self, busy, text=None):
		self.busy = max(0, self.busy + (1 if busy else -1))
		text = _("Lade ...") if text is None else text
		if "status" not in self:
			return
		if self.busy:
			self["status"].setText(text)
			self["status"].show()
		else:
			self["status"].hide()

	def set_status(self, text):
		if "status" not in self:
			return
		if text:
			self["status"].setText(text)
			self["status"].show()
		else:
			self["status"].hide()

	def show_error(self, err, title=None):
		title = _("Fehler") if title is None else title
		msg = str(err) or err.__class__.__name__
		if getattr(err, "status", None) == 401:
			msg += _("\n\nBitte im Hauptmenü des Plugins neu anmelden (rote Taste).")
		self.session.open(MessageBox, "%s:\n%s" % (title, msg), MessageBox.TYPE_ERROR, timeout=10)

	def info(self, text, timeout=3):
		self.session.open(MessageBox, text, MessageBox.TYPE_INFO, timeout=timeout)

	def set_pixmap(self, name, path):
		if self.jf_closed or name not in self:
			return False
		ptr = load_pixmap(path)
		widget = self[name]
		if ptr is None or widget.instance is None:
			widget.hide()
			return False
		widget.instance.setPixmap(ptr)
		widget.show()
		return True

	def load_image(self, name, item, kind, w, h, placeholder=None, keep=False):
		"""Show the picture of an item in a Pixmap widget (w/h in FHD units).

		Pictures are decoded off the GUI thread to exactly the widget size and kept in memory, so revisiting
		a card sets the pixmap at once. Nothing is hidden while a cached picture can be shown (no flicker);
		keep=True leaves the previous picture until the new one is ready (backdrops)."""
		ref = image_ref(item, kind) if item else None
		widget = self[name]
		ph = self[placeholder] if placeholder is not None and placeholder in self else None
		if not ref:
			widget.jf_token = None
			widget.hide()
			if ph is not None:
				ph.show()
			return
		token = (ref, S(w), S(h))
		if getattr(widget, "jf_token", None) == token and getattr(widget, "jf_shown", False):
			return  # already on screen
		widget.jf_token = token
		widget.jf_shown = False

		def show(ptr):
			if self.jf_closed or getattr(widget, "jf_token", None) != token:
				return
			if ptr is None or widget.instance is None:
				if not keep:
					widget.hide()
				return
			widget.instance.setPixmap(ptr)
			widget.jf_shown = True
			widget.show()
			if ph is not None:
				ph.hide()
		self._reveal_expect()
		ptr = self.images.pixmap(ref, S(w), S(h), lambda p: self._reveal(lambda: show(p)))
		if ptr is not None:
			self._reveal_waiting -= 1  # from the memory cache: no wait
			show(ptr)
			return
		if not keep:
			widget.hide()
			if ph is not None:
				ph.show()

	# --------------------------------------------------- user data toggles
	def toggle_played(self, item, callback=None):
		ud = item.setdefault("UserData", {})
		new = not ud.get("Played")

		def ok(res):
			if isinstance(res, dict) and res:
				item["UserData"].update(res)
			else:
				item["UserData"]["Played"] = new
				if new:
					item["UserData"]["PlaybackPositionTicks"] = 0
					item["UserData"]["PlayedPercentage"] = 0
			if callback:
				callback(item)
		self.run(self.cl.set_played, item["Id"], new, callback=ok)

	def toggle_favorite(self, item, callback=None):
		ud = item.setdefault("UserData", {})
		new = not ud.get("IsFavorite")

		def ok(res):
			if isinstance(res, dict) and res:
				item["UserData"].update(res)
			else:
				item["UserData"]["IsFavorite"] = new
			if callback:
				callback(item)
		self.run(self.cl.set_favorite, item["Id"], new, callback=ok)


def cell_sig(item):
	"""What a card shows - an unchanged signature means nothing has to be repainted."""
	if not item:
		return None
	ud = item.get("UserData") or {}
	return (item.get("Id"), item.get("Name"), item.get("_jf_more"), ud.get("Played"), ud.get("PlaybackPositionTicks"), ud.get("IsFavorite"),
		ud.get("UnplayedItemCount"), item.get("_jf_new_count"))


class CoverCells(object):
	"""A set of poster cells (placeholder, cover, progress, badges, label) on a screen."""

	def __init__(self, screen, prefix, count, w, h, badges=True, kind="poster"):
		self.screen = screen
		self.prefix = prefix
		self.count = count
		self.w = w
		self.h = h
		self.badges = badges
		self.kind = kind
		self.items = [None] * count
		self.sigs = [None] * count
		for i in range(count):
			screen[self.n("ph", i)] = Label("")
			screen[self.n("cover", i)] = Pixmap()
			screen[self.n("prog", i)] = ProgressBar()
			if badges:
				screen[self.n("seen", i)] = Pixmap()  # badge PNG from the skin
				screen[self.n("new", i)] = Pixmap()
				screen[self.n("count", i)] = Label("")
			screen[self.n("label", i)] = Label("")

	def n(self, kind, i):
		return "%s%s%d" % (self.prefix, kind, i)

	def clear(self, i):
		s = self.screen
		self.items[i] = None
		self.sigs[i] = None
		s[self.n("ph", i)].hide()
		s[self.n("cover", i)].hide()
		s[self.n("prog", i)].hide()
		if self.badges:
			s[self.n("seen", i)].hide()
			s[self.n("new", i)].hide()
			s[self.n("count", i)].hide()
		s[self.n("label", i)].setText("")
		widget = s[self.n("cover", i)]
		widget.jf_token = None
		widget.jf_shown = False

	def clear_all(self):
		for i in range(self.count):
			self.clear(i)

	def set_item(self, i, item):
		s = self.screen
		if item is None:
			if self.sigs[i] is not None or self.items[i] is not None:
				self.clear(i)
			return
		key = cell_sig(item)
		if key == self.sigs[i]:
			self.items[i] = item  # same card -> no repaint
			return
		self.items[i] = item
		self.sigs[i] = key
		title = display_title(item)
		s[self.n("label", i)].setText(title)
		s[self.n("ph", i)].setText(title)
		pct = played_percentage(item)
		played = is_played(item)
		prog = s[self.n("prog", i)]
		if 0 < pct < 100 and not played and not item.get("_jf_new_count") and item.get("Type") not in ("Series", "Season", "BoxSet", "Folder", "CollectionFolder"):
			prog.setValue(pct)
			prog.show()
		else:
			prog.hide()
		if self.badges:
			seen = s[self.n("seen", i)]
			new = s[self.n("new", i)]
			cnt = s[self.n("count", i)]
			unplayed = unplayed_count(item) if item.get("Type") in ("Series", "Season", "BoxSet", "Folder") else 0
			fresh = item.get("_jf_new_count")
			if played and jfconfig.get_bool("show_played"):
				seen.show()
				new.hide()
			else:
				seen.hide()
				if fresh or is_new(item, jfconfig.get_int("new_days", 7)):
					new.show()
				else:
					new.hide()
			if fresh and fresh > 1:
				cnt.setText("+%d" % fresh if fresh < 100 else "99+")
				cnt.show()
			elif unplayed and not played:
				cnt.setText(str(unplayed) if unplayed < 100 else "99+")
				cnt.show()
			else:
				cnt.hide()
		s.load_image(self.n("cover", i), item, self.kind, self.w, self.h, placeholder=self.n("ph", i))


def make_list(fonts=((28,),), item_height=58):
	"""MenuList with MultiContent; fonts = sizes (FHD) for font index 0..n."""
	from enigma import eListboxPythonMultiContent, gFont
	from Components.MenuList import MenuList
	lst = MenuList([], enableWrapAround=True, content=eListboxPythonMultiContent)
	for idx, f in enumerate(fonts):
		size = f[0] if isinstance(f, tuple) else f
		lst.l.setFont(idx, gFont("Regular", S(size)))
	lst.l.setItemHeight(S(item_height))
	lst.jf_item_height = item_height
	return lst


def text_row(data, text, width, height, value=None, value_width=0, x=18, color=None, value_color=None):
	"""Single-line row: text on the left, optional value right aligned (FHD units)."""
	from enigma import RT_HALIGN_LEFT, RT_HALIGN_RIGHT, RT_VALIGN_CENTER
	from Components.MultiContent import MultiContentEntryText
	row = [data]
	tw = width - x * 2 - (value_width + 10 if value is not None else 0)
	sel = 0xffffff  # selected rows have the accent background -> always white text
	row.append(MultiContentEntryText(pos=(S(x), 0), size=(S(tw), S(height)), font=0, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER, text=text,
		color=color, color_sel=sel if color is not None else None))
	if value is not None:
		row.append(MultiContentEntryText(pos=(S(width - x - value_width), 0), size=(S(value_width), S(height)), font=1,
			flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER, text=value, color=value_color, color_sel=sel if value_color is not None else None))
	return row


def prefetch_posters(screen, items, w, h, kind="poster", decode=True):
	"""Download and decode pictures that are about to become visible (rest of a row, next grid page)."""
	for it in items:
		ref = image_ref(it, kind)
		if ref:
			screen.images.prefetch(ref, S(w), S(h), decode)


def _ignore(*args):
	pass


def move_widget(screen, name, x, y):
	w = screen[name]
	if w.instance is not None:
		w.instance.move(ePoint(S(x), S(y)))


def set_text_color(screen, name, rgb):
	"""Change a label's text colour at runtime (pills: dark text on the white focus pill)."""
	from enigma import gRGB
	w = screen[name]
	if w.instance is not None:
		w.instance.setForegroundColor(gRGB(rgb))
		w.instance.invalidate()


_STATIC = {}


def set_widget_pixmap(screen, name, path):
	"""Swap the picture of a Pixmap widget to a static skin PNG (decoded once)."""
	w = screen[name]
	ptr = _STATIC.get(path)
	if ptr is None:
		ptr = _STATIC[path] = load_pixmap(path)
	if ptr is not None and w.instance is not None:
		w.instance.setPixmap(ptr)


SEP = "   ·   "


def hero_meta(item):
	"""(meta line, is_new) for hero/detail headers: year, runtime, rating, seasons, resume ..."""
	from .jfutil import episode_code, fmt_clock, fmt_rating, fmt_runtime, resume_ticks, ticks_to_seconds
	parts = []
	t = item.get("Type")
	fresh = item.get("_jf_new_count")
	new = bool(fresh) or is_new(item, jfconfig.get_int("new_days", 7))
	if fresh:
		parts.append(ngettext("%d neue Folge", "%d neue Folgen", fresh) % fresh)
	if t == "Episode":
		code = episode_code(item)
		name = item.get("Name") or ""
		parts.append(("%s  %s" % (code, name)).strip())
	elif item.get("ProductionYear"):
		parts.append(str(item["ProductionYear"]))
	rt = fmt_runtime(item.get("RunTimeTicks"))
	if rt and t not in ("Series", "Season", "BoxSet", "MusicAlbum", "Folder"):
		parts.append(rt)
	if item.get("OfficialRating"):
		parts.append(item["OfficialRating"])
	r = fmt_rating(item.get("CommunityRating"))
	if r:
		parts.append(_("Bewertung %s") % r)
	if t in ("Series", "Season", "BoxSet", "MusicAlbum", "Folder") and item.get("ChildCount"):
		parts.append(child_count_text(t, item["ChildCount"]))
	pos = resume_ticks(item)
	if pos and not is_played(item):
		parts.append(_("fortsetzen bei %s") % fmt_clock(ticks_to_seconds(pos)))
	elif is_played(item) and t not in ("Series", "Season", "BoxSet"):
		parts.append(_("gesehen"))
	return SEP.join(p for p in parts if p), new


def play_label(item):
	"""Text of the primary pill for an item."""
	from .jfutil import resume_ticks
	t = item.get("Type")
	if t in ("BoxSet", "Folder", "CollectionFolder", "Playlist", "Person", "MusicArtist"):
		return _("Öffnen")
	focus = item.get("_jf_focus")
	if focus:
		return _("Neue Folge")
	if resume_ticks(item) and not is_played(item):
		return _("Fortsetzen")
	return _("Abspielen")
