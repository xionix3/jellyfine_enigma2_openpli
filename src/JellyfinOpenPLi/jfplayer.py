# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Jellyfin for Enigma2 - playback (MoviePlayer subclass with resume, reporting, autoplay)
from __future__ import absolute_import

from .jfi18n import _, N_

from enigma import eServiceReference, eTimer, iPlayableService

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.ServiceEventTracker import ServiceEventTracker
from Screens.ChoiceBox import ChoiceBox
from Screens.InfoBar import MoviePlayer
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen

from . import jfconfig
from .jfapi import make_play_report
from .jfasync import runner
from .jfutil import (clean_text, display_title, episode_code, fmt_clock, is_played, media_streams, resume_ticks,
	stream_label, ticks_to_seconds, video_label)
from .jflog import log

PTS_PER_SECOND = 90000
TICKS_PER_SECOND = 10000000
REPORT_INTERVAL_MS = 10000
COUNTDOWN_S = 10
# media segments the overlay offers to skip, with the button text
SKIP_LABELS = {"Intro": N_("Intro überspringen"), "Recap": N_("Rückblick überspringen"), "Preview": N_("Vorschau überspringen"),
	"Commercial": N_("Werbung überspringen")}


def pts_to_ticks(pts):
	return int(pts) * 1000 // 9


def ticks_to_pts(ticks):
	return int(ticks) * 9 // 1000


def make_ref(url, title):
	ref = eServiceReference(int(jfconfig.get("player")), 0, url)
	ref.setName(title)
	return ref


def _bg_group():
	# reports must survive the player screen
	return runner().group()


# ------------------------------------------------------------------------------------------
# entry point used by all screens
# ------------------------------------------------------------------------------------------
def play_item(screen, item, context=None, index=0, resume=None, on_finished=None,
		audio_index=None, sub_index=None, media_source_id=None):
	"""Resolve what to play for `item` (series -> next episode, album -> tracks, ...) and start."""
	cl = screen.cl
	if item.get("_jf_focus"):
		item = item["_jf_focus"]
		context = None
	t = item.get("Type")

	def start(queue, idx):
		if not queue:
			screen.info(_("Nichts abspielbar gefunden"))
			return
		_ask_resume_and_play(screen, queue, idx, resume, on_finished, audio_index, sub_index, media_source_id)

	if t == "Series":
		def resolve_series():
			nxt = cl.next_up(limit=1, series_id=item["Id"])
			eps = cl.episodes(item["Id"])
			eps = [e for e in eps if e.get("LocationType") != "Virtual"]
			if nxt:
				for i, e in enumerate(eps):
					if e.get("Id") == nxt[0].get("Id"):
						return eps, i
				return [nxt[0]], 0
			for i, e in enumerate(eps):
				if not is_played(e):
					return eps, i
			return eps, 0
		screen.run(resolve_series, callback=lambda r: start(*r), status=_("Suche nächste Episode ..."))
	elif t == "Season":
		def resolve_season():
			eps = [e for e in cl.episodes(item.get("SeriesId"), item["Id"]) if e.get("LocationType") != "Virtual"]
			for i, e in enumerate(eps):
				if not is_played(e):
					return eps, i
			return eps, 0
		screen.run(resolve_season, callback=lambda r: start(*r), status=_("Lade Episoden ..."))
	elif t == "MusicAlbum":
		screen.run(cl.album_tracks, item["Id"], callback=lambda tracks: start(tracks, 0), status=_("Lade Titel ..."))
	elif t in ("BoxSet", "Playlist", "Folder"):
		def resolve_children():
			params = {"parentId": item["Id"], "recursive": True, "includeItemTypes": "Movie,Episode,Video,MusicVideo,Audio"}
			if t == "BoxSet":
				params.update(sortBy="PremiereDate,ProductionYear,SortName", sortOrder="Ascending")
			elif t == "Folder":
				params.update(sortBy="SortName", sortOrder="Ascending")
			res = cl.items(**params)  # playlists keep their own order
			return res.get("Items") or []
		screen.run(resolve_children, callback=lambda items: start(items, 0), status=_("Lade ..."))
	elif t == "Audio" and context:
		tracks = [it for it in context if it.get("Type") == "Audio"]
		idx = tracks.index(item) if item in tracks else 0
		start(tracks or [item], idx)
	else:
		start([item], 0)


def _ask_resume_and_play(screen, queue, idx, resume, on_finished, audio_index, sub_index, media_source_id):
	item = queue[idx]
	pos = resume_ticks(item)
	mode = jfconfig.get("resume_ask")

	def go(start_ticks):
		start_playback(screen, queue, idx, start_ticks, on_finished, audio_index, sub_index, media_source_id)

	if resume is True:
		go(pos)
	elif resume is False or not pos or is_played(item):
		go(0)
	elif mode == "resume":
		go(pos)
	elif mode == "start":
		go(0)
	else:
		def chosen(choice):
			if choice is not None:
				go(choice[1])
		choices = [(_("Fortsetzen ab %s") % fmt_clock(ticks_to_seconds(pos)), pos), (_("Von Anfang abspielen"), 0)]
		screen.session.openWithCallback(chosen, ChoiceBox, title=display_title(item), list=choices)


def start_playback(screen, queue, idx, start_ticks=0, on_finished=None, audio_index=None, sub_index=None, media_source_id=None):
	cl = screen.cl
	item = queue[idx]
	opts = jfconfig.playback_options()

	def resolve():
		info = cl.playback_info(item["Id"], opts, start_ticks=start_ticks, audio_index=audio_index, sub_index=sub_index, media_source_id=media_source_id)
		stream = cl.resolve_stream(item, info, opts, media_source_id=media_source_id)
		return stream

	def ok(stream):
		log("play %s via %s: %s" % (item.get("Name"), stream.get("play_method"), stream["url"]))
		screen.session.openWithCallback(on_finished or (lambda *a: None), JellyfinPlayer, cl, queue, idx, stream,
			start_ticks, audio_index, sub_index)

	screen.run(resolve, callback=ok, status=_("Starte Wiedergabe ..."), errback=lambda e: screen.show_error(e, _("Wiedergabe nicht möglich")))


# ------------------------------------------------------------------------------------------
# overlay
# ------------------------------------------------------------------------------------------
class PlayerOsd(Screen):
	"""Shown above the video without taking the keys (the player handles OK/EXIT while it is visible)."""

	def __init__(self, session):
		from .jfskin import osd_skin
		Screen.__init__(self, session)
		self.skin = osd_skin()
		self["osd_title"] = Label("")
		self["osd_sub"] = Label("")


# ------------------------------------------------------------------------------------------
# the player
# ------------------------------------------------------------------------------------------
class JellyfinPlayer(MoviePlayer):
	ENABLE_RESUME_SUPPORT = False
	ALLOW_SUSPEND = True

	def __init__(self, session, cl, queue, index, stream, start_ticks=0, audio_index=None, sub_index=None):
		self.cl = cl
		self.queue = list(queue)
		self.index = index
		self.stream = stream
		self.start_ticks = int(start_ticks or 0)
		self.audio_index = audio_index
		self.sub_index = sub_index
		self.started = False
		self.stopped_reported = False
		self.last_ticks = self.start_ticks
		self.offset_ticks = 0
		self.resume_tries = 0
		self.track_tries = 0
		self.switching = False
		self.jf_closing = False
		self.tasks = runner().group()
		self.bg = _bg_group()
		self.autoplay = jfconfig.get_bool("autoplay_next")
		self.seek_skip = jfconfig.get("seek_mode") == "skip"
		self.skip_mode = jfconfig.get("skip_segments")  # ask / auto / off
		self.segments = []
		self.segments_done = set()  # skipped or dismissed (type, start)
		self.osd_kind = None  # None / "skip" / "next"
		self.osd_segment = None
		self.countdown = None
		self.countdown_cancelled = False
		self.queue_extended = False
		ref = make_ref(stream["url"], self.title_for(self.current_item()))
		MoviePlayer.__init__(self, session, ref)
		self.skinName = ["JellyfinE2Player", "MoviePlayer"]
		self.setTitle(self.title_for(self.current_item()))
		self.report_timer = eTimer()
		self.report_timer.callback.append(self.report_progress)
		self.resume_timer = eTimer()
		self.resume_timer.callback.append(self.try_resume)
		self.track_timer = eTimer()
		self.track_timer.callback.append(self.try_select_tracks)
		self.osd_timer = eTimer()
		self.osd_timer.callback.append(self.check_osd)
		self.osd = session.instantiateDialog(PlayerOsd)
		# before the infobar's own OK/EXIT; returns 0 (not handled) while no overlay is shown
		self["JellyfinOsdActions"] = ActionMap(["OkCancelActions"], {"ok": self.osd_ok, "cancel": self.osd_cancel}, -3)
		self["JellyfinActions"] = ActionMap(["MoviePlayerActions", "InfobarEPGActions"], {
			"movePrev": self.play_previous,
			"moveNext": self.play_next_key,
			"showEventInfo": self.show_info,
		}, -2)
		self.__event_tracker = ServiceEventTracker(screen=self, eventmap={
			iPlayableService.evStart: self.on_service_start,
		})
		self.onClose.append(self.on_player_close)
		self.extend_queue()

	# ------------------------------------------------------------- helpers
	def current_item(self):
		return self.queue[self.index]

	@staticmethod
	def title_for(item):
		if item.get("Type") == "Episode":
			code = episode_code(item)
			series = item.get("SeriesName") or ""
			return "%s %s - %s" % (series, code, item.get("Name", "")) if series else item.get("Name", "")
		return display_title(item)

	def current_ticks(self):
		try:
			service = self.session.nav.getCurrentService()
			seek = service and service.seek()
			if seek:
				r = seek.getPlayPosition()
				if r and not r[0] and r[1] >= 0:
					self.last_ticks = self.offset_ticks + pts_to_ticks(r[1])
		except Exception:
			pass
		return self.last_ticks

	def is_paused(self):
		return getattr(self, "seekstate", None) == self.SEEK_STATE_PAUSE

	def report_body(self, failed=False):
		return make_play_report(self.current_item()["Id"], self.stream, self.current_ticks(), self.is_paused(),
			self.audio_index, self.sub_index, failed)

	def extend_queue(self):
		"""For episodes: append the following episodes of the series (autoplay)."""
		item = self.current_item()
		if self.queue_extended or not self.autoplay or item.get("Type") != "Episode" or not item.get("SeriesId") or len(self.queue) > 1:
			return
		self.queue_extended = True
		cl = self.cl

		def load():
			return [e for e in cl.episodes(item["SeriesId"]) if e.get("LocationType") != "Virtual"]

		def ok(eps):
			if self.jf_closing:
				return
			ids = [e.get("Id") for e in eps]
			cur = self.current_item().get("Id")
			if cur in ids:
				pos = ids.index(cur)
				self.queue = [self.current_item()] + eps[pos + 1:]
				self.index = 0
		self.tasks.run(load, callback=ok, errback=lambda e: None)

	# ------------------------------------------------------------- events
	def on_service_start(self):
		if self.jf_closing:
			return
		self.switching = False
		if not self.started:
			self.started = True
			self.stopped_reported = False
			self.bg.run(self.cl.report_start, self.report_body(), pool="bg")
			self.report_timer.start(REPORT_INTERVAL_MS, False)
			self.load_segments()
		if self.start_ticks > 0:
			if self.stream.get("play_method") == "Transcode" and not self.stream.get("is_hls"):
				# progressive transcode already starts at StartTimeTicks
				self.offset_ticks = self.start_ticks
			else:
				self.resume_tries = 0
				self.resume_timer.start(500, False)
		if self.stream.get("play_method") == "DirectPlay" and (self.audio_index is not None or self.sub_index is not None):
			self.track_tries = 0
			self.track_timer.start(1500, False)

	def try_resume(self):
		self.resume_tries += 1
		seek = self.getSeek()
		ready = False
		if seek is not None:
			try:
				length = seek.getLength()
				ready = bool(seek.isCurrentlySeekable()) and length and not length[0] and length[1] > 0
			except Exception:
				ready = False
		if ready or (seek is not None and self.resume_tries >= 40):
			self.resume_timer.stop()
			target = ticks_to_pts(self.start_ticks)
			log("resume at %ss" % ticks_to_seconds(self.start_ticks))
			try:
				seek.seekTo(target)
			except Exception as e:
				log("resume failed: %s" % e)
			self.last_ticks = self.start_ticks
			self.start_ticks = 0
		elif self.resume_tries >= 60:
			self.resume_timer.stop()
			self.start_ticks = 0

	def stream_position(self, kind, index):
		"""Position of a Jellyfin stream index among the container's streams of that type."""
		streams = [s for s in media_streams({}, self.stream.get("media_source") or {}) if s.get("Type") == kind and not s.get("IsExternal")]
		streams.sort(key=lambda s: s.get("Index", 0))
		for pos, s in enumerate(streams):
			if s.get("Index") == index:
				return pos
		return None

	def try_select_tracks(self):
		self.track_tries += 1
		service = self.session.nav.getCurrentService()
		done = True
		if service and self.audio_index is not None:
			pos = self.stream_position("Audio", self.audio_index)
			try:
				tracks = service.audioTracks()
				n = tracks and tracks.getNumberOfTracks() or 0
				if pos is not None and n and pos < n:
					if tracks.getCurrentTrack() != pos:
						tracks.selectTrack(pos)
				elif n == 0:
					done = False
			except Exception as e:
				log("audio track select failed: %s" % e)
		if service and self.sub_index is not None and self.sub_index >= 0:
			pos = self.stream_position("Subtitle", self.sub_index)
			try:
				sub = service.subtitle()
				lst = sub and sub.getSubtitleList() or []
				if pos is not None and pos < len(lst):
					self.enableSubtitle(lst[pos])
				elif not lst:
					done = False
			except Exception as e:
				log("subtitle select failed: %s" % e)
		if done or self.track_tries >= 6:
			self.track_timer.stop()

	def report_progress(self):
		if self.jf_closing or self.switching or not self.started:
			return
		self.bg.run(self.cl.report_progress, self.report_body(), pool="bg")

	def report_stopped(self, finished=False):
		if self.stopped_reported or not self.started:
			return
		self.stopped_reported = True
		body = self.report_body()
		if finished:
			run = self.current_item().get("RunTimeTicks") or 0
			if run:
				body["PositionTicks"] = int(run)
		stream = self.stream
		cl = self.cl

		def send():
			cl.report_stop(body)
			if stream.get("play_method") == "Transcode" and stream.get("play_session_id"):
				cl.stop_encoding(stream["play_session_id"])
		self.bg.run(send, pool="bg")

	# ------------------------------------------------------------- queue handling
	def has_next(self):
		return self.index + 1 < len(self.queue)

	def play_index(self, idx, start_ticks=0):
		if idx < 0 or idx >= len(self.queue):
			return
		self.report_timer.stop()
		self.resume_timer.stop()
		self.track_timer.stop()
		self.osd_timer.stop()
		self.hide_osd()
		self.report_stopped()
		self.switching = True
		item = self.queue[idx]
		opts = jfconfig.playback_options()
		cl = self.cl

		def resolve():
			info = cl.playback_info(item["Id"], opts, start_ticks=start_ticks)
			return cl.resolve_stream(item, info, opts)

		def ok(stream):
			if self.jf_closing:
				return
			self.index = idx
			self.stream = stream
			self.start_ticks = int(start_ticks or 0)
			self.offset_ticks = 0
			self.last_ticks = self.start_ticks
			self.audio_index = None
			self.sub_index = None
			self.started = False
			self.stopped_reported = False
			title = self.title_for(item)
			ref = make_ref(stream["url"], title)
			self.cur_service = ref
			self.setTitle(title)
			self.session.nav.playService(ref)
			self.switching = False
			self.show()

		def fail(err):
			self.switching = False
			if self.jf_closing:
				return
			self.session.openWithCallback(lambda *a: self.close(), MessageBox, _("Nächster Titel kann nicht abgespielt werden:\n%s") % err, MessageBox.TYPE_ERROR, timeout=8)
		self.tasks.run(resolve, callback=ok, errback=fail)

	def play_next_key(self):
		if self.has_next():
			self.play_index(self.index + 1)

	def play_previous(self):
		if self.current_ticks() > 15 * 10000000 or self.index == 0:
			self.doSeek(0)
		else:
			self.play_index(self.index - 1)

	# ------------------------------------------------------------- MoviePlayer overrides
	def doEofInternal(self, playing):
		if self.jf_closing or self.switching:
			return
		self.report_stopped(finished=True)
		if self.autoplay and self.has_next() and not self.countdown_cancelled:
			self.play_index(self.index + 1)
		else:
			self.stop_and_close()

	def leavePlayer(self):
		self.stop_and_close()

	def leavePlayerOnExit(self):
		if self.shown:
			self.hide()
		else:
			self.stop_and_close()

	def stop_and_close(self):
		if self.jf_closing:
			return
		self.current_ticks()
		self.report_stopped()
		self.jf_closing = True
		self.is_closing = True
		self.close()

	def on_player_close(self):
		self.jf_closing = True
		for t in (self.report_timer, self.resume_timer, self.track_timer, self.osd_timer):
			t.stop()
		if self.osd is not None:
			self.osd.hide()
			self.session.deleteDialog(self.osd)
			self.osd = None
		self.report_stopped()
		self.tasks.cancel()

	def showMovies(self, *args, **kwargs):
		pass

	def up(self):
		self.toggleShow()

	def down(self):
		self.toggleShow()

	def left(self):
		if self.seek_skip:
			self.doSeekRelative(-10 * PTS_PER_SECOND)
		else:
			MoviePlayer.left(self)

	def right(self):
		if self.seek_skip:
			self.doSeekRelative(30 * PTS_PER_SECOND)
		else:
			MoviePlayer.right(self)

	# ------------------------------------------------------------- intro skip + next episode countdown
	def load_segments(self):
		self.segments = []
		self.segments_done = set()
		self.countdown = None
		self.countdown_cancelled = False
		self.hide_osd()
		item = self.current_item()
		if item.get("MediaType") == "Audio" or item.get("Type") in ("Audio", "MusicVideo"):
			return
		self.osd_timer.start(1000, False)
		if self.skip_mode == "off" and not (self.autoplay and self.has_next()):
			return
		item_id = item["Id"]

		def ok(segments):
			if not self.jf_closing and self.current_item().get("Id") == item_id:
				self.segments = segments or []
				if self.segments:
					log("media segments: %s" % ", ".join("%s %d-%ds" % (k, a // TICKS_PER_SECOND, b // TICKS_PER_SECOND) for k, a, b in self.segments))
		self.tasks.run(self.cl.media_segments, item_id, item.get("Type"), callback=ok, errback=lambda e: None)

	def can_seek(self):
		if self.stream.get("play_method") == "Transcode" and not self.stream.get("is_hls"):
			return False  # progressive transcode: no seeking
		seek = self.getSeek()
		try:
			return bool(seek and seek.isCurrentlySeekable())
		except Exception:
			return False

	def runtime_ticks(self):
		run = int(self.current_item().get("RunTimeTicks") or 0)
		if run:
			return run
		seek = self.getSeek()
		try:
			length = seek and seek.getLength()
			if length and not length[0] and length[1] > 0:
				return self.offset_ticks + pts_to_ticks(length[1])
		except Exception:
			pass
		return 0

	def countdown_start(self):
		"""Where the countdown to the next title begins: start of the credits (Outro) or 10 s before the end."""
		if not (self.autoplay and self.has_next()) or self.countdown_cancelled:
			return None
		run = self.runtime_ticks()
		for kind, start, _end in self.segments:
			if kind == "Outro" and start > run * 0.5:
				return start
		return run - COUNTDOWN_S * TICKS_PER_SECOND if run > 60 * TICKS_PER_SECOND else None

	def active_segment(self, pos):
		if self.skip_mode == "off":
			return None
		for kind, start, end in self.segments:
			if kind in SKIP_LABELS and start <= pos < end - 2 * TICKS_PER_SECOND and (kind, start) not in self.segments_done:
				return kind, start, end
		return None

	def check_osd(self):
		if self.jf_closing or self.switching or not self.started or self.is_paused():
			return
		pos = self.current_ticks()
		seg = self.active_segment(pos) if self.can_seek() else None
		if seg is not None and self.skip_mode == "auto":
			self.segments_done.add(seg[:2])
			self.skip_to(seg[2])
			return
		cd = self.countdown_start()
		if cd is not None and pos >= cd:
			self.countdown = COUNTDOWN_S if self.countdown is None else self.countdown - 1
			if self.countdown <= 0:
				self.hide_osd()
				self.osd_timer.stop()
				self.play_index(self.index + 1)
				return
			nxt = self.queue[self.index + 1]
			title = _("Nächste Folge in %d s") if nxt.get("Type") == "Episode" else _("Als Nächstes in %d s")
			self.show_osd("next", title % self.countdown, self.title_for(nxt))
			return
		self.countdown = None
		if seg is not None:
			self.osd_segment = seg
			self.show_osd("skip", _(SKIP_LABELS[seg[0]]), _("EXIT blendet aus"))
		else:
			self.hide_osd()

	def skip_to(self, ticks):
		seek = self.getSeek()
		if seek is None:
			return
		log("skip to %ss" % (ticks // TICKS_PER_SECOND))
		try:
			seek.seekTo(ticks_to_pts(max(0, ticks - self.offset_ticks)))
			self.last_ticks = ticks
		except Exception as e:
			log("skip failed: %s" % e)

	def show_osd(self, kind, title, sub):
		self.osd_kind = kind
		if self.osd is None:
			return
		self.osd["osd_title"].setText(title)
		self.osd["osd_sub"].setText(sub)
		if not self.osd.shown:
			self.osd.show()

	def hide_osd(self):
		self.osd_kind = None
		self.osd_segment = None
		if self.osd is not None and self.osd.shown:
			self.osd.hide()

	def osd_ok(self):
		if self.osd_kind == "skip" and self.osd_segment:
			kind, start, end = self.osd_segment
			self.segments_done.add((kind, start))
			self.hide_osd()
			self.skip_to(end)
			return None
		if self.osd_kind == "next":
			self.hide_osd()
			self.osd_timer.stop()
			self.play_index(self.index + 1)
			return None
		return 0  # not ours: the infobar shows/hides

	def osd_cancel(self):
		if self.osd_kind == "skip" and self.osd_segment:
			self.segments_done.add(self.osd_segment[:2])
			self.hide_osd()
			return None
		if self.osd_kind == "next":
			self.countdown_cancelled = True  # stay until the end, then leave instead of playing on
			self.countdown = None
			self.hide_osd()
			return None
		return 0

	def show_info(self):
		item = self.current_item()
		ms = self.stream.get("media_source") or {}
		streams = media_streams(item, ms)
		lines = [self.title_for(item), ""]
		ov = clean_text(item.get("Overview"))
		if ov:
			lines.append(ov[:600])
			lines.append("")
		video = [s for s in streams if s.get("Type") == "Video"]
		if video:
			lines.append(_("Video: %s") % video_label(video[0]))
		audio = [stream_label(s) for s in streams if s.get("Type") == "Audio"]
		if audio:
			lines.append(_("Audio: %s") % ", ".join(audio[:4]))
		method = {"DirectPlay": _("Direkt"), "Transcode": _("Transkodiert (Server)")}.get(self.stream.get("play_method"), "?")
		lines.append(_("Wiedergabe: %s%s") % (method, " / HLS" if self.stream.get("is_hls") else ""))
		if self.has_next():
			lines.append(_("Als Nächstes: %s") % self.title_for(self.queue[self.index + 1]))
		self.session.open(MessageBox, "\n".join(lines), MessageBox.TYPE_INFO, timeout=15)
