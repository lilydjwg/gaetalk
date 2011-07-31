#!/usr/bin/env python2
# vim:fileencoding=utf-8

import logging
import datetime
from google.appengine.api import xmpp
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import taskqueue

import gaetalk
import config
import utils

class XMPPSub(webapp.RequestHandler):
  '''被人加好友了～可能被触发多次'''
  def post(self):
    jid = self.request.get('from')
    gaetalk.try_add_user(jid)

class XMPPUnsub(webapp.RequestHandler):
  def post(self):
    # 注意：由于 gtalk 客户端的错误处理，提供了一个使用命令离开的方式
    jid = self.request.get('from')
    L = utils.MemLock('delete_user')
    L.require()
    try:
      gaetalk.del_user(jid)
    finally:
      L.release()

class XMPPMsg(webapp.RequestHandler):
  def post(self):
    try:
      message = xmpp.Message(self.request.POST)
      gaetalk.handle_message(message)
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
      show = gaetalk.STATUS_CODE[show]
    except KeyError:
      logging.error('%s has sent an incorrect show code %s' % (jid, show))
      return
    try:
      gaetalk.send_status(self.request.get('from'))
    except xmpp.Error:
      logging.error('Error while sending presence to %s' % jid)
      return
    u = gaetalk.get_user_by_jid(jid)
    if u is not None:
      modified = False
      if resource not in u.resources:
        u.resources.append(resource)
        modified = True
      if u.avail != show:
        if u.avail == gaetalk.OFFLINE:
          u.last_online_date = datetime.datetime.now()
        u.avail = show
        modified = True
      if modified:
        gaetalk.log_onoff(u, show, resource)
        u.put()
      if config.warnGtalk105 and resource.startswith('Talk.v105'):
        xmpp.send_message(jid, u'您的客户端使用明文传输数据，为了大家的安全，请使用Gtalk英文版或者其它使用SSL加密的客户端。')
    else:
      gaetalk.try_add_user(jid, show, resource)

class XMPPUnavail(webapp.RequestHandler):
  def post(self):
    jid, resource = self.request.get('from').split('/', 1)
    logging.info(u'%s 下线了' % jid)
    taskqueue.add(url='/_admin/queue', queue_name='userunavailable', params={'jid': jid, 'resource': resource})

class XMPPProbe(webapp.RequestHandler):
  def post(self):
    fulljid = self.request.get('from')
    try:
      gaetalk.send_status(fulljid)
    except xmpp.Error:
      logging.error('Error while sending presence to %s' % fulljid)

class XMPPDummy(webapp.RequestHandler):
  def post(self):
    pass

class UserUnavailable(webapp.RequestHandler):
  def post(self):
    jid = self.request.get('jid')
    resource = self.request.get('resource')
    u = gaetalk.get_user_by_jid(jid)
    if u is not None:
      if resource in u.resources:
        u.resources.remove(resource)
        if not u.resources:
          u.avail = gaetalk.OFFLINE
          u.last_offline_date = datetime.datetime.now()
        u.put()
      gaetalk.log_onoff(u, gaetalk.OFFLINE, resource)

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
    ('/_admin/queue', UserUnavailable),
  ],
  debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  import counter
  main()
