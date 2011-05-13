#!/usr/bin/env python2
# vim:fileencoding=utf-8

import lilytalk
import logging
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

class CleanLog(webapp.RequestHandler):
  def get(self):
    self.response.headers['Content-Type'] = 'text/html; charset=UTF-8';
    self.response.out.write(u'''<!DOCTYPE html>
<meta http-equiv="content-type" content="text/html; charset=utf-8" />
<title>清除所有日志</title>
<form method="post">
<input type="submit" value="确认清除所有日志"/>
</form>'''.encode('utf-8'))

  def post(self):
    logging.warn('清除所有日志')
    for l in lilytalk.Log.all():
      l.delete()
    self.response.out.write(u'已删除所有日志'.encode('utf-8'))

class CleanUser(webapp.RequestHandler):
  def get(self):
    self.response.headers['Content-Type'] = 'text/html; charset=UTF-8';
    self.response.out.write(u'''<!DOCTYPE html>
<meta http-equiv="content-type" content="text/html; charset=utf-8" />
<title>清除所有用户信息</title>
<form method="post">
<input type="submit" value="确认清除所有用户信息"/>
</form>'''.encode('utf-8'))

  def post(self):
    logging.warn('清除所有用户信息')
    for l in lilytalk.User.all():
      l.delete()
    self.response.out.write(u'已删除所有用户信息'.encode('utf-8'))

application = webapp.WSGIApplication(
  [
    ('/_admin/cleanuser', CleanUser),
    ('/_admin/cleanlog', CleanLog),
  ],
  debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()

