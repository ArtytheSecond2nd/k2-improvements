#!/usr/bin/env python3

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


WRAPPER = Path(__file__).resolve().parent / "bin" / "supervisorctl"


def shell_path(path):
    path = Path(path).resolve()
    if os.name != "nt":
        return str(path)
    return f"/{path.drive[0].lower()}{path.as_posix()[2:]}"


def find_shell():
    shell = shutil.which("sh")
    if shell:
        return shell
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    candidate = program_files / "Git" / "usr" / "bin" / "sh.exe"
    return str(candidate) if candidate.exists() else None


class SupervisorctlWrapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = WRAPPER.read_text(encoding="utf-8")

    def test_discovery_does_not_depend_on_moonraker(self):
        self.assertNotIn("moonraker.pid", self.script)
        self.assertNotIn("moonraker_conf", self.script)
        self.assertIn('for script_path in "$INIT_DIR"/*', self.script)

    def test_status_path_does_not_spawn_per_service_commands(self):
        status_helpers = "\n".join(
            re.search(
                rf"{name}\(\) \{{(.*?)\n\}}", self.script, re.DOTALL
            ).group(1)
            for name in (
                "cache_running_processes",
                "set_process_name",
                "is_running",
                "print_process_status",
                "print_all_service_statuses",
            )
        )
        for command in ("cat ", "pidof ", "awk ", "sed ", "tr ", "ls ", "head "):
            self.assertNotIn(command, status_helpers)
        self.assertNotRegex(status_helpers, r"\$\(")

    def test_discovery_deduplicates_service_script_aliases(self):
        self.assertIn('service="${service%_service}"', self.script)
        self.assertIn('seen_services="$seen_services$service "', self.script)

    def test_klipper_uses_its_real_process_name(self):
        self.assertRegex(self.script, r"klipper\) process_name=klippy ;;")

    def test_procfs_fallback_is_lazy_for_pid_file_services(self):
        main = re.search(r"main\(\) \{(.*?)\n\}", self.script, re.DOTALL).group(1)
        self.assertNotIn("cache_running_processes", main)
        self.assertIn(
            '[ "$running_processes_cached" -eq 1 ] || cache_running_processes',
            self.script,
        )

    def test_status_discovers_services_without_a_moonraker_pid(self):
        shell = find_shell()
        if not shell:
            self.skipTest("no POSIX shell is available")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            init_dir = root / "init.d"
            run_dir = root / "run"
            proc_dir = root / "proc"
            init_dir.mkdir()
            run_dir.mkdir()
            (proc_dir / "101").mkdir(parents=True)
            (proc_dir / "202").mkdir()

            for service in ("duplicate", "duplicate_service", "foo", "klipper"):
                (init_dir / service).write_bytes(b"#!/bin/sh\n")
            (proc_dir / "101" / "comm").write_bytes(b"foo\n")
            (proc_dir / "202" / "comm").write_bytes(b"unrelated\n")
            (run_dir / "klippy.pid").write_bytes(b"202\n")

            environment = os.environ.copy()
            environment.update(
                {
                    "SUPERVISORCTL_INIT_DIR": shell_path(init_dir),
                    "SUPERVISORCTL_RUN_DIR": shell_path(run_dir),
                    "SUPERVISORCTL_PROC_DIR": shell_path(proc_dir),
                }
            )
            result = subprocess.run(
                [shell, shell_path(WRAPPER), "status"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )

        statuses = {
            service: state
            for service, state in re.findall(r"^(\S+)\s+(RUNNING|STOPPED)$", result.stdout, re.MULTILINE)
        }
        self.assertEqual(statuses["foo"], "RUNNING", result.stdout)
        self.assertEqual(statuses["klipper"], "RUNNING", result.stdout)
        self.assertEqual(statuses["duplicate"], "STOPPED")
        self.assertEqual(result.stdout.count("duplicate"), 1)

    def test_installer_reloads_moonraker_and_honors_deferred_restart(self):
        installer = (WRAPPER.parent.parent / "install.sh").read_text(encoding="utf-8")
        self.assertIn("/etc/init.d/moonraker restart", installer)
        restart_position = installer.index("/etc/init.d/moonraker restart")
        wait_position = installer.index("nc -z 127.0.0.1 7125")
        defer_position = installer.index("K2_DEFER_FIRMWARE_RESTART:-0")
        self.assertLess(restart_position, wait_position)
        self.assertLess(wait_position, defer_position)
        self.assertIn('[ "$new_moonraker_pid" != "$old_moonraker_pid" ]', installer)
        self.assertIn("K2_DEFER_FIRMWARE_RESTART:-0", installer)


if __name__ == "__main__":
    unittest.main()
