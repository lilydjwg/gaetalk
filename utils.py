#!/usr/bin/env python2
# vim:fileencoding=utf-8

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

