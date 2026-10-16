"""Exercise removal menus/restart handoff with shell stubs, never a printer."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASH = shutil.which("bash") or "C:/Program Files/Git/bin/bash.exe"


@unittest.skipUnless(Path(BASH).is_file(), "bash required")
class RemovalShellTests(unittest.TestCase):
    def run_shell(self, script, **env):
        return subprocess.run([BASH, "-c", script], capture_output=True, timeout=20,
                              env=dict(os.environ, INSTALLER_DIR=ROOT.as_posix(), **env))

    def test_wrapper_restarts_only_after_changed_files_not_failure_or_noop(self):
        script = r'''
set -eu
fixture_python() { printf 'PYTHON:%s\n' "$*"; return "$RESULT"; }
sh() { printf 'RESTART:%s\n' "$1"; return "$RESTART_RESULT"; }
export K2_PYTHON=fixture_python
. "$0"
'''
        for result, restart, expected in ((0, 0, 0), (1, 0, 1), (3, 0, 0), (0, 1, 1)):
            with self.subTest(result=result, restart=restart):
                run = subprocess.run([BASH, "-c", script, (HERE / "uninstall.sh").as_posix()],
                                     capture_output=True, timeout=10,
                                     env=dict(os.environ, INSTALLER_DIR=ROOT.as_posix(), RESULT=str(result),
                                              RESTART_RESULT=str(restart)))
                self.assertEqual(run.returncode, expected, run.stderr.decode())
                output = run.stdout.decode()
                self.assertIn("remove_axis_twist.py --apply", output)
                self.assertEqual("klippy_code_restart.sh" in output, result == 0)

    def test_extras_uninstall_requires_confirmation_and_marks_only_success(self):
        script = r'''
set -eu
. "$INSTALLER_DIR/installer/menus/extras.sh"
has_legacy_axis_twist() { return 0; }
clear() { :; }
ui_heading() { :; }
show_feature_readme() { :; }
press_enter() { :; }
warn() { printf 'WARN:%s\n' "$1"; }
confirm() { [ "$CONFIRM" = yes ]; }
sh() { printf 'ACTION:%s\n' "$1"; return "$RESULT"; }
migration_mark_component_current() { printf 'MARK:%s\n' "$1"; }
run_axis_twist_removal
'''
        for confirm, result in (("no", 0), ("yes", 0), ("yes", 1)):
            with self.subTest(confirm=confirm, result=result):
                run = self.run_shell(script, CONFIRM=confirm, RESULT=str(result))
                output = run.stdout.decode()
                self.assertEqual("ACTION:" in output, confirm == "yes")
                self.assertEqual("MARK:axis-twist-removal" in output, confirm == "yes" and result == 0)
                self.assertEqual(run.returncode, 1 if confirm == "yes" and result else 0, run.stderr.decode())

    def test_absent_atc_does_not_open_confirmation_or_run_uninstall(self):
        script = r'''
set -eu
. "$INSTALLER_DIR/installer/menus/extras.sh"
has_legacy_axis_twist() { return 1; }
info() { printf 'INFO:%s\n' "$1"; }
press_enter() { :; }
clear() { printf 'UNEXPECTED_CLEAR\n'; }
show_feature_readme() { printf 'UNEXPECTED_README\n'; }
confirm() { printf 'UNEXPECTED_CONFIRM\n'; return 0; }
sh() { printf 'UNEXPECTED_UNINSTALL\n'; }
migration_mark_component_current() { printf 'UNEXPECTED_MARK\n'; }
run_axis_twist_removal
'''
        run = self.run_shell(script)
        self.assertEqual(run.returncode, 0, run.stderr.decode())
        self.assertIn("nothing to remove", run.stdout.decode())
        self.assertNotIn("UNEXPECTED_", run.stdout.decode())

    def menu_fixture(self):
        script = r'''
set -eu
. "$INSTALLER_DIR/installer/menus/extras.sh"
clear() { :; }
ui_heading() { :; }
ui_menu_item() { printf 'ITEM:%s:%s\n' "$1" "$2"; }
extra_state() { printf 'STATE'; }
carto_plate_workflow_state() { printf 'STATE'; }
c_yellow() { printf '%s' "$1"; }
state_not_installed() { printf 'STATE'; }
is_cartographer() { [ "$CARTO" = yes ]; }
is_nozzle_usb_cartographer() { return 1; }
has_legacy_axis_twist() { [ "$LEGACY" = yes ]; }
info() { printf 'INFO:%s\n' "$1"; }
press_enter() { :; }
show_feature_readme() { printf 'UNEXPECTED_README\n'; }
confirm() { printf 'UNEXPECTED_CONFIRM\n'; return 0; }
sh() { printf 'UNEXPECTED_UNINSTALL\n'; }
migration_mark_component_current() { printf 'UNEXPECTED_MARK\n'; }
reads=0
read_prompt() {
    reads=$((reads + 1))
    if [ "$STALE" = yes ] && [ "$reads" -eq 1 ]; then
        LEGACY=no
        c=4
    else
        c=0
    fi
}
menu_extras
'''
        return script

    def test_menu_hides_absent_atc_on_both_probe_setups(self):
        for carto in ("no", "yes"):
            for legacy in ("no", "yes"):
                with self.subTest(carto=carto, legacy=legacy):
                    run = self.run_shell(self.menu_fixture(), CARTO=carto, LEGACY=legacy, STALE="no")
                    self.assertEqual(run.returncode, 0, run.stderr.decode())
                    output = run.stdout.decode()
                    self.assertEqual("ITEM:4:Remove legacy Axis Twist" in output, legacy == "yes")
                    self.assertIn("ITEM:3:KAMP adaptive purge", output)
                    self.assertIn("ITEM:7:Material Z Offsets", output)
                    self.assertNotIn("UNEXPECTED_", output)

    def test_stale_menu_selection_after_removal_does_not_run_uninstall(self):
        for carto in ("no", "yes"):
            with self.subTest(carto=carto):
                run = self.run_shell(self.menu_fixture(), CARTO=carto, LEGACY="yes", STALE="yes")
                self.assertEqual(run.returncode, 0, run.stderr.decode())
                output = run.stdout.decode()
                self.assertEqual(output.count("ITEM:4:Remove legacy Axis Twist"), 1)
                self.assertIn("nothing to remove", output)
                self.assertNotIn("UNEXPECTED_", output)

    def test_new_install_actions_and_old_upgrade_entries_are_gone(self):
        extras = (ROOT / "installer/menus/extras.sh").read_text(encoding="utf-8")
        update = (ROOT / "installer/menus/update.sh").read_text(encoding="utf-8")
        catalog = (ROOT / "installer/migrations/catalog.sh").read_text(encoding="utf-8")
        self.assertNotIn("features/axis_twist_compensation/install.sh", extras + update)
        self.assertNotIn("|axis_twist_compensation|", catalog)
        self.assertIn("axis-twist-stock-restoration-v1|axis-twist-removal|", catalog)
        self.assertFalse((ROOT / "features/axis_twist_compensation/install.sh").exists())

    def test_existing_runtime_link_targets_are_retained_unchanged(self):
        # Git blob IDs from the last release before install retirement. Protect
        # existing links and loaded ATC behavior, not just the uninstall menu.
        blobs = {
            "probe.py": "b240272fcda9c1571850c9b6dcb60e9ca1239bfe",
            "axis_twist_compensation.py": "a89a767f4ca8c9500637deedd4a9fa6e66d7fdfa",
            "axis_twist_compensation.cfg": "829aaca393361a21a4b252a1512e990fe5ad5611",
        }
        for name, expected in blobs.items():
            data = (ROOT / "features/axis_twist_compensation" / name).read_bytes().replace(b"\r\n", b"\n")
            blob = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
            self.assertEqual(hashlib.sha1(blob).hexdigest(), expected, name)

    def test_successful_extras_removal_disappears_on_next_menu_draw(self):
        script = self.menu_fixture().replace(
            'sh() { printf \'UNEXPECTED_UNINSTALL\\n\'; }',
            'sh() { printf \'UNINSTALL\\n\'; LEGACY=no; }',
        ).replace(
            'show_feature_readme() { printf \'UNEXPECTED_README\\n\'; }',
            'show_feature_readme() { :; }',
        ).replace(
            'confirm() { printf \'UNEXPECTED_CONFIRM\\n\'; return 0; }',
            'confirm() { return 0; }',
        ).replace(
            'migration_mark_component_current() { printf \'UNEXPECTED_MARK\\n\'; }',
            'migration_mark_component_current() { printf \'MARK:%s\\n\' "$1"; }',
        ).replace(
            '[ "$STALE" = yes ] && [ "$reads" -eq 1 ]',
            '[ "$reads" -eq 1 ]',
        ).replace('        LEGACY=no\n', '')
        for carto in ("no", "yes"):
            run = self.run_shell(script, CARTO=carto, LEGACY="yes", STALE="no")
            self.assertEqual(run.returncode, 0, run.stderr.decode())
            output = run.stdout.decode()
            self.assertEqual(output.count("ITEM:4:Remove legacy Axis Twist"), 1)
            self.assertEqual(output.count("ITEM:3:KAMP adaptive purge"), 2)
            self.assertEqual(output.count("UNINSTALL"), 1)
            self.assertIn("MARK:axis-twist-removal", output)
            self.assertNotIn("UNEXPECTED_", output)

    def test_apply_all_keeps_atc_while_updating_other_components(self):
        script = r'''
set -eu
. "$INSTALLER_DIR/installer/menus/update.sh"
has_legacy_axis_twist() { return 0; }
is_cartographer() { [ "$CARTO" = yes ]; }
migration_catalog() {
    printf 'macros-update|macros|is_macros|Macros\n'
    printf 'atc-remove|axis-twist-removal|is_axis_twist_removed|Remove ATC\n'
}
migration_component_installed() { [ "$1" = macros ]; }
migration_require_idle() { return 0; }
migration_component_label() { printf '%s' "$1"; }
migration_repair_component() { printf 'REPAIR:%s\n' "$1"; }
migration_reconcile_fluidd_layout() { return 0; }
migration_mark_component_current() { printf 'MARK:%s\n' "$1"; }
sh() { printf 'RESTART:%s\n' "$1"; }
warn() { printf 'WARN:%s\n' "$1"; }
c_green() { printf '%s' "$1"; }
migration_pending_components > "$PLAN"
# Include a stale uninstall row as defense in depth.
printf 'axis-twist-removal\n' >> "$PLAN"
migration_apply_components "$PLAN"
'''
        for carto in ("no", "yes"):
            with tempfile.TemporaryDirectory(prefix="k2-atc-apply-all-") as directory:
                run = self.run_shell(script, CARTO=carto, PLAN=(Path(directory) / "plan").as_posix(),
                                     MIGRATION_STATE_DIR=directory, PRINTER_CFG_DIR=directory)
            self.assertEqual(run.returncode, 0, run.stderr.decode())
            output = run.stdout.decode()
            self.assertIn("REPAIR:macros", output)
            self.assertIn("MARK:macros", output)
            self.assertIn("klippy_code_restart.sh", output)
            self.assertNotIn("REPAIR:axis-twist-removal", output)
            self.assertNotIn("MARK:axis-twist-removal", output)
            self.assertNotIn("uninstall.sh", output)

    def test_removal_is_never_recommended_even_with_legacy_snapshot(self):
        script = r'''
set -eu
. "$INSTALLER_DIR/installer/menus/update.sh"
has_legacy_axis_twist() { [ "$LEGACY" = yes ]; }
is_axis_twist_removed() { [ "$RESTORED" = yes ]; }
is_cartographer() { return 0; }
migration_catalog() {
    printf 'carto-update|cartographer|is_cartographer|Cartographer\n'
    printf 'atc-remove|axis-twist-removal|is_axis_twist_removed|Remove ATC\n'
}
migration_pending_components
printf 'ENTRIES\n'
migration_pending_entries
'''
        with tempfile.TemporaryDirectory(prefix="k2-atc-migration-") as directory:
            # Include the ID written by the previous release's pre-pull snapshot.
            (Path(directory) / "installed-before-update").write_text("axis-twist-removal\n")
            for legacy in ("no", "yes"):
                run = self.run_shell(script, LEGACY=legacy, RESTORED="yes" if legacy == "no" else "no",
                                     PRINTER_CFG_DIR=directory, MIGRATION_STATE_DIR=directory)
                self.assertEqual(run.returncode, 0, run.stderr.decode())
                self.assertEqual(run.stdout.decode().splitlines(),
                                 ["cartographer", "ENTRIES", "carto-update|cartographer|Cartographer"])

    def test_old_partial_install_capture_and_completion_require_restoration(self):
        script = r'''
set -eu
. "$INSTALLER_DIR/installer/menus/update.sh"
has_legacy_axis_twist() { [ "$LEGACY" = yes ]; }
is_axis_twist_removed() { [ "$RESTORED" = yes ]; }
warn() { printf 'WARN:%s\n' "$1"; }
migration_catalog() { printf 'atc-remove|axis-twist-removal|is_axis_twist_removed|Remove ATC\n'; }
migration_capture_installed_components
printf 'CAPTURE:'
cat "$MIGRATION_INSTALLED_SNAPSHOT"
if migration_mark_component_current axis-twist-removal; then printf 'MARKED\n'; else printf 'PENDING\n'; fi
'''
        for legacy, restored in (("yes", "no"), ("no", "yes")):
            with tempfile.TemporaryDirectory(prefix="k2-atc-capture-") as directory:
                run = self.run_shell(script, LEGACY=legacy, RESTORED=restored,
                                     PRINTER_CFG_DIR=directory, MIGRATION_STATE_DIR=directory)
                self.assertEqual(run.returncode, 0, run.stderr.decode())
                output = run.stdout.decode()
                if legacy == "yes":
                    self.assertNotIn("CAPTURE:axis-twist-removal", output)
                    self.assertIn("PENDING", output)
                else:
                    self.assertNotIn("CAPTURE:axis-twist-removal", output)
                    self.assertIn("MARKED", output)

    def test_other_repairs_do_not_require_legacy_atc_removal(self):
        script = r'''
set -eu
. "$INSTALLER_DIR/installer/menus/update.sh"
has_legacy_axis_twist() { return 0; }
warn() { printf 'WARN:%s\n' "$1"; }
awk() { printf '/fixture/root\n'; }
sh() { printf 'INSTALL:%s\n' "$1"; }
migration_repair_component macros
'''
        run = self.run_shell(script)
        self.assertEqual(run.returncode, 0, run.stderr.decode())
        self.assertIn("features/macros/install.sh", run.stdout.decode())
        self.assertNotIn("Remove legacy Axis Twist first", run.stdout.decode())
        self.assertNotIn("axis-twist-removal/uninstall.sh", run.stdout.decode())

    def test_direct_migration_repair_cannot_uninstall_atc(self):
        script = r'''
set -eu
. "$INSTALLER_DIR/installer/menus/update.sh"
warn() { printf 'WARN:%s\n' "$1"; }
sh() { printf 'UNEXPECTED_INSTALL:%s\n' "$1"; }
migration_repair_component axis-twist-removal
'''
        run = self.run_shell(script)
        self.assertEqual(run.returncode, 1, run.stderr.decode())
        self.assertIn("ATC removal is optional", run.stdout.decode())
        self.assertNotIn("UNEXPECTED_", run.stdout.decode())

    def test_stale_removal_plan_is_ignored_without_restart(self):
        script = r'''
set -eu
. "$INSTALLER_DIR/installer/menus/update.sh"
migration_require_idle() { return 0; }
migration_component_label() { printf '%s' "$1"; }
migration_repair_component() { printf 'REPAIR:%s\n' "$1"; return 1; }
warn() { printf 'WARN:%s\n' "$1"; }
sh() { printf 'UNEXPECTED_RESTART:%s\n' "$1"; }
migration_apply_components "$PLAN"
'''
        with tempfile.TemporaryDirectory(prefix="k2-atc-failed-batch-") as directory:
            plan = Path(directory) / "plan"
            plan.write_bytes(b"axis-twist-removal\n")
            run = self.run_shell(script, PLAN=plan.as_posix(), MIGRATION_STATE_DIR=directory)
        self.assertEqual(run.returncode, 1, run.stderr.decode())
        self.assertIn("Skipping optional ATC removal", run.stdout.decode())
        self.assertNotIn("REPAIR:", run.stdout.decode())
        self.assertNotIn("UNEXPECTED_RESTART", run.stdout.decode())


if __name__ == "__main__":
    unittest.main()
