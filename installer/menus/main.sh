#!/bin/sh
# Top-level workflow menu. Sourced by menu.sh.

detect_installer_branch() {
    if [ -d "$INSTALLER_DIR/.git" ]; then
        git -C "$INSTALLER_DIR" symbolic-ref --quiet --short HEAD 2>/dev/null || echo 'detached'
    else
        echo 'not a git checkout'
    fi
}

detect_installer_commit() {
    if [ -d "$INSTALLER_DIR/.git" ]; then
        git -C "$INSTALLER_DIR" rev-parse --short=12 HEAD 2>/dev/null || echo 'unknown'
    else
        echo 'not a git checkout'
    fi
}

detect_remote_commit_state() {
    local branch local_commit remote_commit output_file status_file pid elapsed
    if [ ! -d "$INSTALLER_DIR/.git" ]; then
        echo unavailable
        return
    fi
    branch=$(git -C "$INSTALLER_DIR" symbolic-ref --quiet --short HEAD 2>/dev/null || true)
    local_commit=$(git -C "$INSTALLER_DIR" rev-parse --verify HEAD 2>/dev/null || true)
    if [ -z "$branch" ] || [ -z "$local_commit" ]; then
        echo unavailable
        return
    fi

    # Keep an offline printer from delaying the menu indefinitely. This is a
    # read-only remote-head query; option 6 remains responsible for pulling.
    output_file="/tmp/k2-installer-remote-head.$$"
    status_file="/tmp/k2-installer-remote-status.$$"
    rm -f "$output_file" "$status_file"
    (
        GIT_TERMINAL_PROMPT=0 git -C "$INSTALLER_DIR" ls-remote --heads origin \
            "refs/heads/$branch" 2>/dev/null | awk 'NR == 1 { print $1 }' \
            > "$output_file"
        printf '%s\n' "$?" > "$status_file"
    ) &
    pid=$!
    elapsed=0
    while [ ! -f "$status_file" ] && [ "$elapsed" -lt 5 ]; do
        sleep 1
        elapsed=$((elapsed + 1))
    done
    if [ ! -f "$status_file" ]; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        rm -f "$output_file" "$status_file"
        echo unavailable
        return
    fi
    wait "$pid" 2>/dev/null || true
    remote_commit=$(sed -n '1p' "$output_file" 2>/dev/null)
    rm -f "$output_file" "$status_file"
    if [ -z "$remote_commit" ]; then
        echo unavailable
    elif [ "$remote_commit" = "$local_commit" ]; then
        echo current
    else
        echo available
    fi
}

main_menu() {
    local remote_commit_state
    remote_commit_state=
    while :; do
        clear
        local fw chw cfw setup branch commit pending_updates update_state
        fw="$(detect_printer_fw)"
        chw="$(detect_carto_hw)"
        cfw="$(detect_carto_fw)"
        setup="$(detect_install_profile)"
        branch="$(detect_installer_branch)"
        commit="$(detect_installer_commit)"
        pending_updates="$(migration_pending_component_count)"
        if [ "$pending_updates" -gt 0 ]; then
            update_state="$(c_yellow "$pending_updates ACTION(S) PENDING")"
        else
            if [ -z "$remote_commit_state" ]; then
                remote_commit_state="$(detect_remote_commit_state)"
            fi
            case "$remote_commit_state" in
                available) update_state="$(c_yellow 'INSTALLER UPDATE AVAILABLE')" ;;
                current) update_state="$(c_green 'UP TO DATE')" ;;
                *) update_state="$(c_dim 'REMOTE CHECK UNAVAILABLE')" ;;
            esac
        fi

        ui_rule
        printf ' %s\n' "$(c_cyan 'K2 PLUS COMPATIBILITY INSTALLER')"
        printf '%s\n' '------------------------------------------------------------'
        printf ' Firmware : %s\n' "$(c_cyan "$fw")"
        printf ' Branch   : %s\n' "$(c_cyan "$branch")"
        printf ' Commit   : %s\n' "$(c_cyan "$commit")"
        case "$setup" in
            *incomplete*) printf ' Setup    : %s\n' "$(c_yellow "$setup")" ;;
            *) printf ' Setup    : %s\n' "$(c_green "$setup")" ;;
        esac
        if is_cartographer; then
            printf ' Probe    : %s / firmware %s\n' "$(c_cyan "${chw:-unknown}")" "$(c_cyan "${cfw:-unknown}")"
            printf ' Mount    : %s\n' "$(c_cyan "$(detect_carto_offset_label)")"
        fi
        ui_rule

        printf '\n'
        ui_menu_item 1 'Status and diagnostics'
        ui_menu_item 2 'Install or change setup'
        ui_menu_item 3 'Cartographer tools'
        ui_menu_item 4 'Optional extras'
        ui_menu_item 5 'Maintenance and recovery'
        ui_menu_item 6 'Update installer / apply updates' "$update_state"
        printf '\n  0. Exit\n\nSelect [0-6]: '
        read -r c
        case "$c" in
            1) show_status ;;
            2) menu_install_paths ;;
            3) menu_cartographer_tools ;;
            4) menu_extras ;;
            5) menu_maintenance ;;
            6) menu_update_installer ;;
            0|q|Q) exit 0 ;;
            *) ;;
        esac
    done
}
