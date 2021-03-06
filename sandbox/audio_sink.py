#! /usr/bin/env python

import pygst
pygst.require("0.10")
import gst
import gobject

import struct

hdr_fmt = "!LQQi"
hdr_len = struct.calcsize(hdr_fmt)

class AudioSink(gst.BaseSink):
	__gtype_name__ = 'AudioSink'
	__gstdetails__ = ("Audio Sink", "Sink/Network",
		"Receive data over a CCNx network", "Derek Kulinski <takeda@takeda.tk>")

	__gsttemplates__ = (
		gst.PadTemplate("sink",
			gst.PAD_SINK,
			gst.PAD_ALWAYS,
			gst.caps_new_any()),
		)

	def do_start(self):
		print "Starting!"
		self.of = open("audio.bin", "wb")
		return True

	def do_stop(self):
		print "Stopping!"
		self.of.close()
		return True

	def do_set_caps(self, caps):
		print "Caps: %s" % caps
		self.of.write("%s\n" % caps)
		return True

	def do_render(self, buffer):
		print "Buffer timestamp %d %d %d" % (buffer.timestamp, buffer.duration, buffer.flags)
		hdr = struct.pack(hdr_fmt, len(buffer), buffer.timestamp, buffer.duration, buffer.flags)
		self.of.write(hdr)
		self.of.write(buffer.data)
		return gst.FLOW_OK

	def do_preroll(self, buf):
		print "Preroll"
		return gst.FLOW_OK

	def do_event(self, ev):
		print "Got event of type %s" % ev.type
		return gst.FLOW_OK

gst.element_register(AudioSink, 'AudioSink')

if __name__ == '__main__':
	gobject.threads_init()

	pipeline = gst.parse_launch("autoaudiosrc ! ffenc_aac ! AudioSink")

	loop = gobject.MainLoop()
	pipeline.set_state(gst.STATE_PLAYING)

	try:
		loop.run()
	except KeyboardInterrupt:
		print "Ctrl+C pressed, exitting"
		pass

	pipeline.set_state(gst.STATE_NULL)
	pipeline.get_state(gst.CLOCK_TIME_NONE)
