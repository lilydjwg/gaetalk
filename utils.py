#!/usr/bin/env python2
# vim:fileencoding=utf-8

import re
import unicodedata
import time

from google.appengine.api import memcache

timeParser = re.compile(r'^(\d+)([smhd])?$')
timeUnitMap = {
  '':  1,
  's': 1,
  'm': 60,
  'h': 3600,
  'd': 86400,
}

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

def checkNick(nick):
  '''判断一个昵称是否合法'''
  for i in nick:
    if not unicodedata.category(i).startswith('L'):
      return False
  return True

class MemLock:
  def __init__(self, name):
    self.name = name

  def require(self):
    while memcache.get(self.name):
      time.sleep(0.001)
    memcache.set(self.name, True)

  def release(self):
    memcache.set(self.name, False)
