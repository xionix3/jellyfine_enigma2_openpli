# Off-box test harness: fake Enigma2 session, skin validation, event pumping
import os
import sys
import time
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "e2stubs"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

import enigma  # noqa: E402
from Components.ActionMap import ActionMap  # noqa: E402
from Components.GUIComponent import GUIComponent  # noqa: E402
from Components.ServiceEventTracker import TRACKERS  # noqa: E402

SKIN_ERRORS = []


class FakeSeek(object):
	def __init__(self, length_pts):
		self.pos = 0
		self.length = length_pts
		self.seeks = []
		self.ready = True

	def getPlayPosition(self):
		return (0, self.pos)

	def getLength(self):
		return (0, self.length) if self.ready else (1, 0)

	def isCurrentlySeekable(self):
		return 1 if self.ready else 0

	def seekTo(self, pts):
		self.seeks.append(pts)
		self.pos = pts

	def seekRelative(self, direction, pts):
		self.pos = max(0, self.pos + direction * pts)
		self.seeks.append(("rel", direction * pts))


class FakeTracks(object):
	def __init__(self):
		self.current = 0
		self.selected = []

	def getNumberOfTracks(self):
		return 2

	def getCurrentTrack(self):
		return self.current

	def selectTrack(self, i):
		self.current = i
		self.selected.append(i)


class FakeSubs(object):
	def getSubtitleList(self):
		return [(2, 0, 0, 0, "ger"), (2, 1, 0, 0, "eng")]


class FakeService(object):
	def __init__(self, ref):
		self.ref = ref
		self._seek = FakeSeek(90 * 60 * 90000)
		self._tracks = FakeTracks()

	def seek(self):
		return self._seek

	def audioTracks(self):
		return self._tracks

	def subtitle(self):
		return FakeSubs()


class Nav(object):
	def __init__(self):
		self.current = None
		self.history = []
		self.live = enigma.eServiceReference(1, 0, "")

	def playService(self, ref):
		self.history.append(ref)
		self.current = FakeService(ref) if ref is not None and ref.type in (4097, 5001, 5002) else None

	def getCurrentService(self):
		return self.current

	def getCurrentlyPlayingServiceOrGroup(self):
		return self.current.ref if self.current else self.live

	def stopService(self):
		self.current = None


def check_skin(scr):
	for attr in ("items", "values", "keys", "get", "update", "pop", "clear", "copy", "setdefault", "title"):
		if attr in scr.__dict__:
			SKIN_ERRORS.append("%s: instance attribute '%s' shadows Screen/dict API" % (scr.__class__.__name__, attr))
	skin = getattr(scr, "skin", None)
	if not skin:
		return
	try:
		root = ET.fromstring(skin)
	except ET.ParseError as e:
		SKIN_ERRORS.append("%s: XML error %s" % (scr.__class__.__name__, e))
		return
	W, H = enigma.DESKTOP
	sw, sh = [int(v) for v in root.get("size").split(",")]
	sx, sy = [int(v) for v in root.get("position").split(",")]
	if sx + sw > W + 1 or sy + sh > H + 1:
		SKIN_ERRORS.append("%s: screen exceeds desktop %s" % (scr.__class__.__name__, (sx, sy, sw, sh)))
	names = set()
	for w in root.iter("widget"):
		name = w.get("name")
		if name:
			names.add(name)
			if name not in scr:
				SKIN_ERRORS.append("%s: skin widget '%s' has no component (SkinError on box!)" % (scr.__class__.__name__, name))
		elif w.get("source") and not w.get("source").startswith("global."):
			if w.get("source") not in scr:
				SKIN_ERRORS.append("%s: source %s missing" % (scr.__class__.__name__, w.get("source")))
	for el in list(root.iter("widget")) + list(root.iter("ePixmap")):
		pix = el.get("pixmap")
		if pix is not None:
			# absolute paths are used as is by resolveFilename; a missing file is a SkinError on the box
			if not os.path.isabs(pix) or not os.path.isfile(pix):
				SKIN_ERRORS.append("%s: pixmap %s does not exist (SkinError on box!)" % (scr.__class__.__name__, pix))
			if el.get("alphatest") != "blend" and pix.endswith(".png"):
				SKIN_ERRORS.append("%s: %s needs alphatest=blend" % (scr.__class__.__name__, os.path.basename(pix)))
	for el in list(root.iter("widget")) + list(root.iter("eLabel")) + list(root.iter("ePixmap")):
		pos = el.get("position")
		size = el.get("size")
		if pos and size:
			x, y = [int(v) for v in pos.split(",")]
			w, h = [int(v) for v in size.split(",")]
			if x < 0 or y < 0 or x + w > sw + 2 or y + h > sh + 2:
				SKIN_ERRORS.append("%s: element %s out of screen %s" % (scr.__class__.__name__, el.get("name"), (x, y, w, h)))
	for key, comp in scr.items():
		if isinstance(comp, GUIComponent) and key in names:
			comp._attach()
	return names


class Session(object):
	def __init__(self, auto=None):
		self.stack = []
		self.nav = Nav()
		self.closed_log = []

	def open(self, cls, *args, **kwargs):
		return self._open(None, cls, args, kwargs)

	def openWithCallback(self, callback, cls, *args, **kwargs):
		return self._open(callback, cls, args, kwargs)

	def _open(self, callback, cls, args, kwargs):
		scr = cls(self, *args, **kwargs)
		scr._cb = callback
		check_skin(scr)
		if self.stack:
			self.stack[-1].execing = False
		self.stack.append(scr)
		scr.execing = True
		for f in list(scr.onLayoutFinish):
			f()
		for f in list(scr.onShown):
			f()
		return scr

	def instantiateDialog(self, cls, *args, **kwargs):
		dlg = cls(self, *args, **kwargs)
		check_skin(dlg)
		dlg.shown = False
		for f in list(dlg.onLayoutFinish):
			f()
		self.dialogs = getattr(self, "dialogs", [])
		self.dialogs.append(dlg)
		return dlg

	def deleteDialog(self, dlg):
		self.dialogs.remove(dlg)
		for f in list(dlg.onClose):
			f()

	def close(self, scr, *ret):
		assert scr in self.stack, "closing screen not on stack: %s" % scr
		assert self.stack[-1] is scr, "closing %s but top is %s" % (scr.__class__.__name__, self.stack[-1].__class__.__name__)
		self.stack.remove(scr)
		if self.stack:
			self.stack[-1].execing = True
		for f in list(scr.onClose):
			f()
		self.closed_log.append((scr.__class__.__name__, ret))
		if scr._cb:
			scr._cb(*ret)

	@property
	def top(self):
		return self.stack[-1] if self.stack else None


def pump(cond=None, timeout=8.0, step_ms=50):
	"""Advance virtual time and process timers until cond() is true."""
	end = time.time() + timeout
	while time.time() < end:
		enigma.VCLOCK[0] += step_ms
		for t in list(enigma.eTimer.all):
			if t.due():
				t.fire()
		if cond is not None and cond():
			return True
		time.sleep(0.003)
	if cond is None:
		return True
	return False


def press(scr, action):
	maps = sorted([v for v in list(scr.values()) if isinstance(v, ActionMap) and v.enabled], key=lambda m: m.prio)
	for m in maps:
		if action in m.actions:
			res = m.actions[action]()
			if type(res) is int and res == 0:
				continue  # not handled -> next action map (like eActionMap)
			return res
	raise AssertionError("action %s not handled by %s" % (action, scr.__class__.__name__))


def fire_event(scr, ev):
	for tr in TRACKERS:
		if tr.screen is scr and ev in tr.eventmap:
			tr.eventmap[ev]()


def choose(session, match):
	from Screens.ChoiceBox import ChoiceBox
	top = session.top
	assert isinstance(top, ChoiceBox), "expected ChoiceBox, top is %s" % top.__class__.__name__
	for entry in top.list:
		if (isinstance(match, int) and top.list.index(entry) == match) or (isinstance(match, str) and match in entry[0]):
			top.close(entry)
			return entry
	raise AssertionError("choice %r not in %s" % (match, [e[0] for e in top.list]))


def type_text(session, text):
	from Screens.VirtualKeyBoard import VirtualKeyBoard
	top = session.top
	assert isinstance(top, VirtualKeyBoard), "expected VirtualKeyBoard, top is %s" % top.__class__.__name__
	top.close(text)


def answer(session, value=True):
	from Screens.MessageBox import MessageBox
	top = session.top
	assert isinstance(top, MessageBox), "expected MessageBox, top is %s" % top.__class__.__name__
	top.close(value)
