#!/usr/bin/env python3
"""Safely restore Creality probing and remove the retired Axis Twist extra.

No calibration, homing, motion, SAVE_CONFIG, or remote writes are sent here.
The shell entry point performs the protected restart only after this succeeds.
"""

import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import urllib.request


HERE = Path(__file__).resolve().parent
STOCK = HERE / "stock"
# Full OTA-extracted hashes, not prefixes or firmware-version guesses.
WRAPPERS = {
    "0dfd58494d4a580f07e0e0b349ee4531": (
        "1.1.3.13", "a662e0acf57f630986bc73503c13d8af8666308e995a07e57ff2c2b766d94a6c",
        "27415070c0beff9e38aa53491d1e4f2f4f3a2f20d498e59e641de06db199cc1b"),
    "c6878561b7b13c2023df7faebf90934b": (
        "1.1.5.2", "d790528fcd18afac76e6da887e93bbf06d356afd595c4756b2a6f7e7c8890de5",
        "46ffcf8f330fd0ce1253aaca0d8d77c1f88207008f9ee436345e7dc9c2b49674"),
    "d020e2a1db363c46f4ace6a9aa8c82b5": (
        "1.1.5.5", "177f2cd0aeefb292b6c1da3d13b1d42ed2a29d30beb752f40f826345de7a870f",
        "d6917fc49e31088096151291d89c0f69292362bbc8d36ac16ef8f767d1cad0a4"),
}
PRTOUCH_SHA = "e3b6eaa7c1c0aaa2ee237c5ca0ac170cff2b92f95a2c26ce646819bc813c20dc"
# Released repository probe helpers; unknown operator edits are not overwritten.
ATC_PROBES = {
    "960489c443ea6ec64754cb927861d12fbf0a5f6af4b5081597d905bbddd49c67",
    "565a073e77c45563dbdec52f730168c0b58ad52e5399355db743d37f6b574160",
    "ca49afa9daea990f93eb6dfb1a35805f9310f9c7bc027a6445821a04fa6bf1a8",
    "1ff8560215c90a1cbe8f99dab3886660963aafd51ff29e220fb2f8c5ec38239f",
}
NATIVE_NAME = "'axis_twist_compensation', prtouch"
PATCHED_NAME = "'k2_prtouch_axis_twist_status', prtouch"
LEGACY_COMMENT = "    # K2-Improvements supplies the full axis-twist object when this optional feature is installed."
SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*(?:[#;].*)?$")
INCLUDE = re.compile(r"^\s*\[include\s+([^\]]+)\]\s*(?:[#;].*)?$", re.I)


def canonical(data):
    return data.replace(b"\r\n", b"\n")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def exists(path):
    return os.path.lexists(str(path))


def legacy_present(config_dir, klipper_dir):
    config_dir, extras = Path(config_dir), Path(klipper_dir) / "klippy/extras"
    for path in (config_dir / "custom/axis_twist_compensation.cfg",
                 extras / "axis_twist_compensation.py", extras / "axis_twist_compensation.pyc"):
        if exists(path):
            return True
    if list((extras / "__pycache__").glob("axis_twist_compensation.*.pyc")):
        return True
    probe = extras / "probe.py"
    if probe.is_symlink() and "axis_twist_compensation" in os.readlink(str(probe)):
        return True
    if probe.exists() and sha(canonical(probe.read_bytes())) in ATC_PROBES:
        return True
    registration = extras / "prtouch_v3.py"
    if registration.exists():
        text = registration.read_bytes().decode("utf-8")
        if PATCHED_NAME in text or LEGACY_COMMENT in text:
            return True
    try:
        texts, unused = configs_and_cartographer(config_dir)
    except (OSError, ValueError):
        texts = {path: path.read_bytes().decode("utf-8") for path in
                 (config_dir / "printer.cfg", config_dir / "custom/main.cfg") if path.is_file()}
    return any(re.search(r"(?mi)^\s*(?:#\*#\s*)?\[axis_twist_compensation\]\s*$", text)
               for text in texts.values())


def beneath(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def lexical(path):
    # Normalize '..' without following a managed ATC symlink into the repo.
    return Path(os.path.abspath(str(path)))


def stock_probe(extras):
    wrapper = extras / "prtouch_v3_wrapper.cpython-39.so"
    try:
        raw = wrapper.read_bytes()
    except OSError as error:
        raise ValueError("Cannot identify the PR Touch wrapper; nothing changed. Reflash matching stock firmware; do not guess a probe.py.") from error
    digest = hashlib.md5(raw).hexdigest()
    entry = WRAPPERS.get(digest)
    if entry is None or sha(raw) != entry[1]:
        raise ValueError("Unknown PR Touch wrapper hash %s; nothing changed. Reflash matching stock firmware; do not guess a probe.py." % digest)
    version, unused, expected = entry
    data = canonical((STOCK / version / "probe.py").read_bytes())
    if sha(data) != expected:
        raise ValueError("Bundled stock probe.py failed integrity verification")
    return version, digest, data


def clean_config(text):
    """Remove only ATC sections (active or SAVE_CONFIG), retain every other line."""
    output = []
    in_atc = False
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        saved = stripped.startswith("#*#")
        body = stripped[3:].lstrip() if saved else stripped
        match = SECTION.match(body.rstrip("\r\n"))
        if match:
            in_atc = match.group(1).strip().casefold() == "axis_twist_compensation"
        if not in_atc:
            output.append(line)
    return "".join(output)


def configs_and_cartographer(config_dir):
    """Read active includes, including ordinary managed links into the repo.

    The plan separately rejects any required edit through a link/outside the
    config directory; unrelated managed feature configs are read, not written.
    """
    pending = [config_dir / "printer.cfg"]
    # main.cfg may remain as a partial legacy install even if its include is gone.
    if exists(config_dir / "custom/main.cfg"):
        pending.append(config_dir / "custom/main.cfg")
    texts = {}
    cartographer = False
    atc_link = config_dir / "custom/axis_twist_compensation.cfg"
    while pending:
        path = lexical(pending.pop())
        if path == lexical(atc_link) or path in texts:
            continue
        text = path.read_bytes().decode("utf-8")
        texts[path] = text
        for line in text.splitlines():
            header = SECTION.match(line)
            if header and re.match(r"cartographer(?:\s|$)", header.group(1).strip(), re.I):
                cartographer = True
            match = INCLUDE.match(line)
            if not match:
                continue
            name = match.group(1).strip()
            target = path.parent / name
            if lexical(target) == lexical(atc_link):
                continue
            matches = glob.glob(str(target))
            if not matches and not glob.has_magic(name):
                raise ValueError("Included configuration is missing: %s" % target)
            pending.extend(Path(item) for item in matches)
    return texts, cartographer


def clean_includes(text, path, atc_link):
    output = []
    for line in text.splitlines(keepends=True):
        body = line.lstrip()
        # Remove active and commented exact includes, not wildcard includes.
        if body.startswith("#") and not body.startswith("#*#"):
            body = body[1:].lstrip()
        match = INCLUDE.match(body.rstrip("\r\n"))
        if match and lexical(path.parent / match.group(1).strip()) == lexical(atc_link):
            continue
        output.append(line)
    return "".join(output)


def restored_prtouch(extras):
    native = canonical((STOCK / "prtouch_v3.py").read_bytes())
    if sha(native) != PRTOUCH_SHA:
        raise ValueError("Bundled PR Touch registration failed integrity verification")
    path = extras / "prtouch_v3.py"
    backup = extras / "prtouch_v3.py.k2-axis-twist.bak"
    current = canonical(path.read_bytes())
    text = current.decode("utf-8")
    native_text = native.decode("utf-8")
    registration = "    config.get_printer().add_object(" + NATIVE_NAME + ")"
    reverted = text.replace(PATCHED_NAME, NATIVE_NAME)
    if LEGACY_COMMENT in reverted:
        reverted = reverted.replace(LEGACY_COMMENT, registration)
    if canonical(reverted.encode()) != native:
        raise ValueError("Unrecognized prtouch_v3.py changes; nothing changed")
    if exists(backup):
        original = backup.read_bytes()
        if canonical(original) != native:
            raise ValueError("PR Touch backup is not the verified stock registration; nothing changed")
        return original
    if current == native:
        return path.read_bytes()
    # Stock and backup-less current/legacy registration patches are supported.
    return native_text.encode("utf-8")


def plan_removal(config_dir, klipper_dir):
    config_dir = Path(config_dir).absolute()
    extras = Path(klipper_dir).absolute() / "klippy/extras"
    if (extras / "__pycache__").is_symlink():
        raise ValueError("Refusing bytecode cleanup through a symlinked cache directory")
    version, wrapper_hash, desired_probe = stock_probe(extras)
    texts, cartographer = configs_and_cartographer(config_dir)
    if cartographer:
        old = b"self.use_offsets = False"
        if desired_probe.count(old) != 1:
            raise ValueError("Stock Cartographer XY-offset patch cannot be verified")
        desired_probe = desired_probe.replace(old, b"self.use_offsets = True", 1)
    probe_path = extras / "probe.py"
    dangling_atc = (probe_path.is_symlink() and not probe_path.exists()
                    and os.readlink(str(probe_path)).replace("\\", "/").endswith(
                        "/features/axis_twist_compensation/probe.py"))
    current_probe = None if dangling_atc else canonical(probe_path.read_bytes())
    accepted = {sha(canonical((STOCK / version / "probe.py").read_bytes())), sha(desired_probe)} | ATC_PROBES
    if not dangling_atc and sha(current_probe) not in accepted:
        raise ValueError("Unrecognized probe.py changes; nothing changed. Restore matching stock firmware first.")
    driver_path = extras / "prtouch_v3.py"
    driver_before = snapshot(driver_path)
    desired_prtouch = restored_prtouch(extras)
    if snapshot(driver_path) != driver_before:
        raise ValueError("PR Touch registration changed during preflight; nothing changed")
    replacements = {}
    for path, data in ((probe_path, desired_probe), (extras / "prtouch_v3.py", desired_prtouch)):
        # Break feature symlinks; never replace their repository targets.
        if path.is_symlink() or path.read_bytes() != data:
            replacements[path] = data
    atc_link = config_dir / "custom/axis_twist_compensation.cfg"
    if atc_link.exists():
        for line in atc_link.read_bytes().decode("utf-8").splitlines():
            header = SECTION.match(line)
            if header and header.group(1).strip().casefold() != "axis_twist_compensation":
                raise ValueError("ATC config contains another section; separate it before removing the config link")
    for path, text in texts.items():
        new = clean_config(clean_includes(text, path, atc_link))
        if new != text:
            if not beneath(path, config_dir) or path.is_symlink():
                raise ValueError("Refusing a required config edit outside the config directory or through a symlink: %s" % path)
            replacements[path] = new.encode("utf-8")
    removals = [path for path in (atc_link, extras / "axis_twist_compensation.py") if exists(path)]
    # Stock bytecode will be recreated on restart; its presence alone does not
    # mean ATC is still installed or require another removal/restart.
    modules = ["axis_twist_compensation"]
    if replacements or removals:
        modules += ["probe", "prtouch_v3"]
    for module in modules:
        paths = [extras / (module + ".pyc")]
        paths += list((extras / "__pycache__").glob(module + ".*.pyc"))
        removals.extend(path for path in paths if exists(path))
    touched = list(replacements) + list(dict.fromkeys(removals))
    expected = {path: snapshot(path) for path in touched}
    if driver_path in expected and expected[driver_path] != driver_before:
        raise ValueError("PR Touch registration changed during preflight; nothing changed")
    for path, text in texts.items():
        if path in expected and expected[path]["data"] != text.encode("utf-8"):
            raise ValueError("Config changed during preflight; nothing changed: %s" % path)
    if probe_path in expected and expected[probe_path]["data"] is not None and canonical(expected[probe_path]["data"]) != current_probe:
        raise ValueError("Probe changed during preflight; nothing changed")
    return {"version": version, "wrapper_md5": wrapper_hash, "cartographer": cartographer,
            "config_dir": config_dir, "klipper_dir": Path(klipper_dir).absolute(), "replacements": replacements,
            "removals": list(dict.fromkeys(removals)), "expected": expected}


def safe_idle(url):
    endpoint = url.rstrip("/") + "/printer/objects/query?webhooks&print_stats&idle_timeout&configfile"
    with urllib.request.urlopen(endpoint, timeout=10) as response:
        status = json.load(response)["result"]["status"]
    if status.get("webhooks", {}).get("state") != "ready":
        raise ValueError("Klipper must be ready before removal")
    if status.get("print_stats", {}).get("state") not in ("standby", "complete", "cancelled", "error"):
        raise ValueError("Printer must be idle; a printing or paused job cannot be interrupted")
    if status.get("idle_timeout", {}).get("state") not in ("Idle", "Ready"):
        raise ValueError("Printer must finish its current operation before removal")
    configfile = status.get("configfile", {})
    if "save_config_pending" not in configfile or configfile["save_config_pending"]:
        raise ValueError("Save pending meshes/calibration with SAVE_CONFIG and wait for ready before removal")


def snapshot(path):
    if not exists(path):
        return {"data": None, "link": None, "mode": 0o644}
    link = os.readlink(str(path)) if path.is_symlink() else None
    data = path.read_bytes() if path.exists() else None
    return {"data": data, "link": link, "mode": stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644}


def atomic_write(path, data, mode=0o644):
    fd, temp = tempfile.mkstemp(prefix=".atc-restore-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp, mode)
        os.replace(temp, str(path))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def apply_plan(plan, before_commit=None):
    touched = list(plan["replacements"]) + plan["removals"]
    if not touched:
        return None
    originals = {path: snapshot(path) for path in touched}
    if originals != plan["expected"]:
        raise ValueError("A target changed since preflight; nothing changed")
    root = plan["config_dir"] / "atc-removal-backups"
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise ValueError("Backup directory must be a real directory inside printer config")
    root.mkdir(exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S-"), dir=str(root)))
    manifest = {key: plan[key] for key in ("version", "wrapper_md5", "cartographer")}
    manifest["files"] = []
    for index, (path, original) in enumerate(originals.items()):
        name = "%03d-%s" % (index, path.name)
        if original["data"] is not None:
            (backup / name).write_bytes(original["data"])
        manifest["files"].append({"path": str(path), "backup": name,
                                  "link": original["link"], "mode": original["mode"]})
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # Compare again after backups, before the first mutation.
    for path, original in originals.items():
        if snapshot(path) != original:
            raise ValueError("A target changed during backup; nothing changed: %s" % path)
    if before_commit is not None:
        before_commit()
    applied = []
    try:
        for path, data in plan["replacements"].items():
            atomic_write(path, data, originals[path]["mode"])
            applied.append(path)
        for path in plan["removals"]:
            path.unlink()
            applied.append(path)
        verified = plan_removal(plan["config_dir"], plan["klipper_dir"])
        if verified["replacements"] or verified["removals"]:
            raise ValueError("Restored stock files/config did not verify")
    except Exception as error:
        rollback_errors = []
        for path in reversed(applied):
            try:
                original = originals[path]
                if original["link"] is not None:
                    if exists(path):
                        path.unlink()
                    path.symlink_to(original["link"])
                elif original["data"] is not None:
                    atomic_write(path, original["data"], original["mode"])
                elif exists(path):
                    path.unlink()
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
        raise RuntimeError("Removal failed; backup: %s; rollback %s; do not home until recovery: %s" % (
            backup, "FAILED: " + "; ".join(rollback_errors) if rollback_errors else "completed", error)) from error
    print("I: ATC files and calibration preserved in %s" % backup)
    return backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", default=os.environ.get("PRINTER_CFG_DIR", "/mnt/UDISK/printer_data/config"))
    parser.add_argument("--klipper-dir", default=os.environ.get("KLIPPER_DIR", "/usr/share/klipper"))
    parser.add_argument("--url", default=os.environ.get("MOONRAKER_URL", "http://127.0.0.1:7125"))
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--apply", action="store_true")
    actions.add_argument("--check-only", action="store_true")
    actions.add_argument("--verify-only", action="store_true", help="file verification only, for installer detection")
    actions.add_argument("--legacy-present", action="store_true", help="read-only legacy artifact detection")
    args = parser.parse_args(argv)
    try:
        if args.legacy_present:
            return 0 if legacy_present(args.config_dir, args.klipper_dir) else 1
        plan = plan_removal(args.config_dir, args.klipper_dir)
        changed = bool(plan["replacements"] or plan["removals"])
        if args.verify_only:
            return 1 if changed else 0
        safe_idle(args.url)
        print("I: verified stock probe %s, wrapper MD5 %s, Cartographer=%s" % (
            plan["version"], plan["wrapper_md5"], plan["cartographer"]))
        if args.check_only:
            print("I: preflight passed; %d replacements, %d removals; nothing changed" % (
                len(plan["replacements"]), len(plan["removals"])))
            return 0
        if not changed:
            print("I: ATC is already removed; stock probing verified")
            return 3  # Shell entry point skips an unnecessary restart.
        apply_plan(plan, before_commit=lambda: safe_idle(args.url))
        print("I: stock probing restored; ATC removed; meshes and Z offsets retained")
        print("I: re-mesh and recheck global/material Z offsets before normal printing")
        return 0
    except Exception as error:
        print("E: ATC removal refused/failed: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
