# End-to-end flow against the fake Jellyfin server using fake Enigma2 screens.
# usage: python3 test_flow.py <server-version> [desktop-height]
import os
import shutil
import sys

VERSION = sys.argv[1] if len(sys.argv) > 1 else "10.10.3"
HEIGHT = int(sys.argv[2]) if len(sys.argv) > 2 else 1080

from harness import Session, pump, press, choose, type_text, answer, fire_event, SKIN_ERRORS  # noqa: E402
import enigma  # noqa: E402

enigma.DESKTOP[:] = [HEIGHT * 16 // 9, HEIGHT]

from mockjf import start_server  # noqa: E402

srv, state, URL = start_server(VERSION)
shutil.rmtree("/tmp/jellyfine2", ignore_errors=True)

from JellyfinOpenPLi import plugin  # noqa: E402
from JellyfinOpenPLi import jfconfig, jfupdate  # noqa: E402
from JellyfinOpenPLi.jfimages import image_ref  # noqa: E402
from Components import Console as console_stub  # noqa: E402
from Screens import Standby as standby_stub  # noqa: E402

class _Tee(object):
	"""Keeps the plugin's log lines to check that no access token ends up in a log users may post."""
	def __init__(self, out):
		self.out = out
		self.text = []

	def write(self, data):
		self.text.append(data)
		return self.out.write(data)

	def flush(self):
		self.out.flush()


LOG = _Tee(sys.stdout)
sys.stdout = LOG

# the classic layout is tested first, the modern (hero) start screen further below
jfconfig.set_value("home_layout", "classic")
jfconfig.set_value("update_check", "0")
jfupdate.API_URL = URL + "/gh/releases/latest"
from JellyfinOpenPLi.jfapi import parse_version  # noqa: E402
from Components.ActionMap import WARNINGS  # noqa: E402
from Plugins.Plugin import PluginDescriptor  # noqa: E402

failures = []


def check(cond, msg):
	if not cond:
		failures.append(msg)
		print("FAIL:", msg)
	else:
		print("ok  :", msg)


def name(scr):
	return scr.__class__.__name__ if scr is not None else None


s = Session()

# --- plugin descriptors
descs = plugin.Plugins()
check(any(PluginDescriptor.WHERE_PLUGINMENU in d.where for d in descs), "plugin menu entry")
menu_desc = [d for d in descs if PluginDescriptor.WHERE_MENU in d.where][0]
check(menu_desc.fnc("mainmenu") and menu_desc.fnc("setup") == [], "main menu hook")

# --- start: login screen
plugin.main(s)
check(name(s.top) == "LoginScreen", "login screen shown when not logged in")
login = s.top
press(login, "ok")  # server field
type_text(s, URL + "/web/#/home")
check(login.server == URL, "server url normalized (%s)" % login.server)
press(login, "down")
press(login, "ok")
type_text(s, "demo")
press(login, "down")
press(login, "ok")
type_text(s, "falsch")
press(login, "green")
pump(lambda: "Fehler" in login["status"].getText())
check("falsch" in login["status"].getText() or "Fehler" in login["status"].getText(), "wrong password -> error shown: %s" % login["status"].getText())
press(login, "ok")  # still on password row
type_text(s, "geheim")
press(login, "green")
pump(lambda: name(s.top) == "HomeScreen")
check(name(s.top) == "HomeScreen", "login ok -> home")
cl = jfconfig.client()
check(cl.token == "tok123" and cl.user_id == "u1", "token stored")
check(cl.new_api == (parse_version(VERSION) >= (10, 9, 0)), "api style by version")

home = s.top
pump(lambda: len(home.sections) > 5 and home.cells.items[0] is not None, timeout=10)
titles = [sec[1] for sec in home.sections]
check("Fotos" not in titles and "Filme" in titles and "Serien" in titles, "views listed, photos hidden: %s" % titles)
check(titles[:2] == ["Neue Filme", "Neue Episoden meiner Serien"] and "Meine Listen" in titles, "own lists on top: %s" % titles[:4])
check(home.cells.items[0] is not None and home.cells.items[0]["Id"] == "m3", "newest unplayed movie first (%s)" % (home.cells.items[0] or {}).get("Id"))
check(home["pnew0"].visible and not home["pseen0"].visible, "NEU badge on new movie")
check(home["pph0"].visible and not home["pcover0"].visible, "placeholder for movie without poster")
pump(lambda: home["pcover1"].visible and home["pcover1"].instance.pixmap is not None, timeout=10)
check(home["pcover1"].instance.pixmap is not None, "preview poster loaded")
pump(lambda: home["backdrop"].instance.pixmap is not None, timeout=10)
check(home["backdrop"].instance.pixmap is not None, "home backdrop loaded")
# all previews prefetched in background -> switching sections is instant
pump(lambda: len(home.home_cache["previews"]) >= 6, timeout=10)
check(len(home.home_cache["previews"]) >= 6, "previews prefetched (%d)" % len(home.home_cache["previews"]))

# own list: new movies (30 days, unplayed, newest first)
home["menu"].moveToIndex(0)
press(home, "ok")
rg = s.top
pump(lambda: len(rg.entries) > 0, timeout=10)
ids = [e["Id"] for e in rg.entries]
check(name(rg) == "GridScreen" and ids[0] == "m3" and ids[-1] == "m29" and len(ids) == 27, "rule grid newest movies %s..%s (%d)" % (ids[:1], ids[-1:], len(ids)))
check(rg["key_red"].getText() == "", "no sort keys on rule grid")
press(rg, "cancel")

# own list: new episodes of my series, grouped per series
home["menu"].moveToIndex(1)
pump(lambda: home.cells.items[0] is not None and home.cells.items[0].get("Type") == "Episode", timeout=10)
tile = home.cells.items[0]
check(tile["SeriesId"] == "s1" and tile["_jf_new_count"] == 3 and tile["_jf_focus"]["Id"] == "e21", "grouped new episodes tile")
check(home.cells.items[1] is None, "series I don't watch excluded")
check(home["pcount0"].getText() == "+3" and home["plabel0"].getText() == "Serie Eins (3 neu)", "tile badge/label %s / %s" % (home["pcount0"].getText(), home["plabel0"].getText()))
press(home, "ok")
eg = s.top
pump(lambda: len(eg.entries) == 1, timeout=10)
press(eg, "ok")
ep = s.top
check(name(ep) == "EpisodesScreen", "grouped tile opens episodes")
pump(lambda: ep.entries and ep.current() is not None and ep.current()["Id"] == "e21", timeout=10)
check(ep.current()["Id"] == "e21", "focused first new episode e21")
check("NEU" in ep["list"].list[ep["list"].getSelectedIndex()][-2][7], "episode row marked NEU")
press(ep, "cancel")
press(eg, "cancel")

def goto_row(scr, title, timeout=10):
	"""Jump with up/down to the row with this title (rows load and drop out while moving)."""
	pump(lambda: any(r.title == title for r in scr.rows), timeout=timeout)
	for _ in range(80):
		titles_ = [r.title for r in scr.rows]
		if scr.current() is not None and scr.current().title == title:
			break
		press(scr, "down" if titles_.index(title) > scr.row else "up")
		pump(timeout=0.05)
	pump(lambda: scr.row_items, timeout=timeout)
	return scr.current()


# go to Filme -> the library looks like the start screen: rows per category / genre
idx = titles.index("Filme")
home["menu"].moveToIndex(idx)
pump(lambda: home.cells.items[0] is not None and home.cells.items[0].get("Type") == "Movie", timeout=10)
check(home.cells.items[0].get("Type") == "Movie", "movie preview")
press(home, "ok")
lib = s.top
check(name(lib) == "LibraryRowsScreen" and lib.kind == "movies", "movie library as rows")
pump(lambda: lib.row_items and any(r.title == "Alle Filme A-Z" for r in lib.rows) and not lib.loading, timeout=10)
ltitles = [r.title for r in lib.rows]
check(ltitles[0] == "Weiterschauen" and "Neu hinzugefügt" in ltitles and "Neu erschienen" in ltitles and "Komödie" in ltitles
	and "Action" in ltitles and ltitles[-1] == "Alle Filme A-Z", "library rows %s" % ltitles)
check(lib.row_items[0]["Id"] == "m6" and lib["brand"].getText().endswith("FILME"), "first row: continue watching")
press(lib, "down")
check(lib.current().title == "Neu hinzugefügt" and lib.card == 0, "down = next category")
pump(lambda: lib.row_items and lib.cells.items[0] is not None, timeout=10)
press(lib, "right")
check(lib.card == 1 and lib["hero_title"].getText() == lib.row_items[1]["Name"], "right = next title, hero follows")
goto_row(lib, "Komödie")
check(all("Komödie" in (i.get("Genres") or []) for i in lib.row_items if not i.get("_jf_more")), "genre row")
goto_row(lib, "Alle Filme A-Z")
press(lib, "red")
grid = s.top
check(name(grid) == "GridScreen", "grid opened (all titles)")
pump(lambda: len(grid.entries) > 0, timeout=10)
check(grid.total == 40 and len(grid.entries) == 40, "40 movies loaded (got %d/%d)" % (len(grid.entries), grid.total))
check(grid["frame"].instance.pos is not None, "selection frame positioned")
for _ in range(15):
	press(grid, "right")
check(grid.index == 15 and grid.page == 1, "navigate to page 2 (index %d page %d)" % (grid.index, grid.page))
press(grid, "nextBouquet")
check(grid.index == 29, "page down (%d)" % grid.index)
press(grid, "up")
check(grid.index == 22, "up (%d)" % grid.index)
press(grid, "prevBouquet")
press(grid, "prevBouquet")
press(grid, "prevBouquet")
check(grid.index == 0, "back to start")
# sort + filter
press(grid, "red")
choose(s, "Name (Z-A)")
pump(lambda: grid.entries and grid.entries[0]["Name"] == "Film 40", timeout=10)
check(grid.entries[0]["Name"] == "Film 40", "sorted Z-A")
press(grid, "green")
choose(s, "Gesehen")
pump(lambda: grid.total == 2, timeout=10)
check(grid.total == 2, "filter played -> 2")
press(grid, "green")
choose(s, "Genre wählen")
pump(lambda: name(s.top) == "ChoiceBox", timeout=10)
choose(s, "Komödie")
pump(lambda: not grid.loading and grid.genre is not None, timeout=10)
press(grid, "green")
choose(s, "Alle")
pump(lambda: grid.total == 20, timeout=10)
check(grid.total == 20, "genre filter Komödie + Alle -> 20 (got %d)" % grid.total)
press(grid, "green")
choose(s, "Genre-Filter entfernen")
pump(lambda: grid.total == 40, timeout=10)
press(grid, "red")
choose(s, "Name (A-Z)")
pump(lambda: grid.entries and grid.entries[0]["Name"] == "Film 01", timeout=10)

# yellow toggles played on Film 01 (played -> unplayed)
first = grid.entries[0]
press(grid, "yellow")
pump(lambda: not first["UserData"]["Played"], timeout=5)
check(not first["UserData"]["Played"] and not state.lib.items["m1"]["UserData"]["Played"], "toggle played")
press(grid, "blue")
pump(lambda: first["UserData"].get("IsFavorite"), timeout=5)
check(state.lib.items["m1"]["UserData"]["IsFavorite"], "toggle favorite")

# open detail of Film 06 (has resume)
grid.move_to(5)
check(grid.current()["Id"] == "m6", "film 06 selected")
press(grid, "ok")
det = s.top
check(name(det) == "DetailScreen", "detail opened")
pump(lambda: det.item.get("People") is not None, timeout=10)
acts = det.pills
check(acts[:3] == ["resume", "restart", "tracks"] and "cast" not in acts[:5], "detail pills %s" % acts)
check(det["pilltxt0"].getText() == "Fortsetzen" and det["pilltxt0"].instance.fg == 0x101016 and det["pilltxt1"].instance.fg == 0xf2f2f2,
	"focused pill has dark text on the white pill")
check("1080p H264" in det["tech"].getText() and "Audio: " in det["tech"].getText(), "tech info: %s" % det["tech"].getText())
check(det["crumb"].getText().startswith("Film") and det["meta"].getText().startswith("1996") and "\u2605 7,1" in det["meta"].getText()
	and det["state"].getText().startswith("fortsetzen bei 30:00") and "endet um" in det["state"].getText(),
	"facts and state lines: %s | %s | %s" % (det["crumb"].getText(), det["meta"].getText(), det["state"].getText()))
check(det["poster"].visible and det["poster"].instance.pixmap is not None or pump(lambda: det["poster"].instance.pixmap is not None, timeout=5),
	"poster left of the text")
names = [p["Name"] for p in det.cast]
check(names[0] == "Anna Actor" and names[-1] == "Rex Regie" and len(names) == 11, "cast row actors first, director last %s" % names[:3])
check(det["progress"].visible and det["progress"].value == 30, "resume progress bar")
check(not det["pphoto0"].visible and not det["pname0"].visible and det["pill0"].visible and det["tech"].visible, "cast hidden until selected")
check("Mit HTML & Umbruch." in det["overview"].text, "full description")
pump(lambda: det["backdrop"].instance.pixmap is not None, timeout=10)
check(det["backdrop"].instance.pixmap is not None and det["backdrop"].instance.pixmap.size == (int(round(1920 * HEIGHT / 1080.0)), HEIGHT),
	"detail backdrop decoded to screen size %s" % (det["backdrop"].instance.pixmap.size,))
check(det["overlay"].instance.pixmap is not None and det["overlay"].instance.pixmap.path.endswith("detail_overlay.png"), "detail gradient")
# cast row: down shows it (pills hidden, description stays), scroll to the 10th person, open filmography
press(det, "down")
check(det.focus == "cast" and det["cast_frame"].visible and not det["pill0"].visible and not det["tech"].visible and det["cast_title"].visible,
	"cast row shown on demand")
check(det["pname0"].getText() == "Anna Actor" and det["prole0"].getText() == "Heldin", "cast name + role")
pump(lambda: det["pphoto0"].visible and det["pphoto0"].instance.pixmap is not None, timeout=10)
check(det["pphoto0"].visible and not det["pph0"].visible, "actor photo loaded")
check(not det["pphoto3"].visible and det["pph3"].visible and det["pph3"].getText() == "DD", "initials for actor without photo")
for _ in range(10):
	press(det, "right")
check(det.cast_idx == 10 and det.cast_first == 1 and det["pname9"].getText() == "Rex Regie", "cast row scrolls (%d/%d)" % (det.cast_idx, det.cast_first))
press(det, "ok")
pg = s.top
pump(lambda: len(pg.entries) > 0, timeout=10)
check(name(pg) == "GridScreen" and pg.spec["params"]["personIds"] == "p2", "person filmography grid")
press(pg, "cancel")
press(det, "up")
check(det.focus == "pills" and not det["cast_frame"].visible and not det["pphoto0"].visible and det["pill0"].visible, "back to pills")
# full cast as poster grid via menu
press(det, "menu")
choose(s, "Gesamte Besetzung")
cg = s.top
pump(lambda: len(cg.entries) == 11, timeout=10)
check(name(cg) == "GridScreen" and cg.entries[0]["Type"] == "Person" and cg.entries[0]["ImageTags"]["Primary"] == "ph-p1", "cast grid")
press(cg, "cancel")
# choose english audio + german subs
press(det, "yellow")
choose(s, "Audiospur")
choose(s, "Englisch")
check(det.audio_index == 2, "audio index 2 selected")
press(det, "yellow")
choose(s, "Untertitel")
choose(s, "GER")
check(det.sub_index == 3, "subtitle index 3")
# resume playback (first pill)
det.pill = 0
press(det, "ok")
pump(lambda: name(s.top) == "JellyfinPlayer", timeout=10)
player = s.top
check(name(player) == "JellyfinPlayer", "player opened")
pb = state.playback_infos[-1]
check(pb["AudioStreamIndex"] == 2 and pb["SubtitleStreamIndex"] == 3 and pb["StartTimeTicks"] == 30 * 60 * 10000000, "playback info params")
ref = s.nav.history[-1]
check(ref.type == 4097 and "/Videos/m6/stream.mkv?static=true" in ref.path and "api_key=tok123" in ref.path, "direct play url %s" % ref.path)
check(ref.getName() == "Film 06", "service name")
fire_event(player, enigma.iPlayableService.evStart)
pump(lambda: any(r[0] == "/Sessions/Playing" for r in state.reports), timeout=5)
check(any(r[0] == "/Sessions/Playing" for r in state.reports), "playback start reported")
pump(lambda: s.nav.current._seek.seeks, timeout=5)
check(s.nav.current._seek.seeks and s.nav.current._seek.seeks[0] == 30 * 60 * 90000, "resumed at 30min")
pump(lambda: s.nav.current._tracks.selected, timeout=5)
check(s.nav.current._tracks.selected == [1], "audio track 2 (pos 1) selected in E2")
check(player.selected_subtitle == (2, 0, 0, 0, "ger"), "subtitle enabled")
s.nav.current._seek.pos = 40 * 60 * 90000
pump(timeout=0.8)  # report timer fires
press(player, "right")
check(s.nav.current._seek.seeks[-1] == ("rel", 30 * 90000), "right = +30s")
press(player, "leavePlayer")
check(name(s.top) == "DetailScreen", "back on detail after stop")
pump(lambda: any(r[0] == "/Sessions/Playing/Stopped" for r in state.reports), timeout=5)
stop = [r for r in state.reports if r[0] == "/Sessions/Playing/Stopped"][-1][1]
check(stop["PositionTicks"] == (40 * 60 + 30) * 10000000 and stop["PlayMethod"] == "DirectPlay", "stop reported at 40:30 (%s)" % stop["PositionTicks"])
check(s.nav.history[-1].type == 1, "live TV restored")
pump(lambda: det.item["UserData"].get("PlaybackPositionTicks") == stop["PositionTicks"], timeout=5)
check(det.item["UserData"]["PlaybackPositionTicks"] == stop["PositionTicks"], "detail refreshed after playback")
press(det, "cancel")
check(name(s.top) == "GridScreen", "back to grid")

# DTS movie (m7) needs transcoding -> HLS
grid.move_to(6)
press(grid, "playpauseService")
pump(lambda: name(s.top) == "JellyfinPlayer", timeout=10)
player = s.top
ref = s.nav.history[-1]
check("/videos/m7/master.m3u8" in ref.path and "ApiKey=tok123" in ref.path and "api_key" not in ref.path, "DTS -> HLS transcode url")
check(player.stream["play_method"] == "Transcode" and player.stream["is_hls"], "transcode flags")
fire_event(player, enigma.iPlayableService.evStart)
pump(timeout=0.3)
press(player, "leavePlayerOnExit")  # hides infobar first
check(name(s.top) == "JellyfinPlayer", "exit hides infobar first")
press(player, "leavePlayerOnExit")
check(name(s.top) == "GridScreen", "second exit closes")
pump(lambda: "ps-m7" in state.deleted_encodings, timeout=5)
check("ps-m7" in state.deleted_encodings, "transcode encoding stopped")

# 4K HEVC movie (m5): direct on UHD box
grid.move_to(4)
press(grid, "playpauseService")
pump(lambda: name(s.top) == "JellyfinPlayer", timeout=10)
check("/Videos/m5/stream.mkv" in s.nav.history[-1].path, "4K HEVC plays direct on sf8008")
press(s.top, "leavePlayer")

# set max resolution full HD -> m5 transcodes
jfconfig.set_value("max_width", "1920")
press(grid, "playpauseService")
pump(lambda: name(s.top) == "JellyfinPlayer", timeout=10)
check("master.m3u8" in s.nav.history[-1].path, "4K transcodes when limited to 1920")
press(s.top, "leavePlayer")
jfconfig.set_value("max_width", "auto")

# grid menu -> similar
press(grid, "menu")
choose(s, "Ähnliche Titel")
sim = s.top
pump(lambda: len(sim.entries) > 0, timeout=10)
check(name(sim) == "GridScreen" and len(sim.entries) == 5, "similar grid")
press(sim, "cancel")
press(grid, "cancel")
check(name(s.top) == "LibraryRowsScreen", "back to the library")
press(lib, "cancel")
check(lib.row == 0 and name(s.top) == "LibraryRowsScreen", "EXIT jumps to the first row first")
press(lib, "cancel")
check(name(s.top) == "HomeScreen", "back home")

# --- series flow
home["menu"].moveToIndex(titles.index("Serien"))
press(home, "ok")
tvlib = s.top
check(name(tvlib) == "LibraryRowsScreen" and tvlib.kind == "tvshows", "series library as rows")
pump(lambda: tvlib.row_items and any(r.title == "Alle Serien A-Z" for r in tvlib.rows), timeout=10)
check(tvlib.rows[0].title == "Als Nächstes" and tvlib.row_items[0]["Type"] == "Episode", "series rows start with next up")
goto_row(tvlib, "Alle Serien A-Z")
press(tvlib, "red")
sgrid = s.top
pump(lambda: len(sgrid.entries) == 2, timeout=10)
check(sgrid.entries[0]["Name"] == "Serie Eins", "series grid")
check(sgrid["count0"].visible and sgrid["count0"].getText() == "4", "unplayed badge")
press(sgrid, "ok")
sdet = s.top
pump(lambda: sdet.next_up is not None, timeout=10)
acts = sdet.pills
check(acts[0] == "nextup" and "episodes" in acts and sdet["pilltxt0"].getText() == "S01E02 ansehen", "series detail pills %s" % acts)
press(sdet, "right")
check(sdet.pill == 1 and sdet["pilltxt1"].instance.fg == 0x101016 and sdet["pilltxt0"].instance.fg == 0xf2f2f2, "pill focus moves")
sdet.pill = acts.index("episodes")
press(sdet, "ok")
eps = s.top
check(name(eps) == "EpisodesScreen", "episodes screen")
pump(lambda: len(eps.entries) == 3, timeout=10)
check(eps.seasons[eps.season_pos]["Id"] == "s1-1", "focused season 1 (next up)")
check(eps.current()["Id"] == "e12", "focused next-up episode e12 (%s)" % eps.current()["Id"])
pump(lambda: len(eps.thumbs) == 3, timeout=10)
check(len(eps.thumbs) == 3, "episode thumbnails")
press(eps, "right")
pump(lambda: eps.entries and eps.entries[0]["Id"] == "e21", timeout=10)
check([e["Id"] for e in eps.entries] == ["e21", "e22", "e23"], "season 2, virtual episode hidden")
check("Staffel 2" in eps["subtitle"].getText(), "season header %s" % eps["subtitle"].getText())
press(eps, "left")
pump(lambda: eps.entries and eps.entries[0]["Id"] == "e11", timeout=10)
eps["list"].moveToIndex(1)
press(eps, "ok")
choose(s, "Von Anfang")
pump(lambda: name(s.top) == "JellyfinPlayer", timeout=10)
player = s.top
check(player.current_item()["Id"] == "e12", "playing e12")
pump(lambda: len(player.queue) > 1, timeout=10)
check([e["Id"] for e in player.queue] == ["e12", "e13", "e21", "e22", "e23"], "autoplay queue %s" % [e["Id"] for e in player.queue])
fire_event(player, enigma.iPlayableService.evStart)
pump(timeout=0.2)
check(not s.nav.current._seek.seeks, "no resume seek when starting from beginning")
# EOF -> next episode in same player
player.doEofInternal(True)
pump(lambda: player.current_item()["Id"] == "e13", timeout=10)
check(player.current_item()["Id"] == "e13" and "/Videos/e13/" in s.nav.history[-1].path, "autoplay next episode")
check(name(s.top) == "JellyfinPlayer", "still in player")
stops = [r[1]["ItemId"] for r in state.reports if r[0] == "/Sessions/Playing/Stopped"]
check(stops[-1] == "e12", "e12 stop reported")
check(state.lib.items["e12"]["UserData"]["Played"], "e12 marked played by server (finished)")
fire_event(player, enigma.iPlayableService.evStart)
pump(lambda: [r for r in state.reports if r[0] == "/Sessions/Playing" and r[1]["ItemId"] == "e13"], timeout=5)
check([r for r in state.reports if r[0] == "/Sessions/Playing" and r[1]["ItemId"] == "e13"], "e13 start reported")
# intro skip: the overlay offers OK while the intro runs (media segments, or Intro Skipper on old servers)
pump(lambda: player.segments, timeout=10)
check(player.segments and player.segments[0][:2] == ("Intro", 60 * 10000000), "segments loaded %s" % player.segments)
osd = player.osd
seek = s.nav.current._seek
seek.pos = 70 * 90000
pump(lambda: player.osd_kind == "skip", timeout=3)
check(osd.shown and osd["osd_title"].getText() == "Intro überspringen", "skip intro offered: %r" % osd["osd_title"].getText())
press(player, "ok")
check(seek.pos == 150 * 90000 and not osd.shown, "OK skips to the end of the intro")
pump(timeout=1.5)
check(not osd.shown, "skipped intro not offered again")
# credits (Outro): countdown to the next episode, EXIT cancels it, the end then leaves instead of playing on
run = int(player.current_item()["RunTimeTicks"])


def credits_pos(player):
	"""In the credits (Outro segment) or, without one, in the last 10 s."""
	outro = [x for x in player.segments if x[0] == "Outro"]
	return ((outro[0][1] // 10000000 + 10) if outro else (run // 10000000 - 8)) * 90000


seek.pos = credits_pos(player)
pump(lambda: player.osd_kind == "next", timeout=3)
check(osd.shown and osd["osd_title"].getText() == "Nächste Folge in 10 s" and "S02E01" in osd["osd_sub"].getText(),
	"countdown %r / %r" % (osd["osd_title"].getText(), osd["osd_sub"].getText()))
pump(lambda: osd["osd_title"].getText() == "Nächste Folge in 8 s", timeout=4)
check(osd["osd_title"].getText() == "Nächste Folge in 8 s", "counts down")
press(player, "ok")
pump(lambda: player.current_item()["Id"] == "e21", timeout=10)
check(player.current_item()["Id"] == "e21" and not osd.shown, "OK in the countdown plays the next episode at once")
fire_event(player, enigma.iPlayableService.evStart)
pump(lambda: player.segments, timeout=10)
seek = s.nav.current._seek
seek.pos = credits_pos(player)
pump(lambda: player.osd_kind == "next", timeout=3)
press(player, "cancel")
check(not osd.shown and player.countdown_cancelled, "EXIT cancels the countdown")
pump(timeout=3)
check(not osd.shown and player.current_item()["Id"] == "e21", "no countdown after cancel")
player.doEofInternal(True)
check(name(s.top) == "EpisodesScreen" and not s.dialogs, "end after cancelled countdown -> back to episodes, overlay gone")
pump(lambda: [r for r in state.reports if r[0] == "/Sessions/Playing/Stopped" and r[1]["ItemId"] == "e21"], timeout=5)
pump(timeout=0.3)
state.lib.items["e21"]["UserData"].update({"Played": False, "PlaybackPositionTicks": 0, "PlayedPercentage": 0})  # later checks count it as new
pump(lambda: eps["list"].list and eps.current() is not None and eps.current()["Id"] == "e12", timeout=10)
check(eps.current()["Id"] == "e12", "episode focus restored after player")
press(eps, "menu")
choose(s, "Ganze Staffel als gesehen markieren")
pump(lambda: state.lib.items["s1-1"]["UserData"].get("Played"), timeout=5)
check(state.lib.items["s1-1"]["UserData"].get("Played"), "season marked played")
press(eps, "cancel")
press(sdet, "cancel")
press(sgrid, "cancel")
tvlib.close()

# --- music
home["menu"].moveToIndex(titles.index("Musik"))
press(home, "ok")
mlib = s.top
check(name(mlib) == "LibraryRowsScreen", "music library as rows")
goto_row(mlib, "Alle Titel A-Z")
press(mlib, "red")
mgrid = s.top
pump(lambda: len(mgrid.entries) == 1, timeout=10)
press(mgrid, "ok")
alb = s.top
check(name(alb) == "EpisodesScreen" and alb.album, "album screen")
pump(lambda: len(alb.entries) == 3, timeout=10)
alb["list"].moveToIndex(1)
press(alb, "ok")
pump(lambda: name(s.top) == "JellyfinPlayer", timeout=10)
player = s.top
check(player.current_item()["Id"] == "t2" and "/Audio/t2/stream?static=true" in s.nav.history[-1].path, "audio direct url")
player.doEofInternal(True)
pump(lambda: player.current_item()["Id"] == "t3", timeout=10)
check(player.current_item()["Id"] == "t3", "next track")
player.doEofInternal(True)
check(name(s.top) == "EpisodesScreen", "album end closes player")
press(alb, "cancel")
press(mgrid, "cancel")
mlib.close()

# --- home videos: one row per folder
home["menu"].moveToIndex(titles.index("Heimvideos"))
press(home, "ok")
hv = s.top
pump(lambda: any(r.title == "Urlaub" for r in hv.rows), timeout=10)
goto_row(hv, "Urlaub")
check([i["Name"] for i in hv.row_items if not i.get("_jf_more")] == ["Strand"], "folder row content")
hv.close()

# --- search: exact title matches only, results as rows per category
press(home, "green")
type_text(s, "film 1")
sr = s.top
check(name(sr) == "SearchRowsScreen", "search results as rows")
pump(lambda: not sr.loading and sr.rows and sr.row_items, timeout=10)
check([r.title for r in sr.rows] == ["Filme"], "only categories with hits %s" % [r.title for r in sr.rows])
hits = [i["Name"] for i in sr.cache[("search", "Movie")][1]]
check(len(hits) == 10 and all("film 1" in h.lower() for h in hits), "exact hits %s" % hits)
check(sr["row_title"].getText() == "Filme  (10)", "count in row title")
sq = [q for q in state.item_queries if q.get("searchterm") or q.get("namestartswith")]
check(any(q.get("includeitemtypes") == "Series" and q.get("searchterm") for q in sq), "series are searched on their own")
check(any(q.get("namestartswith") == "film 1" for q in sq), "titles starting with the term are queried too")
check(all("sortby" not in q for q in sq if q.get("searchterm")), "server relevance order for the search term")
press(sr, "cancel")
check(name(s.top) == "HomeScreen" and home.last_search == "film 1", "search closed, term remembered")
# a server that returns fuzzy hits: only titles that really contain the term remain
state.fuzzy_search = True
press(home, "green")
type_text(s, "zwei")
sr = s.top
pump(lambda: not sr.loading and sr.rows and sr.row_items, timeout=10)
check([r.title for r in sr.rows] == ["Serien"] and [i["Name"] for i in sr.row_items if not i.get("_jf_more")] == ["Serie Zwei"],
	"fuzzy server: no pseudo hits (%s)" % [(r.title, len(sr.cache[r.key][1])) for r in sr.rows])
state.fuzzy_search = False
sr.close()
press(home, "green")
type_text(s, "i")
sr = s.top
pump(lambda: not sr.loading and len(sr.rows) >= 3, timeout=10)
rt = [r.title for r in sr.rows]
check(rt[:2] == ["Filme", "Serien"] and "Personen" in rt, "categories as rows %s" % rt)
press(sr, "down")
check(sr.current().title == "Serien" and all(i["Type"] == "Series" for i in sr.row_items if not i.get("_jf_more")), "down = next category")
goto_row(sr, "Personen")
check(all(i["Type"] == "Person" for i in sr.row_items if not i.get("_jf_more")), "person row")
press(sr, "ok")
pump(lambda: name(s.top) == "GridScreen" and s.top.entries, timeout=10)
check(s.top.spec["params"].get("personIds"), "person -> filmography")
press(s.top, "cancel")
press(sr, "red")
check(name(s.top) == "GridScreen" and all(e["Type"] == "Person" for e in s.top.entries), "red = all hits of the category")
press(s.top, "cancel")
sr.close()
# favourites (mixed list): restrict to a category
home["menu"].moveToIndex([sec[0] for sec in home.sections].index("favorites"))
press(home, "ok")
fav = s.top
pump(lambda: len(fav.entries) > 0, timeout=10)
press(fav, "green")
check(any(c[0] == "Kategorie: Filme" for c in s.top.list), "favourites offer categories")
choose(s, "Kategorie: Serien")
pump(lambda: not fav.loading, timeout=10)
fq = state.item_queries[-1]
check(fq.get("includeitemtypes") == "Series" and fq.get("filters") == "IsFavorite", "favourites restricted to series")
press(fav, "cancel")

# --- settings
# --- rule editor: new list "Komödien" (all time, newest first)
press(home, "blue")
rs = s.top
check(name(rs) == "RulesScreen" and len(rs.rules) == 4, "rules screen with 4 default lists")
press(rs, "green")
ed = s.top
check(name(ed) == "RuleEditScreen", "rule editor")
press(ed, "ok")
type_text(s, "Komödien")
fields = [r[0] for r in ed["list"].list]
check("my_series" not in fields, "episode-only fields hidden for movies")
ed["list"].moveToIndex(fields.index("genre"))
press(ed, "ok")
pump(lambda: name(s.top) == "ChoiceBox", timeout=10)
choose(s, "Komödie")
ed["list"].moveToIndex(fields.index("days"))
while ed.rule["days"] != "0":
	press(ed, "left")
ed["list"].moveToIndex(fields.index("type"))
press(ed, "right")
press(ed, "right")
check(ed.rule["type"] == "Episode" and "group" in [r[0] for r in ed["list"].list], "episode fields appear")
press(ed, "left")
press(ed, "left")
press(ed, "green")
check(name(s.top) == "RulesScreen" and len(rs.rules) == 5 and rs.rules[-1]["name"] == "Komödien", "rule saved")
import json as _json
check("Komödien" in [r["name"] for r in _json.loads(jfconfig.config.plugins.jellyfine2.rules.value)], "rules persisted in config")
rs["list"].moveToIndex(4)
press(rs, "yellow")
press(s.top, "cancel")  # editor closed without result must not crash
check(name(s.top) == "RulesScreen" and len(rs.rules) == 5, "cancel in rule editor")
press(rs, "ok")
kg = s.top
pump(lambda: len(kg.entries) > 0, timeout=10)
kids = [e["Id"] for e in kg.entries]
check(len(kids) == 19 and kids[0] == "m4", "comedy rule: %d items, first %s" % (len(kids), kids[:1]))
press(kg, "cancel")
press(rs, "cancel")
pump(lambda: "Komödien" in [sec[1] for sec in home.sections], timeout=5)
check("Komödien" in [sec[1] for sec in home.sections], "new list on start screen")

home["menu"].moveToIndex([sec[0] for sec in home.sections].index("settings"))
press(home, "ok")
st = s.top
check(name(st) == "SettingsScreen", "settings opened")
rows = [r[0] for r in st["list"].list]
check(rows.count("_group") == 4 and st["list"].getSelectedIndex() == 1, "settings in 4 groups, cursor on the first setting")
press(st, "up")
check(st["list"].getSelectedIndex() == 1, "group title at the top is not selectable")
st["list"].moveToIndex(rows.index("_group", 2) - 1)
press(st, "down")
check(st["list"].getCurrent()[0] != "_group" and st["list"].getSelectedIndex() == rows.index("_group", 2) + 1, "down jumps over a group title")
press(st, "up")
check(st["list"].getSelectedIndex() == rows.index("_group", 2) - 1, "up jumps back over it")
st["list"].moveToIndex(rows.index("playmode"))
press(st, "right")
check(st.vals["playmode"] == "direct", "change setting")
press(st, "green")
check(jfconfig.get("playmode") == "direct", "setting saved")
jfconfig.set_value("playmode", "auto")
check(name(s.top) == "HomeScreen", "settings closed")

# --- logout + quick connect
press(home, "red")
answer(s, True)
pump(lambda: name(s.top) == "LoginScreen", timeout=5)
check(name(s.top) == "LoginScreen" and not jfconfig.client().token, "logout -> login")
login = s.top
check(login.server == URL, "server remembered")
press(login, "yellow")
pump(lambda: name(s.top) == "QuickConnectScreen", timeout=10)
qc = s.top
check(qc["code"].getText() == "123456", "quick connect code shown")
pump(lambda: name(s.top) == "HomeScreen", timeout=15)
check(name(s.top) == "HomeScreen" and jfconfig.client().token == "tok123", "quick connect login")
home = s.top
pump(lambda: len(home.sections) > 5, timeout=10)

# --- modern start screen (hero): switch via MENU
press(home, "menu")
choose(s, "Ansicht: Moderne Startseite")
pump(lambda: name(s.top) == "HeroHomeScreen", timeout=5)
hero = s.top
check(name(hero) == "HeroHomeScreen" and jfconfig.get("home_layout") == "hero", "switched to hero layout")
pump(lambda: hero.row_items and hero.cells.items[0] is not None, timeout=10)
rows = [r.title for r in hero.rows]
check(rows[:2] == ["Neue Filme", "Neue Episoden meiner Serien"] and "Suche" not in rows and "Einstellungen" not in rows, "hero rows %s" % rows[:4])
check(hero["row_title"].getText() == "Neue Filme" and hero["next_row"].getText() == "Neue Episoden meiner Serien", "row labels")
check(hero["hero_title"].getText() == "Film 01" and "NEU" not in hero["hero_meta"].getText() and hero["hero_new"].visible,
	"hero shows focused movie + NEU badge: %s | %s | %s" % (hero["hero_title"].getText(), hero["hero_meta"].getText(), hero["hero_new"].visible))
check(hero["hero_pill1"].getText() == "Abspielen" and hero["hero_pill2"].getText() == "Details", "hero pills")
check(hero.row_items[-1].get("_jf_more"), "last card = show all")
pump(lambda: hero["ccover1"].visible and hero["ccover1"].instance.pixmap is not None, timeout=10)
check(hero["ccover1"].instance.pixmap is not None, "landscape card image loaded")
pump(lambda: hero["backdrop"].instance.pixmap is not None, timeout=10)
check(hero["backdrop"].instance.pixmap is not None, "hero backdrop loaded")
for _ in range(6):
	press(hero, "right")
check(hero.card == 6 and hero.first == 2 and hero["frame"].instance.pos == (int(round((160 + 4 * 340 - 8) * HEIGHT / 1080.0)), int(round((672 - 8) * HEIGHT / 1080.0))), "cards scroll, frame on 5th card %s" % (hero["frame"].instance.pos,))
check(hero["hero_title"].getText() == hero.row_items[6]["Name"], "hero follows focus")
# smooth: moving inside the visible cards only moves the frame; cards seen before are not decoded again
card_px = (int(round(300 * HEIGHT / 1080.0)), int(round(169 * HEIGHT / 1080.0)))
row_files = set(hero.images.path_for(image_ref(i, "card"), *card_px) for i in hero.row_items if image_ref(i, "card"))


def row_decodes():
	"""Decodes of this row's cards (prefetch of other rows may still run meanwhile)."""
	return [d for d in enigma.ePicLoad.decoded if (d[1], d[2]) == card_px and os.path.splitext(d[0])[0] in row_files]


cards_decoded = len(row_decodes())
covers = [hero["ccover%d" % i].instance.pixmap for i in range(5)]
press(hero, "left")
check([hero["ccover%d" % i].instance.pixmap for i in range(5)] == covers and hero.first == 2, "frame moves, cards stay")
for _ in range(5):
	press(hero, "left")
pump(timeout=0.3)
check(hero.first == 0 and all(hero["ccover%d" % i].visible for i in range(5) if hero.cells.items[i] and image_ref(hero.cells.items[i], "card")),
	"scrolled back, all cards visible at once")
check(len(row_decodes()) == cards_decoded, "no new decoding when scrolling back (cache)")
check(not enigma.JPG_LOADS, "no JPEG decoded on the GUI thread (%d)" % len(enigma.JPG_LOADS))
check(all(not inst.busy for inst in enigma.ePicLoad.instances), "decoders idle")
for _ in range(6):
	press(hero, "right")
press(hero, "down")
check(hero.row == 1 and hero.card == 0, "down = next row")
pump(lambda: hero.row_items and hero.row_items[0].get("_jf_new_count"), timeout=10)
check(hero["hero_title"].getText() == "Serie Eins" and "3 neue Folgen" in hero["hero_meta"].getText() and hero["hero_pill1"].getText() == "Neue Folge",
	"grouped series in hero: %s" % hero["hero_meta"].getText())
press(hero, "ok")
check(name(s.top) == "EpisodesScreen", "OK on grouped tile -> episodes")
press(s.top, "cancel")
press(hero, "up")
press(hero, "left")
check(hero.mode == "rail" and hero["rail_sel"].visible and hero.rail == 1 and hero["rail_name1"].visible and hero["rail_name1"].instance.fg == 0xf2f2f2
	and hero["rail_name0"].instance.fg == 0x9a9aae and not hero["hero_title"].visible and not hero["hero_pillbg1"].visible, "left on first card -> expanded rail")
press(hero, "up")
check(hero.rail == 0 and hero["rail_name0"].instance.fg == 0xf2f2f2, "rail up")
press(hero, "ok")
type_text(s, "serie")
pump(lambda: name(s.top) == "SearchRowsScreen" and s.top.row_items, timeout=10)
check(name(s.top) == "SearchRowsScreen", "rail search")
srh = s.top
press(srh, "left")
check(srh.mode == "rail" and srh.rail == 0, "sidebar in the search too")
press(srh, "down")
press(srh, "down")
press(srh, "down")
press(srh, "ok")
pump(lambda: name(s.top) == "LibraryRowsScreen", timeout=10)
check(name(s.top) == "LibraryRowsScreen" and s.top.kind == "tvshows" and len(s.stack) == 2, "sidebar of a sub screen -> series (stack stays flat)")
check(hero.last_search == "serie", "last search remembered")
s.top.close()
press(hero, "down")
press(hero, "down")
press(hero, "ok")
pump(lambda: name(s.top) == "LibraryRowsScreen" and s.top.row_items, timeout=10)
check(s.top.kind == "movies", "rail -> movie library")
s.top.close()
press(hero, "right")
check(hero.mode == "rows" and hero["frame"].visible and not hero["rail_sel"].visible and not hero["rail_name0"].visible and hero["hero_title"].visible,
	"back to rows")
press(hero, "red")
pump(lambda: name(s.top) == "GridScreen" and s.top.entries, timeout=10)
check(s.top.spec["source"] == "rule", "red = all titles of the row")
press(s.top, "cancel")
press(hero, "info")
check(name(s.top) == "DetailScreen", "INFO -> details")
press(s.top, "cancel")
press(hero, "right")
press(hero, "cancel")
check(name(s.top) == "HeroHomeScreen" and hero.card == 0, "EXIT on a moved row jumps back, does not close")

# --- auto update (GitHub release check)
check(jfupdate.is_newer("v1.10.0", "1.9.3") and not jfupdate.is_newer("v1.2.0", "1.2.0"), "version compare")
check(jfupdate.due("0") and not jfupdate.due(str(__import__("time").time())), "check interval")
jfconfig.set_value("update_check", "1")
jfconfig.set_update_stamp(0)
press(hero, "cancel")
check(not s.stack, "plugin closed")
plugin.main(s)
hero = s.top
pump(lambda: name(s.top) == "MessageBox", timeout=10)
box = s.top
check(name(box) == "MessageBox" and "9.9.9 ist verfügbar" in box.text and "- Neue Startseite mit Titelbild" in box.text and "Installation" not in box.text,
	"update offered: %r" % box.text[:80])
check(float(jfconfig.get_update_stamp()) > 0, "check time stored")
answer(s, True)
pump(lambda: console_stub.COMMANDS, timeout=10)
check(console_stub.COMMANDS and console_stub.COMMANDS[-1].startswith("opkg install --force-reinstall") and "/tmp/jellyfine2_update.ipk" in console_stub.COMMANDS[-1],
	"opkg install %s" % console_stub.COMMANDS[-1:])
pump(lambda: name(s.top) == "MessageBox" and "neu starten" in s.top.text, timeout=5)
answer(s, True)
check(standby_stub.RESTARTS == [3], "GUI restart requested")
while s.stack:
	s.top.close()
# no second prompt within the interval; manual check with a broken checksum
plugin.main(s)
pump(timeout=1.5)
check(name(s.top) == "HeroHomeScreen", "no repeated update prompt")
state.gh_sum = "0" * 64
s.top.updater().run_check(manual=True)
pump(lambda: name(s.top) == "MessageBox", timeout=10)
answer(s, True)
pump(lambda: name(s.top) == "MessageBox" and "Prüfsumme" in s.top.text, timeout=10)
check("Prüfsumme" in s.top.text and len(console_stub.COMMANDS) == 1, "bad checksum -> no install")
answer(s, False)
state.gh_version = "1.0.0"
s.top.updater().run_check(manual=True)
pump(lambda: name(s.top) == "MessageBox", timeout=10)
check("ist aktuell" in s.top.text, "manual check: up to date")
answer(s, False)
press(s.top, "cancel")
check(not s.stack, "plugin closed")

# --- languages: English and Dutch, switched in the settings (default "auto" -> German without system language)
from JellyfinOpenPLi import jfi18n  # noqa: E402

jfconfig.set_value("update_check", "0")


def untranslated(scr, lang):
	"""Labels that still show a German text although a translation exists."""
	cat = jfi18n.load_catalog(lang)
	german = set(k for k, v in cat.items() if isinstance(v, str) and v != k)
	return [(key, w.getText()) for key, w in scr.items() if hasattr(w, "getText") and w.getText() in german]


def switch_language(target):
	hero = s.top
	hero.key_settings()
	st = s.top
	rows = [r[0] for r in st["list"].list]
	check(rows[0] == "_group" and rows[1] == "language", "language is the first setting")
	st["list"].moveToIndex(1)
	for _i in range(5):
		if st.vals["language"] == target:
			break
		press(st, "right")
	press(st, "green")
	pump(lambda: name(s.top) == "HeroHomeScreen" and s.top is not hero, timeout=10)
	return s.top


check(jfi18n.current() == "de" and jfconfig.get("language") == "auto", "auto language without system language: German")
plugin.main(s)
pump(lambda: name(s.top) == "HeroHomeScreen", timeout=10)
for lang, expect in (("en", {"rail_name0": "Search", "rail_name2": "Movies", "rail_name3": "Shows", "key_green": "Search"}),
		("nl", {"rail_name0": "Zoeken", "rail_name2": "Films", "rail_name3": "Series", "key_green": "Zoeken"})):
	hero = switch_language(lang)
	check(jfi18n.current() == lang and jfconfig.get("language") == lang, "%s: language saved and active" % lang)
	pump(lambda: hero.row_items and hero["hero_pill1"].getText(), timeout=10)
	got = dict((k, hero[k].getText()) for k in expect)
	check(got == expect, "%s: start screen translated %s" % (lang, got))
	check(not untranslated(hero, lang), "%s: no German label left on the start screen %s" % (lang, untranslated(hero, lang)))
	titles = [r.title for r in hero.rows]
	check((("Continue watching" in titles) if lang == "en" else ("Verder kijken" in titles)) or (("New movies" in titles) if lang == "en" else ("Nieuwe films" in titles)),
		"%s: row titles %s" % (lang, titles[:4]))
	press(hero, "info")
	det = s.top
	pump(lambda: det["pilltxt0"].getText(), timeout=10)
	check(name(det) == "DetailScreen" and not untranslated(det, lang), "%s: details translated %s" % (lang, untranslated(det, lang)))
	check(det["pilltxt0"].getText() in (("Play", "Resume", "Open") if lang == "en" else ("Afspelen", "Hervatten", "Openen")),
		"%s: detail button %r" % (lang, det["pilltxt0"].getText()))
	press(det, "cancel")
	press(hero, "red")
	grid = s.top
	pump(lambda: grid.entries, timeout=10)
	check(name(grid) == "GridScreen" and not untranslated(grid, lang), "%s: grid translated %s" % (lang, untranslated(grid, lang)))
	press(grid, "cancel")
	press(hero, "blue")
	rs = s.top
	press(rs, "yellow")
	ed = s.top
	check(name(rs) == "RulesScreen" and name(ed) == "RuleEditScreen" and not untranslated(rs, lang) and not untranslated(ed, lang),
		"%s: lists and list editor translated %s" % (lang, untranslated(rs, lang) + untranslated(ed, lang)))
	check(ed.value_text("name") == ("New movies" if lang == "en" else "Nieuwe films"), "%s: default list name %r" % (lang, ed.value_text("name")))
	press(ed, "cancel")
	press(rs, "cancel")
	hero.key_settings()
	st = s.top
	check(st["title"].getText() == ("Jellyfin - Settings" if lang == "en" else "Jellyfin - Instellingen") and not untranslated(st, lang),
		"%s: settings screen translated" % lang)
	desc = [d for d in plugin.Plugins() if PluginDescriptor.WHERE_PLUGINMENU in d.where][0].description
	check(desc.startswith("Jellyfin client" if lang == "en" else "Jellyfin-client"), "%s: plugin description %r" % (lang, desc))
	press(st, "cancel")
check(jfi18n.decimal("7.5") == "7,5" and jfi18n.ngettext("%d Staffel", "%d Staffeln", 2) == "%d seizoenen", "nl number format and plural")
hero = switch_language("auto")
check(jfi18n.current() == "de" and hero["rail_name0"].getText() == "Suche", "back to German")
press(hero, "cancel")
check(not s.stack, "plugin closed")

# --- static checks
unexpected = [w for w in WARNINGS]
check(not unexpected, "all actions exist in keymap contexts %s" % unexpected[:5])
check(not SKIN_ERRORS, "skins valid %s" % SKIN_ERRORS[:5])
# api routes used match version
new_routes = [r for r in state.requests if r[1].startswith(("/UserViews", "/UserItems", "/UserPlayedItems", "/UserFavoriteItems"))]
old_routes = [r for r in state.requests if r[1].startswith("/Users/u1/")]
if parse_version(VERSION) >= (10, 9, 0):
	check(new_routes and not old_routes, "new routes only")
else:
	check(old_routes and not new_routes, "old routes only")
missing = [r for r in state.requests if r[1] not in ("/System/Info/Public",) and r[0] != "GET" or False]
plugin_log = [ln for ln in "".join(LOG.text).splitlines() if ln.startswith("[Jellyfin]")]
check(any("ApiKey=***" in ln for ln in plugin_log) and not any("tok123" in ln for ln in plugin_log),
	"no access token in the log (%d plugin lines)" % len(plugin_log))
noauth = [r for r in state.requests if 'Client="Jellyfin Enigma2"' not in r[4].get("Authorization", "") and not r[1].startswith("/gh/")]
check(not noauth, "every request carries the MediaBrowser auth header")
check(len(state.connections) < 40 and len(state.requests) > 150, "keep-alive: %d requests over %d connections" % (len(state.requests), len(state.connections)))

print("\nVERSION %s HEIGHT %d: %d failures" % (VERSION, HEIGHT, len(failures)))
srv.shutdown()
os._exit(1 if failures else 0)
