#!/bin/sh
# Update the installer checkout, replacing it safely when a fast-forward is impossible.

set -eu

REPO_URL="$1"
BRANCH="$2"
INSTALLER_DIR="$3"
RECOVERY_ROOT="$4"
GIT_BIN="${5:-git}"
INSTALLER_PARENT="$(dirname "$INSTALLER_DIR")"

checkout_branch() {
    if "$GIT_BIN" -C "$INSTALLER_DIR" show-ref --verify --quiet "refs/heads/$BRANCH"; then
        "$GIT_BIN" -C "$INSTALLER_DIR" checkout "$BRANCH"
    else
        "$GIT_BIN" -C "$INSTALLER_DIR" checkout -b "$BRANCH" "origin/$BRANCH"
    fi
}

normal_update() {
    "$GIT_BIN" -C "$INSTALLER_DIR" remote set-url origin "$REPO_URL" &&
        "$GIT_BIN" -C "$INSTALLER_DIR" fetch origin "$BRANCH" &&
        checkout_branch &&
        "$GIT_BIN" -C "$INSTALLER_DIR" pull --ff-only origin "$BRANCH"
}

replace_checkout() {
    timestamp="$(date '+%Y%m%d-%H%M%S' 2>/dev/null || echo unknown-time)"
    temporary="$RECOVERY_ROOT/.checkout-$timestamp-$$"
    backup="$RECOVERY_ROOT/files-before-refresh-$timestamp-$$"

    mkdir -p "$RECOVERY_ROOT"
    rm -rf "$temporary"

    echo "I: cloning a clean $BRANCH checkout before replacing the existing repository."
    if ! "$GIT_BIN" clone --single-branch --branch "$BRANCH" \
        "$REPO_URL" "$temporary"; then
        rm -rf "$temporary"
        echo "E: clean checkout failed; the existing repository was not changed." >&2
        return 1
    fi

    local_changes="$("$GIT_BIN" -C "$INSTALLER_DIR" status --porcelain 2>/dev/null || echo unknown-state)"
    cd "$INSTALLER_PARENT"
    if ! mv "$INSTALLER_DIR" "$backup"; then
        rm -rf "$temporary"
        echo "E: could not move the existing checkout; nothing was replaced." >&2
        return 1
    fi
    if ! mv "$temporary" "$INSTALLER_DIR"; then
        mv "$backup" "$INSTALLER_DIR" 2>/dev/null || true
        rm -rf "$temporary"
        echo "E: could not activate the clean checkout; the existing checkout was restored." >&2
        return 1
    fi

    if [ -n "$local_changes" ]; then
        if ! rm -rf "$backup/.git"; then
            echo "E: clean checkout installed, but old Git metadata remains at $backup/.git" >&2
            return 1
        fi
        echo "I: previous local files were preserved without Git history at $backup"
    else
        rm -rf "$backup"
        echo "I: clean $BRANCH checkout installed; no local file backup was needed."
    fi
}

mkdir -p "$INSTALLER_PARENT"

if [ ! -d "$INSTALLER_DIR/.git" ]; then
    echo "I: cloning k2-improvements..."
    "$GIT_BIN" clone --single-branch --branch "$BRANCH" "$REPO_URL" "$INSTALLER_DIR"
    exit 0
fi

echo "I: k2-improvements already exists; updating existing repo."
if normal_update; then
    exit 0
fi

echo "W: normal fast-forward update failed; starting bootstrap recovery."
replace_checkout
