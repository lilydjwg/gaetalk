#!/usr/bin/env python2
# vim:fileencoding=utf-8

import logging
import datetime
from google.appengine.api import xmpp
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

import lilytalk
import config
import utils

class XMPPSub(webapp.RequestHandler):
  '''被人加好友了～可能被触发多次'''
  def post(self):
    jid = self.request.get('from')
    u = lilytalk.get_user_by_jid(jid)
    lilytalk.try_add_user(jid)

class XMPPUnsub(webapp.RequestHandler):
  def post(self):
    # 注意：由于 gtalk 客户端的错误处理，提供了一个使用命令离开的方式
    jid = self.request.get('from')
    L = utils.MemLock('delete_user')
    L.require()
    try:
      u = lilytalk.get_user_by_jid(jid)
      if u is not None:
        if u.jid == config.root:
          xmpp.send_message(jid, u'root 用户：离开前请确定你已做好善后工作！')
        lilytalk.log_onoff(u, lilytalk.LEAVE)
        lilytalk.send_to_all(u'%s 已经离开' % u.nick)
        u.delete()
        logging.info(u'%s 已经离开' % jid)
    finally:
      L.release()

class XMPPMsg(webapp.RequestHandler):
  def post(self):
    try:
      message = xmpp.Message(self.request.POST)
      lilytalk.handle_message(message)
    except xmpp.InvalidMessageError:
      logging.info('InvalidMessageError: %r' % self.request.POST)

class XMPPAvail(webapp.RequestHandler):
  def post(self):
    '''show 可以是 away、dnd（忙碌）或空（在线）'''
    jid, resource = self.request.get('from').split('/', 1)
    status = self.request.get('status')
    show = self.request.get('show')
    logging.debug(u'%s 的状态: %s (%s)' % (jid, status, show))
    try:
      show = lilytalk.STATUS_CODE[show]
    except KeyError:
      logging.error('%s has sent an incorrect show code %s' % (jid, show))
      return
    try:
      xmpp.send_presence(self.request.get('from'),
        status=lilytalk.notice)
    except xmpp.Error:
      logging.error('Error while sending presence to %s' % jid)
      return
    u = lilytalk.get_user_by_jid(jid)
    if u is not None:
      modified = False
      if resource not in u.resources:
        u.resources.append(resource)
        modified = True
      if u.avail != show:
        if u.avail == lilytalk.OFFLINE:
          u.last_online_date = datetime.datetime.now()
        u.avail = show
        modified = True
      if modified:
        lilytalk.log_onoff(u, show, resource)
        u.put()
      if config.warnGtalk105 and resource.startswith('Talk.v105'):
        xmpp.send_message(jid, u'您的客户端使用明文传输数据，这样不安全，请使用Gtalk英文版或者其它客户端。')
    else:
      lilytalk.try_add_user(jid, show, resource)

class XMPPUnavail(webapp.RequestHandler):
  def post(self):
    jid, resource = self.request.get('from').split('/', 1)
    status = self.request.get('status')
    logging.info(u'%s 下线了' % jid)
    u = lilytalk.get_user_by_jid(jid)
    if u is not None:
      if resource in u.resources:
        u.resources.remove(resource)
        if not u.resources:
          u.avail = lilytalk.OFFLINE
          u.last_offline_date = datetime.datetime.now()
        u.put()
      lilytalk.log_onoff(u, lilytalk.OFFLINE, resource)

class XMPPProbe(webapp.RequestHandler):
  def post(self):
    fulljid = self.request.get('from')
    try:
      xmpp.send_presence(self.request.get('from'),
        status=lilytalk.notice)
    except xmpp.Error:
      logging.error('Error while sending presence to %s' % jid)
      return

class XMPPDummy(webapp.RequestHandler):
  def post(self):
    pass

application = webapp.WSGIApplication(
  [
    ('/_ah/xmpp/subscription/subscribed/', XMPPSub),
    ('/_ah/xmpp/subscription/unsubscribed/', XMPPUnsub),
    ('/_ah/xmpp/message/chat/', XMPPMsg),
    ('/_ah/xmpp/presence/available/', XMPPAvail),
    ('/_ah/xmpp/presence/unavailable/', XMPPUnavail),
    ('/_ah/xmpp/presence/probe/', XMPPProbe),
    ('/_ah/xmpp/subscription/subscribe/', XMPPDummy),
    ('/_ah/xmpp/subscription/unsubscribe/', XMPPDummy),
  ],
  debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
