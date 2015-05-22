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
            ['apt-get', 'install', '-y', 'python-pip', 'git'])
        subprocess.check_call(['pip', 'install', 'charmhelpers'])
