#!/usr/bin/env python3
"""Read or set the clock of a Kantronics KPC-3 Plus from the host clock.

Usage:
  kpcclock.py show /dev/ttyUSB0          compare the TNC clock with the host
  kpcclock.py set  /dev/ttyUSB0          set the TNC to host local time
  kpcclock.py set  /dev/ttyUSB0 --utc    set the TNC to UTC

The TNC has no time zone: it stores whatever wall-clock time it is given.
Local time must be set again after a DST change; UTC never does.
"""

import argparse
import calendar
import re
import subprocess
import sys
import time

import serial

from kpc3 import BAUDS, TNC, TNCError, send_clock

# Default DAYSTR is mm/dd/yyyy hh:mm:ss
DAYTIME_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2}):(\d{2})")


def host_synced():
    """True/False from systemd's NTP status, None if it cannot be determined."""
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return {"yes": True, "no": False}.get(out)


def read_clock(tnc, utc):
    """Return (raw DAYTIME text, offset of TNC vs host in seconds or None)."""
    raw = tnc.cmd("DAYTIME", quiet=True).replace("DAYTIME", "").strip()
    host = time.time()
    m = DAYTIME_RE.search(raw)
    if not m:
        return raw, None  # unreadable date (e.g. a fresh RTC) or custom DAYSTR
    mo, d, y, hh, mi, ss = map(int, m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return raw, None
    fields = (y, mo, d, hh, mi, ss, 0, 0, -1)
    tnc_epoch = calendar.timegm(fields) if utc else time.mktime(fields)
    return raw, tnc_epoch - host


def fmt_offset(off):
    if off is None:
        return "unknown (clock not set or not readable)"
    if abs(off) < 1.5:
        return "in sync (within 1 s)"
    return f"{off:+.0f} s ({'ahead' if off > 0 else 'behind'})"


def run(args):
    if args.action == "set" and not args.dry_run:
        synced = host_synced()
        if synced is False and not args.force:
            raise TNCError("host clock is not NTP-synchronized (use --force to set it anyway)")
        if synced is None:
            print("note: could not check NTP sync of the host clock")

    if args.dry_run:
        stamp = time.gmtime() if args.utc else time.localtime()
        print("DAYTIME " + time.strftime("%y%m%d%H%M%S", stamp))
        return

    tnc = TNC(args.port, verbose=args.action == "set")
    tnc.find(args.baud)
    zone = "UTC" if args.utc else time.strftime("%Z")

    raw, off = read_clock(tnc, args.utc)
    print(f"TNC clock:  {raw}")
    print(f"Host clock: {time.strftime('%m/%d/%Y %H:%M:%S', time.gmtime() if args.utc else time.localtime())} {zone}")
    print(f"Offset:     {fmt_offset(off)}")
    if args.action == "show":
        return

    send_clock(tnc, args.utc)
    raw, off = read_clock(tnc, args.utc)
    print(f"\nTNC clock now: {raw} ({zone})")
    print(f"Offset:        {fmt_offset(off)}")
    if off is None or abs(off) >= 2:
        raise TNCError("TNC clock does not match after setting it")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=["show", "set"])
    p.add_argument("port", help="serial port, e.g. /dev/ttyUSB0")
    p.add_argument("--utc", action="store_true", help="use UTC instead of host local time")
    p.add_argument("--baud", type=int, default=9600, choices=BAUDS, help="baud to try first (default 9600)")
    p.add_argument("--force", action="store_true", help="set even if the host clock is not NTP-synced")
    p.add_argument("--dry-run", action="store_true", help="only print the DAYTIME command")
    args = p.parse_args()
    try:
        run(args)
    except (TNCError, serial.SerialException) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
