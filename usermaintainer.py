#!/usr/bin/env python2
# vim:fileencoding=utf-8

import lilytalk
import logging
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

class Userdedup(webapp.RequestHandler):
  def get(self):
    users = {}
    for u in lilytalk.User.all():
      if u.jid in users:
        users[u.jid].append(u)
      else:
        users[u.jid] = [u]
    for k, v in users.items():
      if len(v) == 1:
        continue
      v.sort(key=lambda u: lilytalk.STATUS_LIST.index(u.avail))
      logging.error(' '.join([x.avail for x in v]))
      for i in v[1:]:
        l = lilytalk.Log(msg=u'删除重复用户', jid=i.jid,
                         nick=i.nick, type='misc')
        l.put()
        i.delete()
    self.response.out.write(u'OK.'.encode('utf-8'))

application = webapp.WSGIApplication(
  [
    ('/_admin/userdedup', Userdedup),
  ],
  debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()

