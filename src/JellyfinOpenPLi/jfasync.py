# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0-or-later
# Jellyfin for Enigma2 - run blocking work in threads, deliver results on the GUI thread
from __future__ import absolute_import

import collections
import threading

try:
	import queue
except ImportError:  # pragma: no cover
	import Queue as queue

from enigma import eTimer
from .jflog import log, log_exception


class _Task(object):
	__slots__ = ("fn", "args", "kwargs", "callback", "errback", "group", "cancelled", "urgent")

	def __init__(self, fn, args, kwargs, callback, errback, group, urgent=True):
		self.fn = fn
		self.args = args
		self.kwargs = kwargs
		self.callback = callback
		self.errback = errback
		self.group = group
		self.cancelled = False
		self.urgent = urgent


class PriorityStack(object):
	"""Download queue for pictures: what is on screen comes first (newest first), prefetch only after it
	(oldest first). A prefetch that becomes visible is moved to the front (promote)."""

	def __init__(self, background_limit=2):
		self.cond = threading.Condition()
		self.urgent = []
		self.background = collections.deque()
		self.background_limit = background_limit  # the other workers stay free for what is on screen
		self.background_running = 0

	def put(self, task):
		with self.cond:
			if task is None or task.urgent:
				self.urgent.append(task)
			else:
				self.background.append(task)
			self.cond.notify()

	def get(self):
		with self.cond:
			while not self.urgent and (not self.background or self.background_running >= self.background_limit):
				self.cond.wait()
			if self.urgent:
				return self.urgent.pop()
			self.background_running += 1
			return self.background.popleft()

	def finished(self, task):
		if task is not None and not task.urgent:
			with self.cond:
				self.background_running -= 1
				self.cond.notify()

	def promote(self, task):
		with self.cond:
			try:
				self.background.remove(task)
			except ValueError:
				return False  # already running
			task.urgent = True
			self.urgent.append(task)
			self.cond.notify()
			return True


class TaskGroup(object):
	"""Tasks bound to a screen; cancel() drops pending callbacks (e.g. on close)."""

	def __init__(self, runner):
		self.runner = runner
		self.cancelled = False

	def run(self, fn, *args, **kwargs):
		callback = kwargs.pop("callback", None)
		errback = kwargs.pop("errback", None)
		pool = kwargs.pop("pool", "api")
		urgent = kwargs.pop("urgent", True)
		if self.cancelled:
			return None
		return self.runner.submit(_Task(fn, args, kwargs, callback, errback, self, urgent), pool)

	def cancel(self):
		self.cancelled = True


class AsyncRunner(object):
	def __init__(self, api_threads=3, image_threads=6):
		self.results = queue.Queue()
		self.queues = {"api": queue.Queue(), "image": PriorityStack(), "bg": queue.Queue()}
		self.pending = 0
		self.lock = threading.Lock()
		self.timer = eTimer()
		try:
			self.timer.callback.append(self._drain)
		except AttributeError:  # DreamOS style
			self._conn = self.timer.timeout.connect(self._drain)
		for name, count in (("api", api_threads), ("image", image_threads), ("bg", 1)):
			for i in range(count):
				t = threading.Thread(target=self._worker, args=(self.queues[name],), name="jellyfin-%s-%d" % (name, i))
				t.daemon = True
				t.start()

	def group(self):
		return TaskGroup(self)

	def promote(self, task):
		"""A queued prefetch picture is needed on screen now."""
		q = self.queues["image"]
		return task is not None and not task.urgent and q.promote(task)

	def submit(self, task, pool="api"):
		with self.lock:
			self.pending += 1
		self.queues.get(pool, self.queues["api"]).put(task)
		if not self.timer.isActive():
			self.timer.start(40, False)
		return task

	def _worker(self, q):
		finished = getattr(q, "finished", None)
		while True:
			task = q.get()
			if task is None:
				return
			try:
				self._execute(task)
			finally:
				if finished is not None:
					finished(task)

	def _execute(self, task):
		if task.group is not None and task.group.cancelled:
			self.results.put((task, False, None, True))
			return
		try:
			res = task.fn(*task.args, **task.kwargs)
			self.results.put((task, True, res, False))
		except Exception as e:  # noqa
			if not getattr(e, "status", None) and e.__class__.__name__ != "JellyfinError":
				log_exception("background task")
			self.results.put((task, False, e, False))

	def _drain(self):
		handled = 0
		while handled < 50:
			try:
				task, ok, res, skipped = self.results.get_nowait()
			except queue.Empty:
				break
			handled += 1
			with self.lock:
				self.pending -= 1
			if skipped or task.cancelled or (task.group is not None and task.group.cancelled):
				continue
			try:
				if ok:
					if task.callback:
						task.callback(res)
				elif task.errback:
					task.errback(res)
				else:
					log("background task failed: %s" % res)
			except Exception:
				log_exception("error in callback")
		with self.lock:
			idle = self.pending <= 0
		if idle and self.results.empty():
			self.timer.stop()


_runner = None


def runner():
	global _runner
	if _runner is None:
		_runner = AsyncRunner()
	return _runner
