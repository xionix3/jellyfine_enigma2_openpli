# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 xionix
# Jellyfin for Enigma2 - row screens (start screen, libraries, search): backdrop + info of the focused title,
# one row of 16:9 cards, up/down jumps between the rows ("folders"/categories), sidebar on the left.
from __future__ import absolute_import

from .jfi18n import _, N_, badge

import time

from enigma import eTimer

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Screens.ChoiceBox import ChoiceBox

from . import jfconfig, jfnav
from .jfcommon import CoverCells, JFScreen, cell_sig, hero_meta, move_widget, play_label, prefetch_posters, set_text_color
from .jfimages import image_ref
from .jfskin import (C_DIM, C_TEXT, CARD_COUNT, CARD_H, CARD_STEP, CARD_W, CARD_X0, CARD_Y, FRAME_PAD, HERO_RAIL, RAIL_STEP, RAIL_X,
	RAIL_Y0, S, rows_skin)
from .jfutil import clean_text

RAIL_KEYS = [k for k, _n in HERO_RAIL]
HERO_WIDGETS = ("hero_title", "hero_meta", "hero_genres", "hero_overview", "hero_pill1", "hero_pill2", "hero_pillbg1", "hero_pillbg2",
	"hero_icon1", "hero_icon2")


class Row(object):
	"""One row: title, worker function fetch(client, limit) -> items, what "Alle anzeigen" opens."""

	def __init__(self, key, title, fetch, more=None, count=False):
		self.key = key
		self.title = title
		self.fetch = fetch
		self.more = more  # grid spec (dict) or callable(screen, callback)
		self.count = count  # show the number of entries in the title (search)


sig = cell_sig


class RowsScreen(JFScreen):
	row_limit = 20
	cache_ttl = 300
	drop_empty = True  # rows without entries disappear (libraries, search)
	load_window = 3  # rows above/below the current one that are loaded ahead
	rail_self = None  # own entry in the sidebar

	def __init__(self, session, cache=None):
		JFScreen.__init__(self, session)
		self.skin = rows_skin()
		self.skinName = "JellyfinE2Rows"
		self.rows = []
		self.row = 0
		self.card = 0
		self.first = 0
		self.mode = "rows"
		self.rail = RAIL_KEYS.index(self.rail_self) if self.rail_self in RAIL_KEYS else 1
		self.row_items = []
		self.shown = None
		self.hero_shown = None
		self.cache = cache if cache is not None else {}
		self.loading = set()
		self.backdrops = jfconfig.get_bool("backdrops")
		for name in ("brand", "server", "hero_title", "hero_meta", "hero_genres", "hero_overview", "hero_pill1", "hero_pill2",
				"row_title", "row_count", "next_row", "more_rows", "status"):
			self[name] = Label("")
		for name in ("backdrop", "overlay", "rail_shade", "hero_new", "rail_sel", "frame", "hero_pillbg1", "hero_pillbg2", "hero_icon1", "hero_icon2"):
			self[name] = Pixmap()
		self.static_layers.update(overlay="hero_overlay.png", rail_shade="rail_overlay.png")
		for i, (_key, title) in enumerate(HERO_RAIL):
			self["rail_name%d" % i] = Label(_(title))
		self.cells = CoverCells(self, "c", CARD_COUNT, CARD_W, CARD_H, kind="card")
		self.add_keys(red=_("Alle anzeigen"), green=_("Suche"), yellow=_("Aktualisieren"), blue=_("Meine Listen"), hint=_("OK Details   ▶ Abspielen   MENU Optionen"))
		self.bd_timer = eTimer()
		self.bd_timer.callback.append(self.load_backdrop)
		self.load_timer = eTimer()
		self.load_timer.callback.append(self.ensure_loaded)
		self.onClose.append(self.bd_timer.stop)
		self.onClose.append(self.load_timer.stop)
		self["actions"] = ActionMap(["OkCancelActions", "DirectionActions", "ColorActions", "MenuActions", "ChannelSelectBaseActions",
			"EPGSelectActions", "InfobarSeekActions"], {
			"ok": self.key_ok,
			"cancel": self.key_cancel,
			"up": lambda: self.key_vertical(-1),
			"down": lambda: self.key_vertical(1),
			"upRepeated": lambda: self.key_vertical(-1),
			"downRepeated": lambda: self.key_vertical(1),
			"left": lambda: self.key_horizontal(-1),
			"right": lambda: self.key_horizontal(1),
			"leftRepeated": lambda: self.key_horizontal(-1),
			"rightRepeated": lambda: self.key_horizontal(1),
			"nextBouquet": lambda: self.key_horizontal(CARD_COUNT),
			"prevBouquet": lambda: self.key_horizontal(-CARD_COUNT),
			"red": self.key_all,
			"green": self.key_search,
			"yellow": self.key_refresh,
			"blue": self.key_rules,
			"menu": self.key_menu,
			"info": self.key_info,
			"playpauseService": self.key_play,
			"unPauseService": self.key_play,
		}, -1)
		self.onLayoutFinish.append(self.rows_layout)

	# ------------------------------------------------------------- setup
	def rows_layout(self):
		self["status"].hide()
		self["backdrop"].hide()
		self["hero_pill2"].setText(_("Details"))
		self.cells.clear_all()
		self["frame"].hide()
		self.show_rail(False)
		self["brand"].setText(self.brand_text())
		self["server"].setText(self.info_text())
		self.clear_hero(_("Lade ..."))
		self.rows_start()

	def rows_start(self):
		self.set_rows(self.build_rows())

	def brand_text(self):
		return "JELLYFIN"

	def info_text(self):
		return ""

	def build_rows(self):
		return []

	def set_rows(self, rows):
		"""Replace the rows, keep the position on the same row if it still exists."""
		cur = self.current()
		if self.drop_empty:
			# rows known to be empty (fresh in the cache) are left out right away
			now = time.time()
			rows = [r for r in rows if not (r.key in self.cache and not self.cache[r.key][1] and now - self.cache[r.key][0] < self.cache_ttl)]
		self.rows = list(rows)
		idx = 0
		if cur is not None:
			for i, r in enumerate(self.rows):
				if r.key == cur.key:
					idx = i
					break
			else:
				self.card = 0
				self.first = 0
		self.row = idx
		self.shown = None
		self.show_row()
		self.ensure_loaded()

	def current(self):
		if 0 <= self.row < len(self.rows):
			return self.rows[self.row]
		return None

	def cached(self, row):
		return self.cache.get(row.key) if row is not None else None

	# ------------------------------------------------------------- loading
	def ensure_loaded(self, force=False):
		"""Current row first, then the neighbours; far away rows load when the user gets close."""
		n = len(self.rows)
		order = [self.row]
		for d in range(1, n):
			for i in (self.row + d, self.row - d):
				if 0 <= i < n and (d <= self.load_window or self.load_window < 0):
					order.append(i)
		for i in order:
			if not 0 <= i < n:
				continue
			r = self.rows[i]
			c = self.cached(r)
			if force or c is None or time.time() - c[0] > self.cache_ttl:
				self.load_row(r)

	def load_row(self, row):
		if row.key in self.loading:
			return
		self.loading.add(row.key)
		limit = self.row_limit

		def ok(items):
			self.loading.discard(row.key)
			old = self.cache.get(row.key)
			self.cache[row.key] = (time.time(), items or [])
			self.row_loaded(row, items or [], old)

		def fail(err):
			self.loading.discard(row.key)
			cur = self.current()
			if cur is not None and cur.key == row.key and self.cached(row) is None:
				self.clear_hero(_("Fehler: %s") % err)
		self.run(row.fetch, self.cl, limit, callback=ok, errback=fail)

	def row_loaded(self, row, items, old):
		if not items and self.drop_empty and row in self.rows:
			idx = self.rows.index(row)
			self.rows.remove(row)
			if idx < self.row or (idx == self.row and self.row >= len(self.rows)):
				self.row = max(0, self.row - 1)
			if idx == self.row or not self.rows:
				self.card = 0
				self.first = 0
				self.shown = None
				self.show_row()
			else:
				self.update_row_labels()
			self.ensure_loaded()
			return
		cur = self.current()
		if cur is row:
			self.show_row()
		else:
			self.update_row_labels()
			# first cards of rows nearby are decoded in advance -> jumping up/down is instant
			prefetch_posters(self, items[:CARD_COUNT], CARD_W, CARD_H, kind="card")

	def key_refresh(self):
		self.cache.clear()
		self.shown = None
		self.ensure_loaded(force=True)

	def child_closed(self, result=None, *args):
		"""After details/player: user data may have changed -> refresh quietly (old cards stay until then)."""
		if isinstance(result, tuple) and result and result[0] == "rail":
			self.rail_action(result[1])
			return
		if result == "home":
			self.go_home()
			return
		self.later(1500, self.refresh_quietly)

	def refresh_quietly(self):
		for key, entry in list(self.cache.items()):
			self.cache[key] = (0, entry[1])
		self.set_rows(self.build_rows() + self.extra_rows())

	def extra_rows(self):
		return []

	# ------------------------------------------------------------- drawing
	def show_row(self):
		row = self.current()
		c = self.cached(row)
		if row is None:
			self.row_items = []
			self.cells.clear_all()
			self["frame"].hide()
			self.clear_hero(self.empty_text())
			self.update_row_labels()
			return
		if c is None:
			self.row_items = []
			self.cells.clear_all()
			self["frame"].hide()
			self.shown = None
			self.clear_hero(_("Lade ..."))
			self.update_row_labels()
			return
		items = list(c[1])
		if items and row.more is not None:
			items.append({"_jf_more": True, "Name": _("Alle anzeigen"), "Id": None})
		signature = (row.key, tuple(sig(i) for i in items))
		self.row_items = items
		if signature == self.shown:
			return
		self.shown = signature
		self.card = max(0, min(self.card, len(items) - 1))
		self.draw_cards()
		prefetch_posters(self, [i for i in c[1]], CARD_W, CARD_H, kind="card")

	def empty_text(self):
		return _("Keine Einträge")

	def draw_cards(self):
		n = len(self.row_items)
		if self.card < self.first:
			self.first = self.card
		elif self.card >= self.first + CARD_COUNT:
			self.first = self.card - CARD_COUNT + 1
		self.first = max(0, min(self.first, max(0, n - CARD_COUNT)))
		for i in range(CARD_COUNT):
			idx = self.first + i
			self.cells.set_item(i, self.row_items[idx] if idx < n else None)
		self.place_frame()
		self.update_hero()
		self.update_row_labels()

	def place_frame(self):
		if self.row_items and self.mode == "rows":
			move_widget(self, "frame", CARD_X0 + (self.card - self.first) * CARD_STEP - FRAME_PAD, CARD_Y - FRAME_PAD)
			self["frame"].show()
		else:
			self["frame"].hide()

	def update_row_labels(self):
		row = self.current()
		title = row.title if row else ""
		c = self.cached(row)
		if row is not None and row.count and c is not None:
			title = "%s  (%d)" % (title, len(c[1]))
		self["row_title"].setText(title)
		nxt = self.rows[self.row + 1:]
		self["next_row"].setText(nxt[0].title if nxt else "")
		self["more_rows"].setText("   ·   ".join(r.title for r in nxt[1:5]))
		real = len([i for i in self.row_items if not i.get("_jf_more")])
		self["row_count"].setText("%d / %d" % (self.card + 1, real) if real and self.card < real else "")

	def focused(self):
		if self.mode == "rows" and 0 <= self.card < len(self.row_items):
			return self.row_items[self.card]
		return None

	def clear_hero(self, text=""):
		row = self.current()
		self.hero_shown = None
		self["hero_title"].setText(row.title if row else "")
		self["hero_meta"].setText("")
		self["hero_genres"].setText("")
		self["hero_overview"].setText(text)
		self["hero_pill1"].setText(_("Öffnen"))
		self["hero_new"].hide()
		move_widget(self, "hero_meta", 160, 206)

	def update_hero(self):
		it = self.focused() or (self.row_items[0] if self.row_items else None)
		if it is None:
			self.clear_hero(self.empty_text())
			return
		key = sig(it)
		if key == self.hero_shown:
			return
		self.hero_shown = key
		row = self.current()
		if it.get("_jf_more"):
			real = len(self.row_items) - 1
			self["hero_title"].setText(row.title if row else "")
			self["hero_meta"].setText("")
			self["hero_new"].hide()
			move_widget(self, "hero_meta", 160, 206)
			self["hero_genres"].setText("")
			self["hero_overview"].setText(_("OK: alle Titel von '%s' anzeigen (hier die ersten %d).") % (row.title if row else "", real))
			self["hero_pill1"].setText(_("Alle anzeigen"))
			return
		t = it.get("Type")
		title = it.get("SeriesName") if t == "Episode" and it.get("SeriesName") else it.get("Name", "")
		focus = it.get("_jf_focus")
		meta, new = hero_meta(it)
		self["hero_title"].setText(title or "")
		self["hero_meta"].setText(meta if t != "Person" else _("Person"))
		if new and self.mode == "rows":
			self["hero_new"].show()
			move_widget(self, "hero_meta", 160 + badge("new")[1] + 12, 206)
		else:
			self["hero_new"].hide()
			move_widget(self, "hero_meta", 160, 206)
		self["hero_genres"].setText(", ".join((it.get("Genres") or [])[:4]))
		self["hero_overview"].setText(clean_text((focus or it).get("Overview") or it.get("Overview") or ""))
		self["hero_pill1"].setText(play_label(it))
		self.schedule_backdrop()

	# ------------------------------------------------------------- backdrop
	def schedule_backdrop(self, delay=300):
		"""Backdrop of the focused title: at once when it is decoded already or nothing is shown yet (screen
		opens -> appears together with the cards), otherwise after a short pause (no downloads while scrolling)."""
		if not self.backdrops:
			return
		self.bd_timer.stop()
		it = self.backdrop_item()
		ref = image_ref(it, "backdrop") if it is not None else None
		if ref is None:
			return
		if not getattr(self["backdrop"], "jf_shown", False) or self.images.has_pixmap(ref, S(1920), S(1080)):
			self.load_backdrop()
		else:
			self.bd_timer.start(delay, True)

	def backdrop_item(self):
		it = self.focused()
		if it is None and self.row_items:
			it = self.row_items[0]
		if it is None or it.get("_jf_more"):
			return None
		return it.get("_jf_focus") or it

	def load_backdrop(self):
		it = self.backdrop_item()
		if it is None or not image_ref(it, "backdrop"):
			return  # keep the last picture instead of a black screen
		self.load_image("backdrop", it, "backdrop", 1920, 1080, keep=True)
		# the next title's backdrop is decoded in advance, the ones around downloaded
		for d, decode in ((1, True), (2, False), (-1, False)):
			j = self.card + d
			if 0 <= j < len(self.row_items) and not self.row_items[j].get("_jf_more"):
				nb = self.row_items[j].get("_jf_focus") or self.row_items[j]
				self.images.prefetch(image_ref(nb, "backdrop"), S(1920), S(1080), decode)

	# ------------------------------------------------------------- sidebar
	def show_rail(self, on):
		"""Expanded sidebar: names next to the icons, hero text hidden underneath."""
		for i in range(len(HERO_RAIL)):
			w = self["rail_name%d" % i]
			w.show() if on else w.hide()
		for name in ("rail_sel", "rail_shade"):
			self[name].show() if on else self[name].hide()
		for name in HERO_WIDGETS:
			self[name].hide() if on else self[name].show()
		if on:
			self["hero_new"].hide()
		else:
			self.hero_shown = None

	def enter_rail(self):
		self.mode = "rail"
		self.rail = RAIL_KEYS.index(self.rail_self) if self.rail_self in RAIL_KEYS else 1
		self["frame"].hide()
		self.show_rail(True)
		self.draw_rail()

	def leave_rail(self):
		self.mode = "rows"
		self.show_rail(False)
		self.place_frame()
		self.update_hero()

	def draw_rail(self):
		y = RAIL_Y0 + self.rail * RAIL_STEP
		move_widget(self, "rail_sel", RAIL_X - 14, y - 14)
		for i in range(len(HERO_RAIL)):
			set_text_color(self, "rail_name%d" % i, C_TEXT if i == self.rail else C_DIM)

	def rail_action(self, key):
		"""Sub screens hand the sidebar over to the start screen (keeps the screen stack flat)."""
		if key == self.rail_self or (key == "home" and self.rail_self == "home"):
			self.go_home()
		elif key == "home":
			self.close("home")
		else:
			self.close(("rail", key))

	def go_home(self):
		if self.mode == "rail":
			self.leave_rail()
		if self.row or self.card:
			self.row = 0
			self.card = 0
			self.first = 0
			self.shown = None
			self.show_row()
			self.ensure_loaded()

	# ------------------------------------------------------------- keys
	def key_vertical(self, step):
		if self.mode == "rail":
			self.rail = (self.rail + step) % len(HERO_RAIL)
			self.draw_rail()
			return
		row = self.row + step
		# skip rows that are known to be empty
		while 0 <= row < len(self.rows):
			c = self.cached(self.rows[row])
			if c is None or c[1]:
				break
			row += step
		if not 0 <= row < len(self.rows):
			return
		self.row = row
		self.card = 0
		self.first = 0
		self.shown = None
		self.show_row()
		# loading of the rows around waits until the user stops jumping
		self.load_timer.stop()
		self.load_timer.start(250 if self.cached(self.current()) is not None else 0, True)

	def key_horizontal(self, step):
		if self.mode == "rail":
			if step > 0:
				self.leave_rail()
			return
		if step < 0 and self.card == 0:
			self.enter_rail()
			return
		n = len(self.row_items)
		if not n:
			return
		card = max(0, min(n - 1, self.card + step))
		if card == self.card:
			return
		self.card = card
		first = self.first
		if first <= card < first + CARD_COUNT:
			self.place_frame()  # only the frame moves, the cards stay
			self.update_hero()
			self.update_row_labels()
		else:
			self.draw_cards()

	def key_cancel(self):
		if self.mode == "rail":
			self.leave_rail()
		elif self.row > 0 or self.card > 0:
			self.go_home()
		else:
			self.close()

	def key_ok(self):
		if self.mode == "rail":
			self.rail_action(RAIL_KEYS[self.rail])
			return
		it = self.focused()
		if it is None:
			return
		if it.get("_jf_more"):
			self.key_all()
		else:
			real = [x for x in self.row_items if not x.get("_jf_more")]
			jfnav.open_item(self, it, real, self.card, callback=self.child_closed)

	def key_info(self):
		it = self.focused()
		if it is not None and not it.get("_jf_more") and it.get("Type") != "Person":
			jfnav.open_detail(self, it.get("_jf_focus") or it, self.child_closed)

	def key_play(self):
		it = self.focused()
		if it is None or it.get("_jf_more") or play_label(it) == _("Öffnen"):
			self.key_ok()
			return
		from .jfplayer import play_item
		play_item(self, it, [x for x in self.row_items if not x.get("_jf_more")], self.card, on_finished=self.child_closed)

	def key_all(self):
		row = self.current()
		if row is None or row.more is None:
			return
		if callable(row.more):
			row.more(self, self.child_closed)
		else:
			jfnav.open_grid(self, row.more, callback=self.child_closed)

	def key_search(self):
		self.rail_action("search")

	def key_rules(self):
		self.rail_action("lists")

	def key_settings(self):
		self.rail_action("settings")

	def key_menu(self):
		lst = [(_("Alle Titel dieser Reihe"), "all"), (_("Aktualisieren"), "refresh"), (_("Suche"), "search"), (_("Zur Startseite"), "home")]
		self.session.openWithCallback(self.rows_menu_chosen, ChoiceBox, title=self.brand_text().title(), list=lst)

	def rows_menu_chosen(self, choice=None):
		if choice is None:
			return
		a = choice[1]
		if a == "all":
			self.key_all()
		elif a == "refresh":
			self.key_refresh()
		elif a == "search":
			self.key_search()
		elif a == "home":
			self.rail_action("home")


# ------------------------------------------------------------------ libraries
TYPE_NAMES = {"movies": N_("Filme"), "tvshows": N_("Serien"), "music": N_("Musik"), "boxsets": N_("Sammlungen"), "homevideos": N_("Videos"),
	"musicvideos": N_("Musikvideos"), "mixed": N_("Gemischt")}


def _items(cl, n, **params):
	params.setdefault("recursive", True)
	params.setdefault("enableTotalRecordCount", False)
	params["limit"] = n
	return cl.items(**params).get("Items") or []


def _grid(title, params, sort=None):
	spec = {"title": title, "source": "items", "params": dict(params, recursive=True)}
	if sort:
		spec["sort"] = sort
	return spec


def library_rows(views, kind):
	"""Rows of a library (or of all libraries of one kind): folders/libraries, categories, genres."""
	ids = [v.get("Id") for v in views]
	parent = ids[0] if len(ids) == 1 else None
	pp = {"parentId": parent} if parent else {}
	rows = []
	if kind == "movies":
		t = "Movie"
		rows.append(Row("resume", _("Weiterschauen"), lambda cl, n: cl.resume(limit=n, includeItemTypes=t, **pp)))
		if len(views) > 1:
			for v in views:
				rows.append(Row(("lib", v["Id"]), v.get("Name", "?"), lambda cl, n, v=v: cl.latest(v["Id"], limit=n),
					more=lambda scr, cb, v=v: open_library(scr, [v], cb)))
		else:
			rows.append(Row("latest", _("Neu hinzugefügt"), lambda cl, n: cl.latest(parent, limit=n) if parent else
				_items(cl, n, includeItemTypes=t, sortBy="DateCreated", sortOrder="Descending"),
				more=_grid(_("Neu hinzugefügt"), dict(pp, includeItemTypes=t), "DateCreated")))
		rows.append(Row("released", _("Neu erschienen"), lambda cl, n: _items(cl, n, includeItemTypes=t, sortBy="PremiereDate,SortName",
			sortOrder="Descending", **pp), more=_grid(_("Neu erschienen"), dict(pp, includeItemTypes=t), "PremiereDate")))
		rows.append(Row("top", _("Ungesehen - am besten bewertet"), lambda cl, n: _items(cl, n, includeItemTypes=t, filters="IsUnplayed",
			sortBy="CommunityRating,SortName", sortOrder="Descending", minCommunityRating=6, **pp)))
		rows.append(Row("fav", _("Favoriten"), lambda cl, n: _items(cl, n, includeItemTypes=t, filters="IsFavorite", sortBy="DateCreated",
			sortOrder="Descending", **pp), more=_grid(_("Favoriten"), dict(pp, includeItemTypes=t, filters="IsFavorite"))))
	elif kind == "tvshows":
		t = "Series"
		rows.append(Row("nextup", _("Als Nächstes"), lambda cl, n: cl.next_up(limit=n, **pp)))
		if len(views) > 1:
			for v in views:
				rows.append(Row(("lib", v["Id"]), v.get("Name", "?"), lambda cl, n, v=v: cl.latest(v["Id"], limit=n),
					more=lambda scr, cb, v=v: open_library(scr, [v], cb)))
		else:
			rows.append(Row("latest", _("Neue Folgen"), lambda cl, n: cl.latest(parent, limit=n) if parent else
				_items(cl, n, includeItemTypes=t, sortBy="DateLastContentAdded", sortOrder="Descending")))
		rows.append(Row("updated", _("Zuletzt aktualisiert"), lambda cl, n: _items(cl, n, includeItemTypes=t, sortBy="DateLastContentAdded,SortName",
			sortOrder="Descending", **pp), more=_grid(_("Zuletzt aktualisiert"), dict(pp, includeItemTypes=t), "DateLastContentAdded")))
		rows.append(Row("newseries", _("Neue Serien"), lambda cl, n: _items(cl, n, includeItemTypes=t, sortBy="DateCreated,SortName",
			sortOrder="Descending", **pp), more=_grid(_("Neue Serien"), dict(pp, includeItemTypes=t), "DateCreated")))
		rows.append(Row("fav", _("Favoriten"), lambda cl, n: _items(cl, n, includeItemTypes=t, filters="IsFavorite", sortBy="SortName", **pp),
			more=_grid(_("Favoriten"), dict(pp, includeItemTypes=t, filters="IsFavorite"))))
	else:
		# other libraries: newest + one row per folder
		rows.append(Row("latest", _("Neu hinzugefügt"), lambda cl, n: cl.latest(parent, limit=n) if parent else []))
	return rows


def genre_rows(genres, kind, views):
	ids = [v.get("Id") for v in views]
	pp = {"parentId": ids[0]} if len(ids) == 1 else {}
	t = {"movies": "Movie", "tvshows": "Series", "music": "MusicAlbum"}.get(kind)
	rows = []
	for g in genres:
		gid = g.get("Id")
		if not gid:
			continue
		params = dict(pp, genreIds=gid)
		if t:
			params["includeItemTypes"] = t
		rows.append(Row(("genre", gid), g.get("Name", "?"), lambda cl, n, p=params: _items(cl, n, sortBy="DateCreated,SortName",
			sortOrder="Descending", **p), more=_grid(g.get("Name", "?"), params, "DateCreated")))
	return rows


def folder_rows(folders):
	rows = []
	for f in folders:
		rows.append(Row(("folder", f["Id"]), f.get("Name", "?"), lambda cl, n, f=f: _items(cl, n, parentId=f["Id"], recursive=False,
			sortBy="IsFolder,DateCreated,SortName", sortOrder="Descending"),
			more={"title": f.get("Name", "?"), "source": "items", "params": {"parentId": f["Id"]}}))
	return rows


class LibraryRowsScreen(RowsScreen):
	"""Movies, shows or any library like the start screen: up/down jumps through folders, categories and genres."""
	load_window = 4

	def __init__(self, session, views, kind=None):
		self.views = list(views)
		self.kind = kind or ((self.views[0].get("CollectionType") or "").lower() if self.views else "")
		self.rail_self = {"movies": "movies", "tvshows": "tv"}.get(self.kind)
		RowsScreen.__init__(self, session)

	def brand_text(self):
		if len(self.views) == 1:
			return _("JELLYFIN  ·  %s") % (self.views[0].get("Name") or "").upper()
		return _("JELLYFIN  ·  %s") % _(TYPE_NAMES.get(self.kind, "")).upper()

	def info_text(self):
		return _("▲▼ Kategorie   ◀▶ Titel")

	def build_rows(self):
		return library_rows(self.views, self.kind)

	def rows_start(self):
		RowsScreen.rows_start(self)
		cl = self.cl
		views = self.views
		kind = self.kind
		parent = views[0]["Id"] if len(views) == 1 else None
		types = {"movies": "Movie", "tvshows": "Series", "music": "MusicAlbum"}.get(kind)

		def extra():
			out = []
			if kind not in ("movies", "tvshows") and parent:
				res = cl.items(parentId=parent, recursive=False, sortBy="SortName", limit=40, enableTotalRecordCount=False).get("Items") or []
				out += folder_rows([f for f in res if f.get("IsFolder")][:15])
			if kind in ("movies", "tvshows", "music"):
				out += genre_rows(cl.genres(parent, types), kind, views)
			title = {"movies": _("Alle Filme A-Z"), "tvshows": _("Alle Serien A-Z")}.get(kind) or _("Alle Titel A-Z")
			params = {"parentId": parent} if parent else {}
			if types:
				params["includeItemTypes"] = types
			out.append(Row("az", title, lambda cl, n: _items(cl, n, sortBy="SortName", **params), more=_grid(title, params, "SortName")))
			return out

		def ok(rows):
			self.extra = rows
			self.set_rows(self.build_rows() + rows)
		self.run(extra, callback=ok, errback=lambda e: None)

	def extra_rows(self):
		return getattr(self, "extra", [])


def open_library(screen, views, callback=None, kind=None):
	screen.session.openWithCallback(callback or (lambda *a: None), LibraryRowsScreen, views, kind)


# ------------------------------------------------------------------ search
SEARCH_GROUPS = [("Movie", N_("Filme")), ("Series", N_("Serien")), ("Episode", N_("Episoden")), ("BoxSet", N_("Sammlungen")),
	("MusicAlbum,MusicArtist,Audio,MusicVideo", N_("Musik")), ("Video", N_("Videos")), ("Person", N_("Personen"))]


class SearchRowsScreen(RowsScreen):
	"""Search results as rows per category; only titles that really contain the term."""
	rail_self = "search"
	load_window = -1  # all categories at once
	row_limit = 0

	def __init__(self, session, term):
		self.term = term
		RowsScreen.__init__(self, session)

	def brand_text(self):
		return _("SUCHE  ·  „%s“") % self.term

	def info_text(self):
		return _("▲▼ Kategorie   ◀▶ Titel")

	def empty_text(self):
		return _("Keine Treffer für „%s“.") % self.term if not self.loading else _("Suche ...")

	def build_rows(self):
		term = self.term
		rows = []
		for types, title in SEARCH_GROUPS:
			title = _(title)
			rows.append(Row(("search", types), title, lambda cl, n, t=types: cl.search(term, types=t), count=True,
				more=lambda scr, cb, t=types, title=title: scr.open_results(t, title, cb)))
		return rows

	def open_results(self, types, title, callback):
		c = self.cache.get(("search", types))
		items = c[1] if c else []
		jfnav.open_grid(self, {"title": _("%s: „%s“") % (title, self.term), "source": "static", "items": items, "sortable": False},
			callback=callback)

	def row_loaded(self, row, items, old):
		RowsScreen.row_loaded(self, row, items, old)
		if not self.rows and not self.loading:
			self.clear_hero(self.empty_text())

	def refresh_quietly(self):
		pass  # results stay; played/favourite marks are refreshed on the next search

	def rail_action(self, key):
		if key == "search":
			self.close(("rail", "search"))  # new search via the start screen keeps the stack flat
		else:
			RowsScreen.rail_action(self, key)
