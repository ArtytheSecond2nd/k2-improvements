#!/bin/sh
# Install the optional live editor for saved Cartographer Touch-model Z offsets.

set -eu

SCRIPT_DIR="$(readlink -f "$(dirname "$0")")"
INSTALLER_BASE="${INSTALLER_DIR:-/mnt/UDISK/k2-improvements}"
CFG_DIR="${PRINTER_CFG_DIR:-/mnt/UDISK/printer_data/config}"
CUSTOM="$CFG_DIR/custom"
KLIPPER_EXTRAS="${KLIPPER_DIR:-${HOME}/klipper}/klippy/extras"
FLUIDD_ROOT="${FLUIDD_DIR:-/usr/share/fluidd}"
FLUIDD_ARCHIVE="$SCRIPT_DIR/fluidd-v1.37.4.zip"
FLUIDD_VERSION=v1.37.4
FLUIDD_OVERLAY_VERSION=2
PYTHON="${K2_PYTHON:-python3}"

[ -d "$CUSTOM" ] || { echo "ERROR: $CUSTOM not found — install macros first"; exit 1; }
[ -d "$KLIPPER_EXTRAS" ] || { echo "ERROR: $KLIPPER_EXTRAS not found — Klipper is required"; exit 1; }
grep -q '^\[cartographer\]' "$CFG_DIR/printer.cfg" "$CUSTOM"/*.cfg 2>/dev/null || {
    echo "ERROR: no [cartographer] section found — install Cartographer first"
    exit 1
}

install_fluidd_dialog() {
    [ -f "$FLUIDD_ARCHIVE" ] || {
        echo "ERROR: bundled Fluidd UI archive is missing: $FLUIDD_ARCHIVE"
        exit 1
    }
    [ -d "$FLUIDD_ROOT" ] || {
        echo "ERROR: Fluidd is not installed at $FLUIDD_ROOT"
        exit 1
    }
    command -v unzip >/dev/null 2>&1 || {
        echo "ERROR: unzip is required; install the Fluidd core component first"
        exit 1
    }

    fluidd_target="$(readlink -f "$FLUIDD_ROOT")"
    case "$fluidd_target" in
        ''|'/'|"$HOME")
            echo "ERROR: refusing unsafe Fluidd target: $fluidd_target"
            exit 1
            ;;
    esac

    if [ "$(cat "$fluidd_target/global-touch-offsets-support.txt" 2>/dev/null || true)" = "$FLUIDD_OVERLAY_VERSION" ]; then
        echo "I: Fluidd Global Carto Touch Z Offsets dialog is already installed"
        return
    fi

    installed_version="$(cat "$fluidd_target/.version" 2>/dev/null || true)"
    [ "$installed_version" = "$FLUIDD_VERSION" ] || {
        echo "ERROR: Global Carto Touch Z Offsets requires Jacob Fluidd $FLUIDD_VERSION"
        echo "       Installed version: ${installed_version:-unknown}"
        echo "       Reinstall the Fluidd core component, then try again."
        exit 1
    }

    staging="${fluidd_target}.global-touch-offsets.$$"
    replaced="${fluidd_target}.replaced.$$"
    backup="${fluidd_target}.before-global-touch-offsets"
    mkdir -p "$staging"
    cleanup_fluidd_swap() {
        if [ -e "$replaced" ] && [ ! -e "$fluidd_target" ]; then
            mv "$replaced" "$fluidd_target"
        fi
        rm -rf "$staging"
        if [ -e "$fluidd_target" ]; then
            rm -rf "$replaced"
        fi
    }
    trap cleanup_fluidd_swap EXIT INT TERM
    unzip -oq "$FLUIDD_ARCHIVE" -d "$staging"
    [ "$(cat "$staging/.version" 2>/dev/null || true)" = "$FLUIDD_VERSION" ] &&
        [ -f "$staging/index.html" ] &&
        [ -f "$staging/sw.js" ] &&
        [ "$(cat "$staging/global-touch-offsets-support.txt" 2>/dev/null || true)" = "$FLUIDD_OVERLAY_VERSION" ] || {
            echo "ERROR: bundled Fluidd UI failed validation"
            exit 1
        }

    if [ ! -e "$backup" ]; then
        cp -a "$fluidd_target" "$backup"
        echo "I: backed up Fluidd to $backup"
    fi

    mv "$fluidd_target" "$replaced"
    if ! mv "$staging" "$fluidd_target"; then
        mv "$replaced" "$fluidd_target"
        echo "ERROR: could not activate the Fluidd Global Carto Touch Z Offsets dialog"
        exit 1
    fi
    rm -rf "$replaced"
    trap - EXIT INT TERM

    if [ "${K2_SKIP_NGINX_RESTART:-0}" != "1" ]; then
        /etc/init.d/nginx restart
    fi
    echo "I: installed the Fluidd Global Carto Touch Z Offsets dialog"
}

install_fluidd_dialog

ln -sfn "$SCRIPT_DIR/global_touch_offsets.cfg" "$CUSTOM/global_touch_offsets.cfg"
ln -sfn "$SCRIPT_DIR/k2_cartographer_offset_editor.py" \
    "$KLIPPER_EXTRAS/k2_cartographer_offset_editor.py"
"$PYTHON" "$INSTALLER_BASE/scripts/ensure_included.py" \
    "$CUSTOM/main.cfg" global_touch_offsets.cfg

if ! "$PYTHON" "$SCRIPT_DIR/configure_fluidd_layout.py"; then
    echo "W: editor installed, but its Fluidd category metadata could not be configured"
fi

echo "I: optional Global Carto Touch Z Offsets editor installed"
if [ "${K2_SKIP_KLIPPY_RESTART:-0}" != "1" ]; then
    sh "$INSTALLER_BASE/scripts/klippy_code_restart.sh"
fi
