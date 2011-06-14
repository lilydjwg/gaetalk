#!/usr/bin/env python2
# vim:fileencoding=utf-8

from google.appengine.api import xmpp
from google.appengine.api import memcache
import datetime

old_send_presence = xmpp.send_presence
old_send_message = xmpp.send_message

def count(type):
  name = '%s_%s' % (type, datetime.datetime.now().strftime('%Y-%m-%d_%H'))
  memcache.incr(name, initial_value=0)

def send_presence(*args, **kwargs):
  count('presence')
  old_send_presence(*args, **kwargs)

def send_message(*args, **kwargs):
  count('message')
  old_send_message(*args, **kwargs)

xmpp.send_presence = send_presence
xmpp.send_message = send_message
