#!/usr/bin/env python2
# vim:fileencoding=utf-8

import urllib
from google.appengine.api import urlfetch

# 时区
timezoneoffset = 8
# 默认的命令前缀
default_prefix = '-'
# 除了 Unicode 分类为“字母”的字符外，昵称里还允许哪些字符。注意即使指定空白
# 符昵称中也不能包含之
allowedSymbolInNick = u'+-_@.™'
# 是否允许多次更改昵称
nick_can_change = True
# 单位是字节。一个汉字为 3 字节
nick_maxlen = 16
# Gtalk 官方中文版使用非加密的协议。检测到 Gtalk 官方中文版用户时要不要提示之。
warnGtalk105 = True
# root 用户，请指定群主的 JID。
root = 'lilydjwg@gmail.com'
# 发统计报告邮件用
appid = 'lilydjwg'

# 离开时某些客户端自动发送的消息（全文）
blocked_away_messages = (
  "I'm currently away and will reply as soon as I return to eBuddy on my iPod touch",
  'This is an autoreply: I am currently not available. Please leave your message, and I will get back to you as soon as possible.',
)

def post_code(msg):
  '''将代码贴到网站，返回 URL 地址 或者 None（失败）'''
  form_data = urllib.urlencode({
    'vimcn': msg.encode('utf-8'),
  })
  try:
    result = urlfetch.fetch(url='http://p.vim-cn.com/',
        payload=form_data,
        method=urlfetch.POST,
        headers={'Content-Type': 'application/x-www-form-urlencoded'})
    return result.content.strip() + '/text' # 默认当作纯文本高亮
  except urlfetch.DownloadError:
    return
