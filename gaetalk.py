#!/usr/bin/env python2
# vim:fileencoding=utf-8

import re
import logging
import datetime

from google.appengine.ext import db
from google.appengine.api import xmpp

import utils
import config

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
NOTICE     = u'通告：%s'
BLOCK      = u'封禁 %s，原因：%s'
UNBLOCK    = u'解封 %s'

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

  avail = db.StringProperty(required=True)
  is_admin = db.BooleanProperty(required=True, default=False)
  resources = db.StringListProperty(required=True)
  #允许他人私信？
  reject_pm = db.BooleanProperty(default=False)

  prefix = db.StringProperty(required=True, default=config.default_prefix)
  nick_pattern = db.StringProperty(required=True, default='[%s]')
  nick_changed = db.BooleanProperty(required=True, default=False)
  intro = db.StringProperty()

class Log(db.Model):
  time = db.DateTimeProperty(auto_now_add=True, indexed=True)
  msg = db.StringProperty(required=True, multiline=True)
  jid = db.StringProperty()
  nick = db.StringProperty()
  type = db.StringProperty(required=True, indexed=True,
                           choices=set(['chat', 'member', 'admin', 'misc']))

class Group(db.Model):
  time = db.DateTimeProperty(auto_now_add=True)
  topic = db.StringProperty(multiline=True)
  status = db.StringProperty()

class BlockedUser(db.Model):
  jid = db.StringProperty(required=True, indexed=True)
  add_date = db.DateTimeProperty(auto_now_add=True)
  reason = db.StringProperty()

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

def log_admin(sender, action):
  l = Log(jid=sender.jid, nick=sender.nick,
          type='admin', msg=action)
  l.put()

def get_user_by_jid(jid):
  return User.gql('where jid = :1', jid.lower()).get()

def get_user_by_nick(nick):
  return User.gql('where nick = :1', nick).get()

def get_group_info():
  return Group.all().get()

def get_blocked_user(jid):
  return BlockedUser.gql('where jid = :1', jid.lower()).get()

def get_member_list():
  now = datetime.datetime.now()
  #一个查询中最多只能有一个不等比较
  l = User.gql('where avail != :1', OFFLINE)
  return [unicode(x.jid) for x in l \
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

def send_status(jid):
  if get_blocked_user(jid):
    xmpp.send_presence(jid, status=u'您已经被本群封禁')
    return

  grp = get_group_info()
  if grp is None or not grp.status:
    xmpp.send_presence(jid)
  else:
    xmpp.send_presence(jid, status=grp.status)

def handle_message(msg):
  jid = msg.sender.split('/')[0]

  sender = get_blocked_user(jid)
  if sender is not None:
    msg.reply(u'您已经被本群封禁，原因为 %s。' % sender.reason)
    return

  sender = get_user_by_jid(jid)
  if sender is None:
    msg.reply('很抱歉，出错了，请尝试更改状态或者重新添加好友。')
    return

  if msg.body.startswith('?OTR:'):
    msg.reply('不支持 OTR 加密！')
    return

  if msg.body in config.blocked_away_messages:
    msg.reply('系统认为您的客户端正在自动发送离开消息。如果您认为这并不正确，请向管理员反馈。')
    return

  if len(msg.body) > 500 or msg.body.count('\n') > 5:
    msgbody = config.post_code(msg.body)
    if msgbody:
      msg.reply(u'内容过长，已贴至 %s 。' % msgbody)
      firstline = ''
      lineiter = iter(msg.body.split('\n'))
      try:
        while not firstline:
          firstline = lineiter.next()
      except StopIteration:
        pass
      if len(firstline) > 40:
        firstline = firstline[:40]
      msgbody += '\n' + firstline + '...'
    else:
      logging.warn(u'贴代码失败，代码长度 %d' % len(msg.body))
      msg.reply('由于技术限制，每条消息最长为 500 字。大段文本请贴 paste 网站。\n'
                '如 http://paste.ubuntu.org.cn/ http://slexy.org/\n'
               )
      return
    ch = None
  else:
    msgbody = msg.body
    if sender.is_admin or sender.jid == config.root:
      ch = AdminCommand(msg, sender)
    else:
      ch = BasicCommand(msg, sender)

  if not ch or not ch.handled:
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

    # handles ping, which does the following:
    # - tells the user the network and the bot are OK
    # - undoes snoozing
    # - tells a previously 'quieted' person if s/he can speak now
    if msgbody == 'ping':
      if sender.snooze_before:
        sender.snooze_before = None
        sender.put()
      msg.reply('pong')
      return

    if msgbody.lower() in ('test', u'测试'):
      if sender.snooze_before:
        sender.snooze_before = None
        sender.put()
      msg.reply('test ok')
      return

    sender.last_speak_date = now
    sender.snooze_before = None
    try:
      sender.msg_count += 1
      sender.msg_chars += len(msgbody)
    except TypeError:
      sender.msg_count = 1
      sender.msg_chars = len(msgbody)
    sender.put()
    body = utils.removelinks(msgbody)
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
    log_msg(sender, msgbody)

def try_add_user(jid, show=OFFLINE, resource=''):
  '''使用 memcache 作为锁添加用户'''
  u = get_blocked_user(jid)
  if u is not None:
    xmpp.send_message(jid, u'您已经被本群封禁，原因为 %s。' % u.reason)
    return

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
  # same user name with different domains are possible
  while get_user_by_nick(nick):
    nick += '_'
  u = User(jid=jid.lower(), avail=show, nick=nick)
  if show != OFFLINE:
    u.last_online_date = datetime.datetime.now()
  if resource:
    u.resources.append(resource)
  u.put()
  log_onoff(u, NEW)
  logging.info(u'%s 已经加入' % jid)
  send_status(jid)
  xmpp.send_message(jid, u'欢迎 %s 加入！要获取使用帮助，请输入 %shelp，要获知群主题，请输入 %stopic。' % (
    u.nick, u.prefix, u.prefix))
  return u

def del_user(jid, by_cmd=False):
  l = User.gql('where jid = :1', jid.lower())
  for u in l:
    if u.jid == config.root:
      xmpp.send_message(jid, u'root 用户：离开前请确定你已做好善后工作！')
    log_onoff(u, LEAVE)
    if by_cmd:
      logging.info(u'%s (%s) 已经离开 (通过使用命令)' % (u.nick, u.jid))
    else:
      logging.info(u'%s (%s) 已经离开' % (u.nick, u.jid))
    u.delete()

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
        logging.debug('%s did command %s' % (sender.jid, cmd[0]))
    else:
      self.handled = False

  def get_msg_part(self, index):
    '''返回消息中第 index 个单词及其后的所有字符'''
    return self.msg.body[len(self.sender.prefix):].split(None, index)[-1]

  def do_online(self, args):
    '''在线成员列表。可带一个参数，指定在名字中出现的一个子串。'''
    r = []
    pat = args[0] if args else None
    now = datetime.datetime.now()
    l = User.gql('where avail != :1', OFFLINE)
    for u in l:
      m = u.nick
      if pat and m.find(pat) == -1:
        continue
      status = u.avail
      if status != ONLINE:
        m += u' (%s)' % status
      if u.snooze_before is not None and u.snooze_before > now:
        m += u' (snoozing)'
      if u.black_before is not None and u.black_before > now:
        m += u' (已禁言)'
      r.append(unicode('* ' + m))
    r.sort()
    n = len(r)
    if pat:
      r.insert(0, u'在线成员列表（包含子串 %s）:' % pat)
      r.append(u'共 %d 人。' % n)
    else:
      r.insert(0, u'在线成员列表:')
      r.append(u'共 %d 人在线。' % n)
    self.msg.reply(u'\n'.join(r).encode('utf-8'))

  def do_lsadmin(self, args):
    '''管理员列表'''
    r = []
    now = datetime.datetime.now()
    l = User.gql('where is_admin = :1', True)
    for u in l:
      m = u.nick
      status = u.avail
      if status != ONLINE:
        m += u' (%s)' % status
      if u.snooze_before is not None and u.snooze_before > now:
        m += u' (snoozing)'
      if u.black_before is not None and u.black_before > now:
        m += u' (已禁言)'
      r.append(unicode('* ' + m))
    r.sort()
    n = len(r)
    r.insert(0, u'管理员列表:')
    r.append(u'共 %d 位管理员。' % n)
    self.msg.reply(u'\n'.join(r).encode('utf-8'))

  def do_lsblocked(self, args):
    '''列出被封禁用户名单'''
    r = []
    l = BlockedUser.all()
    for u in l:
      r.append(unicode('* %s (%s, %s)' % (u.jid,
                                          utils.strftime(u.add_date, timezone),
                                          u.reason)
                      )
              )
    r.sort()
    n = len(r)
    r.insert(0, u'封禁列表:')
    r.append(u'共 %d 个 JID 被封禁。' % n)
    self.msg.reply(u'\n'.join(r).encode('utf-8'))

  def do_chatty(self, args):
    '''消息数排行'''
    r = []
    for u in User.gql('ORDER BY msg_count ASC'):
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
    '''更改昵称，需要一个参数，不能使用大部分标点符号'''
    if len(args) != 1:
      self.msg.reply('错误：请给出你想到的昵称（不能包含空格）')
      return

    q = get_user_by_nick(args[0])
    if q is not None:
      self.msg.reply('错误：该昵称已被使用，请使用其它昵称')
    elif not utils.checkNick(args[0]):
      self.msg.reply('错误：非法的昵称')
    else:
      if not config.nick_can_change and self.sender.nick_changed:
        self.msg.reply('乖哦，你已经没机会再改昵称了')
        return
      old_nick = self.sender.nick
      log_onoff(self.sender, NICK % (old_nick, args[0]))
      self.sender.nick = args[0]
      self.sender.nick_changed = True
      self.sender.put()
      send_to_all_except(self.sender.jid,
        (u'%s 的昵称改成了 %s' % (old_nick, args[0])).encode('utf-8'))
      self.msg.reply('昵称更改成功！')
  do_nick.__doc__ += '，最长 %d 字节' % config.nick_maxlen

  def do_whois(self, args):
    '''查看用户信息，参数为用户昵称'''
    if len(args) != 1:
      self.msg.reply('错误：你想知道关于谁的信息？')
      return

    u = get_user_by_nick(args[0])
    if u is None:
      self.msg.reply(u'Sorry，查无此人。')
      return

    now = datetime.datetime.now()
    status = u.avail
    addtime = (u.add_date + timezone).strftime('%Y年%m月%d日 %H时%M分').decode('utf-8')
    allowpm = u'否' if u.reject_pm else u'是'
    if u.snooze_before is not None and u.snooze_before > now:
      status += u' (snoozing)'
    if u.black_before is not None and u.black_before > now:
      status += u' (已禁言)'
    r = []
    r.append(u'昵称：\t%s' % u.nick)
    if self.sender.is_admin:
      r.append(u'JID：\t%s' % u.jid)
    r.append(u'状态：\t%s' % status)
    r.append(u'消息数：\t%d' % u.msg_count)
    r.append(u'消息总量：\t%s' % utils.filesize(u.msg_chars))
    r.append(u'加入时间：\t%s' % addtime)
    r.append(u'接收私信：\t%s' % allowpm)
    r.append(u'自我介绍：\t%s' % u.intro)
    self.msg.reply(u'\n'.join(r).encode('utf-8'))

  def do_help(self, args=()):
    '''显示本帮助。参数 long 显示详细帮助，也可指定命令名。'''
    doc = []
    prefix = self.sender.prefix

    if len(args) > 1:
      self.msg.reply('参数错误。')
      return
    arg = args[0] if args else None

    if arg is None or arg == 'long':
      for b in self.__class__.__bases__ + (self.__class__,):
        for c, f in b.__dict__.items():
          if c.startswith('do_'):
            if arg is None:
              doc.append(u'%s%s:\t%s' % (prefix, c[3:], f.__doc__.decode('utf-8').\
                                         split(u'，', 1)[0].split(u'。', 1)[0]))
            else:
              doc.append(u'%s%s:\t%s' % (prefix, c[3:], f.__doc__.decode('utf-8')))
      doc.sort()
      if arg is None:
        doc.insert(0, u'** 命令指南 **\n(当前命令前缀 %s，可设置。使用 %shelp long 显示详细帮助)' % (prefix, prefix))
      else:
        doc.insert(0, u'** 命令指南 **\n(当前命令前缀 %s，可设置)' % prefix)
      doc.append(u'要离开，直接删掉好友即可。')
      doc.append(u'Gtalk 客户端用户要离开请使用 quit 命令。')
      self.msg.reply(u'\n'.join(doc).encode('utf-8'))
    else:
      try:
        handle = getattr(self, 'do_' + arg)
      except AttributeError:
        self.msg.reply(u'错误：未知命令 %s' % arg)
      except UnicodeEncodeError:
        self.msg.reply(u'错误：命令名解码失败。此问题在 GAE 升级其 Python 到 3.x 后方能解决。')
      else:
        self.msg.reply(u'%s%s:\t%s' % (prefix, arg, handle.__doc__.decode('utf-8')))

  def do_topic(self, args=()):
    '''查看群主题'''
    grp = get_group_info()
    if grp is None or not grp.topic:
      self.msg.reply(u'没有设置群主题。')
    else:
      self.msg.reply(grp.topic)

  def do_iam(self, args):
    '''查看自己的信息'''
    u = self.sender
    addtime = (u.add_date + timezone).strftime('%Y年%m月%d日 %H时%M分').decode('utf-8')
    allowpm = u'否' if u.reject_pm else u'是'
    r = []
    r.append(u'昵称：\t%s' % u.nick)
    r.append(u'JID：\t%s' % u.jid)
    r.append(u'资源：\t%s' % u' '.join(u.resources))
    r.append(u'消息数：\t%d' % u.msg_count)
    r.append(u'消息总量：\t%s' % utils.filesize(u.msg_chars))
    r.append(u'加入时间：\t%s' % addtime)
    r.append(u'命令前缀：\t%s' % u.prefix)
    r.append(u'接收私信：\t%s' % allowpm)
    r.append(u'自我介绍：\t%s' % u.intro)
    self.msg.reply(u'\n'.join(r).encode('utf-8'))

  def do_m(self, args):
    '''发私信，需要昵称和内容两个参数。私信不会以任何方式被记录。用户可使用 set 命令设置是否接收私信。'''
    if len(args) < 2:
      self.msg.reply('请给出昵称和内容。')
      return

    target = get_user_by_nick(args[0])
    if target is None:
      self.msg.reply('Sorry，查无此人。')
      return

    if target.reject_pm:
      self.msg.reply('很抱歉，对方不接收私信。')
      return

    msg = self.get_msg_part(2)
    msg = u'_私信_ %s %s' % (target.nick_pattern % self.sender.nick, msg)
    xmpp.send_message(target.jid, msg)

  def do_intro(self, arg):
    '''设置自我介绍信息'''
    if not arg:
      self.msg.reply('请给出自我介绍的内容。')
      return

    msg = self.get_msg_part(1)
    u = self.sender
    try:
      u.intro = msg
    except db.BadValueError:
      # 过长文本已在 handle_message 中被拦截
      self.msg.reply('错误：自我介绍内容只能为一行。')
      return

    u.put()
    self.msg.reply(u'设置成功！')

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
      self.msg.reply(u'OK，停止接收消息 %s。' % utils.displayTime(n))
    log_onoff(self.sender, SNOOZE % n)

  def do_offline(self, args):
    '''假装离线，让程序认为你的所有资源已离线。如在你离线时程序仍认为你在线，请使用此命令。'''
    del self.sender.resources[:]
    self.sender.avail = OFFLINE
    self.sender.last_offline_date = datetime.datetime.now()
    self.sender.put()
    self.msg.reply('OK，在下次你说你在线之前我都认为你已离线。')

  def do_fakeresource(self, args):
    '''假装在线，人工加入一个新的资源，使程序认为你总是在线。使用 off 参数来取消。'''
    if args and args[0] == 'off':
      try:
        self.sender.resources.remove('fakeresouce')
        self.msg.reply('OK，fakeresouce 已取消。')
        self.sender.put()
      except ValueError:
        self.msg.reply('没有设置 fakeresouce。')
    else:
      try:
        self.sender.resources.index('fakeresouce')
        self.msg.reply('你已经设置了永远在线。')
      except ValueError:
        self.sender.resources.append('fakeresouce')
        self.msg.reply('OK，你将永远在线。')
        self.sender.put()

  def do_old(self, args):
    '''聊天记录查询，可选一个数字参数。默认为最后20条。特殊参数 OFFLINE （不区分大小写）显示离线消息（最多 100 条）'''
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
        if datetime.datetime.today() - q[0].time > datetime.timedelta(hours=24):
          show_date = True
        else:
          show_date = False
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
    '''设置参数。参数格式 key=value；不带参数以查看说明。'''
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
      cmd = args[0].split('=', 1)
      if len(cmd) == 1 or cmd[1] == '':
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

  def do_quit(self, args):
    '''删除用户数据。某些自称“不作恶”的公司的客户端会不按协议要求发送删除好友的消息，请 gtalk 官方客户端用户使用此命令退出。参见 http://xmpp.org/rfcs/rfc3921.html#rfc.section.6.3 。'''
    del_user(self.sender.jid)
    self.msg.reply(u'OK.')

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

  def set_allowpm(self, arg):
    '''设置是否接收私信，参数为 y（接收）或者 n（拒绝）'''
    if arg not in 'yn':
      self.msg.reply(u'错误的参数。')
      return

    if arg == 'y':
      self.sender.reject_pm = False
    else:
      self.sender.reject_pm = True
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

    if target.jid == config.root:
      self.msg.reply('不能删除 root 用户')
      return

    targetjid = target.jid
    targetnick = target.nick
    target.delete()
    self.msg.reply((u'OK，删除 %s。' % target.nick).encode('utf-8'))
    send_to_all_except(self.sender.jid, (u'%s 已被删除。' % target.nick) \
                       .encode('utf-8'))
    xmpp.send_message(targetjid, u'你已被管理员从此群中删除，请删除该好友。')
    log_admin(self.sender, KICK % (targetnick, targetjid))

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
    self.msg.reply(u'OK，禁言 %s %s。' % (target.nick, utils.displayTime(n)))
    send_to_all_except((self.sender.jid, target.jid),
                       (u'%s 已被禁言 %s。' % (target.nick, utils.displayTime(n))) \
                       .encode('utf-8'))
    xmpp.send_message(target.jid, u'你已被管理员禁言 %s。' % utils.displayTime(n))
    log_admin(self.sender, BLACK % (target.nick, n))

  def do_notice(self, arg):
    '''发送群通告。只会发给在线的人，包括 snoozing 者。'''
    if not arg:
      self.msg.reply('请给出群通告的内容。')
      return

    msg = self.msg.body[len(self.sender.prefix):].split(None, 1)[-1]

    l = User.gql('where avail != :1', OFFLINE)
    log_admin(self.sender, NOTICE % msg)
    for u in l:
      try:
        xmpp.send_message(u.jid, u'通告：' + msg)
      except xmpp.InvalidJidError:
        pass

  def do_topic(self, args=()):
    '''查看或设置群主题'''
    grp = get_group_info()
    if not args:
      if grp is None or not grp.topic:
        self.msg.reply(u'没有设置群主题。')
      else:
        self.msg.reply(grp.topic)
    else:
      grp = get_group_info()
      if grp is None:
        grp = Group()
      grp.topic = self.msg.body[len(self.sender.prefix):].split(None, 1)[-1]
      grp.put()
      self.msg.reply(u'群主题已更新。')

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
    log_admin(self.sender, ADMIN % (target.nick, self.sender.nick))

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
    log_admin(self.sender, UNADMIN % (target.nick, self.sender.nick))

  def do_block(self, args):
    '''封禁某个 ID，参数为用户昵称或者 ID（如果不是已经加入的 ID 的话），以及封禁原因'''
    if len(args) < 2:
      self.msg.reply(u'请给出要封禁的用户和原因。')
      return

    target = get_user_by_nick(args[0])
    reason = self.msg.body[len(self.sender.prefix):].split(None, 2)[-1]
    if target is None:
      jid = args[0]
      name = jid
      fullname = name
    else:
      jid = target.jid
      name = target.nick
      fullname = '%s (%s)' % (name, jid)
    u = BlockedUser.gql('where jid = :1', jid).get()
    if u is not None:
      self.msg.reply(u'此 JID 已经被封禁。')
      return

    if jid == config.root:
      self.msg.reply('不能封禁 root 用户')
      return

    if target:
      target.delete()
    u = BlockedUser(jid=jid, reason=reason)
    u.put()

    send_to_all_except(self.sender.jid,
                       (u'%s 已被本群封禁，理由为 %s。' % (name, reason)) \
                       .encode('utf-8'))
    self.msg.reply(u'%s 已被本群封禁，理由为 %s。' % (fullname, reason))
    xmpp.send_message(jid, u'你已被本群封禁，理由为 %s。' % reason)
    xmpp.send_presence(jid, status=u'您已经被本群封禁')
    log_admin(self.sender, BLOCK % (fullname, reason))

  def do_unblock(self, args):
    '''解封某个 ID'''
    if len(args) != 1:
      self.msg.reply(u'请给出要解封用户的 JID。')
      return

    target = get_blocked_user(args[0])
    if target is None:
      self.msg.reply(u'封禁列表中没有这个 JID。')
      return

    target.delete()
    send_to_all((u'%s 已被解除封禁。' % args[0]) \
                .encode('utf-8'))
    log_admin(self.sender, UNBLOCK % args[0])

  def do_groupstatus(self, arg):
    '''设置群状态'''
    grp = get_group_info()
    if grp is None:
      grp = Group()
    grp.status = self.msg.body[len(self.sender.prefix):].split(None, 1)[-1]
    grp.put()
    for u in User.all():
      xmpp.send_presence(u.jid, status=grp.status)
    self.msg.reply(u'设置成功！')
