#!/usr/bin/env python2
# vim:fileencoding=utf-8

import logging
import datetime
from google.appengine.api import xmpp
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

import lilytalk
import config

class XMPPSub(webapp.RequestHandler):
  '''被人加好友了～可能被触发多次'''
  def post(self):
    jid = self.request.get('from')
    u = lilytalk.get_user_by_jid(jid)
    if u is None:
      lilytalk.add_user(jid)

class XMPPUnsub(webapp.RequestHandler):
  def post(self):
    jid = self.request.get('from')
    u = lilytalk.get_user_by_jid(jid)
    if u is not None:
      u.delete()
      lilytalk.log_onoff(u, lilytalk.LEAVE)
      lilytalk.send_to_all(u'%s 已经离开' % jid.split('@')[0])
      logging.info(u'%s 已经离开' % jid)

class XMPPMsg(webapp.RequestHandler):
  def post(self):
    message = xmpp.Message(self.request.POST)
    lilytalk.handle_message(message)

class XMPPAvail(webapp.RequestHandler):
  def post(self):
    '''show 可以是 away、dnd（忙碌）或空（在线）'''
    jid, resource = self.request.get('from').split('/', 1)
    status = self.request.get('status')
    show = self.request.get('show')
    logging.debug(u'%s 的状态: %s (%s)' % (jid, status, show))
    show = lilytalk.STATUS_CODE[show]
    xmpp.send_presence(self.request.get('from'),
      status=lilytalk.notice, from_jid='%s@appspot.com/bot' % config.appid)
    u = lilytalk.get_user_by_jid(jid)
    if u is not None:
      if u.avail != show:
        u.avail = show
        u.last_online_date = datetime.datetime.now()
        u.put()
        lilytalk.log_onoff(u, show)
    else:
      logging.info(u'Adding %s (%s)', jid, show)
      lilytalk.add_user(jid, show)
      lilytalk.log_onoff(u, show)

class XMPPUnavail(webapp.RequestHandler):
  def post(self):
    jid, resource = self.request.get('from').split('/', 1)
    status = self.request.get('status')
    logging.info(u'%s 下线了' % jid)
    u = lilytalk.get_user_by_jid(jid)
    if u is not None:
      if u.avail != lilytalk.OFFLINE:
        u.avail = lilytalk.OFFLINE
        u.last_offline_date = datetime.datetime.now()
        u.put()
        lilytalk.log_onoff(u, lilytalk.OFFLINE)

class XMPPProbe(webapp.RequestHandler):
  def post(self):
    fulljid = self.request.get('from')
    xmpp.send_presence(self.request.get('from'),
      status=lilytalk.notice, from_jid='%s@appspot.com/bot' % config.appid)

application = webapp.WSGIApplication(
  [
    ('/_ah/xmpp/subscription/subscribed/', XMPPSub),
    ('/_ah/xmpp/subscription/unsubscribe/', XMPPUnsub),
    ('/_ah/xmpp/message/chat/', XMPPMsg),
    ('/_ah/xmpp/presence/available/', XMPPAvail),
    ('/_ah/xmpp/presence/unavailable/', XMPPUnavail),
    ('/_ah/xmpp/presence/probe/', XMPPProbe),
  ],
  debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
