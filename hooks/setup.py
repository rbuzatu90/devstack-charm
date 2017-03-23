# Copyright 2015 Cloudbase Solutions SRL
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import subprocess


def pre_install():
    """
    Do any setup required before the install hook.
    """
    # Juju runs apt-get update && apt-get upgrade if configured. This sometimes
    # updates the kernel. We check whether or not we need to reboot the system
    # for the changes to take effect.
    if os.path.isfile("/var/run/reboot-required"):
        subprocess.call(["juju-reboot", "--now"])

    install_charmhelpers()


def install_charmhelpers():
    """
    Install the charmhelpers library, if not present.
    """
    try:
        import charmhelpers  # noqa
    except ImportError:
        import subprocess
        subprocess.check_call(
            ['apt-get', 'install', '-y', 'python-pip', 'git', 'python-netifaces'])
        subprocess.check_call(['pip', 'install', 'charmhelpers'])
