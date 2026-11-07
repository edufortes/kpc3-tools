#!/usr/bin/env python3
"""Factory-reset and configure a Kantronics KPC-3 Plus (firmware 8.3).

Usage examples:
  kpc3-setup.py fillin        N0CALL-11 /dev/ttyUSB1
  kpc3-setup.py fillin-beacon N0CALL-11 /dev/ttyUSB1 --lat 50.1000 --lon 8.6800 --comment "WIDE1-1 Fill-in Digi" --interval 10
  kpc3-setup.py fillin-beacon N0CALL-10 /dev/ttyUSB1 --lat 50.1000 --lon 8.6800 --interval 15 --beacon-only
  kpc3-setup.py digi          N0CALL-11 /dev/ttyUSB1 --alias RELAY
  kpc3-setup.py kiss          N0CALL-11 /dev/ttyUSB1
  kpc3-setup.py pbbs          N0CALL-11 /dev/ttyUSB1 --pbbs-call N0CALL-1
  kpc3-setup.py show          -         /dev/ttyUSB1

Every configuring mode does: find the TNC (any baud, also leaves KISS mode),
RESTORE DEFAULT, autobaud, set MYCALL, then apply the mode's settings.
"""

import argparse
import re
import sys

import serial

from kpc3lib import BAUDS, TNC, TNCError, set_clock

CALL_RE = re.compile(r"^[A-Z0-9]{3,6}(-([0-9]|1[0-5]))?$")


def check_call(call):
    call = call.upper()
    if not CALL_RE.match(call):
        raise argparse.ArgumentTypeError(f"invalid callsign: {call}")
    return call


def beacon_minutes(value):
    n = int(value)
    if not 1 <= n <= 30:
        raise argparse.ArgumentTypeError("beacon interval must be 1-30 minutes")
    return n


def dwait_ms(value):
    n = int(value)
    if not 0 <= n <= 2550:
        raise argparse.ArgumentTypeError("DWAIT must be 0-2550 ms")
    return round(n / 10)


def aprs_lat(lat):
    if not -90 <= lat <= 90:
        raise ValueError("latitude out of range")
    hemi = "N" if lat >= 0 else "S"
    lat = abs(lat)
    deg = int(lat)
    return f"{deg:02d}{(lat - deg) * 60:05.2f}{hemi}"


def aprs_lon(lon):
    if not -180 <= lon <= 180:
        raise ValueError("longitude out of range")
    hemi = "E" if lon >= 0 else "W"
    lon = abs(lon)
    deg = int(lon)
    return f"{deg:03d}{(lon - deg) * 60:05.2f}{hemi}"


def next_ssid(call):
    base, _, ssid = call.partition("-")
    return f"{base}-{(int(ssid or 0) + 1) % 16}"


# --- mode configurations -----------------------------------------------------

def base_settings(args):
    cmds = [
        f"MYCALL {args.call}",
        "INTFACE TERMINAL",
    ]
    return cmds


def common_settings(args):
    # Sent after INTFACE TERMINAL is active (NEWUSER mode refuses some commands).
    # Software DCD detects packets in the audio, not just squelch/noise
    cmds = [f"CD {args.cd.upper()}"]
    if args.txdelay is not None:
        cmds.append(f"TXDELAY {args.txdelay}")
    return cmds


def fillin_settings(args):
    # Tested setup: only answer WIDE1-1, no plain digipeating, no ID packets
    return [
        "UIDIGI ON WIDE1-1",
        f"DWAIT {args.dwait}",  # with UIDWAIT ON, repeats wait DWAIT x 10 ms
        "UIDWAIT ON",
        "DIGIPEAT OFF",
        "HID OFF",
        "BEACON EVERY 0",
        "MONITOR ON",
        "MRPT ON",
        "PBBS 0",  # factory default enables a 100 KB PBBS
    ]


def digi_settings(args):
    # Plain AX.25 digipeater, no APRS: repeats any frame (also connected mode,
    # e.g. Winlink) whose next unused hop is MYCALL or MYALIAS
    return [
        "DIGIPEAT ON",
        f"MYALIAS {args.alias or '%'}",
        "UIDIGI OFF",
        "HID OFF",
        "BEACON EVERY 0",
        "MONITOR ON",
        "MRPT ON",
        "PBBS 0",
    ]


def beacon_settings(args):
    # LT/LTP/BLT location beacon: unlike BTEXT (always sent to BEACON), LTP sets
    # the APRS destination and via path. Works without a GPS attached.
    sym = args.symbol
    if len(sym) != 2:
        raise TNCError("--symbol must be 2 characters (table + code), e.g. /# or 1#")
    text = f"!{aprs_lat(args.lat)}{sym[0]}{aprs_lon(args.lon)}{sym[1]}{args.comment}"
    if len(text) > 128:
        raise TNCError(f"beacon text too long ({len(text)} > 128 chars)")
    return [
        "BEACON EVERY 0",
        "BTEXT %",
        f"LT 1 {text}",
        "LTP 1 APN383" + (f" VIA {args.path}" if args.path else ""),
        f"BLT 1 EVERY 00:{args.interval:02d}:00",
    ]


def pbbs_settings(args):
    pbbs_call = args.pbbs_call or next_ssid(args.call)
    if pbbs_call == args.call:
        raise TNCError("PBBS callsign must differ from MYCALL")
    cmds = [
        f"PBBS {args.size}",
        f"MYPBBS {pbbs_call}",
        "HID OFF",
        "BEACON EVERY 0",
    ]
    if args.ptext:
        cmds.append(f"PTEXT {args.ptext}")
    return cmds


def run(args):
    tnc = TNC(args.port)
    tnc.find(args.baud)

    if args.mode == "show":
        tnc.verbose = False
        print(tnc.cmd("DISPLAY", timeout=40))
        return

    if args.mode == "fillin-beacon":
        if args.lat is None or args.lon is None:
            raise TNCError("fillin-beacon needs --lat and --lon")

    if args.beacon_only:
        if args.mode != "fillin-beacon":
            raise TNCError("--beacon-only only works with fillin-beacon")
        cmds = beacon_settings(args)
        if args.dry_run:
            print("\n".join(cmds))
            return
        # No reset, no digi settings: just replace the beacon on the running TNC
        mycall = tnc.cmd("MYCALL").split()[-1]
        if mycall != args.call:
            print(f"warning: TNC MYCALL is {mycall}, beacon will be sent as {mycall} (not {args.call})")
        for c in cmds:
            tnc.cmd(c)
        return

    mode_cmds = {
        "fillin": fillin_settings,
        "fillin-beacon": lambda a: [c for c in fillin_settings(a) if not c.startswith("BEACON")] + beacon_settings(a),
        "digi": digi_settings,
        "kiss": lambda a: [],
        "pbbs": pbbs_settings,
    }[args.mode](args)
    mode_cmds = common_settings(args) + mode_cmds

    if args.dry_run:
        print("\n".join(["RESTORE DEFAULT"] + base_settings(args) + ["RESET", "XMITOK OFF"]
                        + mode_cmds + (["INTFACE KISS", "RESET"] if args.mode == "kiss" else ["XMITOK ON"])))
        return

    if not args.no_restore:
        tnc.factory_reset(args.baud, args.call)
    elif tnc.baud != args.baud:
        raise TNCError(f"TNC runs at {tnc.baud} baud; --no-restore cannot change it to {args.baud}")

    for c in base_settings(args):
        tnc.cmd(c)
    # Factory default may be NEWUSER mode; TERMINAL only takes effect after a reset
    tnc.reset()
    tnc.cmd("XMITOK OFF")
    set_clock(tnc)
    for c in mode_cmds:
        tnc.cmd(c)
    tnc.cmd("XMITOK ON")

    if args.mode == "kiss":
        tnc.cmd("INTFACE KISS")
        tnc.ser.write(b"RESET\r")
        tnc.log("> RESET   (TNC now in KISS mode at %d baud)" % args.baud)
        return

    print("\n--- resulting configuration (selected) ---")
    tnc.verbose = False
    out = tnc.cmd("DISPLAY", timeout=40)
    keys = ("MYCALL", "MYALIAS", "MYPBBS", "INTFACE", "ABAUD", "DIGIPEAT", "UIDIGI", "UIDWAIT",
            "UIFLOOD", "UITRACE", "HID", "DWAIT", "CD ", "BEACON", "BTEXT", "UNPROTO", "PBBS ", "PTEXT", "TXDELAY")
    beacon = ("LT ", "LTP ", "BLT ")
    current = None
    for line in out.splitlines():
        if line.startswith(keys):
            print(line)
        elif line.startswith(beacon):
            current = line.split()[0]
        elif current and line.startswith("1"):
            print(f"{current:<9}{line}")  # only slot 1 is used
            current = None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["fillin", "fillin-beacon", "digi", "kiss", "pbbs", "show"])
    p.add_argument("call", help="callsign (MYCALL), e.g. N0CALL-11 ('-' for show)")
    p.add_argument("port", help="serial port, e.g. /dev/ttyUSB1")
    p.add_argument("--baud", type=int, default=9600, choices=BAUDS, help="host serial baud (default 9600)")
    p.add_argument("--txdelay", type=int, help="TXDELAY in 10 ms units (default: firmware default 30)")
    p.add_argument("--cd", choices=["software", "internal", "external"], default="software",
                   help="carrier detect (default software; factory default is internal)")
    p.add_argument("--no-restore", action="store_true", help="skip the factory reset")
    p.add_argument("--dry-run", action="store_true", help="only print the commands")
    p.add_argument("--beacon-only", action="store_true",
                   help="fillin-beacon: only update the beacon (no reset, digi settings untouched)")
    d = p.add_argument_group("digipeater")
    d.add_argument("--dwait", type=dwait_ms, default=0, metavar="MS",
                   help="fillin modes: delay before repeating, 0-2550 ms in 10 ms steps (default 0)")
    d.add_argument("--alias", type=check_call, help="digi: MYALIAS, a second digipeat name (default none)")
    b = p.add_argument_group("beacon (fillin-beacon)")
    b.add_argument("--lat", type=float, help="latitude, decimal degrees (south negative)")
    b.add_argument("--lon", type=float, help="longitude, decimal degrees (west negative)")
    b.add_argument("--comment", default="WIDE1-1 Fill-in Digi", help="beacon comment")
    b.add_argument("--symbol", default="/#", help="APRS table+symbol (default /#, fill-in overlay: 1#)")
    b.add_argument("--path", default="WIDE2-1", help="beacon via path (default WIDE2-1, '' for direct)")
    b.add_argument("--interval", type=beacon_minutes, default=30, help="beacon interval, 1-30 minutes (default 30)")
    s = p.add_argument_group("pbbs")
    s.add_argument("--pbbs-call", type=check_call, help="PBBS callsign (default: MYCALL with SSID+1)")
    s.add_argument("--size", type=int, default=100, help="PBBS memory in KB (default 100)")
    s.add_argument("--ptext", help="PBBS greeting text")
    args = p.parse_args()

    if args.mode != "show":
        try:
            args.call = check_call(args.call)
        except argparse.ArgumentTypeError as e:
            p.error(str(e))

    try:
        run(args)
    except (TNCError, ValueError, serial.SerialException) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
