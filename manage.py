#!/usr/bin/env python

from __future__ import absolute_import, division, generators, nested_scopes, print_function, unicode_literals, with_statement

import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dbs.settings")

    #if os.getuid() == 0 and 'collectstatic' not in sys.argv:
    #    from django.conf import settings
    #    import pwd
    #    user = pwd.getpwnam(getattr(settings, 'USERNAME', 'dbs'))
    #    os.setgid(user.pw_gid)
    #    os.setuid(user.pw_uid)
    #    os.environ['USER']  = user.pw_name
    #    os.environ['HOME']  = user.pw_dir
    #    os.environ['SHELL'] = user.pw_shell
    #    os.chdir(os.environ['HOME'])

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
