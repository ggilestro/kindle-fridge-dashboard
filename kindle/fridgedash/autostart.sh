#!/bin/sh
# Manage starting the fridge dashboard at boot.
#   autostart.sh on       enable (touch the flag file)
#   autostart.sh off      disable (remove the flag file)
#   autostart.sh install  install the boot hook in the root filesystem and enable
#   autostart.sh remove   remove the boot hook from the root filesystem and disable
PATH=/usr/sbin:/usr/bin:/sbin:/bin
DIR=/mnt/us/fridgedash
FLAG=$DIR/AUTOSTART
INIT=/etc/init.d/fridgedash
LINK=/etc/rc5.d/S99fridgedash

# Run "$@" with the root filesystem writable, always remounting it read-only afterwards.
with_rw_root() {
    mntroot rw || return 1
    "$@"
    rc=$?
    sync
    mntroot ro
    return $rc
}

do_install() {
    cp "$DIR/fridgedash.init" "$INIT" && chmod 755 "$INIT" && ln -sf "$INIT" "$LINK"
}

do_remove() {
    rm -f "$LINK" "$INIT"
}

case "$1" in
on) touch "$FLAG" ;;
off) rm -f "$FLAG" ;;
install) with_rw_root do_install && touch "$FLAG" ;;
remove) with_rw_root do_remove && rm -f "$FLAG" ;;
*)
    echo "usage: $0 on|off|install|remove" >&2
    exit 2
    ;;
esac
