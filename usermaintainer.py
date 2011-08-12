#!/usr/bin/env python2
# vim:fileencoding=utf-8

import gaetalk
import logging
import datetime
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import xmpp

class Userdeactive(webapp.RequestHandler):
  def get(self):
    self.response.headers['Content-Type'] = 'text/plain'
    for u in gaetalk.User.all():
      if u.jid.endswith('@gmail.com'):
        if u.avail != gaetalk.OFFLINE and 'fakeresouce' not in u.resources:
          if not xmpp.get_presence(u.jid):
            del u.resources[:]
            u.avail = gaetalk.OFFLINE
            u.last_offline_date = datetime.datetime.now()
            u.put()
            self.response.out.write(u.jid + ' should be offline.\n')
    self.response.out.write(u'OK.'.encode('utf-8'))

class Userdedup(webapp.RequestHandler):
  def get(self):
    users = {}
    for u in gaetalk.User.all():
      if u.jid in users:
        users[u.jid].append(u)
      else:
        users[u.jid] = [u]
    for k, v in users.items():
      if len(v) == 1:
        continue
      v.sort(key=lambda u: gaetalk.STATUS_LIST.index(u.avail))
      logging.error(' '.join([x.avail for x in v]))
      for i in v[1:]:
        l = gaetalk.Log(msg=u'删除重复用户', jid=i.jid,
                         nick=i.nick, type='misc')
        l.put()
        i.delete()
    self.response.out.write(u'OK.'.encode('utf-8'))

application = webapp.WSGIApplication(
  [
    ('/_admin/userdedup', Userdedup),
    ('/_admin/userdeactive', Userdeactive),
  ],
  debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()

