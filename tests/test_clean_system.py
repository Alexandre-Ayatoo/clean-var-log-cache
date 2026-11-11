"""Tests isolés : aucun accès aux vrais logs, caches ou commandes de nettoyage."""

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import call, patch

SPEC = importlib.util.spec_from_file_location(
    "clean_system", Path(__file__).resolve().parents[1] / "clean-system.py"
)
clean = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clean)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = io.StringIO()
        self.redirect = contextlib.ExitStack()
        self.redirect.enter_context(contextlib.redirect_stdout(self.output))
        self.redirect.enter_context(contextlib.redirect_stderr(self.output))
        self.addCleanup(self.redirect.close)

    def file(self, name, days=40):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old log\n")
        timestamp = time.time() - days * 86400
        os.utime(path, (timestamp, timestamp))
        return path

    def cleaner(self, *args):
        return clean.Cleaner(clean.parse_args(list(args)))

    def test_simulation_does_not_change_files(self):
        target = self.file("app.log.1.gz")
        before = target.stat()
        cleaner = self.cleaner("--verbose")
        cleaner.scan(self.root, 14, logs=True)
        self.assertEqual(cleaner.files, 1)
        self.assertEqual(target.read_bytes(), b"old log\n")
        self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)

    def test_only_old_recognized_rotations_are_deleted(self):
        removed = [self.file(name) for name in (
            "app.log.1", "syslog.2.gz", "nginx/access.log.12.zst",
            "app.log-20260101.xz", "dmesg.0", "weird ' \n.log.1")]
        kept = [self.file(name, days) for name, days in (
            ("app.log", 40), ("syslog", 40), ("backup.gz", 40),
            ("app.log.2", 1), ("unknown.123", 40), ("wtmp", 40),
            ("journal/test.log.1", 40), ("private/test.log.1", 40),
            ("nested/audit/audit.log.1", 40), ("zabbix/agent.log.1", 40))]
        cleaner = self.cleaner("--apply")
        cleaner.scan(self.root, 14, logs=True)
        self.assertTrue(all(not item.exists() for item in removed))
        self.assertTrue(all(item.exists() for item in kept))
        self.assertEqual(cleaner.files, len(removed))

    def test_exclusion_includes_subdirectories(self):
        kept = self.file("nginx/nested/access.log.1")
        deleted = self.file("app.log.1")
        cleaner = self.cleaner("--apply", "--exclude", str(self.root / "nginx"))
        cleaner.scan(self.root, 14, logs=True)
        self.assertTrue(kept.exists())
        self.assertFalse(deleted.exists())

    def test_symlinks_and_hardlinks_are_preserved(self):
        external = self.file("outside/target.log.1")
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "alias.log.1").symlink_to(external)
        (logs / "directory").symlink_to(external.parent, target_is_directory=True)
        os.link(external, logs / "hard.log.1")
        self.cleaner("--apply").scan(logs, 14, logs=True)
        self.assertTrue(external.exists())
        self.assertTrue((logs / "alias.log.1").is_symlink())
        self.assertTrue((logs / "hard.log.1").exists())

    def test_symlink_in_root_path_is_rejected(self):
        target = self.file("real/subdir/app.log.1")
        (self.root / "link").symlink_to(self.root / "real", target_is_directory=True)
        cleaner = self.cleaner("--apply")
        cleaner.scan(self.root / "link/subdir", 14, logs=True)
        self.assertEqual(cleaner.errors, 1)
        self.assertTrue(target.exists())

    def test_man_cache_respects_age(self):
        old = self.file("index.db")
        recent = self.file("recent.db", 1)
        self.cleaner("--apply").scan(self.root, 30)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_foreign_device_is_not_traversed(self):
        target = self.file("mount/app.log.1")
        original = os.stat

        def other_device(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == "mount":
                values = list(info)
                values[2] = info.st_dev + 1
                return os.stat_result(values)
            return info

        with patch.object(clean.os, "stat", side_effect=other_device):
            self.cleaner("--apply").scan(self.root, 14, logs=True)
        self.assertTrue(target.exists())

    def test_file_changed_after_scan_is_preserved(self):
        target = self.file("app.log.1")
        original = os.stat
        calls = 0

        def changed(path, *args, **kwargs):
            nonlocal calls
            if path == target.name:
                calls += 1
                if calls == 2:
                    target.write_bytes(b"new contents")
            return original(path, *args, **kwargs)

        with patch.object(clean.os, "stat", side_effect=changed):
            cleaner = self.cleaner("--apply")
            cleaner.scan(self.root, 14, logs=True)
        self.assertTrue(target.exists())
        self.assertEqual(cleaner.files, 0)

    def test_native_commands_never_run_in_preview(self):
        with patch.object(clean.shutil, "which", return_value="/usr/bin/journalctl"), \
                patch.object(clean.subprocess, "run") as run:
            self.cleaner().command("journalctl", "--vacuum-time=14d")
        run.assert_not_called()

    def test_native_command_failure_and_timeout_are_reported(self):
        for failure in (subprocess.CalledProcessError(1, "apt-get"),
                        subprocess.TimeoutExpired("apt-get", 300)):
            with self.subTest(failure=failure), \
                    patch.object(clean.shutil, "which", return_value="/usr/bin/apt-get"), \
                    patch.object(clean.subprocess, "run", side_effect=failure) as run:
                cleaner = self.cleaner("--apply")
                cleaner.command("apt-get", "clean")
                self.assertEqual(cleaner.errors, 1)
                self.assertNotIn("shell", run.call_args.kwargs)
                self.assertEqual(run.call_args.kwargs["timeout"], 300)

    def test_lock_prevents_parallel_execution(self):
        original = os.fstat

        def owned(fd):
            values = list(original(fd))
            values[4] = 0
            return os.stat_result(values)

        with patch.object(clean, "LOCK_PATH", str(self.root / "lock")), \
                patch.object(clean.os, "fstat", side_effect=owned):
            with clean.execution_lock():
                with self.assertRaisesRegex(OSError, "déjà en cours"):
                    with clean.execution_lock():
                        self.fail("double verrou accepté")

    def test_invalid_arguments(self):
        for argv in (("--days", "0"), ("--days", "-1"), ("--days", "x"),
                     ("--only", "logs,"), ("--only", "unknown"),
                     ("--exclude", "relative"), ("--exclude", "/var/log/../cache"),
                     ("--apply", "--dry-run")):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as error:
                clean.parse_args(argv)
            self.assertEqual(error.exception.code, 2)

    def test_root_required_before_any_action(self):
        with patch.object(clean.sys, "platform", "linux"), \
                patch.object(clean.os, "geteuid", return_value=1000), \
                patch.object(clean.Cleaner, "run") as run:
            self.assertEqual(clean.main(["--apply"]), 1)
        run.assert_not_called()

    def test_selected_categories_and_retention(self):
        with patch.object(clean.Cleaner, "command") as command, \
                patch.object(clean.Cleaner, "scan") as scan:
            self.cleaner("--only", "journal,tmp", "--journal-days", "30").run()
        scan.assert_not_called()
        self.assertEqual(command.call_args_list, [
            call("journalctl", "--vacuum-time=30d"),
            call("systemd-tmpfiles", "--clean", "--prefix=/tmp", "--prefix=/var/tmp")])


if __name__ == "__main__":
    unittest.main()
