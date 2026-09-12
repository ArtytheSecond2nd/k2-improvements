#!/usr/bin/env python3

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


HERE = pathlib.Path(__file__).parent
SCRIPT = HERE / "repository-refresh.sh"


def bash_path(path):
    value = pathlib.Path(path).resolve().as_posix()
    if os.name == "nt" and len(value) > 2 and value[1] == ":":
        return "/%s/%s" % (value[0].lower(), value[3:])
    return value


class RepositoryRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = shutil.which("bash")
        if not cls.bash and os.name == "nt":
            candidate = pathlib.Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
            if candidate.is_file():
                cls.bash = str(candidate)
        cls.git = shutil.which("git")
        if not cls.bash or not cls.git:
            raise unittest.SkipTest("bash and git are required")

    def git_run(self, *args, cwd=None):
        return subprocess.run(
            [self.git, *args], cwd=cwd, check=True,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()

    def commit_file(self, checkout, content, message):
        (checkout / "tracked.txt").write_text(content, encoding="utf-8")
        self.git_run("add", "tracked.txt", cwd=checkout)
        self.git_run(
            "-c", "user.name=Bootstrap Test", "-c", "user.email=test@example.invalid",
            "commit", "-m", message, cwd=checkout,
        )

    def run_refresh(self, remote, checkout, recovery):
        environment = os.environ.copy()
        if os.name == "nt":
            git_root = pathlib.Path(self.bash).parents[1]
            environment["PATH"] = os.pathsep.join((
                str(git_root / "usr" / "bin"),
                str(git_root / "mingw64" / "bin"),
                str(git_root / "cmd"),
                environment.get("PATH", ""),
            ))
        return subprocess.run(
            [
                self.bash,
                bash_path(SCRIPT),
                bash_path(remote),
                "main",
                bash_path(checkout),
                bash_path(recovery),
                "git",
            ],
            check=True,
            text=True,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        ).stdout

    def make_remote(self, root):
        remote = root / "remote.git"
        seed = root / "seed"
        self.git_run("init", "--bare", str(remote))
        self.git_run("clone", str(remote), str(seed))
        self.git_run("checkout", "-b", "main", cwd=seed)
        self.commit_file(seed, "one\n", "initial")
        self.git_run("push", "-u", "origin", "main", cwd=seed)
        return remote, seed

    def test_normal_fast_forward_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            remote, seed = self.make_remote(root)
            checkout = root / "checkout"
            recovery = root / "recovery"
            self.git_run("clone", "--branch", "main", str(remote), str(checkout))
            self.commit_file(seed, "two\n", "forward")
            self.git_run("push", cwd=seed)

            output = self.run_refresh(remote, checkout, recovery)

            self.assertIn("Fast-forward", output)
            self.assertEqual((checkout / "tracked.txt").read_text(), "two\n")
            self.assertFalse(recovery.exists())

    def test_diverged_history_is_replaced_after_clean_clone(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            remote, seed = self.make_remote(root)
            checkout = root / "checkout"
            recovery = root / "recovery"
            self.git_run("clone", "--branch", "main", str(remote), str(checkout))
            self.commit_file(checkout, "local edit\n", "local commit")
            (checkout / "tracked.txt").write_text("uncommitted edit\n", encoding="utf-8")
            (checkout / "untracked.txt").write_text("keep me\n", encoding="utf-8")
            self.commit_file(seed, "rewritten remote\n", "replacement")
            self.git_run("push", "--force", cwd=seed)

            output = self.run_refresh(remote, checkout, recovery)

            self.assertIn("bootstrap recovery", output)
            self.assertEqual((checkout / "tracked.txt").read_text(), "rewritten remote\n")
            backups = [path for path in recovery.iterdir() if path.name.startswith("files-before-refresh-")]
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0] / "tracked.txt").read_text(), "uncommitted edit\n")
            self.assertEqual((backups[0] / "untracked.txt").read_text(), "keep me\n")
            self.assertFalse((backups[0] / ".git").exists())

    def test_clean_checkout_recovers_from_rewritten_remote_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            remote, seed = self.make_remote(root)
            checkout = root / "checkout"
            recovery = root / "recovery"
            initial = self.git_run("rev-parse", "HEAD", cwd=seed)
            self.git_run("clone", "--branch", "main", str(remote), str(checkout))
            self.commit_file(seed, "old remote history\n", "old remote")
            self.git_run("push", cwd=seed)
            self.git_run("pull", "--ff-only", cwd=checkout)
            self.git_run("reset", "--hard", initial, cwd=seed)
            self.commit_file(seed, "clean rewritten history\n", "rewritten remote")
            self.git_run("push", "--force", cwd=seed)

            output = self.run_refresh(remote, checkout, recovery)

            self.assertIn("bootstrap recovery", output)
            self.assertEqual((checkout / "tracked.txt").read_text(), "clean rewritten history\n")
            self.assertEqual(list(recovery.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
