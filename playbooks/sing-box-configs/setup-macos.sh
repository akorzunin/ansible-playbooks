#!/bin/bash
# Published with the private Linux profile URL substituted by generate.py.
set -euo pipefail
umask 077

fail() { printf '%s\n' "$1" >&2; exit 1; }
[[ $(uname -s) == Darwin ]] || fail 'Run this script on macOS.'
[[ $EUID -ne 0 ]] || fail 'Run as your desktop user, without sudo.'

profile_url='__PROFILE_URL__'
root="$HOME/Library/Application Support/sing-box-remote"
label=io.github.akorzunin.sing-box-remote
agent="$HOME/Library/LaunchAgents/$label.plist"
domain="gui/$(id -u)"
mkdir -p "$root" "$HOME/Library/LaunchAgents"
chmod 700 "$root"
# One managed profile: serialize manual runs; remove a stale lock after a hard kill.
mkdir "$root/.update-lock" 2>/dev/null || fail 'Another update is running (or remove .update-lock after a crashed update).'
work=$(mktemp -d "$root/.update-XXXXXX")
trap 'rm -rf "$work"; rmdir "$root/.update-lock"' EXIT

fetch() {
    # Profile recovery must not depend on the local proxy. Do not log private URLs.
    local status
    status=$(curl --noproxy '*' --proto '=https' --fail --silent \
        --connect-timeout 15 --max-time 180 --max-filesize 1048576 \
        --write-out '%{http_code}' "$1" -o "$2" 2>/dev/null) || fail 'Download failed; existing configuration retained.'
    [[ $status == 200 ]] || fail 'Profile download did not return HTTP 200; existing configuration retained.'
}

core="$root/core/sing-box"
if [[ ! -x $core ]]; then
    core=$(command -v sing-box || true)
fi
if [[ -z $core ]]; then
    case $(uname -m) in
        arm64) arch=arm64; checksum=925c5382eca8492b0150f868a6db20b18290a38700e621724b3703fd453e032d ;;
        x86_64) arch=amd64; checksum=b0bfb0dc70a5fc708710b9f5ea98b9ee76d40fa4169928d25d73edc4331df2fe ;;
        *) fail 'Unsupported Mac architecture.' ;;
    esac
    # Pinned upstream release, including Naive support; update hashes with the version.
    archive="sing-box-1.14.2-darwin-$arch"
    printf 'Installing sing-box 1.14.2...\n'
    # Release assets redirect to GitHub's CDN; profile downloads above must not redirect.
    curl --noproxy '*' --proto '=https' --proto-redir '=https' --location --fail --silent \
        --connect-timeout 15 --max-time 300 \
        "https://github.com/SagerNet/sing-box/releases/download/v1.14.2/$archive.tar.gz" \
        -o "$work/core.tar.gz" 2>/dev/null || fail 'Core download failed.'
    actual=$(shasum -a 256 "$work/core.tar.gz")
    [[ ${actual%% *} == "$checksum" ]] || fail 'Core checksum mismatch.'
    tar -xzf "$work/core.tar.gz" -C "$work"
    mv "$work/$archive" "$root/core"
    core="$root/core/sing-box"
fi

fetch "$profile_url" "$work/config.json"
# curl does not follow redirects here; reject empty/redirect bodies through core validation.
"$core" check -c "$work/config.json" >/dev/null 2>&1 || fail 'Profile validation failed. Use a Naive-enabled sing-box 1.14+ core; existing configuration retained.'

# Do not start a second core beside an existing GUI/service using the same listeners.
if ! launchctl print "$domain/$label" >/dev/null 2>&1 && pgrep -x sing-box >/dev/null; then
    fail 'Quit the existing sing-box client/service before enrolling this managed instance.'
fi

# plutil handles XML escaping in paths (spaces, ampersands, etc.).
printf '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict/></plist>\n' > "$work/agent.plist"
plutil -insert Label -string "$label" "$work/agent.plist"
plutil -insert ProgramArguments -xml '<array/>' "$work/agent.plist"
plutil -insert ProgramArguments.0 -string "$core" "$work/agent.plist"
plutil -insert ProgramArguments.1 -string run "$work/agent.plist"
plutil -insert ProgramArguments.2 -string -c "$work/agent.plist"
plutil -insert ProgramArguments.3 -string "$root/config.json" "$work/agent.plist"
plutil -insert WorkingDirectory -string "$root" "$work/agent.plist"
plutil -insert RunAtLoad -bool true "$work/agent.plist"
plutil -insert StandardOutPath -string "$root/sing-box.log" "$work/agent.plist"
plutil -insert StandardErrorPath -string "$root/sing-box.log" "$work/agent.plist"

had_config=false
had_agent=false
if [[ -f $root/config.json ]]; then
    cp "$root/config.json" "$work/previous.json"
    had_config=true
fi
if [[ -f $agent ]]; then
    cp "$agent" "$work/previous.plist"
    had_agent=true
fi
launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
mv "$work/config.json" "$root/config.json"
mv "$work/agent.plist" "$agent"
started=false
if launchctl bootstrap "$domain" "$agent" >/dev/null 2>&1; then
    sleep 2
    # Immediate process liveness only, not an end-to-end connectivity check.
    if launchctl list | awk -v label="$label" '$3 == label && $1 ~ /^[0-9]+$/ { found=1 } END { exit !found }'; then
        started=true
    fi
fi
if [[ $started != true ]]; then
    launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
    rm -f "$root/config.json" "$agent"
    if [[ $had_config == true ]]; then mv "$work/previous.json" "$root/config.json"; fi
    if [[ $had_agent == true ]]; then
        mv "$work/previous.plist" "$agent"
        launchctl bootstrap "$domain" "$agent" >/dev/null 2>&1 || fail 'Startup and rollback restart failed; previous files restored. Check sing-box.log.'
    fi
    fail 'Startup failed; previous files restored. Check sing-box.log.'
fi
printf 'Profile refreshed; sing-box is running (starts again at login).\n'
printf 'HTTP/SOCKS proxy: 127.0.0.1:12334 (set this in your apps or macOS proxy settings).\n'
printf 'Dashboard: https://yacd.metacubex.one | API: http://127.0.0.1:9091 | secret: admin\n'
