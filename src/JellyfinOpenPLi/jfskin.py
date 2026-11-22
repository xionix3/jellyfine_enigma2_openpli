# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 xionix
# Jellyfin for Enigma2 - embedded skins (designed for 1920x1080, scaled at runtime)
#
# Note: Enigma2 fills (eLabel backgroundColor) overwrite pixels including alpha instead of
# blending. Everything translucent (gradients over backdrops, glass panels, rounded frames,
# badges) is therefore an alpha PNG drawn with alphatest="blend".
from __future__ import absolute_import, division

from .jfi18n import N_, badge

import os
import re

from enigma import getDesktop

IMAGES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

BG = "#000b0b10"
PANEL = "#001a1a24"
PLACEHOLDER = "#00262634"
ACCENT = "#0000a4dc"
ACCENT2 = "#00aa5cc3"
TEXT = "#00f2f2f2"
DIM = "#009a9aae"
DIMMER = "#006e6e80"
DARK_TEXT = "#00101016"
PROGRESS_BG = "#00202028"
RED_C = "#00e53935"
GREEN_C = "#0043a047"
YELLOW_C = "#00fbc02d"
BLUE_C = "#001e88e5"

# integer colours for MultiContent / setForegroundColor
C_TEXT = 0xf2f2f2
C_DIM = 0x9a9aae
C_ACCENT = 0x00a4dc
C_GREEN = 0x43a047
C_SEL_BG = 0x00a4dc
C_PLACEHOLDER = 0x262634
C_DARK = 0x101016
C_WHITE = 0xffffff


def factor():
	try:
		h = getDesktop(0).size().height()
	except Exception:
		h = 1080
	return h / 1080.0


def res_dir():
	"""Assets exist pixel exact for 1080p (images/) and 720p (images/hd/); others are scaled by the skin."""
	f = factor()
	if abs(f - 1.0) < 0.01:
		return IMAGES, False
	if abs(f - 2 / 3.0) < 0.01:
		return os.path.join(IMAGES, "hd"), False
	return IMAGES, True


def img(name):
	return os.path.join(res_dir()[0], name)


def scale_attr():
	return ' scale="1"' if res_dir()[1] else ""


def S(v):
	"""Scale a FHD pixel value to the current desktop."""
	return int(round(v * factor()))


def scale_skin(xml):
	f = factor()
	if abs(f - 1.0) < 0.001:
		return xml

	def sc(v):
		return str(int(round(int(v) * f)))

	xml = re.sub(r'(position|size)="(-?\d+),(-?\d+)"', lambda m: '%s="%s,%s"' % (m.group(1), sc(m.group(2)), sc(m.group(3))), xml)
	xml = re.sub(r'font="([A-Za-z]+);(\d+)"', lambda m: 'font="%s;%s"' % (m.group(1), sc(m.group(2))), xml)
	xml = re.sub(r'(itemHeight|borderWidth|scrollbarWidth)="(\d+)"', lambda m: '%s="%s"' % (m.group(1), sc(m.group(2))), xml)
	return xml


# ---------------------------------------------------------------- building blocks
def label(name, x, y, w, h, size=28, color=TEXT, bg=None, halign="left", valign="center", extra=""):
	bgattr = 'backgroundColor="%s"' % bg if bg else 'backgroundColor="%s" transparent="1"' % BG
	return ('<widget name="%s" position="%d,%d" size="%d,%d" font="Regular;%d" foregroundColor="%s" %s halign="%s" valign="%s" %s />'
		% (name, x, y, w, h, size, color, bgattr, halign, valign, extra))


def rect(x, y, w, h, color, z=0):
	return '<eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" zPosition="%d" />' % (x, y, w, h, color, z)


def epixmap(name, x, y, w, h, z=0):
	"""Static alpha PNG (glass panel, icon), pixel exact for 1080p/720p."""
	return '<ePixmap pixmap="%s" position="%d,%d" size="%d,%d" alphatest="blend"%s zPosition="%d" />' % (img(name), x, y, w, h, scale_attr(), z)


def pixmap_widget(name, x, y, w, h, image=None, z=0, blend=True):
	"""Pixmap widget. Pictures from the server are decoded to the exact widget size, so no scaling while painting."""
	extra = ' pixmap="%s"%s' % (img(image), scale_attr()) if image else ""
	return '<widget name="%s" position="%d,%d" size="%d,%d" alphatest="%s" zPosition="%d"%s />' % (
		name, x, y, w, h, "blend" if blend else "off", z, extra)


def progress(name, x, y, w, h, z=2):
	return ('<widget name="%s" position="%d,%d" size="%d,%d" foregroundColor="%s" backgroundColor="%s" borderWidth="0" zPosition="%d" />'
		% (name, x, y, w, h, ACCENT, PROGRESS_BG, z))


def clock():
	return ('<widget source="global.CurrentTime" render="Label" position="1640,30" size="220,50" font="Regular;38" '
		'foregroundColor="%s" backgroundColor="%s" transparent="1" halign="right" valign="center" zPosition="2">'
		'<convert type="ClockToText">Default</convert></widget>' % (TEXT, BG))


def keybar(y=1024, hint=True, z=2):
	out = []
	x = 60
	zattr = 'zPosition="%d"' % z
	for name, col in (("key_red", RED_C), ("key_green", GREEN_C), ("key_yellow", YELLOW_C), ("key_blue", BLUE_C)):
		out.append(rect(x, y + 6, 6, 28, col, z))
		out.append(label(name, x + 16, y, 300, 40, 25, TEXT, extra=zattr))
		x += 330
	if hint:
		out.append(label("key_hint", 1380, y, 480, 40, 22, DIM, halign="right", extra=zattr))
	return "\n".join(out)


def status_label(x=560, y=440, w=800, h=140):
	return label("status", x, y, w, h, 34, TEXT, bg=PANEL, halign="center", extra='zPosition="9"')


def backdrop_layer():
	"""Item backdrop + gradient on top. The full screen gradient is set from code (decoded once per session)."""
	return "\n".join([
		pixmap_widget("backdrop", 0, 0, 1920, 1080, z=-3, blend=False),
		pixmap_widget("overlay", 0, 0, 1920, 1080, z=-2),
	])


def background_layer():
	return ""


def screen(name, body, title="Jellyfin", bg=BG):
	return scale_skin('<screen name="%s" position="0,0" size="1920,1080" flags="wfNoBorder" backgroundColor="%s" title="%s">\n%s\n</screen>'
		% (name, bg, title, body))


# ---------------------------------------------------------------- poster cells
GRID_COLS = 7
GRID_ROWS = 2
GRID_X0 = 69
GRID_Y0 = 150
GRID_STEP_X = 264
GRID_STEP_Y = 372
COVER_W = 200
COVER_H = 300
CELL_LABEL_H = 34
FRAME_PAD = 8


def cell_pos(i, cols=GRID_COLS, x0=GRID_X0, y0=GRID_Y0, sx=GRID_STEP_X, sy=GRID_STEP_Y):
	r, c = divmod(i, cols)
	return x0 + c * sx, y0 + r * sy


def cover_cells(prefix, count, cols, x0, y0, sx, sy, w=COVER_W, h=COVER_H, badges=True, label_h=CELL_LABEL_H, label_size=24):
	new_png, new_w = badge("new")
	seen_png, seen_w = badge("seen")
	out = []
	for i in range(count):
		x, y = cell_pos(i, cols, x0, y0, sx, sy)
		out.append(label("%sph%d" % (prefix, i), x, y, w, h, 24, DIM, bg=PLACEHOLDER, halign="center", valign="center", extra='zPosition="0"'))
		out.append(pixmap_widget("%scover%d" % (prefix, i), x, y, w, h, z=1, blend=False))
		out.append(progress("%sprog%d" % (prefix, i), x, y + h - 7, w, 7, z=2))
		if badges:
			out.append(pixmap_widget("%sseen%d" % (prefix, i), x + 8, y + 8, seen_w, 28, seen_png, z=3))
			out.append(pixmap_widget("%snew%d" % (prefix, i), x + 8, y + 8, new_w, 28, new_png, z=3))
			out.append(label("%scount%d" % (prefix, i), x + w - 66, y + 8, 58, 30, 21, TEXT, bg=ACCENT, halign="center", extra='zPosition="3"'))
		out.append(label("%slabel%d" % (prefix, i), x - 10, y + h + 4, w + 20, label_h, label_size, TEXT, halign="center", extra='noWrap="1"'))
	return "\n".join(out)


# ---------------------------------------------------------------- screens
def grid_skin():
	cells = GRID_COLS * GRID_ROWS
	body = [
		backdrop_layer(),
		label("title", 60, 24, 1300, 64, 46, TEXT),
		label("subtitle", 60, 88, 1350, 40, 26, DIM),
		label("pageinfo", 1420, 88, 440, 40, 26, DIM, halign="right"),
		clock(),
		pixmap_widget("frame", GRID_X0 - FRAME_PAD, GRID_Y0 - FRAME_PAD, COVER_W + 2 * FRAME_PAD, COVER_H + 2 * FRAME_PAD, "frame_poster.png", z=4),
		cover_cells("", cells, GRID_COLS, GRID_X0, GRID_Y0, GRID_STEP_X, GRID_STEP_Y),
		epixmap("glass_info.png", 50, 852, 1820, 168, -1),
		label("info_title", 78, 862, 1764, 44, 34, TEXT, extra='noWrap="1"'),
		label("info_meta", 78, 906, 1764, 34, 26, ACCENT, extra='noWrap="1"'),
		label("info_overview", 78, 942, 1764, 70, 24, DIM, valign="top"),
		keybar(y=1030),
		status_label(),
	]
	return screen("JellyfinE2Grid", "\n".join(body))


HOME_COLS = 5
HOME_ROWS = 2
HOME_X0 = 650
HOME_Y0 = 214
HOME_STEP_X = 246
HOME_STEP_Y = 372


def home_skin():
	"""Classic start screen: menu on the left, poster preview on the right."""
	body = [
		backdrop_layer(),
		label("title", 60, 24, 900, 64, 50, ACCENT),
		label("subtitle", 60, 90, 1300, 40, 26, DIM),
		clock(),
		epixmap("glass_menu.png", 50, 150, 540, 872, -1),
		'<widget name="menu" position="60,160" size="520,858" itemHeight="66" scrollbarMode="showOnDemand" backgroundColor="%s" '
		'foregroundColor="%s" backgroundColorSelected="%s" foregroundColorSelected="#00ffffff" transparent="1" zPosition="1" />' % (BG, TEXT, ACCENT),
		label("preview_title", HOME_X0, 156, 1220, 46, 34, TEXT),
		cover_cells("p", HOME_COLS * HOME_ROWS, HOME_COLS, HOME_X0, HOME_Y0, HOME_STEP_X, HOME_STEP_Y),
		label("preview_hint", HOME_X0, 960, 1220, 40, 26, DIM),
		keybar(y=1030),
		status_label(),
	]
	return screen("JellyfinE2Home", "\n".join(body))


# hero start screen geometry
HERO_RAIL = [("search", N_("Suche")), ("home", N_("Start")), ("movies", N_("Filme")), ("tv", N_("Serien")), ("lists", N_("Meine Listen")), ("settings", N_("Einstellungen"))]
RAIL_X = 48
RAIL_Y0 = 150
RAIL_STEP = 78
CARD_COUNT = 5
CARD_X0 = 160
CARD_Y = 672
CARD_STEP = 340
CARD_W = 300
CARD_H = 169


def rows_skin():
	"""Start screen, libraries and search: backdrop + info of the focused title, one row of cards, sidebar."""
	new_png, new_w = badge("new")
	seen_png, seen_w = badge("seen")
	body = [
		backdrop_layer(),
		pixmap_widget("rail_shade", 0, 0, 1920, 1080, z=0),
		label("brand", 160, 36, 1100, 40, 26, ACCENT, extra='noWrap="1"'),
		label("server", 1100, 84, 760, 32, 22, DIM, halign="right", extra='noWrap="1"'),
		clock(),
	]
	for i, (key, _name) in enumerate(HERO_RAIL):
		y = RAIL_Y0 + i * RAIL_STEP
		body.append(epixmap("icon_%s.png" % key, RAIL_X, y, 44, 44, 2))
		body.append(label("rail_name%d" % i, 132, y, 420, 44, 30, DIM, extra='noWrap="1" zPosition="2"'))
	body += [
		pixmap_widget("rail_sel", RAIL_X - 14, RAIL_Y0 - 14, 72, 72, "rail_sel.png", z=1),
		label("hero_title", 160, 104, 1400, 92, 64, TEXT, extra='noWrap="1"'),
		pixmap_widget("hero_new", 160, 214, new_w, 28, new_png, z=2),
		label("hero_meta", 160 + new_w + 12, 206, 1400, 44, 28, "#00d0d0da", extra='noWrap="1"'),
		label("hero_genres", 160, 250, 1300, 36, 26, DIM, extra='noWrap="1"'),
		label("hero_overview", 160, 296, 1020, 170, 29, "#00e0e0e8", valign="top"),
		pixmap_widget("hero_pillbg1", 160, 482, 280, 64, "pill_primary.png", z=1),
		pixmap_widget("hero_icon1", 192, 500, 28, 28, "icon_play_dark.png", z=2),
		label("hero_pill1", 232, 482, 200, 64, 28, DARK_TEXT, extra='zPosition="2"'),
		pixmap_widget("hero_pillbg2", 460, 482, 280, 64, "pill_secondary.png", z=1),
		pixmap_widget("hero_icon2", 492, 500, 28, 28, "icon_info.png", z=2),
		label("hero_pill2", 532, 482, 200, 64, 28, TEXT, extra='zPosition="2"'),
		label("row_title", 160, 598, 1200, 52, 36, TEXT, extra='noWrap="1"'),
		label("row_count", 1460, 610, 400, 36, 24, DIM, halign="right"),
		pixmap_widget("frame", CARD_X0 - FRAME_PAD, CARD_Y - FRAME_PAD, CARD_W + 16, CARD_H + 16, "frame_card.png", z=4),
	]
	for i in range(CARD_COUNT):
		x = CARD_X0 + i * CARD_STEP
		body.append(label("cph%d" % i, x, CARD_Y, CARD_W, CARD_H, 26, DIM, bg=PLACEHOLDER, halign="center", extra='zPosition="0"'))
		body.append(pixmap_widget("ccover%d" % i, x, CARD_Y, CARD_W, CARD_H, z=1, blend=False))
		body.append(progress("cprog%d" % i, x, CARD_Y + CARD_H - 7, CARD_W, 7, z=2))
		body.append(pixmap_widget("cseen%d" % i, x + 8, CARD_Y + 8, seen_w, 28, seen_png, z=3))
		body.append(pixmap_widget("cnew%d" % i, x + 8, CARD_Y + 8, new_w, 28, new_png, z=3))
		body.append(label("ccount%d" % i, x + CARD_W - 66, CARD_Y + 8, 58, 30, 21, TEXT, bg=ACCENT, halign="center", extra='zPosition="3"'))
		body.append(label("clabel%d" % i, x, CARD_Y + CARD_H + 10, CARD_W, 36, 25, TEXT, extra='noWrap="1"'))
	body += [
		label("next_row", 160, 900, 1600, 42, 30, "#00b0b0c0", extra='noWrap="1"'),
		label("more_rows", 160, 946, 1600, 34, 24, DIMMER, extra='noWrap="1"'),
		keybar(y=1030),
		status_label(),
	]
	return screen("JellyfinE2Rows", "\n".join(body))


hero_skin = rows_skin

# detail page geometry: text on the left over the darkened part, the picture stays visible on the right
PILL_COUNT = 6
PILL_X0 = 120
PILL_Y = 790
PILL_STEP = 292
PILL_W = 280
PILL_H = 64
CAST_COUNT = 10
CAST_X0 = 120
CAST_Y = 760
CAST_STEP = 170
CAST_W = 130
CAST_H = 195


# details: poster left, text column right of it (moved to the left edge when there is no poster)
DETAIL_POSTER = (120, 196, 300, 450)
DETAIL_COL = 460
DETAIL_LINES_Y = (196, 246, 290)  # facts, genres, state
DETAIL_TEXT_Y = 346


def detail_skin():
	new_png, new_w = badge("new")
	px, py, pw, ph = DETAIL_POSTER
	col = DETAIL_COL
	body = [
		backdrop_layer(),
		label("crumb", 120, 40, 1300, 36, 24, DIM, extra='noWrap="1"'),
		clock(),
		label("title", 120, 84, 1500, 92, 62, TEXT, extra='noWrap="1"'),
		pixmap_widget("poster", px, py, pw, ph, z=1, blend=False),
		pixmap_widget("badge", col, DETAIL_LINES_Y[0] + 8, new_w, 28, new_png, z=2),
		label("meta", col + new_w + 12, DETAIL_LINES_Y[0], 1340, 44, 28, "#00e2e2ea", extra='noWrap="1"'),
		label("genres", col, DETAIL_LINES_Y[1], 1340, 36, 26, DIM, extra='noWrap="1"'),
		label("state", col, DETAIL_LINES_Y[2], 1340, 36, 26, ACCENT, extra='noWrap="1"'),
		'<widget name="overview" position="%d,%d" size="1000,360" font="Regular;30" foregroundColor="#00ececf2" backgroundColor="%s" '
		'transparent="1" zPosition="2" />' % (col, DETAIL_TEXT_Y, BG),
		label("tech", 120, 724, 1700, 36, 23, DIM, extra='noWrap="1"'),
		label("cast_title", 120, 712, 1000, 40, 28, TEXT, extra='noWrap="1"'),
		label("cast_hint", 120, 900, 1200, 36, 25, DIM, extra='noWrap="1"'),
	]
	for i in range(PILL_COUNT):
		x = PILL_X0 + i * PILL_STEP
		body.append(pixmap_widget("pill%d" % i, x, PILL_Y, PILL_W, PILL_H, "pill_secondary.png", z=1))
		body.append(label("pilltxt%d" % i, x + 14, PILL_Y, PILL_W - 28, PILL_H, 26, TEXT, halign="center", extra='zPosition="2" noWrap="1"'))
	body.append(progress("progress", PILL_X0 + 20, PILL_Y + PILL_H + 8, PILL_W - 40, 6, z=2))
	body.append(pixmap_widget("cast_frame", CAST_X0 - FRAME_PAD, CAST_Y - FRAME_PAD, CAST_W + 16, CAST_H + 16, "frame_person.png", z=4))
	for i in range(CAST_COUNT):
		x = CAST_X0 + i * CAST_STEP
		body.append(label("pph%d" % i, x, CAST_Y, CAST_W, CAST_H, 36, DIM, bg=PLACEHOLDER, halign="center", extra='zPosition="0"'))
		body.append(pixmap_widget("pphoto%d" % i, x, CAST_Y, CAST_W, CAST_H, z=1, blend=False))
		body.append(label("pname%d" % i, x - 18, CAST_Y + CAST_H + 6, CAST_W + 36, 30, 21, TEXT, halign="center", extra='noWrap="1"'))
		body.append(label("prole%d" % i, x - 18, CAST_Y + CAST_H + 34, CAST_W + 36, 26, 18, DIM, halign="center", extra='noWrap="1"'))
	body += [
		label("status", 1200, 40, 420, 36, 24, ACCENT, halign="right"),
		keybar(y=1030),
	]
	return screen("JellyfinE2Detail", "\n".join(body))


def episodes_skin():
	body = [
		backdrop_layer(),
		label("title", 60, 24, 1500, 64, 46, TEXT, extra='noWrap="1"'),
		label("subtitle", 60, 88, 1500, 44, 30, ACCENT),
		clock(),
		epixmap("glass_episodes.png", 50, 140, 1820, 712, -1),
		'<widget name="list" position="60,146" size="1800,696" itemHeight="174" scrollbarMode="showOnDemand" backgroundColor="%s" '
		'foregroundColor="%s" backgroundColorSelected="#00203a4c" foregroundColorSelected="#00ffffff" transparent="1" zPosition="1" />' % (BG, TEXT),
		label("info", 60, 866, 1800, 150, 26, DIM, valign="top"),
		keybar(y=1030),
		status_label(),
	]
	return screen("JellyfinE2Episodes", "\n".join(body))


def list_skin(name="JellyfinE2Login", with_status=True, item_height=70):
	body = [
		label("title", 60, 24, 1500, 64, 46, TEXT),
		label("subtitle", 60, 88, 1500, 40, 26, DIM),
		clock(),
		epixmap("glass_list.png", 340, 150, 1240, 600, -1),
		'<widget name="list" position="360,170" size="1200,560" itemHeight="%d" scrollbarMode="showOnDemand" backgroundColor="%s" '
		'foregroundColor="%s" backgroundColorSelected="%s" foregroundColorSelected="#00ffffff" transparent="1" zPosition="1" />' % (item_height, PANEL, TEXT, ACCENT),
		label("description", 360, 770, 1200, 100, 26, DIM, valign="top"),
	]
	if with_status:
		body.append(label("status", 360, 880, 1200, 120, 28, ACCENT, valign="top"))
	body.append(keybar(y=1030, hint=False))
	return screen(name, "\n".join(body))


OSD_X, OSD_Y, OSD_W, OSD_H = 1200, 690, 640, 132


def osd_skin():
	"""Small overlay above the player's infobar: 'Intro überspringen' / 'Nächste Folge in 8 s'."""
	body = [
		epixmap("osd_panel.png", 0, 0, OSD_W, OSD_H),
		label("osd_title", 34, 18, 470, 50, 32, TEXT, extra='zPosition="1" noWrap="1"'),
		label("osd_sub", 34, 70, 470, 42, 24, DIM, extra='zPosition="1" noWrap="1"'),
		epixmap("key_ok.png", 524, 40, 92, 52, z=1),
	]
	return scale_skin('<screen name="JellyfinE2Osd" position="%d,%d" size="%d,%d" flags="wfNoBorder" backgroundColor="#ff000000" zPosition="10">\n%s\n</screen>'
		% (OSD_X, OSD_Y, OSD_W, OSD_H, "\n".join(body)))


def quickconnect_skin():
	body = [
		rect(0, 0, 1000, 520, PANEL),
		rect(0, 0, 1000, 6, ACCENT),
		label("title", 40, 24, 920, 56, 40, TEXT, bg=PANEL),
		label("text", 40, 92, 920, 120, 28, DIM, bg=PANEL, valign="top"),
		label("code", 40, 220, 920, 140, 110, ACCENT, bg=PANEL, halign="center"),
		label("status", 40, 380, 920, 80, 26, TEXT, bg=PANEL, halign="center"),
		rect(40, 470, 6, 32, RED_C),
		label("key_red", 58, 466, 400, 40, 26, TEXT, bg=PANEL),
	]
	xml = '<screen name="JellyfinE2QuickConnect" position="460,280" size="1000,520" flags="wfNoBorder" backgroundColor="%s">\n%s\n</screen>' % (PANEL, "\n".join(body))
	return scale_skin(xml)
