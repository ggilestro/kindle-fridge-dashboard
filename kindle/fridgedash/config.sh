# shellcheck shell=sh disable=SC2034  # sourced by dash.sh
# fridgedash configuration (sourced by dash.sh). Edit over USB in /mnt/us/fridgedash/.

# Where the rendered PNG lives (plain HTTP: the Kindle 4 has no usable TLS).
SERVER="http://192.168.68.124:8090"

# Seconds between refreshes; wakes are aligned to the clock (3600 = top of every hour).
INTERVAL=3600

# Local hours with no refresh, as "START-END" (23-6 = sleep from 23:00 to 06:00).
# Empty string refreshes around the clock.
QUIET_HOURS="23-6"

# POSIX timezone used for quiet hours and log timestamps (UK: GMT/BST).
TZ="GMT0BST,M3.5.0/1,M10.5.0"
export TZ

# Seconds to wait for WiFi + server before giving up on a refresh.
NET_TIMEOUT=45

# After a power-button refresh: seconds without a key press before going back to page 1
# and sleeping. Page keys browse; Back returns to page 1; HOME exits to the Kindle UI.
BROWSE_IDLE=60
