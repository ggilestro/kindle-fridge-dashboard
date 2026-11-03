#!/bin/sh
# Launched from KUAL. Copies the dashboard to /tmp and runs it detached, so it survives
# both KUAL exiting (framework stop) and /mnt/us being unmounted by a USB plug.
SRC=/mnt/us/fridgedash
WORK=/tmp/fridgedash

if [ -f "$WORK/pid" ] && kill -0 "$(cat "$WORK/pid")" 2>/dev/null; then
    exit 0
fi
mkdir -p "$WORK"
cp "$SRC/dash.sh" "$SRC/config.sh" "$WORK/"
cd / || exit 1
# BusyBox 1.7.2 has no setsid/nohup; start-stop-daemon -b detaches the same way.
/sbin/start-stop-daemon -S -b -x /bin/sh -- "$WORK/dash.sh" "$@"
