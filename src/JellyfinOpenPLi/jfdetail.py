# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 xionix
# Jellyfin for Enigma2 - detail page for movies, episodes and series: the picture stays visible, the description
# can be read completely, the cast (with photos) only appears when it is selected (down key or "Besetzung")
from __future__ import absolute_import

from .jfi18n import _, N_, badge, ngettext

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.ProgressBar import ProgressBar
from Components.ScrollLabel import ScrollLabel
from Screens.ChoiceBox import ChoiceBox

from . import jfconfig
from .jfcommon import SEP, JFScreen, move_widget, set_text_color, set_widget_pixmap
from .jfimages import image_ref
from .jfskin import (C_DARK, C_TEXT, CAST_COUNT, CAST_H, CAST_STEP, CAST_W, CAST_X0, CAST_Y, DETAIL_COL, DETAIL_LINES_Y, DETAIL_POSTER,
	DETAIL_TEXT_Y, FRAME_PAD, PILL_COUNT, S, detail_skin, img)
from .jfutil import (child_count_text, clean_text, episode_code, fmt_clock, fmt_ends_at, fmt_rating, fmt_runtime, is_favorite, is_new,
	is_played, lang_name, played_percentage, resume_ticks, stream_label, subtitle_line, ticks_to_seconds, video_label)

PLAYABLE = ("Movie", "Episode", "Video", "MusicVideo", "Trailer", "Recording", "Program", "TvChannel")
ROLES = {"Actor": N_("Darsteller"), "Director": N_("Regie"), "Writer": N_("Drehbuch"), "Producer": N_("Produktion"), "GuestStar": N_("Gaststar"),
	"Composer": N_("Musik")}
LABELS = {"resume": N_("Fortsetzen"), "start": N_("Abspielen"), "restart": N_("Von Anfang"), "tracks": N_("Audio & Untertitel"), "version": N_("Version"),
	"season": N_("Alle Episoden"), "series": N_("Zur Serie"), "nextup": N_("Weiterschauen"), "episodes": N_("Staffeln & Episoden"),
	"playseries": N_("Abspielen"), "played": N_("Gesehen"), "unplayed": N_("Ungesehen"), "fav": N_("Favorit"), "unfav": N_("Kein Favorit"),
	"similar": N_("Ähnliche Titel"), "cast": N_("Besetzung"), "castgrid": N_("Gesamte Besetzung"), "more": N_("Mehr ...")}


def cast_list(item):
	"""Actors first (with role), then directors/writers; each person only once."""
	people = item.get("People") or []
	order = {"Actor": 0, "GuestStar": 1, "Director": 2, "Writer": 3, "Producer": 4}
	seen = set()
	out = []
	for p in sorted(people, key=lambda p: order.get(p.get("Type"), 5)):
		pid = p.get("Id")
		if not pid or pid in seen:
			continue
		seen.add(pid)
		out.append(p)
	return out


def initials(name):
	parts = [w for w in (name or "").split() if w[:1].isalpha()]
	return "".join(w[0].upper() for w in parts[:2]) or "?"


def person_item(p):
	"""People entry -> Person item usable in a poster grid."""
	it = {"Id": p.get("Id"), "Name": p.get("Name", ""), "Type": "Person"}
	if p.get("PrimaryImageTag"):
		it["ImageTags"] = {"Primary": p["PrimaryImageTag"]}
	role = p.get("Role") or _(ROLES.get(p.get("Type"), ""))
	if role:
		it["Overview"] = role
	return it


def detail_lines(it):
	"""(facts, state, is_new): what the title is - and where the user stands with it."""
	t = it.get("Type")
	facts = []
	if t == "Episode":
		facts.append(episode_code(it))
	elif t == "Series":
		facts.append(subtitle_line(it))
	elif it.get("ProductionYear"):
		facts.append(str(it["ProductionYear"]))
	if t in PLAYABLE:
		facts.append(fmt_runtime(it.get("RunTimeTicks")))
	elif it.get("ChildCount") and t in ("Series", "Season", "BoxSet", "MusicAlbum", "Folder"):
		facts.append(child_count_text(t, it["ChildCount"]))
	facts.append(it.get("OfficialRating") or "")
	rating = fmt_rating(it.get("CommunityRating"))
	if rating:
		facts.append("\u2605 %s" % rating)
	if it.get("CriticRating"):
		facts.append(_("Kritiker %s%%") % it["CriticRating"])
	state = []
	fresh = it.get("_jf_new_count")
	if fresh:
		state.append(ngettext("%d neue Folge", "%d neue Folgen", fresh) % fresh)
	if t == "Series":
		state.append({"Continuing": _("laufend"), "Ended": _("beendet")}.get(it.get("Status"), ""))
	pos = resume_ticks(it)
	if is_played(it) and t not in ("Series", "Season", "BoxSet"):
		state.append(_("gesehen"))
	elif pos:
		state.append(_("fortsetzen bei %s") % fmt_clock(ticks_to_seconds(pos)))
	if t in PLAYABLE and it.get("RunTimeTicks"):
		state.append(fmt_ends_at(it["RunTimeTicks"], pos if not is_played(it) else 0) or "")
	if is_favorite(it):
		state.append(_("Favorit"))
	new = bool(fresh) or is_new(it, jfconfig.get_int("new_days", 7))
	return SEP.join(f for f in facts if f), SEP.join(s for s in state if s), new


class DetailScreen(JFScreen):
	def __init__(self, session, item):
		JFScreen.__init__(self, session)
		self.skin = detail_skin()
		self.skinName = "JellyfinE2Detail"
		self.item = item
		self.next_up = None
		self.audio_index = None
		self.sub_index = None
		self.source_id = None
		self.pills = []
		self.pill = 0
		self.cast = []
		self.cast_idx = 0
		self.cast_first = 0
		self.focus = "pills"
		self.loaded = False
		self["backdrop"] = Pixmap()
		self["poster"] = Pixmap()
		self["overlay"] = Pixmap()
		self.static_layers["overlay"] = "detail_overlay.png"
		self["badge"] = Pixmap()
		self["cast_frame"] = Pixmap()
		self["progress"] = ProgressBar()
		for name in ("crumb", "title", "meta", "genres", "state", "tech", "cast_title", "cast_hint", "status"):
			self[name] = Label("")
		self["title"].setText(item.get("Name", ""))
		self["overview"] = ScrollLabel("")
		for i in range(PILL_COUNT):
			self["pill%d" % i] = Pixmap()
			self["pilltxt%d" % i] = Label("")
		for i in range(CAST_COUNT):
			self["pph%d" % i] = Label("")
			self["pphoto%d" % i] = Pixmap()
			self["pname%d" % i] = Label("")
			self["prole%d" % i] = Label("")
		self.add_keys(red=_("Gesehen +/-"), green=_("Abspielen"), yellow=_("Audio / Untertitel"), blue=_("Favorit +/-"), hint=_("CH+/- Text blättern   MENU Optionen"))
		self["key_actions"] = ActionMap(["OkCancelActions", "DirectionActions", "ColorActions", "MenuActions", "ChannelSelectBaseActions",
			"EPGSelectActions", "InfobarSeekActions"], {
			"ok": self.key_ok,
			"cancel": self.close,
			"up": lambda: self.set_focus("pills"),
			"down": lambda: self.set_focus("cast"),
			"upRepeated": self["overview"].pageUp,
			"downRepeated": self["overview"].pageDown,
			"left": lambda: self.key_horizontal(-1),
			"right": lambda: self.key_horizontal(1),
			"leftRepeated": lambda: self.key_horizontal(-1),
			"rightRepeated": lambda: self.key_horizontal(1),
			"nextBouquet": self["overview"].pageDown,
			"prevBouquet": self["overview"].pageUp,
			"red": self.key_red,
			"green": self.key_green,
			"yellow": self.key_yellow,
			"blue": self.key_blue,
			"menu": self.key_menu,
			"info": self.key_menu,
			"playpauseService": self.key_green,
			"unPauseService": self.key_green,
		}, -1)
		self.onLayoutFinish.append(self.start)

	# ------------------------------------------------------------- data
	def start(self):
		self["progress"].hide()
		self["badge"].hide()
		self.show_cast(False)
		# the backdrop of the title the user came from is usually decoded already -> shown at once
		self.load_image("backdrop", self.item, "backdrop", 1920, 1080, keep=True)
		self.render()
		self.load()

	def load(self):
		item_id = self.item.get("Id")
		cl = self.cl
		is_series = self.item.get("Type") == "Series"

		def fetch():
			full = cl.item(item_id)
			nxt = None
			if is_series or (full and full.get("Type") == "Series"):
				try:
					lst = cl.next_up(limit=1, series_id=item_id)
					nxt = lst[0] if lst else None
				except Exception:
					nxt = None
			return full, nxt

		def ok(res):
			full, nxt = res
			if full:
				self.item = full
			self.next_up = nxt
			self.loaded = True
			self.render()

		def fail(err):
			self["status"].setText("")
			self.show_error(err)
		self.run(fetch, callback=ok, errback=fail)
		self["status"].setText(_("Lade Details ..."))

	def media_source(self):
		sources = self.item.get("MediaSources") or []
		if not sources:
			return {}
		if self.source_id:
			for s in sources:
				if s.get("Id") == self.source_id:
					return s
		return sources[0]

	def streams(self, kind):
		return [s for s in (self.media_source().get("MediaStreams") or self.item.get("MediaStreams") or []) if s.get("Type") == kind]

	def selected_audio(self):
		idx = self.audio_index
		if idx is None:
			idx = self.media_source().get("DefaultAudioStreamIndex")
		for s in self.streams("Audio"):
			if s.get("Index") == idx:
				return s
		audio = self.streams("Audio")
		return audio[0] if audio else None

	def selected_sub(self):
		idx = self.sub_index
		if idx is None:
			idx = self.media_source().get("DefaultSubtitleStreamIndex")
		if idx is None or idx < 0:
			return None
		for s in self.streams("Subtitle"):
			if s.get("Index") == idx:
				return s
		return None

	# ------------------------------------------------------------- drawing
	def render(self):
		it = self.item
		t = it.get("Type")
		self["status"].setText("")
		self["crumb"].setText(self.crumb_text())
		self["title"].setText(it.get("Name") or "")
		facts, state, new = detail_lines(it)
		# poster left; without one the text starts at the left edge
		col = DETAIL_COL if image_ref(it, "poster") else 120
		if col != getattr(self, "text_col", None):
			self.text_col = col
			move_widget(self, "genres", col, DETAIL_LINES_Y[1])
			move_widget(self, "state", col, DETAIL_LINES_Y[2])
			move_widget(self, "overview", col, DETAIL_TEXT_Y)
			move_widget(self, "badge", col, DETAIL_LINES_Y[0] + 8)
		if col == DETAIL_COL:
			self.load_image("poster", it, "poster", DETAIL_POSTER[2], DETAIL_POSTER[3])
		else:
			self["poster"].hide()
		self["meta"].setText(facts)
		if new:
			self["badge"].show()
			move_widget(self, "meta", col + badge("new")[1] + 12, DETAIL_LINES_Y[0])
		else:
			self["badge"].hide()
			move_widget(self, "meta", col, DETAIL_LINES_Y[0])
		self["genres"].setText(", ".join(it.get("Genres") or []))
		self["state"].setText(state)
		overview = clean_text(it.get("Overview"))
		if it.get("Taglines") and t != "Episode":
			overview = ("%s\n\n%s" % (it["Taglines"][0], overview)).strip()
		self["overview"].setText(overview or (_("Lade ...") if not self.loaded else _("Keine Beschreibung vorhanden.")))
		self["tech"].setText(self.tech_text())
		self.build_pills()
		pct = played_percentage(it)
		if 0 < pct < 100 and not is_played(it) and t in PLAYABLE and self.pills and self.pills[0] == "resume":
			self["progress"].setValue(pct)
			self["progress"].show()
		else:
			self["progress"].hide()
		self.cast = cast_list(it)
		self.cast_idx = min(self.cast_idx, max(0, len(self.cast) - 1))
		if not self.cast and self.focus == "cast":
			self.focus = "pills"
		if self.focus == "cast":
			self.draw_cast()
		elif self.cast:
			# photos are decoded in the background, so the cast row appears at once when selected
			for p in self.cast[:CAST_COUNT]:
				self.images.prefetch(image_ref(p, "person"), S(CAST_W), S(CAST_H))
		self.show_cast(self.focus == "cast")
		self.draw_focus()
		self.load_image("backdrop", it, "backdrop", 1920, 1080, keep=True)

	def crumb_text(self):
		it = self.item
		t = it.get("Type")
		if t == "Episode":
			return SEP.join(x for x in (it.get("SeriesName"), it.get("SeasonName")) if x)
		if t == "Series":
			studios = [s.get("Name") for s in (it.get("Studios") or [])][:2]
			return SEP.join([_("Serie")] + studios)
		if t == "Movie":
			parts = [_("Film")]
			if it.get("OriginalTitle") and it.get("OriginalTitle") != it.get("Name"):
				parts.append(it["OriginalTitle"])
			return SEP.join(parts)
		return {"MusicVideo": _("Musikvideo"), "Video": _("Video"), "Trailer": _("Trailer")}.get(t, t or "")

	def tech_text(self):
		it = self.item
		if it.get("Type") not in PLAYABLE:
			people = it.get("People") or []
			directors = [p.get("Name") for p in people if p.get("Type") == "Director"]
			return _("Regie: %s") % ", ".join(directors[:3]) if directors else ""
		parts = []
		video = self.streams("Video")
		ms = self.media_source()
		if video:
			parts.append(video_label(video[0]))
		if ms.get("Container"):
			parts.append(ms["Container"].split(",")[0].upper())
		if len(it.get("MediaSources") or []) > 1:
			parts.append(_("Version: %s") % (ms.get("Name") or "?"))
		audio = self.streams("Audio")
		if audio:
			sel = self.selected_audio()
			more = " (+%d)" % (len(audio) - 1) if len(audio) > 1 else ""
			parts.append(_("Audio: %s%s") % (stream_label(sel) if sel else "?", more))
		subs = self.streams("Subtitle")
		if subs:
			sel = self.selected_sub()
			langs = []
			for s in subs:
				name = lang_name(s.get("Language")) or s.get("DisplayTitle") or "?"
				if name not in langs:
					langs.append(name)
			parts.append(_("UT: %s (%d)") % (stream_label(sel) if sel else _("aus"), len(langs)))
		return SEP.join(parts)

	def actions(self):
		it = self.item
		t = it.get("Type")
		acts = []
		if t in PLAYABLE:
			if resume_ticks(it) and not is_played(it):
				acts += ["resume", "restart"]
			else:
				acts.append("start")
			if self.streams("Audio") or self.streams("Subtitle"):
				acts.append("tracks")
			if t == "Episode" and it.get("SeriesId"):
				acts.append("season")
		elif t == "Series":
			acts.append("nextup" if self.next_up else "playseries")
			acts.append("episodes")
		acts.append("unplayed" if is_played(it) else "played")
		acts.append("unfav" if is_favorite(it) else "fav")
		if t in ("Movie", "Series"):
			acts.append("similar")
		if t == "Episode" and it.get("SeriesId"):
			acts.append("series")
		if len(it.get("MediaSources") or []) > 1:
			acts.append("version")
		if self.cast or it.get("People"):
			acts.append("cast")
		return acts

	def pill_label(self, key):
		if key == "nextup" and self.next_up:
			code = episode_code(self.next_up)
			return _("%s ansehen") % code if code else _(LABELS["nextup"])
		return _(LABELS.get(key, key))

	def build_pills(self):
		acts = self.actions()
		if len(acts) > PILL_COUNT:
			acts = acts[:PILL_COUNT - 1] + ["more"]
		self.pills = acts
		self.pill = min(self.pill, len(acts) - 1) if acts else 0
		for i in range(PILL_COUNT):
			if i < len(acts):
				self["pilltxt%d" % i].setText(self.pill_label(acts[i]))
				self["pilltxt%d" % i].show()
				self["pill%d" % i].show()
			else:
				self["pilltxt%d" % i].setText("")
				self["pilltxt%d" % i].hide()
				self["pill%d" % i].hide()

	def draw_cast(self):
		n = len(self.cast)
		self["cast_title"].setText((_("Besetzung  (%d)") % n) if n > CAST_COUNT else (_("Besetzung") if n else ""))
		if self.cast_idx < self.cast_first:
			self.cast_first = self.cast_idx
		elif self.cast_idx >= self.cast_first + CAST_COUNT:
			self.cast_first = self.cast_idx - CAST_COUNT + 1
		for i in range(CAST_COUNT):
			idx = self.cast_first + i
			ph, photo, name, role = ("pph%d" % i, "pphoto%d" % i, "pname%d" % i, "prole%d" % i)
			if idx < n:
				p = self.cast[idx]
				self[ph].setText(initials(p.get("Name")))
				self[name].setText(p.get("Name") or "")
				self[role].setText(p.get("Role") or _(ROLES.get(p.get("Type"), "")))
				self.load_image(photo, p, "person", CAST_W, CAST_H, placeholder=ph)
			else:
				self[ph].hide()
				self[photo].hide()
				self[photo].jf_token = None
				self[name].setText("")
				self[role].setText("")

	def show_cast(self, on):
		"""Cast row and pills share the lower part of the page; the description above stays readable."""
		for i in range(CAST_COUNT):
			for name in ("pph%d" % i, "pphoto%d" % i, "pname%d" % i, "prole%d" % i):
				if not on:
					self[name].hide()
					self[name].jf_shown = False
				elif name.startswith(("pname", "prole")):
					self[name].show()
		self["cast_title"].show() if on else self["cast_title"].hide()
		self["cast_frame"].show() if on else self["cast_frame"].hide()
		for i in range(PILL_COUNT):
			used = i < len(self.pills)
			for name in ("pill%d" % i, "pilltxt%d" % i):
				self[name].show() if (used and not on) else self[name].hide()
		self["tech"].hide() if on else self["tech"].show()
		n = len(self.cast)
		self["cast_hint"].setText(_("\u25bc  Besetzung (%d): %s") % (n, ", ".join(p.get("Name", "") for p in self.cast[:4]) + (" ..." if n > 4 else "")) if n else "")
		self["cast_hint"].hide() if on or not n else self["cast_hint"].show()
		if on:
			self["progress"].hide()
		elif self.pills and self.pills[0] == "resume":
			pct = played_percentage(self.item)
			if 0 < pct < 100:
				self["progress"].setValue(pct)
				self["progress"].show()

	def draw_focus(self):
		primary = img("pill_primary.png")
		secondary = img("pill_secondary.png")
		for i in range(min(PILL_COUNT, len(self.pills))):
			on = self.focus == "pills" and i == self.pill
			set_widget_pixmap(self, "pill%d" % i, primary if on else secondary)
			set_text_color(self, "pilltxt%d" % i, C_DARK if on else C_TEXT)
		if self.focus == "cast" and self.cast:
			move_widget(self, "cast_frame", CAST_X0 + (self.cast_idx - self.cast_first) * CAST_STEP - FRAME_PAD, CAST_Y - FRAME_PAD)
			self["cast_frame"].show()
		else:
			self["cast_frame"].hide()

	# ------------------------------------------------------------- navigation
	def set_focus(self, focus):
		if focus == "cast" and not self.cast:
			self["overview"].pageDown()
			return
		if focus == self.focus:
			if focus == "pills":
				self["overview"].pageUp()
			return
		self.focus = focus
		if focus == "cast":
			self.draw_cast()
		self.show_cast(focus == "cast")
		self.draw_focus()

	def key_horizontal(self, step):
		if self.focus == "pills":
			if self.pills:
				self.pill = max(0, min(len(self.pills) - 1, self.pill + step))
				self.draw_focus()
		elif self.cast:
			idx = max(0, min(len(self.cast) - 1, self.cast_idx + step))
			if idx != self.cast_idx:
				first = self.cast_first
				self.cast_idx = idx
				if not first <= idx < first + CAST_COUNT:
					self.draw_cast()
				self.draw_focus()

	def key_ok(self):
		if self.focus == "cast" and self.cast:
			self.open_person(self.cast[self.cast_idx])
		elif self.pills:
			self.do(self.pills[self.pill])

	def open_person(self, p):
		from .jfnav import open_item
		open_item(self, {"Id": p.get("Id"), "Type": "Person", "Name": p.get("Name")}, callback=self.after_play)

	# ------------------------------------------------------------- actions
	def do(self, action):
		from . import jfnav
		from .jfplayer import play_item
		it = self.item
		opts = dict(on_finished=self.after_play, audio_index=self.audio_index, sub_index=self.sub_index, media_source_id=self.source_id)
		if action == "resume":
			play_item(self, it, resume=True, **opts)
		elif action in ("start", "restart"):
			play_item(self, it, resume=False, **opts)
		elif action == "tracks":
			self.key_yellow()
		elif action == "audio":
			self.choose_audio()
		elif action == "subs":
			self.choose_subs()
		elif action == "version":
			lst = [(s.get("Name") or s.get("Id"), s.get("Id")) for s in it.get("MediaSources") or []]
			self.session.openWithCallback(self.version_chosen, ChoiceBox, title=_("Version"), list=lst)
		elif action == "season":
			jfnav.open_season(self, it, callback=self.after_play)
		elif action == "series":
			jfnav.open_detail(self, {"Id": it["SeriesId"], "Type": "Series", "Name": it.get("SeriesName", "")}, callback=self.after_play)
		elif action == "nextup" and self.next_up:
			play_item(self, self.next_up, on_finished=self.after_play)
		elif action == "episodes":
			from .jfepisodes import EpisodesScreen
			focus_season = self.next_up.get("SeasonId") if self.next_up else None
			focus_ep = self.next_up.get("Id") if self.next_up else None
			self.session.openWithCallback(self.after_play, EpisodesScreen, series_id=it["Id"], season_id=focus_season,
				series_name=it.get("Name", ""), focus_id=focus_ep)
		elif action in ("playseries", "nextup"):
			play_item(self, it, on_finished=self.after_play)
		elif action in ("played", "unplayed"):
			self.key_red()
		elif action in ("fav", "unfav"):
			self.key_blue()
		elif action == "similar":
			jfnav.open_grid(self, {"title": _("Ähnlich wie %s") % it.get("Name", ""), "source": "similar", "item_id": it["Id"], "categories": True},
				callback=self.after_play)
		elif action == "cast":
			self.set_focus("cast")
		elif action == "castgrid":
			people = [person_item(p) for p in cast_list(it)]
			jfnav.open_grid(self, {"title": _("Besetzung: %s") % it.get("Name", ""), "source": "static", "items": people, "sortable": False},
				callback=self.after_play)
		elif action == "more":
			self.key_menu()

	def version_chosen(self, choice=None):
		if choice is not None:
			self.source_id = choice[1]
			self.audio_index = None
			self.sub_index = None
			self.render()

	def choose_audio(self):
		audio = self.streams("Audio")
		if not audio:
			return
		sel = self.selected_audio()
		lst = [(stream_label(s), s.get("Index")) for s in audio]
		pos = audio.index(sel) if sel in audio else 0
		self.session.openWithCallback(self.audio_chosen, ChoiceBox, title=_("Audiospur"), list=lst, selection=pos)

	def audio_chosen(self, choice=None):
		if choice is not None:
			self.audio_index = choice[1]
			self["tech"].setText(self.tech_text())

	def choose_subs(self):
		subs = self.streams("Subtitle")
		lst = [(_("Aus"), -1)] + [(stream_label(s), s.get("Index")) for s in subs]
		sel = self.selected_sub()
		pos = subs.index(sel) + 1 if sel in subs else 0
		self.session.openWithCallback(self.subs_chosen, ChoiceBox, title=_("Untertitel (externe/Bild-Untertitel werden eingebrannt)"), list=lst, selection=pos)

	def subs_chosen(self, choice=None):
		if choice is not None:
			self.sub_index = choice[1]
			self["tech"].setText(self.tech_text())

	def after_play(self, *args):
		if not self.jf_closed:
			self.later(1500, self.load)

	def key_green(self):
		it = self.item
		if it.get("Type") in PLAYABLE:
			from .jfplayer import play_item
			play_item(self, it, on_finished=self.after_play, audio_index=self.audio_index, sub_index=self.sub_index, media_source_id=self.source_id)
		elif it.get("Type") == "Series":
			self.do("nextup" if self.next_up else "playseries")

	def key_yellow(self):
		if self.item.get("Type") not in PLAYABLE:
			return
		lst = []
		if self.streams("Audio"):
			lst.append((_("Audiospur wählen"), "audio"))
		if self.streams("Subtitle"):
			lst.append((_("Untertitel wählen"), "subs"))
		if not lst:
			self.info(_("Keine Audio-/Untertitelspuren bekannt"))
			return
		if len(lst) == 1:
			self.do(lst[0][1])
			return
		self.session.openWithCallback(lambda c=None: c and self.do(c[1]), ChoiceBox, title=_("Audio / Untertitel"), list=lst)

	def key_red(self):
		self.toggle_played(self.item, callback=lambda it: self.render())

	def key_blue(self):
		self.toggle_favorite(self.item, callback=lambda it: self.render())

	def key_menu(self):
		lst = [(self.pill_label(a), a) for a in self.actions()]
		if self.item.get("People"):
			lst.append((_(LABELS["castgrid"]), "castgrid"))
		lst.append((_("Neu laden"), "reload"))
		self.session.openWithCallback(self.menu_chosen, ChoiceBox, title=self.item.get("Name", ""), list=lst)

	def menu_chosen(self, choice=None):
		if choice is None:
			return
		if choice[1] == "reload":
			self.load()
		else:
			self.do(choice[1])
