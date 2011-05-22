#!/usr/bin/env python2
# vim:fileencoding=utf-8

import re
import logging
import datetime

from google.appengine.ext import db
from google.appengine.api import xmpp

import utils
import config

notice = u'这是一个测试群'
helpre = re.compile(r'^\W{0,2}help$')

#用户所有资源离线时，会加上“完全”二字
OFFLINE = u'离线'
AWAY    = u'离开'
XAWAY   = u'离开'
BUSY    = u'忙碌'
ONLINE  = u'在线'
CHAT    = u'和我说话吧'

NEW        = u'加入'
LEAVE      = u'退出'
NICK       = u'昵称更改 (%s -> %s)'
SNOOZE     = u'snooze %ds'
BLACK      = u'禁言 %s %ds'
BLACK_AUTO = u'被禁言 %ds'
KICK       = u'删除 %s (%s)'
ADMIN      = u'%s 成为管理员 (by %s)'
UNADMIN    = u'%s 不再是管理员 (by %s)'

STATUS_CODE = {
  '':     ONLINE,
  'away': AWAY,
  'dnd':  BUSY,
  'xa':   XAWAY,
  'chat': CHAT,
}

#状态的排序顺序
STATUS_LIST = [CHAT, ONLINE, AWAY, XAWAY, BUSY, OFFLINE]

timezone = datetime.timedelta(hours=config.timezoneoffset)

class User(db.Model):
  jid = db.StringProperty(required=True, indexed=True)
  nick = db.StringProperty(required=True, indexed=True)

  add_date = db.DateTimeProperty(auto_now_add=True)
  last_online_date = db.DateTimeProperty()
  last_offline_date = db.DateTimeProperty()
  last_speak_date = db.DateTimeProperty()

  msg_count = db.IntegerProperty(required=True, default=0)
  msg_chars = db.IntegerProperty(required=True, default=0)
  credit = db.IntegerProperty(required=True, default=0)

  black_before = db.DateTimeProperty(auto_now_add=True)
  snooze_before = db.DateTimeProperty()
  flooding_point = db.IntegerProperty(default=0)

  avail = db.StringProperty(required=True)
  is_admin = db.BooleanProperty(required=True, default=False)
  blocked = db.BooleanProperty(required=True, default=False)
  resources = db.StringListProperty(required=True)

  prefix = db.StringProperty(required=True, default=config.default_prefix)
  nick_pattern = db.StringProperty(required=True, default='[%s]')
  intro = db.StringProperty()

class Log(db.Model):
  time = db.DateTimeProperty(auto_now_add=True, indexed=True)
  msg = db.StringProperty(required=True, multiline=True)
  jid = db.StringProperty()
  nick = db.StringProperty()
  type = db.StringProperty(required=True, indexed=True,
                           choices=set(['chat', 'member', 'misc']))

def log_msg(sender, msg):
  l = Log(jid=sender.jid, nick=sender.nick,
          type='chat', msg=msg)
  l.put()

def log_onoff(sender, action, resource=''):
  if resource:
    if action == OFFLINE and not sender.resources:
      msg = u'完全%s (%s)' % (action, resource)
    else:
      msg = '%s (%s)' % (action, resource)
  else:
    msg = action
  l = Log(jid=sender.jid, nick=sender.nick,
          type='member', msg=msg)
  l.put()

def get_user_by_jid(jid):
  return User.gql('where jid = :1', jid).get()

def get_user_by_nick(nick):
  return User.gql('where nick = :1', nick).get()

def get_member_list():
  r = []
  now = datetime.datetime.now()
  #一个查询中最多只能有一个不等比较
  l = User.gql('where avail != :1', OFFLINE)
  for u in l:
    r.append(u)
  return [unicode(x.jid) for x in r \
          if x.snooze_before is None or x.snooze_before < now]

def send_to_all_except(jid, message):
  if isinstance(jid, str):
    jids = [x for x in get_member_list() if x != jid]
  else:
    jids = [x for x in get_member_list() if x not in jid]
  logging.debug(jid)
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
  if msg.body.startswith('?OTR:'):
    msg.reply('不支持 OTR 加密！')
    return
  if len(msg.body) > 500:
    msg.reply('由于技术限制，每条消息最长为 500 字。大段文本请贴 paste 网站。')
    return
  if sender.is_admin:
    ch = AdminCommand(msg, sender)
  else:
    ch = BasicCommand(msg, sender)
  if not ch.handled:
    now = datetime.datetime.now()
    if sender.black_before is not None \
       and sender.black_before > now:
      if (datetime.datetime.today()+timezone).date() == \
         (sender.black_before+timezone).date():
        format = '%H时%M分%S秒'
      else:
        format = '%m月%d日 %H时%M分%S秒'
      msg.reply('你已被禁言至 ' \
                + (sender.black_before+timezone).strftime(format))
      return

    if sender.last_speak_date is not None:
      d = now - sender.last_speak_date
      t = d.seconds
      if d.days > 0 or t > 60:
        sender.flooding_point = 0
      else:
        k = 1000 / (t * t)
        if k > 0:
          sender.flooding_point += k
        else:
          sender.flooding_point = 0

        k = sender.flooding_point / 1500
        if k > 0:
          msg.reply('刷屏啊？禁言 %d 分钟！' % k)
          send_to_all_except(sender.jid,
            (u'%s 已因刷屏而被禁言 %d 分钟。' % (sender.nick, k)) \
                                  .encode('utf-8'))
          log_onoff(sender, BLACK_AUTO % (60 * k))
          sender.black_before = now + datetime.timedelta(seconds=60*k)
          sender.put()
          return

    sender.last_speak_date = now
    sender.snooze_before = None
    try:
      sender.msg_count += 1
      sender.msg_chars += len(msg.body)
    except TypeError:
      sender.msg_count = 1
      sender.msg_chars = len(msg.body)
    sender.put()
    body = utils.removelinks(msg.body)
    for u in User.gql('where avail != :1', OFFLINE):
      if u.snooze_before is not None and u.snooze_before >= now:
        continue
      if u.jid == sender.jid:
        continue
      try:
        message = '%s %s' % (
          u.nick_pattern % sender.nick,
          body
        )
        xmpp.send_message(u.jid, message)
      except xmpp.InvalidJidError:
        pass
    log_msg(sender, msg.body)

def try_add_user(jid, show=OFFLINE, resource=''):
  '''使用 memcache 作为锁添加用户'''
  L = utils.MemLock('add_user')
  L.require()
  try:
    u = get_user_by_jid(jid)
    if u is not None:
      return
    u = add_user(jid, show, resource)
  finally:
    L.release()
  if show != OFFLINE:
    log_onoff(u, show, resource)
  logging.info(u'%s added', jid)

def add_user(jid, show=OFFLINE, resource=''):
  '''resource 在 presence type 为 available 里使用'''
  nick = jid.split('@')[0]
  old = User.gql('where nick = :1', nick).get()
  while old:
    nick += '_'
    old = User.gql('where nick = :1', nick).get()
  u = User(jid=jid, avail=show, nick=nick)
  if show != OFFLINE:
    u.last_online_date = datetime.datetime.now()
  if resource:
    u.resources.append(resource)
  u.put()
  log_onoff(u, NEW)
  logging.info(u'%s 已经加入' % jid)
  send_to_all_except(jid, u'%s 已经加入' % u.nick)
  xmpp.send_presence(jid, status=notice)
  xmpp.send_message(jid, u'欢迎 %s 加入！获取使用帮助，请输入 %shelp' % (
    u.nick, u.prefix))
  return u

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
        handle = getattr(self, 'do_' + cmd[0])
      except AttributeError:
        msg.reply(u'错误：未知命令 %s' % cmd[0])
      except IndexError:
        msg.reply(u'错误：无命令')
      except UnicodeEncodeError:
        msg.reply(u'错误：命令名解码失败。此问题在 GAE 升级其 Python 到 3.x 后方能解决。')
      else:
        handle(cmd[1:])
        logging.debug('%s did command %s' % (sender.jid, msg.body))
    else:
      self.handled = False

  def do_online(self, args):
    '''显示在线成员列表'''
    r = []
    now = datetime.datetime.now()
    l = User.gql('where avail != :1', OFFLINE)
    for u in l:
      m = u.nick
      status = u.avail
      if status != u'在线':
        m += u' (%s)' % status
      if u.snooze_before is not None and u.snooze_before > now:
        m += u' (snoozing)'
      if u.black_before is not None and u.black_before > now:
        m += u' (已禁言)'
      r.append(unicode('* ' + m))
    r.sort()
    n = len(r)
    r.insert(0, u'在线成员列表:')
    r.append(u'共 %d 人在线。' % n)
    self.msg.reply(u'\n'.join(r).encode('utf-8'))

  def do_chatty(self, args):
    '''显示成员发送的消息数量'''
    r = []
    for u in User.gql('ORDER BY msg_chars ASC'):
      m = u.nick
      m = u'* %s:\t%5d条，共 %s' % (
        u.nick, u.msg_count,
        utils.filesize(u.msg_chars))
      r.append(m)
    n = len(r)
    r.insert(0, u'消息数量排行:')
    r.append(u'共 %d 人。' % n)
    self.msg.reply(u'\n'.join(r).encode('utf-8'))

  def do_nick(self, args):
    '''更改昵称，需要一个参数'''
    if len(args) != 1:
      self.msg.reply('错误：请给出你想到的昵称（不能包含空格）')
      return

    q = User.gql('where nick = :1', args[0]).get()
    if q is not None:
      self.msg.reply('错误：该昵称已被使用，请使用其它昵称')
    elif not utils.checkNick(args[0]):
      self.msg.reply('错误：非法的昵称')
    else:
      old_nick = self.sender.nick
      log_onoff(self.sender, NICK % (old_nick, args[0]))
      self.sender.nick = args[0]
      self.sender.put()
      send_to_all_except(self.sender.jid,
        (u'%s 的昵称改成了 %s' % (old_nick, args[0])).encode('utf-8'))
      self.msg.reply('昵称更改成功！')

  def do_help(self, args=None):
    '''显示本帮助'''
    doc = []
    prefix = self.sender.prefix
    for c, f in self.__class__.__dict__.items():
      if c.startswith('do_'):
        doc.append(u'%s%s:\t%s' % (prefix, c[3:], f.__doc__.decode('utf-8')))
    for b in self.__class__.__bases__:
      for c, f in b.__dict__.items():
        if c.startswith('do_'):
          doc.append(u'%s%s:\t%s' % (prefix, c[3:], f.__doc__.decode('utf-8')))
    doc.sort()
    doc.insert(0, u'命令指南 (当前命令前缀 %s，可设置)' % prefix)
    doc.append(u'要离开，直接删掉好友即可。')
    self.msg.reply(u'\n'.join(doc).encode('utf-8'))

  def do_iam(self, args):
    '''查看自己的信息'''
    s = self.sender
    r = u'昵称：\t\t%s\n消息数：\t\t%d\n消息总量：\t%s\n命令前缀：\t%s\n自我介绍：\t%s' % (
      s.nick, s.msg_count, utils.filesize(s.msg_chars), s.prefix, s.intro)
    self.msg.reply(r.encode('utf-8'))

  def do_m(self, args):
    '''给某人发私信，需要昵称和内容两个参数。私信不会以任何方式被记录。'''
    if len(args) < 2:
      self.msg.reply('请给出昵称和内容。')
      return

    target = get_user_by_nick(args[0])
    if target is None:
      self.msg.reply('Sorry，查无此人。')
      return

    msg = self.msg.body[len(self.sender.prefix):].split(None, 2)[-1]
    msg = u'_私信_ %s %s' % (target.nick_pattern % self.sender.nick, msg)
    if xmpp.send_message(target.jid, msg) == xmpp.NO_ERROR:
      self.msg.reply(u'OK')
    else:
      self.msg.reply(u'消息发送失败')

  def do_snooze(self, args):
    '''暂停接收消息，参数为时间（默认单位为秒）。再次发送消息时自动清除'''
    if len(args) != 1:
      self.msg.reply('你想停止接收消息多久？')
      return
    else:
      try:
        n = utils.parseTime(args[0])
      except ValueError:
        self.msg.reply('Sorry，我无法理解你说的时间。')
        return

    try:
      self.sender.snooze_before = datetime.datetime.now() + datetime.timedelta(seconds=n)
    except OverflowError:
      self.msg.reply('Sorry，你不能睡太久。')
      return
    self.sender.put()
    if n == 0:
      self.msg.reply('你已经醒来。')
    else:
      self.msg.reply('OK，停止接收消息 %d 秒。' % n)
    log_onoff(self.sender, SNOOZE % n)

  def do_offline(self, args):
    '''让程序认为你的所有资源已离线。如在你离线时程序仍认为你在线，请使用此命令。'''
    del self.sender.resources[:]
    self.sender.avail = OFFLINE
    self.sender.last_offline_date = datetime.datetime.now()
    self.sender.put()
    self.msg.reply('OK，在下次你说你在线之前我都认为你已离线。')

  def do_old(self, args):
    '''查询聊天记录，可选一个数字参数。默认为最后20条。特殊参数 OFFLINE 显示离线消息（最多 100 条）'''
    s = self.sender
    q = False
    if not args:
      q = Log.gql("WHERE type = 'chat' ORDER BY time DESC LIMIT 20")
    elif len(args) == 1:
      try:
        n = int(args[0])
        if n > 0:
          q = Log.gql("WHERE type = 'chat' ORDER BY time DESC LIMIT %d" % n)
      except ValueError:
        if args[0].upper() == 'OFFLINE':
          q = Log.gql("WHERE time < :1 AND time > :2 AND type = 'chat' ORDER BY time DESC LIMIT 100", s.last_online_date, s.last_offline_date)
        else:
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

  def do_set(self, args):
    '''设置一些参数。参数格式 key=value；不带参数以查看说明。'''
    #注意：选项名/值中不能包含空格
    if len(args) != 1:
      doc = []
      for c, f in self.__class__.__dict__.items():
        if c.startswith('set_'):
          doc.append(u'* %s:\t%s' % (c[4:], f.__doc__.decode('utf-8')))
      for b in self.__class__.__bases__:
        for c, f in b.__dict__.items():
          if c.startswith('set_'):
            doc.append(u'* %s:\t%s' % (c[4:], f.__doc__.decode('utf-8')))
      doc.sort()
      doc.insert(0, u'设置选项：')
      self.msg.reply(u'\n'.join(doc).encode('utf-8'))
    else:
      msg = self.msg
      cmd = msg.body.split(None, 1)[1].split('=', 1)
      if len(cmd) == 1:
        msg.reply(u'错误：请给出选项值')
        return
      try:
        handle = getattr(self, 'set_' + cmd[0])
      except AttributeError:
        msg.reply(u'错误：未知选项 %s' % cmd[0])
      except IndexError:
        msg.reply(u'错误：无选项')
      except UnicodeEncodeError:
        msg.reply(u'错误：选项名解码失败。此问题在 GAE 升级其 Python 到 3.x 后方能解决。')
      else:
        handle(cmd[1])

  def set_prefix(self, arg):
    '''设置命令前缀'''
    self.sender.prefix = arg
    self.sender.put()
    self.msg.reply(u'设置成功！')

  def set_nickpattern(self, arg):
    '''设置昵称显示格式，用 %s 表示昵称的位置'''
    try:
      arg % 'test'
    except (TypeError, ValueError):
      self.msg.reply(u'错误：不正确的格式')
      return

    self.sender.nick_pattern = arg
    self.sender.put()
    self.msg.reply(u'设置成功！')

class AdminCommand(BasicCommand):
  def do_kick(self, args):
    '''删除某人。他仍可以重新加入。'''
    if len(args) != 1:
      self.msg.reply('请给出昵称。')
      return

    target = get_user_by_nick(args[0])
    if target is None:
      self.msg.reply('Sorry，查无此人。')
      return

    targetjid = target.jid
    targetnick = target.nick
    target.delete()
    self.msg.reply((u'OK，删除 %s。' % target.nick).encode('utf-8'))
    send_to_all_except(self.sender.jid, (u'%s 已被删除。' % self.sender.nick) \
                       .encode('utf-8'))
    xmpp.send_message(targetjid, u'你已被管理员从此群中删除，请删除该好友。')
    log_onoff(self.sender, KICK % (targetnick, targetjid))

  def do_quiet(self, args):
    '''禁言某人，参数为昵称和时间（默认单位秒）'''
    if len(args) != 2:
      self.msg.reply('请给出昵称和时间。')
      return
    else:
      try:
        n = utils.parseTime(args[1])
      except ValueError:
        self.msg.reply('Sorry，我无法理解你说的时间。')
        return

    target = get_user_by_nick(args[0])
    if target is None:
      self.msg.reply('Sorry，查无此人。')
      return

    target.black_before = datetime.datetime.now() + datetime.timedelta(seconds=n)
    target.put()
    self.msg.reply((u'OK，禁言 %s %d 秒。' % (target.nick, n)).encode('utf-8'))
    send_to_all_except((self.sender.jid, target.jid),
                       (u'%s 已被禁言 %s 秒。' % (self.sender.nick, n)) \
                       .encode('utf-8'))
    xmpp.send_message(target.jid, u'你已被管理员禁言 %d 秒。' % n)
    log_onoff(self.sender, BLACK % (target.nick, n))

  def do_admin(self, args):
    '''将某人添加为管理员'''
    if len(args) != 1:
      self.msg.reply(u'请给出昵称。')
      return

    target = get_user_by_nick(args[0])
    if target is None:
      self.msg.reply(u'Sorry，查无此人。')
      return

    if target.is_admin:
      self.msg.reply(u'%s 已经是管理员了。' % target.nick)
      return

    target.is_admin = True
    target.put()
    send_to_all_except(target.jid,
                       (u'%s 已成为管理员。' % target.nick) \
                       .encode('utf-8'))
    xmpp.send_message(target.jid, u'你已是本群管理员。')
    log_onoff(self.sender, ADMIN % (target.nick, self.sender.nick))

  def do_unadmin(self, args):
    '''取消某人管理员的权限'''
    if len(args) != 1:
      self.msg.reply(u'请给出昵称。')
      return

    target = get_user_by_nick(args[0])
    if target is None:
      self.msg.reply(u'Sorry，查无此人。')
      return

    if not target.is_admin:
      self.msg.reply(u'%s 不是管理员。' % target.nick)
      return

    target.is_admin = False
    target.put()
    send_to_all_except(target.jid,
                       (u'%s 已不再是管理员。' % target.nick) \
                       .encode('utf-8'))
    xmpp.send_message(target.jid, u'你已不再是本群管理员。')
    log_onoff(self.sender, UNADMIN % (target.nick, self.sender.nick))

