#!/usr/bin/python

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

import setup
setup.pre_install()

import devstack

from charmhelpers.core import hookenv


def install():
    hookenv.log('Installing devstack')
    config = hookenv.config()
    use_bonding = config.get("use-bonding", False)
    if use_bonding:
        b = devstack.Bonding()
        b.run()
    # add steps for installing dependencies and packages here
    # e.g.: from charmhelpers import fetch
    #       fetch.apt_install(fetch.filter_installed_packages(['nginx']))
    devstack.install_extra_packages()
    devstack.sync_time()
    d = devstack.Devstack(username=devstack.DEFAULT_USER)
    d.run()


if __name__ == "__main__":
    install()
