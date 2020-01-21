#!/usr/bin/env python

# Copyright (C) 2003-2007  Robey Pointer <robeypointer@gmail.com>
#
# This file is part of paramiko.
#
# Paramiko is free software; you can redistribute it and/or modify it under the
# terms of the GNU Lesser General Public License as published by the Free
# Software Foundation; either version 2.1 of the License, or (at your option)
# any later version.
#
# Paramiko is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Paramiko; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA.

import base64
import threading

import paramiko
from paramiko.py3compat import decodebytes


class Server(paramiko.ServerInterface):

    try:
        key = paramiko.RSAKey.from_private_key_file("rsa.key")
    except FileNotFoundError:
        genkey = paramiko.RSAKey.generate(2048)
        genkey.write_private_key_file("rsa.key")
        key = paramiko.RSAKey.from_private_key_file("rsa.key")
    data = base64.b64encode(key.asbytes())

    good_pub_key = paramiko.RSAKey(data=decodebytes(data))

    def __init__(self, sshlogin=None):
        self.event = threading.Event()
        self.sshlogin = sshlogin

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_auth_password(self, username, password):
        return paramiko.AUTH_FAILED

    def check_auth_none(self, username):
        if username == self.sshlogin:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "none,password"

    def check_channel_shell_request(self, channel):
        self.event.set()
        return True

    def check_channel_pty_request(
        self, channel, term, width, height, pixelwidth, pixelheight, modes
    ):
        return True
