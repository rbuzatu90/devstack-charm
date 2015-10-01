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

import subprocess
import pwd
import os
import urlparse
import string
import ConfigParser
import urllib2
import shutil
import netifaces
import json
import base64

from os import urandom
from itertools import islice, imap, repeat

from charmhelpers import fetch
from charmhelpers.core import hookenv, host, templating

from subprocess import PIPE


EXT_BR="br-ex"
INT_BR="br-int"
DEVSTACK_REPOSITORY = "https://github.com/openstack-dev/devstack"
UTC_TIMEZONE = "/usr/share/zoneinfo/UTC"
LOCALTIME = "/etc/localtime"
SUDOERSD = "/etc/sudoers.d"
STACK_LOCATION = "/opt/stack"
DEFAULT_USER = "ubuntu"
BONDING_MASTERS = "/sys/class/net/bonding_masters"

KEYSTONERC = """
export OS_USERNAME=admin
export OS_TENANT_NAME=admin
export OS_PASSWORD=%s
export OS_AUTH_URL=http://127.0.0.1:35357/v2.0/
"""


def interfaces():
    ret = {}
    interfaces = netifaces.interfaces()
    for i in interfaces:
        link = os.path.join("/sys/class/net", i)
        master = os.path.join(link, "master")
        iface = i
        if os.path.islink(master):
            # if this interface is part of a bridge, return the bridge to which
            # it belongs
            iface = os.path.basename(os.path.abspath(os.readlink(master)))
        details = netifaces.ifaddresses(iface).get(netifaces.AF_LINK)
        if details:
            addr = details[0]["addr"]
            ret[addr.upper()] = iface
    return ret


def get_port(ports):
    port_list = ports.split(" ")
    iface_by_mac = interfaces()
    ifaces = netifaces.interfaces()
    for i in port_list:
        if i in ifaces:
            return i
        if i.upper() in iface_by_mac:
            return iface_by_mac[i.upper()]
    raise Exception("Could not find port. Looked for: %s" % ports)

def find_bond_interfaces(ports):
    ifaces = interfaces()
    found = []
    for i in ports:
        port = ifaces.get(i.upper())
        if port:
            found.append(port)
    return found


def download_file(url, destination):
    hookenv.log("Downloading from %s to %s" % (url, destination))
    resource = urllib2.urlopen(url)
    with open(destination, "wb") as fd:
        while True:
            chunk = resource.read(8192)
            if not chunk:
                break
            fd.write(chunk)
        


class DevstackContext(object):

    RELATION = "devstack"

    def __init__(self, username=DEFAULT_USER):
        self.relation_data = {}
        self.user = pwd.getpwnam(username)

    def _fetch_relation_data(self):
        for rid in hookenv.relation_ids(self.RELATION):                                        
            for unit in hookenv.related_units(rid):                                         
                self.relation_data[unit] = hookenv.relation_get(rid=rid, unit=unit)

    def render_ad_credentials(self):
        self._fetch_relation_data()
        location = os.path.join(self.user.pw_dir, "ad_credentials")
        for i in self.relation_data.keys():
            creds = self.relation_data[i].get("ad_credentials")
            if not creds:
                continue
            credential_data = json.loads(base64.b64decode(creds).decode("utf-16"))
            with open(location, "wb") as fd:                                    
                for i in credential_data.keys():                                          
                    fd.write("%s=%s\n" % (i.upper(), credential_data[i]))
        if os.path.isfile(location):
            os.chown(location, self.user.pw_uid, self.user.pw_gid)                  
            os.chmod(location, 0o700)

    def render_nodes(self):
        units = {}
        location = os.path.join(self.user.pw_dir, "nodes")
        for i in self.relation_data.keys():
            name = "_".join(i.split("-")[:-1]).upper()
            if units.get(name):
                units[name] += ",%s" % self.relation_data[i]["private-address"]
            else:
                units[name] = self.relation_data[i]["private-address"]
        with open(location, "w") as fd:
            for i in units.keys():
                fd.write("%s=%s\n" % (i, units[i]))
        if os.path.isfile(location):
            os.chown(location, self.user.pw_uid, self.user.pw_gid)                                  
            os.chmod(location, 0o700)


class ExecException(Exception):
    pass


def get_packages(name):
    pkg = hookenv.config(name)
    arr = []
    if pkg:
        arr = pkg.split()
    return arr


def install_extra_packages():
    system_pkg = get_packages("extra-packages")
    python_pkg = get_packages("extra-python-packages")
    if len(system_pkg) > 0:
        fetch.apt_install(system_pkg, fatal=True)
    if len(python_pkg) > 0:
        args = ["pip", "install"]
        args.extend(python_pkg)
        subprocess.check_call(args)


def sync_time():
    ntp_server = hookenv.config("ntp-server")
    if ntp_server and ntp_server != "":
        try:
            subprocess.check_call(["ntpdate", ntp_server])
        except Exception as err:
            hookenv.log("Failed to sync time", level=hookenv.WARNING)
    if os.path.exists(UTC_TIMEZONE) and os.path.exists(LOCALTIME):
        os.remove(LOCALTIME)
        os.symlink(UTC_TIMEZONE, LOCALTIME)


def rand_string(length=12):
    chars = set(string.ascii_uppercase + string.digits)
    char_gen = (c for c in imap(urandom, repeat(1)) if c in chars)
    return ''.join(islice(char_gen, None, length))


def demote(uid, gid):
    os.setgid(gid)
    os.setuid(uid)


def run_command(args, cwd=None, username=DEFAULT_USER, extra_env=None):
    # We error out if user does not exist
    user = pwd.getpwnam(username)
    user_uid = user.pw_uid
    user_gid = user.pw_gid
    env = os.environ.copy()
    env["HOME"] = user.pw_dir
    if cwd is None:
        cwd = user.pw_dir
    # env["PWD"] = cwd
    # env["USER"] = username

    if extra_env:
        for k, v in extra_env.iteritems():
            env[k] = v

    cmd = [
        "sudo", "-u", username, "-E", "--",
    ]
    cmd.extend(args)
    hookenv.log("running command: %r" % cmd)
    # child = os.fork()
    # if child == 0:
    process = subprocess.Popen(
        cmd, cwd=cwd, env=env
    )
    result = process.wait()
    if result:
        raise ExecException(
            "Error running command: %s" % " ".join(args))
        # return
    # os.waitpid(child, 0)


class Project(object):

    def __init__(self, username=DEFAULT_USER):
        self.username = username
        self.env = {}
        self.config = hookenv.config()
        self.env["ZUUL_PROJECT"] = self.config.get('zuul-project')
        self.env["ZUUL_URL"] = self.config.get('zuul-url')
        self.env["ZUUL_REF"] = self.config.get('zuul-ref')
        self.env["ZUUL_CHANGE"] = self.config.get('zuul-change')
        self.env["BRANCH"] = self.config.get('zuul-branch')
        self.charm_dir = os.environ.get("CHARM_DIR")

    @property
    def gerrit_site(self):
        url = urlparse.urlparse(self.env["ZUUL_URL"])
        gerrit_site = urlparse.urlunsplit((url.scheme, url.netloc, '', '', ''))
        return gerrit_site

    @property
    def project_location(self):
        project_basename = os.path.basename(self.env["ZUUL_PROJECT"])
        location = os.path.join(STACK_LOCATION, project_basename)
        return location

    def _validate(self, d):
        for k, v in d.iteritems():
            if v is None:
                raise ValueError("Missing required configuration: %s" % k)

    def _create_project_root(self, owner=DEFAULT_USER):
        user = pwd.getpwnam(owner)
        if os.path.isdir(self.project_location) is False:
            os.makedirs(self.project_location, 0o755)
        os.chown(self.project_location, user.pw_uid, user.pw_gid)

    def _run_gerrit_git_prep(
            self, gerrit_site, git_origin=None, username=DEFAULT_USER):
        gerrit_gitprep = os.path.join(
            self.charm_dir, "files", "gerrit-git-prep.sh")
        if os.path.isfile(gerrit_gitprep) is False:
            raise Exception("Could not find gerrit-git-prep.sh")
        if os.access(gerrit_gitprep, os.X_OK) is False:
            os.chmod(gerrit_gitprep, 0o755)
        args = [
            gerrit_gitprep,
            gerrit_site
        ]
        if git_origin:
            args.append(git_origin)

        run_command(
            args,
            cwd=self.project_location,
            extra_env=self.env,
            username=username)

    def run(self):
        self._validate(self.env)
        self._create_project_root(self.username)
        self._run_gerrit_git_prep(self.gerrit_site)


class Bonding(object):

    def __init__(self):
        """
        ports: a list of mac addresses that are meant to be part of a bond
        """
        self.config = hookenv.config()
        self.bonding_mode = self.config.get("bonding-mode", 4)
        self.bond_name = self.config.get("bond-name", "bond0")
        self.bond_sysfs = os.path.join("/sys/class/net", self.bond_name)
        self.bond_settings = os.path.join(self.bond_sysfs, "bonding")

    def _create_bond_interface(self):
        subprocess.check_call(["modprobe", "bonding"])
        if os.path.isdir(self.bond_sysfs):
            if os.path.isdir(self.bond_settings) is False:
                raise Exception("%s already on system and is not a bond." % self.bond_name)
        else:
            with open(BONDING_MASTERS, "w") as b:
                b.write("+%s\n" % self.bond_name)
        # bond mode can only be set when link is down
        subprocess.check_call(["ip", "link", "set", self.bond_name, "down"])
        # remove slaves
        slaves = os.path.join(self.bond_settings, "slaves")
        with open(slaves, "w+") as s:
            p = s.read().split()
            for i in p:
                s.write("-%s" % i)
                s.flush()
        # set mode
        mode = os.path.join(self.bond_settings, "mode")
        with open(mode, "w+") as m:
            m.write("%s\n" % self.bonding_mode)
        # bring the interface up
        subprocess.check_call(["ip", "link", "set", self.bond_name, "up"])

    def _assign_ports_to_bond(self):
        bonds = self.config.get("bond-ports", "")
        ports = find_bond_interfaces(bonds.split())
        if len(ports) == 0:
            raise Exception("No valid bond ports were found on this node.")
        slaves = os.path.join(self.bond_settings, "slaves")
        with open(slaves, "w+") as s:
            p = s.read().split()
            # Check which ports we need to still add to bond
            for i in ports:
                if i not in p:
                    s.write("+%s" % i)
                    s.flush()
            # remove foreign ports from bond. If you manually configure this bond
            # before running this charm, its your problem :).
            for i in p:
                if i not in ports:
                    s.write("-%s" % i)
                    s.flush()

    def run(self):
        self._create_bond_interface()
        self._assign_ports_to_bond()
        


class Devstack(object):

    def __init__(self, username=DEFAULT_USER):
        self.username = username
        self.pwd = pwd.getpwnam(self.username)
        self.project = Project(username=self.username)
        self.config = hookenv.config()
        self.context = self._get_context()
        self.prep_project = self.config.get('prep-project')

    @property
    def rabbit_user(self):
        branch = self.config.get('zuul-branch')
        if branch in ("stable/icehouse", "stable/juno"):
            return "guest"
        return "stackrabbit"

    @property
    def password(self):
        devstack_passwd = os.path.join(self.pwd.pw_dir, "devstack_passwd")
        passwd = rand_string(32)
        if os.path.isfile(devstack_passwd) is False:
            with open(devstack_passwd, "wb") as fd:
                fd.write(passwd)
            return passwd
        fd = open(devstack_passwd).read().strip()
        return fd

    def _devstack_location(self):
        basename = os.path.basename(DEVSTACK_REPOSITORY)
        location = os.path.join(self.pwd.pw_dir, basename)
        return location

    def _clone_devstack(self):
        location = self._devstack_location()
        if os.path.exists(location):
            shutil.rmtree(location)
        args = ["git", "clone", DEVSTACK_REPOSITORY, location]
        run_command(args, username=self.username)
        args = ["git", "checkout", self.config.get('zuul-branch'), ]
        run_command(args, cwd=location, username=self.username)

    def _render_localconf(self, context):
        devstack = self._devstack_location()
        conf_dest = os.path.join(devstack, "local.conf")
        templating.render(
            "local.conf", conf_dest, context,
            owner=self.username, group=self.username)

    def _render_local_sh(self, context):
        devstack = self._devstack_location()                                    
        context["devstack_location"] = devstack
        conf_dest = os.path.join(devstack, "local.sh")                        
        templating.render(                                                      
            "local.sh", conf_dest, context,                                   
            owner=self.username, group=self.username)
        os.chmod(conf_dest, 0o755)

    def _get_enable_plugin(self):
        plugins = []
        enable_plugins = self.config.get("enable-plugin")
        if not enable_plugins:
            return plugins
        lst = enable_plugins.split()
        for i in lst:
            plugin = i.split("|")
            if len(plugin) < 2 or len(plugin) > 3:
                raise Exception(
                    "Invalid plugin definition: must be name|url|gitref")
            if len(plugin) == 2:
                plugin.append("master")
            plugins.append(" ".join(plugin))
        return plugins

    def _get_ext_port(self):
        ext_ports = self.config.get("external-port", "eth2")
        return get_port(ext_ports)

    def _get_data_port(self):
        data_ports = self.config.get("data-port", "eth1")
        return get_port(data_ports)

    def _get_context(self):
        context = {
            "devstack_ip": None,
            "enabled_services": None,
            "ml2_mechanism": None,
            "tenant_network_type": None,
            "enable_vlans": None,
            "enable_tunneling": None,
            "heartbeat_threshold": None,
            "ssh_user": None,
            "heartbeat_rate": None,
            "vlan_range": None,
            "ceilometer_backend": None,
            "enable_live_migration": None,
            "nameservers": None,
            "password": None,
            "verbose": None,
            "debug": None,
            "test_image_url": None,
            "heat_image_url": None,
            "tenant_name": None,
            "zuul_branch": None,
            "scenario_img": None,
            "same_host_resize": None,
        }

        for k, v in context.iteritems():
            opt = k.replace("_", "-")
            val = self.config.get(opt)
            if val is not None:
                context[k] = val

        # add dynamic variables here
        context["devstack_ip"] = hookenv.unit_private_ip()
        context["password"] = self.password
        if self.config.get("disable-ipv6"):
            context["ip_version"] = 4
        if self.config.get("locarc-extra-blob"):
            context["locarc_extra_blob"] = self.config.get("locarc-extra-blob")
        if self.config.get("libs-from-git"):
            context["libs_from_git"] = self._get_libs_from_pip()
        context["enable_plugin"] = self._get_enable_plugin()
        context["ext_iface"] = self._get_ext_port()
        context["data_iface"] = self._get_data_port()

        if self.config.get("disabled-services"):
            context["disabled_services"] = self.config.get("disabled-services")

        run_command(["ifconfig", context["ext_iface"], "promisc", "up"], username="root")
        run_command(["ifconfig", context["data_iface"], "promisc", "up"], username="root")

        # validate context
        for k, v in context.iteritems():
            if v is None:
                raise ValueError("Option %s must be set in config" % k)
        self.context = context
        return self.context

    def _get_libs_from_pip(self):
        libs = self.config.get("libs-from-git")
        if not libs:
            return None
        libs_list = libs.split()
        if len(libs_list) == 0:
            return None
        ret = {"as_string": "", "packages": []}
        names = []
        for i in libs_list:
            lib_name_and_branch = i.split("|")
            if len(lib_name_and_branch) == 2:
                name, branch = lib_name_and_branch
            else:
                name = lib_name_and_branch[0]
                branch = self.config.get('zuul-branch') 
            names.append(name)
            ret["packages"].append({"name": self._sanitize_package_name(name), "branch": branch})
        ret["as_string"] = " ".join(names)
        return ret

    def _sanitize_package_name(self, name):
        if name.startswith("python-"):
            return "-".join(name.split("-")[1:])
        return name

    def _install_pip(self):
        get_pip = "/tmp/get-pip.py"
        response = urllib2.urlopen("https://bootstrap.pypa.io/get-pip.py")
        html = response.read()
        with open(get_pip, "wb") as fd:
            fd.write(html)
        os.chmod(get_pip, 0o755)
        run_command([get_pip, ], username="root")

    def _set_pip_mirror(self):
        pypi_mirror = self.config.get("pypi-mirror")
        if pypi_mirror is None:
            return
        # generate config
        config = ConfigParser.RawConfigParser()
        config.add_section('global')
        config.set('global', 'index-url', pypi_mirror)
        # create pip folder
        home = self.pwd.pw_dir
        pip_dir = os.path.join(home, ".pip")
        if os.path.isdir(pip_dir) is False:
            os.makedirs(pip_dir, 0o755)
            os.chown(pip_dir, self.pwd.pw_uid, self.pwd.pw_gid)
        pip_conf = os.path.join(pip_dir, "pip.conf")
        # write pip config
        with open(pip_conf, "wb") as fd:
            config.write(fd)
        return True

    def _run_stack_sh(self):
        devstack = self._devstack_location()
        unstack = os.path.join(devstack, "unstack.sh")
        stack = os.path.join(devstack, "stack.sh")
        args = [
            unstack,
        ]
        try:
            run_command(args, username=self.username)
        except Exception as err:
            hookenv.log("Error running unstack: %s" % err)
        subprocess.check_call(
            [
                "chown", "%s:%s" % (self.username, self.username),
                "-R", "/opt"
            ])
        args = [
            stack,
        ]
        run_command(args, username=self.username)

    def _assign_interfaces(self):
        PHY_BR = "br-%s" % self.context["data_iface"]
        assign_ext_port = [
            "ovs-vsctl", "--", "--may-exist", "add-port", EXT_BR, self.context["ext_iface"],
        ]
        run_command(assign_ext_port, username="root")

        assign_data_port = [
            "ovs-vsctl", "--", "--may-exist", "add-port", PHY_BR, self.context["data_iface"],
        ]
        run_command(assign_data_port, username="root")
        return None

    def _write_keystonerc(self):
        location = os.path.join(self.pwd.pw_dir, "keystonerc")
        tpl = KEYSTONERC % self.password
        with open(location, "wb") as fd:
            fd.write(tpl)

    def _set_active(self):
        args = ["status-set", "active"]
        subprocess.check_call(args)

    def _download_images(self):
        # download_file
        test_images_list = heat_images = []
        test_images = self.config.get("test-image-url")
        heat_images = self.config.get("heat-image-url")
        if test_images:
            test_images_list = test_images.split(",")
        if heat_images:
            heat_images_list = heat_images.split(",")
        test_images_list.extend(heat_images_list)

        dst_folder = os.path.join(self._devstack_location(), "files", "images")
        if os.path.isdir(dst_folder) is False:                                        
            os.path.makedirs(img, 0o755)

        for i in test_images_list:
            if i.startswith("http") is False:
                continue
            url = urlparse.urlparse(i)
            name = os.path.basename(url.path)
            destination = os.path.join(dst_folder, name)
            if os.path.isfile(destination):
                continue
            download_file(i, destination)
        subprocess.check_call(
            [
                "chown", "%s:%s" % (self.username, self.username),
                "-R", dst_folder
            ])
    
    def _clone_extra_repos(self):
        repos = self.config.get("extra-repos")
        if repos is None:
            return
        r = repos.split()
        for i in r:
            url, rev, dst = i.split("|")
            hookenv.log("Cloning repository %s (%s) to %s" % (url, rev, dst))
            parent = os.path.dirname(dst)
            if os.path.isdir(parent) is False:
                os.makedirs(parent, 0o755)
                os.chown(parent, self.pwd.pw_uid, self.pwd.pw_gid)
            args = ["git", "clone", url, dst]
            run_command(args, username=self.username)
            args = ["git", "checkout", rev]
            run_command(args, username=self.username, cwd=dst)

    def run(self):
        self._install_pip()
        self._set_pip_mirror()
        self._clone_devstack()
        #self._clone_extra_repos()
        self._render_localconf(self.context)
        self._render_local_sh(self.context)
        if self.prep_project:
            self.project.run()
        self._run_stack_sh()
        self._assign_interfaces()
        self._write_keystonerc()
        self._download_images()
        self._set_active()
