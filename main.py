#!/usr/bin/env python2
# -*- coding: utf-8 -*-

import os
import sys
from glob import iglob
import mailbox
from multiprocessing import cpu_count, Pool

# procmail-py - Email content and spam filtering
# MIT License
# © 2012 Noah K. Tilton <noahktilton@gmail.com>

from config import BASE_MAILDIR, addresses, mark_read
from spam import spamc, blacklisted
from utils import mv, spammy_spamc, mark_as_read, uniq

INBOXDIR            = os.path.join(BASE_MAILDIR, "INBOX")
maildirs_on_disk    = [os.path.basename(dir) for dir in iglob(os.path.join(BASE_MAILDIR, "*"))]
maildirs_in_file    = addresses.values() # <- some of these may not exist
maildirs            = uniq(maildirs_on_disk + maildirs_in_file)
mailboxes           = dict((d, mailbox.Maildir(os.path.join(BASE_MAILDIR, d), create=True)) for d in maildirs)


# N.B.: the order of the following filters matters.  note the return
# statements.  this short-circuiting is desirable, but has to be done
# carefully to avoid double-booking mails.
def filter(args):
    try:
        key, message = args

        # BLACKLISTED WORDS/PHRASES
        if not message.is_multipart():
            # Can't run blacklist logic against multipart messages
            # because random phrases such as "gucci" may show up in
            # base64-encoded strings ... and I'm too lazy to write a
            # better loop here.  Derp.
            flat_msg = message.as_string()
            for badword in blacklisted:
                if badword in flat_msg:
                    print("badword: %s (%s)" % (badword, message["subject"]))
                    mark_as_read(message)
                    mv(INBOX, mailboxes["Junk"], message, key)
                    return

        # SPAM?
        if spammy_spamc(message):
            # FIXME 
            mark_as_read(message)
            mv(INBOX, mailboxes["Junk"], message, key)
            return

        # MARK-AS-READ?
        for header, string in mark_read.items():
            if string in message[header]:
                # http://docs.python.org/library/mailbox.html#mailbox.MaildirMessage
                mark_as_read(message)

        # MAILING LIST?
        for list_header in [message["delivered-to"], message["reply-to"], message["list-id"]]:
            if list_header is not None:
                try:
                    list_id, remainder = list_header.split("@")
                    if list_id in mailboxes.keys():
                        mv(INBOX, mailboxes[list_id], message, key)
                        return
                except ValueError:
                    print("couldn't split %s %s %s" % (list_header, key,
                          message["subject"]))

        # WHITELISTED SENDER?
        for addr in addresses.keys():
            if addr in message["from"].lower():
                mv(INBOX, mailboxes[addresses[addr]], message, key)
                return
    except Exception, e:
        print("error", e)

if __name__ == '__main__':
    INBOX       = mailbox.Maildir(INBOXDIR, factory=None)
    numprocs    = (min((cpu_count() + 2), len(INBOX)))
    if numprocs < 1: sys.exit()
    get_pool    = lambda: Pool(processes=numprocs)

    print("Pool size: %s" % numprocs)

    # run mail through spamc in parallel
    print("Running bogo ...")
    bogo_pool = get_pool()
    bogo_pool.imap(spamc, iglob(os.path.join(INBOXDIR, "new", "*")))
    bogo_pool.close()
    bogo_pool.join()

    print("Filtering ...")
    # filter in parallel
    filter_pool = get_pool()
    filter_pool.map(filter, INBOX.iteritems())
    filter_pool.close()
    filter_pool.join()

    [box.close() for name, box in mailboxes.items()]
