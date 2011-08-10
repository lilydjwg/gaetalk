#!/usr/bin/env python2
# vim:fileencoding=utf-8

import re
import unicodedata
import time
import config
import urllib

from google.appengine.api import memcache
from google.appengine.api import urlfetch

timeParser = re.compile(r'^(\d+)([smhd])?$')
linkre = re.compile(r' <https?://(?!i.imgur.com/)[^>]+>')
linkjsre = re.compile(r' <javascript:[^>]+>')
timeUnitMap = {
  '':  1,
  's': 1,
  'm': 60,
  'h': 3600,
  'd': 86400,
}
timeZhUnitMap = (60, 60, 24, 36524)
timeZhUnits = (u'秒', u'分', u'小时', u'天')

def filesize(size):
  '''将 数字 转化为 xxKiB 的形式'''
  units = 'KMGT'
  left = abs(size)
  unit = -1
  while left > 1100 and unit < 3:
    left = left / 1024
    unit += 1
  if unit == -1:
    return '%dB' % size
  else:
    if size < 0:
      left = -left
    return '%.1f%siB' % (left, units[unit])

def strftime(time, timezone, show_date=False):
  '''将时间转换为字符串，考虑时区，可能带日期'''
  if not show_date:
    format = '%H:%M:%S'
  else:
    format = '%m-%d %H:%M:%S'
  return (time + timezone).strftime(format)

def parseTime(s):
  '''将 3s，5d，1h，6m 等转换成秒数'''
  m = timeParser.match(s)
  if m is None:
    raise ValueError('not a time')
  n = int(m.group(1))
  u = m.group(2)
  if u is None:
    return n
  else:
    return n * timeUnitMap[u]

def displayTime(t):
  '''友好地显示时间'''
  r = []
  for i in timeZhUnitMap:
    r.append(t % i)
    t = t // i
    if t == 0:
      break
  return u''.join(reversed(map(lambda x, y: unicode(x)+y if x else u'', r, timeZhUnits)))

def checkNick(nick):
  '''判断一个昵称是否合法'''
  if len(nick.encode('utf-8')) > config.nick_maxlen:
    return False
  for i in nick:
    cat = unicodedata.category(i)
    # Lt & Lm are special chars
    if (not (cat.startswith('L') or cat.startswith('N')) or cat in ('Lm', 'Lt')) \
       and i not in config.allowedSymbolInNick:
      return False
  return True

def removelinks(msg):
  '''清除多余的链接文本'''
  links = linkre.findall(msg)
  if len(links) != 1:
    msg = linkre.sub('', msg)
  msg = linkjsre.sub('', msg)
  return msg

class MemLock:
  def __init__(self, name):
    self.name = name

  def require(self):
    while memcache.get(self.name):
      time.sleep(0.001)
    memcache.set(self.name, True)

  def release(self):
    memcache.set(self.name, False)

