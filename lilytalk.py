#!/usr/bin/env python2
# vim:fileencoding=utf-8

#FIXME 会有两个不同的资源

import re
import logging
import datetime

from google.appengine.ext import db
from google.appengine.api import xmpp

import utils
import config

notice = u'本群正在内部测试中……'
helpre = re.compile(r'^\W{0,2}help$')

OFFLINE = u'离线'
AWAY    = u'离开'
XAWAY   = u'离开'
BUSY    = u'忙碌'
ONLINE  = u'在线'
CHAT    = u'和我说话吧'

NEW     = u'加入'
LEAVE   = u'退出'
NICK    = u'昵称更改 (%s -> %s)'

STATUS_CODE = {
  '':     ONLINE,
  'away': AWAY,
  'dnd':  BUSY,
  'xa':   XAWAY,
  'chat': CHAT,
}

timezone = datetime.timedelta(hours=config.timezoneoffset)

class User(db.Model):
  jid = db.StringProperty(required=True, indexed=True)
  nick = db.StringProperty(indexed=True)

  add_date = db.DateTimeProperty(auto_now_add=True)
  last_online_date = db.DateTimeProperty()
  last_offline_date = db.DateTimeProperty()
  last_speak_date = db.DateTimeProperty()
  msg_count = db.IntegerProperty(required=True, default=0)
  msg_chars = db.IntegerProperty(required=True, default=0)
  black_minutes = db.IntegerProperty(required=True, default=0)
  snooze_minutes = db.IntegerProperty(required=True, default=0)
  credit = db.IntegerProperty(required=True, default=0)

  avail = db.StringProperty(required=True)
  is_admin = db.BooleanProperty(required=True, default=False)
  blocked = db.BooleanProperty(required=True, default=False)

  prefix = db.StringProperty(required=True, default='//')
  nick_pattern = db.StringProperty(required=True, default='[%s]')
  intro = db.StringProperty()

class Log(db.Model):
  time = db.DateTimeProperty(auto_now_add=True, indexed=True)
  msg = db.StringProperty(required=True, multiline=True)
  jid = db.StringProperty()
  nick = db.StringProperty()
  type = db.StringProperty(required=True, indexed=True,
                           choices=set(['chat', 'member', 'admin']))

def log_msg(sender, msg):
  l = Log(jid=sender.jid, nick=guess_nick(sender),
          type='chat', msg=msg)
  l.put()

def log_onoff(sender, action):
  l = Log(jid=sender.jid, nick=guess_nick(sender),
          type='member', msg=action)
  l.put()

def get_user_by_jid(jid):
  return User.gql('where jid = :1', jid).get()

def get_member_list():
  r = []
  l = User.gql('where avail != :1', OFFLINE)
  for u in l:
    r.append(unicode(u.jid))
  return r

def guess_nick(u):
  return u.nick or u.jid.split('@')[0].decode('utf-8')

def send_to_all_except_self(jid, message):
  jids = [x for x in get_member_list() if x != jid]
  logging.debug(jids)
  try:
    xmpp.send_message(jids, message)
  except xmpp.InvalidJidError:
    pass

def send_to_all(message):
  jids = get_member_list()
  xmpp.send_message(jids, message)

def handle_message(msg):
  sender = get_user_by_jid(msg.sender.split('/')[0])
  if sender is None:
    msg.reply('很抱歉，出错了，请重新添加好友。')
    return
  #TODO 管理员命令
  if len(msg.body) > 500:
    msg.reply('由于技术限制，每条消息最长为 500 字。大段文本请贴 paste 网站。')
    return
  ch = BasicCommand(msg, sender)
  if not ch.handled:
    sender.last_speak_date = datetime.datetime.now()
    try:
      sender.msg_count += 1
      sender.msg_chars += len(msg.body)
    except TypeError:
      sender.msg_count = 1
      sender.msg_chars = len(msg.body)
    sender.put()
    message = '%s %s' % (
      sender.nick_pattern % guess_nick(sender),
      msg.body
    )
    send_to_all_except_self(sender.jid, message)
    log_msg(sender, msg.body)

def add_user(jid, show=OFFLINE):
  u = User(jid=jid, avail=show)
  u.put()
  log_onoff(u, NEW)
  logging.info(u'%s 已经加入' % jid)
  send_to_all_except_self(jid, u'%s 已经加入' % jid.split('@')[0])
  xmpp.send_presence(jid, status=notice)
  xmpp.send_message(jid, u'欢迎 %s 加入～' % jid.split('@')[0])

class BasicCommand:
  handled = True
  def __init__(self, msg, sender):
    self.sender = sender
    self.msg = msg

    if helpre.match(msg.body):
      self.do_help()
    elif msg.body.startswith(sender.prefix):
      cmd = msg.body[len(sender.prefix):].split()
      try:
        getattr(self, 'do_' + cmd[0])(cmd[1:])
        logging.debug('did command: ' + msg.body)
      except AttributeError:
        msg.reply(u'错误：未知命令 %s' % cmd[0])
      except UnicodeEncodeError:
        msg.reply(u'错误：命令名解码失败。此问题在 GAE 升级其 Python 到 3.x 后方能解决。')
    else:
      self.handled = False

  def do_online(self, args):
    '''显示在线成员列表'''
    r = [u'在线成员列表:']
    l = User.gql('where avail != :1', OFFLINE)
    for u in l:
      m = guess_nick(u)
      status = u.avail
      if status != u'在线':
        m += u' (%s)' % status
      r.append(unicode('* ' + m))
    self.msg.reply(u'\n'.join(r).encode('utf-8'))

  def do_nick(self, args):
    '''更改昵称，需要一个参数'''
    if len(args) != 1:
      self.msg.reply('错误：请给出你想到的昵称（不能包含空格）')
      return

    q = User.gql('where nick = :1', args[0]).get()
    if q is not None:
      self.msg.reply('错误：该昵称已被使用，请使用其它昵称')
    else:
      old_nick = guess_nick(self.sender)
      self.sender.nick = args[0]
      self.sender.put()
      send_to_all_except_self(self.sender.jid,
        (u'%s 的昵称改成了 %s' % (old_nick, args[0])).encode('utf-8'))
      self.msg.reply('昵称更改成功！')
      log_onoff(self.sender, NICK % (old_nick, args[0]))

  def do_help(self, args=None):
    '''显示本帮助'''
    doc = [u'命令指南 (使用时请加上你的命令前缀，默认为 // )']
    for c, f in self.__class__.__dict__.items():
      if c.startswith('do_'):
        doc.append(u'%s: %s' % (c[3:], f.__doc__.decode('utf-8')))
    self.msg.reply(u'\n'.join(doc).encode('utf-8'))

  def do_iam(self, args):
    '''查看自己的信息'''
    s = self.sender
    r = u'昵称：\t\t%s\n消息数：\t\t%d\n消息总量：\t%s\n命令前缀：\t%s\n自我介绍：\t%s' % (
      s.nick, s.msg_count, utils.filesize(s.msg_chars), s.prefix, s.intro)
    self.msg.reply(r.encode('utf-8'))

  def do_old(self, args):
    '''查询聊天记录，可选一个数字参数。默认为最后100条或者所有离线时消息'''
    s = self.sender
    q = False
    if not args:
      q = Log.gql("WHERE time < :1 AND time > :2 AND type = 'chat' ORDER BY time DESC LIMIT 100", s.last_online_date, s.last_offline_date)
    elif len(args) == 1:
      try:
        n = int(args[0])
        if n > 0:
          q = Log.gql("WHERE type = 'chat' ORDER BY time DESC LIMIT %d" % n)
      except ValueError:
        pass
    if q is not False:
      r = []
      q = list(q)
      q.reverse()
      if q:
        if (datetime.datetime.today() + timezone).date() == (q[0].time + timezone).date():
          show_date = False
        else:
          show_date = True
      for l in q:
        message = '%s %s %s' % (
          utils.strftime(l.time, timezone, show_date),
          s.nick_pattern % l.nick,
          l.msg
        )
        r.append(message)
      if r:
        self.msg.reply(u'\n'.join(r).encode('utf-8'))
      else:
        self.msg.reply('没有符合的聊天记录。')
    else:
      self.msg.reply('Oops, 参数不正确哦。')

