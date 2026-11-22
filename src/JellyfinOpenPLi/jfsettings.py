# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 xionix
# Jellyfin for Enigma2 - settings
from __future__ import absolute_import

from .jfi18n import _, N_, set_language

from Components.ActionMap import ActionMap
from Components.Label import Label
from Screens.MessageBox import MessageBox

from . import jfconfig
from .jfapi import CLIENT_VERSION
from .jfcommon import JFScreen, make_list, text_row
from .jfskin import C_ACCENT, list_skin

ROW_W = 1200
AUTHOR = "xionix"
HOMEPAGE = "https://github.com/xionix3/jellyfine_enigma2_openpli"


def about_text(cl=None):
	lines = [_("Jellyfin für Enigma2  -  Version %s") % CLIENT_VERSION, "", _("Entwickelt von %s") % AUTHOR, HOMEPAGE, "",
		_("Freie Software (GPL-2.0-or-later). Kein offizielles Jellyfin-Projekt."), _("Box: %s") % jfconfig.box_name()]
	if cl is not None and cl.server:
		ver = ".".join(str(x) for x in cl.server_version) if cl.server_version != (0, 0, 0) else "?"
		lines.append(_("Server: %s (Jellyfin %s)") % (cl.server_name or cl.server, ver))
	return "\n".join(lines)


# settings shown in groups; anything not listed lands in the last group
GROUPS = (
	(N_("Allgemein"), ("language", "home_layout", "backdrops", "rules_first", "show_played", "new_days", "update_check", "mainmenu", "extmenu")),
	(N_("Wiedergabe"), ("playmode", "player", "autoplay_next", "skip_segments", "resume_ask", "seek_mode")),
	(N_("Qualität"), ("max_bitrate", "max_width", "hevc", "dts", "truehd", "vc1", "vp9", "audio_channels", "protocol")),
	(N_("System"), ("cache_dir", "verify_ssl")),
)
HEADER = "_group"


def grouped_settings():
	"""[(group title, [setting tuples])] in display order."""
	by_id = dict((s[0], s) for s in jfconfig.SETTINGS)
	listed = set(sid for _title, ids in GROUPS for sid in ids)
	out = []
	for title, ids in GROUPS:
		out.append((title, [by_id[sid] for sid in ids if sid in by_id]))
	out[-1][1].extend(s for s in jfconfig.SETTINGS if s[0] not in listed)
	return out


class SettingsScreen(JFScreen):
	def __init__(self, session):
		JFScreen.__init__(self, session)
		self.skin = list_skin("JellyfinE2Settings", item_height=62)
		self.skinName = "JellyfinE2Settings"
		self.vals = dict((s[0], getattr(jfconfig.config.plugins.jellyfine2, s[0]).value) for s in jfconfig.SETTINGS)
		cl = self.cl
		self["title"] = Label(_("Jellyfin - Einstellungen"))
		self["subtitle"] = Label(_("Plugin %s von %s  |  %s @ %s") % (CLIENT_VERSION, AUTHOR, cl.user_name or "-", cl.server or "-"))
		self["list"] = make_list(fonts=((28,), (28,)), item_height=62)
		self["description"] = Label("")
		self["status"] = Label("")
		self.add_keys(red=_("Abbrechen"), green=_("Speichern"), yellow=_("Bild-Cache leeren"), blue=_("Abmelden"))
		self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions", "ChannelSelectBaseActions", "MenuActions"], {
			"menu": self.key_menu,
			"ok": lambda: self.change(1),
			"cancel": self.close,
			"up": lambda: self.move("up"),
			"down": lambda: self.move("down"),
			"left": lambda: self.change(-1),
			"right": lambda: self.change(1),
			"nextBouquet": lambda: self.move("pageDown"),
			"prevBouquet": lambda: self.move("pageUp"),
			"red": self.close,
			"green": self.save,
			"yellow": self.clear_cache,
			"blue": self.logout,
		}, -1)
		self["list"].onSelectionChanged.append(self.update_description)
		self.onLayoutFinish.append(self.build)

	def build(self):
		rows = []
		for title, settings in grouped_settings():
			if not settings:
				continue
			rows.append(text_row(HEADER, _(title).upper(), ROW_W, 62, color=C_ACCENT))
			for sid, label, _choices, _default, _help in settings:
				value = self.vals[sid]
				text = jfconfig.label_for(sid, value)
				if sid == "player" and value not in [v for v, _lbl in jfconfig.player_choices()]:
					text = jfconfig.label_for(sid, "4097")
				rows.append(text_row(sid, "    " + _(label), ROW_W, 62, value="<  %s  >" % text, value_width=560, value_color=C_ACCENT))
		idx = self["list"].getSelectedIndex() if self["list"].list else 1
		self["list"].setList(rows)
		self["list"].moveToIndex(idx)
		self.skip_header(1)
		self.update_description()

	def move(self, how):
		"""Up/down/page; group titles are skipped."""
		lst = self["list"]
		before = lst.getSelectedIndex()
		getattr(lst, how)()
		step = 1 if how in ("down", "pageDown") else -1
		if lst.getSelectedIndex() == before and how in ("up", "down"):
			return
		self.skip_header(step)

	def skip_header(self, step):
		lst = self["list"]
		rows = lst.list
		i = lst.getSelectedIndex()
		while 0 <= i < len(rows) and rows[i][0] == HEADER:
			i += step
		if not 0 <= i < len(rows):  # list starts/ends with a title -> go the other way
			i = lst.getSelectedIndex()
			while 0 <= i < len(rows) and rows[i][0] == HEADER:
				i -= step
		if 0 <= i < len(rows) and i != lst.getSelectedIndex():
			lst.moveToIndex(i)

	def update_description(self):
		cur = self["list"].getCurrent()
		if not cur:
			return
		for s in jfconfig.SETTINGS:
			if s[0] == cur[0]:
				extra = ""
				if s[0] == "max_width" and self.vals["max_width"] == "auto":
					extra = _(" Erkannt: %s.") % (_("UHD-Box") if jfconfig.is_uhd_box() else _("HD-Box"))
				if s[0] == "player" and not jfconfig.serviceapp_installed():
					extra = _(" ServiceApp ist nicht installiert.")
				self["description"].setText(_(s[4]) + extra)
				return

	def change(self, step):
		cur = self["list"].getCurrent()
		if not cur or cur[0] == HEADER:
			return
		sid = cur[0]
		choices = [v for v, _lbl in jfconfig.choices_for(sid)]
		if not choices:
			return
		value = self.vals[sid]
		pos = choices.index(value) if value in choices else 0
		self.vals[sid] = choices[(pos + step) % len(choices)]
		self.build()

	def save(self):
		changed = False
		for sid, value in self.vals.items():
			if getattr(jfconfig.config.plugins.jellyfine2, sid).value != value:
				jfconfig.set_value(sid, value)
				changed = True
		self.cl.verify_ssl = jfconfig.get_bool("verify_ssl")
		set_language(jfconfig.get("language"))
		self.close("changed" if changed else None)

	def clear_cache(self):
		from .jfimages import clear
		clear()
		self["status"].setText(_("Bild-Cache geleert."))

	def logout(self):
		self.session.openWithCallback(lambda yes=False: yes and self.close("logout"), MessageBox, _("Abmelden und Anmeldedaten löschen?"), MessageBox.TYPE_YESNO, default=False)

	def key_menu(self):
		from Screens.ChoiceBox import ChoiceBox
		self.session.openWithCallback(self.menu_chosen, ChoiceBox, title="Jellyfin", list=[(_("Nach Updates suchen"), "update"), (_("Über dieses Plugin"), "about")])

	def menu_chosen(self, choice=None):
		if choice is None:
			return
		if choice[1] == "update":
			from .jfupdate import Updater
			Updater(self).run_check(manual=True)
		else:
			self.session.open(MessageBox, about_text(self.cl), MessageBox.TYPE_INFO)
