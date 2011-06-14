#!/usr/bin/env python2
# vim:fileencoding=utf-8

import datetime
import config
from google.appengine.api import memcache
from google.appengine.api import mail
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

class Stat(webapp.RequestHandler):
  def get(self):
    time = datetime.datetime.now() - datetime.timedelta(hours=1)
    time = time.strftime('%Y-%m-%d_%H')
    msg = []
    for type in ('message', 'presence'):
      count = memcache.get('%s_%s' % (type, time))
      if count is None:
        count = '0'
      msg.append('%s: %s' % (type, count))
    msg = '\n'.join(msg)
    mail.send_mail(sender='"GAE stat" <stat@%s.appspotmail.com>' % config.appid,
                   to="Admin <%s>" % config.root,
                   subject="Stats for %s in %s" % (config.appid, time),
                   body=msg)
    self.response.out.write(u'OK.'.encode('utf-8'))

application = webapp.WSGIApplication(
  [
    ('/_admin/stat', Stat),
  ],
  debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()

