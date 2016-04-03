# coding=utf-8
"""
private_tell.py - Sopel Less obnoxious Tell and Ask Module
Copyright 2016, Daniel Muller
Licensed under the Eiffel Forum License 2.

http://sopel.chat
"""
from __future__ import unicode_literals, absolute_import, print_function, division

import os
import time
import threading
import sys
from sopel.tools import Identifier, iterkeys
from sopel.tools.time import get_timezone, format_time
from sopel.module import commands, nickname_commands, rule, priority, example
from sopel.config.types import (
    StaticSection, ValidatedAttribute, FilenameAttribute
)


class tellSection(StaticSection):
    private_tells = ValidatedAttribute('private_tells', bool, default=False)
    """Deliver tells via private message"""
    maximum_tells_in_channel = ValidatedAttribute('maximum amount of tells in channel', int, default=4)


def configure(config):
    config.define_section('tell', tellSection)
    config.tell.configure_setting('private_tells',
                                   "Deliver tells via private message?")
    config.tell.configure_setting('maximum_tells_in_channel',
                                   'How many tells should a person recieve in channel before the rest gets send via private message?')


def setup(bot):
    bot.config.define_section('tell', tellSection)

def loadReminders(fn, lock):
    lock.acquire()
    try:
        result = {}
        f = open(fn)
        for line in f:
            line = line.strip()
            if sys.version_info.major < 3:
                line = line.decode('utf-8')
            if line:
                try:
                    tellee, teller, verb, timenow, msg = line.split('\t', 4)
                except ValueError:
                    continue  # @@ hmm
                result.setdefault(tellee, []).append((teller, verb, timenow, msg))
        f.close()
    finally:
        lock.release()
    return result


def dumpReminders(fn, data, lock):
    lock.acquire()
    try:
        f = open(fn, 'w')
        for tellee in iterkeys(data):
            for remindon in data[tellee]:
                line = '\t'.join((tellee,) + remindon)
                try:
                    to_write = line + '\n'
                    if sys.version_info.major < 3:
                        to_write = to_write.encode('utf-8')
                    f.write(to_write)
                except IOError:
                    break
        try:
            f.close()
        except IOError:
            pass
    finally:
        lock.release()
    return True


def setup(self):
    fn = self.nick + '-' + self.config.core.host + '.tell.db'
    self.tell_filename = os.path.join(self.config.core.homedir, fn)
    if not os.path.exists(self.tell_filename):
        try:
            f = open(self.tell_filename, 'w')
        except OSError:
            pass
        else:
            f.write('')
            f.close()
    self.memory['tell_lock'] = threading.Lock()
    self.memory['reminders'] = loadReminders(self.tell_filename, self.memory['tell_lock'])


@commands("ask")
@commands("tell")
@example('Sopel, tell Embolalia he broke something again.')
def f_remind(bot, trigger):
    """Give someone a message the next time they're seen"""
    teller = trigger.nick
    verb = trigger.group(1)

    if not trigger.group(3):
        bot.reply("%s whom?" % verb)
        return

    tellee = trigger.group(3).rstrip('.,:;')
    msg = trigger.group(2).lstrip(tellee).lstrip()

    if not msg:
        bot.reply("%s %s what?" % (verb, tellee))
        return

    tellee = Identifier(tellee)

    if not os.path.exists(bot.tell_filename):
        return

    if len(tellee) > 20:
        return bot.reply('That nickname is too long.')
    if tellee == bot.nick:
        return bot.reply("I'm here now, you can tell me whatever you want!")

    if not tellee in (Identifier(teller), bot.nick, 'me'):
        tz = get_timezone(bot.db, bot.config, None, tellee)
        timenow = format_time(bot.db, bot.config, tz, tellee)
        bot.memory['tell_lock'].acquire()
        try:
            if not tellee in bot.memory['reminders']:
                bot.memory['reminders'][tellee] = [(teller, verb, timenow, msg)]
            else:
                bot.memory['reminders'][tellee].append((teller, verb, timenow, msg))
        finally:
            bot.memory['tell_lock'].release()

        response = "I'll pass that on when %s is around..." % tellee
        if bot.config.tell.private_tells:
            bot.msg(teller, response)
        else:
            bot.reply(response)
    elif Identifier(teller) == tellee:
        bot.say('You can %s yourself that.' % verb)
    else:
        bot.say("Hey, I'm not as stupid as Monty you know!")

    dumpReminders(bot.tell_filename, bot.memory['reminders'], bot.memory['tell_lock'])  # @@ tell


def getReminders(bot, channel, key, tellee):
    lines = []
    template_tellee = "Message from %s at %s : %s"
    template_teller = "Message for %s delivered at %s : %s"
    template_public = "%s: %s <%s> %s %s %s"

    today = time.strftime('%d %b', time.gmtime())

    bot.memory['tell_lock'].acquire()
    try:
        for (teller, verb, datetime, msg) in bot.memory['reminders'][key]:
            if datetime.startswith(today):
                datetime = datetime[len(today) + 1:]
            lines.append((template_tellee % (teller, datetime, msg), template_teller % (tellee, datetime, msg), template_public % (tellee, datetime, teller, verb, tellee, msg), teller))

        try:
            del bot.memory['reminders'][key]
        except KeyError:
            bot.msg(channel, 'Er...')
    finally:
        bot.memory['tell_lock'].release()
    return lines


@rule('(.*)')
@priority('low')
def message(bot, trigger):

    tellee = trigger.nick
    channel = trigger.sender

    if not os.path.exists(bot.tell_filename):
        return

    reminders = []
    remkeys = list(reversed(sorted(bot.memory['reminders'].keys())))

    for remkey in remkeys:
        if not remkey.endswith('*') or remkey.endswith(':'):
            if tellee == remkey:
                reminders.extend(getReminders(bot, channel, remkey, tellee))
        elif tellee.startswith(remkey.rstrip('*:')):
            reminders.extend(getReminders(bot, channel, remkey, tellee))
    if bot.config.tell.private_tells[0:]:
        for line_tellee, line_teller, line_public, teller in reminders:
            bot.msg(tellee, line_tellee)
            bot.msg(teller, line_teller)
    else:
        for line_tellee, line_teller, line_public in reminders[:bot.config.tell.maximum_tells_in_channel]:
            bot.say(line_public)

        if reminders[bot.config.tell.maximum_tells_in_channel:]:
            bot.say('Further messages sent privately')
            for line in reminders[bot.config.tell.maximum_tells_in_channel:]:
                bot.msg(tellee, line_tellee)

                
    if len(bot.memory['reminders'].keys()) != remkeys:
        dumpReminders(bot.tell_filename, bot.memory['reminders'], bot.memory['tell_lock'])  # @@ tell
