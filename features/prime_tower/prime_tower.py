# First-layer footprint discovery for adaptive mesh and purge placement.
#
# EXCLUDE_OBJECT_DEFINE polygons do not necessarily include brims, supports,
# skirts, or a prime tower. This module reads the selected G-code's complete
# first-layer extrusion footprint and publishes one conservative rectangle
# for other Klipper components to consume before printing begins.
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging
import math
import os
import re
import threading


_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_TOWER_MARKER_BYTES_RE = re.compile(
    br"(?im)^[ \t]*;[ \t]*TYPE[ \t]*:[ \t]*Prime[ \t]+tower[ \t]*\r?$"
)
_NO_SPARSE_BYTES_RE = re.compile(
    br"(?im)^[ \t]*;[ \t]*wipe_tower_no_sparse_layers[ \t]*="
    br"[ \t]*(?:1|true)[ \t]*(?:;[^\r\n]*)?\r*$"
)
_TOWER_ENABLED_BYTES_RE = re.compile(
    br"(?im)^[ \t]*;[ \t]*enable_prime_tower[ \t]*="
    br"[ \t]*(?:1|true)[ \t]*(?:;[^\r\n]*)?\r*$"
)
_TOWER_ENABLED_PRESENT_BYTES_RE = re.compile(
    br"(?im)^[ \t]*;[ \t]*enable_prime_tower[ \t]*="
    br"[ \t]*(?:0|1|true|false)[ \t]*(?:;[^\r\n]*)?\r*$"
)
_MARKER_SCAN_CHUNK = 1024 * 1024
_MARKER_SCAN_OVERLAP = 512
_METADATA_TAIL_SIZE = 1024 * 1024
_DETAILED_CANCEL_INTERVAL = 4096
_START_PRINT_PREFIX_SIZE = 1024 * 1024
_START_PRINT_LINE_RE = re.compile(
    r"(?im)^[ \t]*START_PRINT\b([^\r\n;]*)")
_START_PRINT_PARAM_RE = re.compile(
    r"(?:^|\s)(BED_TEMP|CHAMBER_TEMP)\s*=\s*(%s)" % _NUMBER,
    re.IGNORECASE)

_NO_SPARSE_BLOCK_REASON = (
    "Prime-tower safety: Creality Print 'No sparse layers (beta)' is "
    "enabled. On the K2 Plus, a delayed tower can raise a partially "
    "printed model into the toolhead or X rail. Disable that setting, "
    "reslice, and resend this file."
)


class _ScanCancelled(Exception):
    pass


class _UnsupportedPrimeTower(Exception):
    pass


class _ScanJob:
    def __init__(self, cache_key, path, started_at, timeout):
        self.cache_key = cache_key
        self.path = path
        self.started_at = started_at
        self.deadline = started_at + timeout
        self.cancel_event = threading.Event()
        self.done_event = threading.Event()
        self.status = None
        self.error = None
        self.block_reason = None


def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise _ScanCancelled()


def _finite_point(point):
    return point[0] is not None and point[1] is not None \
        and math.isfinite(point[0]) and math.isfinite(point[1])


def _comment_type(line):
    """Return a normalized TYPE value for a standalone byte comment."""
    comment = line.lstrip()
    if not comment.startswith(b";"):
        return None
    comment = comment[1:].strip().lower()
    if not comment.startswith(b"type"):
        return None
    value = comment[4:].lstrip()
    if not value.startswith(b":"):
        return None
    return value[1:].strip()


def _command_number(code):
    """Return (command letter, number, parameter offset), if supported."""
    if not code:
        return None
    command_letter = code[:1].upper()
    if command_letter not in (b"G", b"M"):
        return None
    index = 1
    while index < len(code) and 48 <= code[index] <= 57:
        index += 1
    if index == 1:
        return None
    # Preserve the old regex's word-boundary behavior for malformed input.
    if index < len(code) and code[index] not in b" \t;\r\n":
        return None
    return command_letter, int(code[1:index]), index


def _motion_parameters(code, offset):
    """Return supported motion parameters using a cheap token parser.

    Creality Print emits normal whitespace-delimited G-code. Supporting an
    axis letter separated from its value retains the flexibility of the old
    regular expressions without applying them to every motion line.
    """
    values = {}
    pending_axis = None
    for token in code[offset:].split():
        if pending_axis is not None:
            try:
                value = float(token)
            except ValueError:
                pending_axis = None
            else:
                values[pending_axis] = value
                pending_axis = None
                continue

        axis = token[:1].upper()
        if axis not in (b"X", b"Y", b"E", b"I", b"J", b"R", b"P"):
            continue
        if len(token) == 1:
            pending_axis = axis
            continue
        try:
            value = float(token[1:])
        except ValueError:
            continue
        values[axis] = value
    return values


def _is_layer_change(line):
    comment = line.lstrip()
    if not comment.startswith(b";"):
        return False
    marker = comment[1:].strip().lower().replace(b" ", b"_")
    return marker in (b"layer_change", b"change_layer")


def _directed_sweep(start_angle, end_angle, clockwise):
    if clockwise:
        return (start_angle - end_angle) % (2.0 * math.pi)
    return (end_angle - start_angle) % (2.0 * math.pi)


def _arc_geometry(old_x, old_y, new_x, new_y, values, clockwise):
    """Return (center_x, center_y, radius, start_angle, sweep), if valid."""
    if b"I" in values or b"J" in values:
        center_x = old_x + values.get(b"I", 0.0)
        center_y = old_y + values.get(b"J", 0.0)
        radius = math.hypot(old_x - center_x, old_y - center_y)
        if radius <= 0.0:
            return None
        start = math.atan2(old_y - center_y, old_x - center_x)
        end = math.atan2(new_y - center_y, new_x - center_x)
        sweep = _directed_sweep(start, end, clockwise)
        if abs(old_x - new_x) < 1e-9 and abs(old_y - new_y) < 1e-9:
            sweep = 2.0 * math.pi
    elif b"R" in values:
        signed_radius = values[b"R"]
        radius = abs(signed_radius)
        delta_x, delta_y = new_x - old_x, new_y - old_y
        chord = math.hypot(delta_x, delta_y)
        if radius <= 0.0 or chord <= 0.0 or chord > 2.0 * radius:
            return None
        mid_x, mid_y = (old_x + new_x) / 2.0, (old_y + new_y) / 2.0
        offset = math.sqrt(max(0.0, radius * radius - chord * chord / 4.0))
        perpendicular_x = -delta_y / chord
        perpendicular_y = delta_x / chord
        candidates = []
        for sign in (-1.0, 1.0):
            candidate_x = mid_x + sign * perpendicular_x * offset
            candidate_y = mid_y + sign * perpendicular_y * offset
            start = math.atan2(old_y - candidate_y, old_x - candidate_x)
            end = math.atan2(new_y - candidate_y, new_x - candidate_x)
            sweep = _directed_sweep(start, end, clockwise)
            candidates.append((candidate_x, candidate_y, start, sweep))
        want_major = signed_radius < 0.0
        matching = [candidate for candidate in candidates
                    if (candidate[3] > math.pi) == want_major]
        center_x, center_y, start, sweep = (matching or candidates)[0]
    else:
        return None

    repeats = max(1, int(values.get(b"P", 1.0)))
    if repeats > 1:
        sweep += (repeats - 1) * 2.0 * math.pi
    return center_x, center_y, radius, start, sweep


def _arc_extrema(old_x, old_y, new_x, new_y, values, clockwise):
    points = [(old_x, old_y), (new_x, new_y)]
    geometry = _arc_geometry(
        old_x, old_y, new_x, new_y, values, clockwise)
    if geometry is None:
        return points
    center_x, center_y, radius, start, sweep = geometry
    if sweep >= 2.0 * math.pi - 1e-9:
        cardinals = range(4)
    else:
        cardinals = [index for index in range(4)
                     if _directed_sweep(start, index * math.pi / 2.0,
                                        clockwise) <= sweep + 1e-9]
    for index in cardinals:
        angle = index * math.pi / 2.0
        points.append((center_x + radius * math.cos(angle),
                       center_y + radius * math.sin(angle)))
    return points


def _file_contains_prime_tower(path, cancel_event=None):
    """Quickly reject files without a prime-tower type marker.

    This scan operates on large byte chunks so a normal single-color G-code
    does not pay the cost of decoding and applying several regular
    expressions to every motion line.  The overlap preserves markers split
    across read boundaries; a false positive only falls back to the detailed
    parser and is therefore safe.
    """
    overlap = b""
    with open(path, "rb") as handle:
        while True:
            _check_cancel(cancel_event)
            chunk = handle.read(_MARKER_SCAN_CHUNK)
            if not chunk:
                return False
            data = overlap + chunk
            if _TOWER_MARKER_BYTES_RE.search(data) is not None:
                return True
            overlap = data[-_MARKER_SCAN_OVERLAP:]


def _read_prime_tower_footer(path, cancel_event=None):
    """Read Creality Print's effective per-job tower settings."""
    _check_cancel(cancel_event)
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        file_size = handle.tell()
        handle.seek(max(0, file_size - _METADATA_TAIL_SIZE), os.SEEK_SET)
        metadata = handle.read()
    _check_cancel(cancel_event)
    return {
        "enabled": _TOWER_ENABLED_BYTES_RE.search(metadata) is not None,
        "no_sparse": _NO_SPARSE_BYTES_RE.search(metadata) is not None,
        "enabled_present":
            _TOWER_ENABLED_PRESENT_BYTES_RE.search(metadata) is not None,
    }


def _read_start_print_temperatures(path):
    """Read the sliced bed/chamber targets without scanning the whole file."""
    with open(path, "rb") as handle:
        prefix = handle.read(_START_PRINT_PREFIX_SIZE)
    text = prefix.decode("utf-8", errors="replace")
    line_match = _START_PRINT_LINE_RE.search(text)
    if line_match is None:
        return None
    temperatures = {}
    for name, raw_value in _START_PRINT_PARAM_RE.findall(
            line_match.group(1)):
        value = float(raw_value)
        if math.isfinite(value) and value >= 0.0:
            temperatures[name.upper()] = value
    if "BED_TEMP" not in temperatures:
        return None
    return temperatures


def parse_prime_tower(path, padding=0.5, cancel_event=None):
    """Return the complete first-layer positive-extrusion footprint.

    Startup purge is excluded by starting at the first layer marker. Brims,
    skirts, supports, models, and an enabled non-sparse prime tower are all
    included. Parsing stops at the second layer marker, so time no longer
    scales with the total print duration.
    """
    footer = _read_prime_tower_footer(path, cancel_event)
    # An explicitly disabled tower is safe even if the profile retains the
    # no-sparse option. An enabled no-sparse tower is rejected before parsing.
    if footer["enabled"] and footer["no_sparse"]:
        raise _UnsupportedPrimeTower(_NO_SPARSE_BLOCK_REASON)
    # If an older file says no-sparse but omits the effective tower setting,
    # preserve the previous fail-closed safety behavior. This compatibility
    # search is intentionally limited to the ambiguous legacy case.
    if footer["no_sparse"] and not footer["enabled_present"] and \
            _file_contains_prime_tower(path, cancel_event):
        raise _UnsupportedPrimeTower(_NO_SPARSE_BLOCK_REASON)

    absolute_xy = True
    absolute_e = True
    x_pos = None
    y_pos = None
    e_pos = 0.0
    in_first_layer = False
    layer_markers = 0
    tower_blocks = 0
    extrusion_moves = 0
    x_min = x_max = y_min = y_max = None

    with open(path, "rb") as handle:
        for line_number, raw_line in enumerate(handle):
            if line_number % _DETAILED_CANCEL_INTERVAL == 0:
                _check_cancel(cancel_event)
            line = raw_line.lstrip()
            if not line:
                continue
            if line.startswith(b";"):
                if _is_layer_change(line):
                    layer_markers += 1
                    if layer_markers == 1:
                        in_first_layer = True
                    else:
                        break
                    continue
                type_value = _comment_type(line)
                if in_first_layer and type_value == b"prime tower":
                    tower_blocks += 1
                continue

            comment_offset = line.find(b";")
            code = (line if comment_offset < 0 else
                    line[:comment_offset]).rstrip()
            if not code:
                continue
            command_info = _command_number(code)
            if command_info is None:
                continue
            command_letter, command_number, parameter_offset = command_info
            if command_letter == b"G" and command_number == 90:
                absolute_xy = True
                continue
            if command_letter == b"G" and command_number == 91:
                absolute_xy = False
                continue
            if command_letter == b"M" and command_number == 82:
                absolute_e = True
                continue
            if command_letter == b"M" and command_number == 83:
                absolute_e = False
                continue

            if command_letter != b"G" or command_number not in \
                    (0, 1, 2, 3, 92):
                continue
            values = _motion_parameters(code, parameter_offset)
            x_value = values.get(b"X")
            y_value = values.get(b"Y")
            e_value = values.get(b"E")
            if command_number == 92:
                if x_value is not None:
                    x_pos = x_value
                if y_value is not None:
                    y_pos = y_value
                if e_value is not None:
                    e_pos = e_value
                continue

            old_x, old_y = x_pos, y_pos
            new_x, new_y = x_pos, y_pos
            if x_value is not None:
                if absolute_xy or x_pos is None:
                    new_x = x_value
                else:
                    new_x = x_pos + x_value
            if y_value is not None:
                if absolute_xy or y_pos is None:
                    new_y = y_value
                else:
                    new_y = y_pos + y_value
            e_delta = 0.0
            if e_value is not None:
                e_delta = e_value - e_pos if absolute_e else e_value
                e_pos = e_value if absolute_e else e_pos + e_value
            x_pos, y_pos = new_x, new_y
            if in_first_layer and e_delta > 0.000001 and \
                    _finite_point((old_x, old_y)) and \
                    _finite_point((x_pos, y_pos)):
                extrusion_moves += 1
                points = [(old_x, old_y), (x_pos, y_pos)]
                if command_number in (2, 3):
                    points = _arc_extrema(
                        old_x, old_y, x_pos, y_pos, values,
                        clockwise=command_number == 2)
                for point_x, point_y in points:
                    x_min = point_x if x_min is None else min(x_min, point_x)
                    x_max = point_x if x_max is None else max(x_max, point_x)
                    y_min = point_y if y_min is None else min(y_min, point_y)
                    y_max = point_y if y_max is None else max(y_max, point_y)

    if layer_markers == 0:
        raise ValueError("first-layer marker was not found")

    if x_min is None:
        return {
            "detected": False,
            "polygon": [],
            "bounds": [],
            "blocks": tower_blocks,
            "moves": 0,
            "tower_enabled": footer["enabled"],
        }

    padding = max(0.0, float(padding))
    x_min -= padding
    x_max += padding
    y_min -= padding
    y_max += padding
    bounds = [x_min, y_min, x_max, y_max]
    return {
        "detected": True,
        "polygon": [
            [x_min, y_min], [x_max, y_min],
            [x_max, y_max], [x_min, y_max],
        ],
        "bounds": bounds,
        "blocks": tower_blocks,
        "moves": extrusion_moves,
        "tower_enabled": footer["enabled"] or tower_blocks > 0,
    }


class PrimeTower:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")
        self.padding = config.getfloat("padding", 0.5, minval=0.0)
        self.scan_timeout = config.getfloat(
            "scan_timeout", 120.0, minval=1.0)
        self.scan_timeout_per_mb = config.getfloat(
            "scan_timeout_per_mb", 10.0, minval=0.0)
        self._cache_key = None
        self._active_job = None
        self._status = self._empty_status()
        self.gcode.register_command(
            "PRIME_TOWER_WAIT", self.cmd_PRIME_TOWER_WAIT,
            desc="Wait cooperatively for first-layer footprint discovery")
        self.gcode.register_command(
            "KAMP_REPORT_MESH_BOUNDS", self.cmd_KAMP_REPORT_MESH_BOUNDS,
            desc="Report scan time and requested adaptive mesh bounds")
        register_event_handler = getattr(
            self.printer, "register_event_handler", None)
        if register_event_handler is not None:
            register_event_handler(
                "klippy:connect", self._install_cartographer_mesh_hook)

    def _install_cartographer_mesh_hook(self, *args):
        """Add the first-layer footprint to Cartographer's object list.

        Cartographer 3D owns BED_MESH_CALIBRATE when it is installed, so its
        adapter computes adaptive bounds without calling Klipper's native
        BedMeshCalibrate.set_adaptive_mesh().  Hook the adapter at connect
        time, after the Cartographer package is importable, while leaving the
        native bed_mesh integration in place for other probes.
        """
        try:
            from cartographer.adapters.klipper.bed_mesh import KlipperBedMesh
        except (ImportError, AttributeError):
            return
        if getattr(KlipperBedMesh, "_k2_prime_tower_hook", False):
            return

        original_get_objects = KlipperBedMesh.get_objects

        def get_objects_with_prime_tower(adapter):
            polygons = list(original_get_objects(adapter))
            tower = adapter.printer.lookup_object("prime_tower", None)
            if tower is None:
                return polygons
            eventtime = adapter.printer.get_reactor().monotonic()
            status = tower.wait_for_scan(eventtime)
            if status.get("blocked"):
                raise adapter.printer.command_error(status["block_reason"])
            if not status.get("detected"):
                return polygons
            polygon = [tuple(point) for point in status.get("polygon", [])]
            if polygon and polygon not in polygons:
                polygons.append(polygon)
                bounds = status.get("bounds", [])
                if len(bounds) == 4:
                    logging.info(
                        "prime_tower: Cartographer adaptive mesh includes "
                        "first-layer footprint X[%.3f, %.3f] Y[%.3f, %.3f]",
                        bounds[0], bounds[2], bounds[1], bounds[3])
            return polygons

        KlipperBedMesh.get_objects = get_objects_with_prime_tower
        KlipperBedMesh._k2_prime_tower_hook = True
        logging.info(
            "prime_tower: installed Cartographer adaptive-mesh integration")

    @staticmethod
    def _empty_status(source=None, error=None, ready=True,
                      blocked=False, block_reason=None):
        return {
            "detected": False,
            "polygon": [],
            "bounds": [],
            "blocks": 0,
            "moves": 0,
            "tower_enabled": False,
            "source": source,
            "error": error,
            "ready": ready,
            "blocked": blocked,
            "block_reason": block_reason,
            "mesh_bounds_reporting": True,
        }

    def _selected_path(self, eventtime):
        virtual_sdcard = self.printer.lookup_object("virtual_sdcard", None)
        if virtual_sdcard is None:
            return None
        try:
            return virtual_sdcard.get_status(eventtime).get("file_path")
        except Exception:
            logging.exception("prime_tower: unable to query virtual_sdcard")
            return None

    def _cancel_active_job(self):
        job = self._active_job
        if job is not None:
            job.cancel_event.set()
            self._active_job = None

    def _finish_scan(self, eventtime, job):
        if job is not self._active_job or not job.done_event.is_set():
            return
        self._active_job = None
        if job.cancel_event.is_set():
            return
        if job.block_reason is not None:
            logging.error(
                "prime_tower: blocked unsafe file %s: %s",
                job.path, job.block_reason)
            self._status = self._empty_status(
                job.path, blocked=True, block_reason=job.block_reason)
            return
        if job.error is not None:
            logging.error(
                "prime_tower: scan failed for %s: %s", job.path, job.error)
            self._status = self._empty_status(job.path, job.error)
            return
        status = job.status
        if status is None:
            error = "scan worker completed without a result"
            logging.error("prime_tower: %s for %s", error, job.path)
            self._status = self._empty_status(job.path, error)
            return
        status["source"] = job.path
        status["error"] = None
        status["ready"] = True
        status["blocked"] = False
        status["block_reason"] = None
        status["mesh_bounds_reporting"] = True
        self._status = status
        elapsed = max(0.0, eventtime - job.started_at)
        status["scan_duration"] = elapsed
        file_size = job.cache_key[1]
        # Publish on the reactor, once per completed job (not cached reads).
        # This measures scan startup through result publication, including
        # worker scheduling and callback/poll latency.
        try:
            tower_state = "prime tower enabled" if status.get(
                "tower_enabled") else "prime tower disabled or absent"
            footprint_state = "first-layer footprint detected" if status[
                "detected"] else "no first-layer extrusion detected"
            self.gcode.respond_info(
                "KAMP first-layer scan complete in %.3f seconds; %s; %s."
                % (elapsed, footprint_state, tower_state))
        except Exception:
            logging.exception("prime_tower: unable to report scan completion")
        if status["detected"]:
            logging.info(
                "prime_tower: detected %d first-layer extrusion moves "
                "(%d prime-tower blocks) at "
                "X[%.3f, %.3f] Y[%.3f, %.3f] in %s "
                "(%s bytes, %.3fs)",
                status.get("moves", 0), status["blocks"], status["bounds"][0],
                status["bounds"][2], status["bounds"][1],
                status["bounds"][3], job.path, file_size, elapsed)
        else:
            logging.info(
                "prime_tower: no first-layer extrusion detected in %s "
                "(%s bytes, %.3fs)",
                job.path, file_size, elapsed)

    def _scan_worker(self, job):
        cancelled = False
        try:
            job.status = parse_prime_tower(
                job.path, self.padding, job.cancel_event)
        except _ScanCancelled:
            cancelled = True
        except _UnsupportedPrimeTower as err:
            job.block_reason = str(err)
        except Exception as err:
            job.error = str(err)
        finally:
            job.done_event.set()
        if cancelled or job.cancel_event.is_set():
            return
        try:
            self.reactor.register_async_callback(
                lambda eventtime: self._finish_scan(eventtime, job))
        except Exception:
            logging.exception(
                "prime_tower: unable to publish scan result for %s; "
                "the reactor poll will recover it", job.path)

    def _report_scan_status(self):
        message = (
            "KAMP: scanning selected G-code first layer for complete print "
            "footprint...")
        try:
            self.gcode.respond_info(message)
        except Exception:
            logging.exception("prime_tower: unable to report scan status")

    def _hold_scan_temperatures(self, path):
        try:
            temperatures = _read_start_print_temperatures(path)
        except Exception:
            logging.exception(
                "prime_tower: unable to read START_PRINT temperatures from %s",
                path)
            return
        if temperatures is None:
            logging.warning(
                "prime_tower: START_PRINT bed target was not found in the "
                "first %d bytes of %s; leaving heaters unchanged",
                _START_PRINT_PREFIX_SIZE, path)
            return
        commands = [
            "M104 S140",
            "M140 S%.3f" % (temperatures["BED_TEMP"],),
        ]
        chamber_temp = temperatures.get("CHAMBER_TEMP", 0.0)
        if chamber_temp > 0.0:
            commands.append("M141 S%.3f" % (chamber_temp,))
        try:
            self.gcode.run_script_from_command("\n".join(commands))
        except Exception:
            # Temperature holding is a convenience during a potentially long
            # scan. It must never weaken the fail-open parser behavior.
            logging.exception(
                "prime_tower: unable to hold preheat temperatures while "
                "scanning %s", path)

    def _start_scan(self, cache_key, path, eventtime):
        self._cancel_active_job()
        self._cache_key = cache_key
        file_size = cache_key[1]
        size_timeout = 0.0
        if file_size is not None:
            size_timeout = (file_size / float(1024 * 1024)) * \
                self.scan_timeout_per_mb
        timeout = max(self.scan_timeout, size_timeout)
        job = _ScanJob(cache_key, path, eventtime, timeout)
        self._active_job = job
        self._status = self._empty_status(path, ready=False)
        self._report_scan_status()
        worker = threading.Thread(
            target=self._scan_worker,
            args=(job,),
            name="prime-tower-scan")
        worker.daemon = True
        try:
            worker.start()
        except Exception as err:
            error = "unable to start scan worker: %s" % (err,)
            logging.exception("prime_tower: %s for %s", error, path)
            job.cancel_event.set()
            self._active_job = None
            self._status = self._empty_status(path, error)

    def get_status(self, eventtime):
        path = self._selected_path(eventtime)
        if not path:
            self._cancel_active_job()
            self._cache_key = None
            self._status = self._empty_status()
            return dict(self._status)
        try:
            stat_result = os.stat(path)
            modified = getattr(stat_result, "st_mtime_ns", None)
            if modified is None:
                modified = int(stat_result.st_mtime * 1000000000)
            cache_key = (path, stat_result.st_size, modified)
        except OSError as err:
            cache_key = (path, None, None)
            if cache_key != self._cache_key or self._active_job is not None:
                logging.warning("prime_tower: cannot inspect %s: %s", path, err)
                self._cancel_active_job()
                self._cache_key = cache_key
                self._status = self._empty_status(path, str(err))
            return dict(self._status)

        if cache_key != self._cache_key:
            self._start_scan(cache_key, path, eventtime)
        elif self._active_job is not None:
            # This polling path also publishes a completed worker result if
            # register_async_callback() was unavailable during shutdown or
            # resource pressure.
            self._finish_scan(eventtime, self._active_job)
        return dict(self._status)

    def wait_for_scan(self, eventtime):
        """Wait for the selected-file scan while continuing reactor service."""
        status = self.get_status(eventtime)
        while not status.get("ready", True):
            job = self._active_job
            if job is None:
                return status
            # Prefer a result that completed at the deadline over a timeout.
            # This also makes callback-publication failure recover without
            # waiting for the next 50 ms reactor pause.
            if job.done_event.is_set():
                self._finish_scan(eventtime, job)
                return dict(self._status)
            if eventtime >= job.deadline:
                elapsed = max(0.0, eventtime - job.started_at)
                timeout = job.deadline - job.started_at
                error = "scan timed out after %.1fs" % (timeout,)
                logging.error(
                    "prime_tower: %s for %s (%s bytes, %.3fs elapsed)",
                    error, job.path, job.cache_key[1], elapsed)
                # Cancel the parser and detach this job. A late callback is
                # rejected by object identity, while the same selected file
                # retains this fail-open result instead of relaunching work.
                job.cancel_event.set()
                self._active_job = None
                self._status = self._empty_status(job.path, error)
                return dict(self._status)
            waketime = min(eventtime + 0.050, job.deadline)
            eventtime = self.reactor.pause(waketime)
            status = self.get_status(eventtime)
        return status

    def cmd_KAMP_REPORT_MESH_BOUNDS(self, gcmd):
        self.cmd_PRIME_TOWER_WAIT(gcmd)
        status = self._status
        exclude = self.printer.lookup_object("exclude_object", None)
        objects = exclude.get_status(self.reactor.monotonic()).get("objects", []) \
            if exclude is not None else []
        points = [point for obj in objects for point in obj.get("polygon", [])]
        # Match the Cartographer adapter hook: the complete first-layer
        # footprint is included even without exclude-object polygons.
        if status.get("detected"):
            points.extend(status.get("polygon", []))
        margin = gcmd.get_float("ADAPTIVE_MARGIN", minval=0.0)
        mesh_min = [float(v) for v in gcmd.get("MESH_MIN").split(",")]
        mesh_max = [float(v) for v in gcmd.get("MESH_MAX").split(",")]
        duration = status.get("scan_duration")
        timing = "%.3f seconds" % duration if duration is not None else "unavailable"
        if points:
            low = [min(p[i] for p in points) for i in (0, 1)]
            high = [max(p[i] for p in points) for i in (0, 1)]
            combined = "X[%.3f, %.3f] Y[%.3f, %.3f]" % (
                low[0], high[0], low[1], high[1])
            mesh_min = [max(mesh_min[i], low[i] - margin) for i in (0, 1)]
            mesh_max = [min(mesh_max[i], high[i] + margin) for i in (0, 1)]
        else:
            combined = "none; full configured mesh"
        gcmd.respond_info(
            "KAMP first-layer scan: file scan time %s; combined first-layer/"
            "object bounds %s; margin %.3f mm; requested mesh X[%.3f, %.3f] "
            "Y[%.3f, %.3f]." % (timing, combined, margin,
                mesh_min[0], mesh_max[0], mesh_min[1], mesh_max[1]))

    def cmd_PRIME_TOWER_WAIT(self, gcmd):
        eventtime = self.reactor.monotonic()
        status = self.get_status(eventtime)
        if not status.get("ready", True):
            # Creality Print begins the virtual-SD stream after file selection.
            # Its preamble resets the heater targets before START_PRINT invokes
            # this command, so apply the hold here, after those resets, rather
            # than when the background scan first starts.
            path = status.get("source")
            if path:
                self._hold_scan_temperatures(path)
            status = self.wait_for_scan(eventtime)
        if status.get("blocked"):
            try:
                self.gcode.run_script_from_command("TURN_OFF_HEATERS")
            except Exception:
                # Preserve the original hard-rejection reason even if the
                # printer's heater shutdown command itself reports a fault.
                logging.exception(
                    "prime_tower: unable to turn heaters off after rejecting "
                    "unsafe G-code")
            raise gcmd.error(status["block_reason"])
        if status.get("error"):
            gcmd.respond_info(
                "prime_tower: footprint scan failed; continuing without "
                "first-layer geometry: %s" % (status["error"],))


def load_config(config):
    return PrimeTower(config)
