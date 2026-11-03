#!/bin/sh
# Stop the dashboard and bring back the normal Kindle UI (run over SSH).
PID=$(cat /tmp/fridgedash/pid 2>/dev/null)
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    # dash.sh traps TERM and restores the framework itself.
    kill -TERM "$PID"
else
    killall -CONT volumd 2>/dev/null
    lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
    lipc-set-prop com.lab126.cmd wirelessEnable 1 2>/dev/null
    /etc/init.d/framework start
fi
