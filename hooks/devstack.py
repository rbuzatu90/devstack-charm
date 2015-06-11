import subprocess
import pwd
import os
import urlparse
import string
import ConfigParser
import urllib2
import shutil

from os import urandom
from itertools import islice, imap, repeat

from charmhelpers import fetch
from charmhelpers.core import hookenv, host, templating

from subprocess import PIPE


DEVSTACK_REPOSITORY = "https://git.openstack.org/openstack-dev/devstack"
UTC_TIMEZONE = "/usr/share/zoneinfo/UTC"
LOCALTIME = "/etc/localtime"
SUDOERSD = "/etc/sudoers.d"
STACK_LOCATION = "/opt/stack"
DEFAULT_USER = "ubuntu"
KEYSTONERC = """
export OS_USERNAME=admin
export OS_TENANT_NAME=admin
export OS_PASSWORD=%s
export OS_AUTH_URL=http://127.0.0.1:35357/v2.0/
"""


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


class Devstack(object):

    def __init__(self, username=DEFAULT_USER):
        self.username = username
        self.pwd = pwd.getpwnam(self.username)
        self.project = Project(username=self.username)
        self.config = hookenv.config()

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
        pass

    def _get_enable_plugin(self):
        plugins = []
        enable_plugins = self.config.get("enable-plugin")
        if not enable_plugins:
            return plugins
        lst = enable_plugins.split()
        for i in lst:
            plugin = i.split("|")
            if len(plugin) < 2 and len(plugin) > 3:
                raise Exception(
                    "Invalid plugin definition: must be name|url|gitref")
            if len(plugin) == 2:
                plugin.append("master")
            plugins.append(" ".join(plugin))
        return plugins

    def _get_context(self):
        context = {
            "devstack_ip": None,
            "enabled_services": None,
            "ml2_mechanism": None,
            "tenant_network_type": None,
            "enable_vlans": None,
            "enable_tunneling": None,
            "vlan_range": None,
            "public_interface": None,
            "guest_interface": None,
            "ceilometer_backend": None,
            "enable_live_migration": None,
            "password": None,
            "verbose": None,
            "debug": None,
            "test_image_url": None,
            "heat_image_url": None,
            "zuul_branch": None,
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
        context["enable_plugin"] = self._get_enable_plugin()

        # validate context
        for k, v in context.iteritems():
            if v is None:
                raise ValueError("Option %s must be set in config" % k)
        return context

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
        run_command(args, username=self.username)
        args = [
            stack,
        ]
        run_command(args, username=self.username)

    def _write_keystonerc(self):
        location = os.path.join(self.pwd.pw_dir, "keystonerc")
        tpl = KEYSTONERC % self.password
        with open(location, "wb") as fd:
            fd.write(tpl)

    def run(self):
        self._install_pip()
        self._set_pip_mirror()
        context = self._get_context()
        self._clone_devstack()
        self._render_localconf(context)
        self.project.run()
        self._run_stack_sh()
        self._write_keystonerc()
