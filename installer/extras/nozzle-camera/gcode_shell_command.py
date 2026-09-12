"""Minimal shell-command bridge for trusted, installer-owned K2 macros."""

import logging
import shlex
from subprocess import PIPE, Popen, TimeoutExpired


class ShellCommand:
    def __init__(self, config):
        self.name = config.get_name().split()[-1]
        self.gcode = config.get_printer().lookup_object("gcode")
        self.command = config.get("command")
        self.timeout = config.getfloat("timeout", 2.0, above=0.0)
        self.verbose = config.getboolean("verbose", True)
        self.gcode.register_mux_command(
            "RUN_SHELL_COMMAND",
            "CMD",
            self.name,
            self.cmd_RUN_SHELL_COMMAND,
            desc="Run a registered shell command",
        )

    cmd_RUN_SHELL_COMMAND_help = "Run a registered shell command"

    def cmd_RUN_SHELL_COMMAND(self, gcmd):
        params = gcmd.get("PARAMS", default="")
        try:
            argv = shlex.split(self.command)
            if params:
                argv.extend(shlex.split(params))
        except ValueError as exc:
            raise gcmd.error("Bad shell command: %s" % (exc,))

        try:
            process = Popen(argv, stdout=PIPE, stderr=PIPE)
        except Exception as exc:
            raise gcmd.error("Unable to start shell command: %s" % (exc,))

        try:
            stdout, stderr = process.communicate(timeout=self.timeout)
        except TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            raise gcmd.error("Shell command timed out after %.1f seconds" % self.timeout)

        out = (stdout or b"").decode("utf-8", errors="replace").strip()
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        if self.verbose and out:
            gcmd.respond_info(out)
        if self.verbose and err:
            gcmd.respond_info(err)
        if process.returncode:
            logging.warning(
                "shell command %s exited with %d", self.name, process.returncode
            )
            raise gcmd.error(
                "Shell command %s failed with exit code %d"
                % (self.name, process.returncode)
            )


def load_config_prefix(config):
    return ShellCommand(config)
