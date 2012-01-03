#! /usr/bin/env python

import pygst
pygst.require("0.10")
import gst
import gobject

import pyccn, threading, Queue, sys

import utils, pytimecode

CMD_SEEK = 1

def debug(text):
	print "CCNReceiver: %s" % text

class CCNReceiver(pyccn.Closure):
	queue = Queue.Queue(2)
	caps = None
	frame_rate = None
	last_frame = None

	_cmd_q = Queue.Queue(2)
	_running = False
	_segment = 0
	_seek_segment = None
	_duration_last = None
	_purge_data = False

	def __init__(self, uri):
		self._handle = pyccn.CCN()
		self._get_handle = pyccn.CCN()
		self._uri = pyccn.Name(uri)
		self._name_segments = self._uri.append('segments')
		self._name_frames = self._uri.append('frames')

	def fetch_stream_info(self):
		name = self._uri.append('stream_info')
		debug("Fetching stream_info from %s ..." % name)

		co = self._get_handle.get(name)
		if not co:
			debug("Unable to fetch %s" % name)
			sys.exit(10)

		self.caps = gst.caps_from_string(co.content)
		debug("Stream caps: %s" % self.caps)

		framerate = self.caps[0]['framerate']
		self.frame_rate = utils.framerate2str(framerate)

		return self.caps

	def fetch_seek_query(self, tc):
		debug("Fetching segment number for %s" % tc)
		interest = pyccn.Interest(childSelector=1)
		interest.exclude = pyccn.ExclusionFilter()

		exc_tc = tc + 1
		interest.exclude.add_name(pyccn.Name([exc_tc.make_timecode()]))
		interest.exclude.add_any()

		#debug("Sending interest to %s" % self._name_frames)
		#debug("Interest: %s" % interest)
		co = self._get_handle.get(self._name_frames, interest)
		if not co:
			raise Exception("Some bullshit exception")
		debug("Got segment: %s" % co.content)

		tc = pytimecode.PyTimeCode(exc_tc.framerate, start_timecode=co.name[-1])
		segment = int(co.content)

		return tc, segment

	def fetch_last_frame(self):
		assert(self.frame_rate)

		interest = pyccn.Interest(childSelector = 1)

		if self._duration_last:
			interest.exclude = pyccn.ExclusionFilter()
			interest.exclude.add_any()
			interest.exclude.add_name(pyccn.Name([self._duration_last]))

		co = self._get_handle.get(self._name_frames, interest)
		if co:
			self._duration_last = co.name[-1]

		self.last_frame = pytimecode.PyTimeCode(self.frame_rate, start_timecode=self._duration_last)

	def process_commands(self):
		try:
			if self._cmd_q.empty():
				return
			cmd = self._cmd_q.get_nowait()
		except Queue.Empty:
			return

		if cmd[0] == CMD_SEEK:
			tc, segment = self.fetch_seek_query(cmd[1])
			debug("Seeking to segment %d [%s]" % (segment, tc))
			self._seek_segment = segment
			self._cmd_q.task_done()
		else:
			raise Exception, "Unknown command: %d" % cmd

	def seek(self, ns):
		tc = pytimecode.PyTimeCode(self.frame_rate, start_seconds=ns/float(gst.SECOND))
		debug("Requesting tc: %s" % tc)
		self._cmd_q.put([CMD_SEEK, tc])
		debug("Seek comand queued")
		self.finish_ccn_loop()

	def start(self):
		self._receiver_thread = threading.Thread(target=self.run)
		self._running = True
		self._receiver_thread.start()
		self.next_interest()

	def stop(self):
		self._running = False
		self._handle.setRunTimeout(0)
		self._receiver_thread.join()

	def finish_ccn_loop(self):
		self._handle.setRunTimeout(0)

	def run(self):
		debug("Running ccn loop")
		self.fetch_last_frame()

		iter = 0
		while self._running:
			if iter > 100:
				iter = 0
				self.fetch_last_frame()

			self._handle.run(100)
			self.process_commands()
			iter += 1

		debug("Finished running ccn loop")

	def next_interest(self):
		if type(self._seek_segment) is int:
			debug("Starting pulling from segment %d" % self._seek_segment)
			self.segbuf = []
			self._segment = self._seek_segment
			self._seek_segment = True

		name = self._name_segments.appendSegment(self._segment)
		self._segment += 1

		#debug("Issuing an interest for: %s" % name)
		self._handle.expressInterest(name, self)

	def upcall(self, kind, info):
		if kind == pyccn.UPCALL_FINAL:
			return pyccn.RESULT_OK

		elif kind == pyccn.UPCALL_CONTENT:
			if not hasattr(self, '_upcall_segbuf'):
				self._upcall_segbuf = []

			#debug("Received %s" % info.ContentObject.name)

			last, content = utils.packet2buffer(info.ContentObject.content)
			self._upcall_segbuf.append(content)

			if last == 0:
				status = 0

				#Merging, maybe I shouldn't do this :/
				res = self._upcall_segbuf[0]
				for e in self._upcall_segbuf[1:]:
					res = res.merge(e)
				self._upcall_segbuf = []

				# Marking jump due to seeking
				if self._seek_segment == True:
					debug("Marking as discontinued")
					status = CMD_SEEK
					self._seek_segment = None

				#debug("before put")
				self.queue.put((status, res))
				#debug("after put")

			self.next_interest()
			return pyccn.RESULT_OK

		elif kind == pyccn.UPCALL_INTEREST_TIMED_OUT:
			debug("timeout - reexpressing")
			return pyccn.RESULT_REEXPRESS

		debug("Got unknown kind: %d" % kind)

		return pyccn.RESULT_ERR

if __name__ == '__main__':
	import time

	def consumer(receiver):
		while True:
			data = receiver.queue.get()
			time.sleep(.01)

	def do_seek(receiver, sec):
		ns = int(sec * 1000 * 1000 * 1000)
		receiver.seek(ns)

	receiver = CCNReceiver('/videostream')
	receiver.fetch_stream_info()

	thread = threading.Thread(target=consumer, args=[receiver])
	thread.start()

	timer = threading.Timer(2, do_seek, args=[receiver, 30])
	timer.start()

	timer = threading.Timer(5, do_seek, args=[receiver, 0])
	timer.start()

	timer = threading.Timer(6, do_seek, args=[receiver, 0])
	timer.start()

	receiver.start()
