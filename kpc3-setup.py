#!/usr/bin/env python3
"""Factory-reset and configure a Kantronics KPC-3 Plus (firmware 8.3 and 9.x).

Usage examples:
  kpc3-setup.py fillin        N0CALL-11 /dev/ttyUSB1
  kpc3-setup.py fillin-beacon N0CALL-11 /dev/ttyUSB1 --lat 50.1000 --lon 8.6800 --comment "WIDE1-1 Fill-in Digi" --interval 10
  kpc3-setup.py fillin-beacon N0CALL-10 /dev/ttyUSB1 --lat 50.1000 --lon 8.6800 --interval 15 --beacon-only
  kpc3-setup.py wide          N0CALL-10 /dev/ttyUSB1 --alias CITY --lat 50.1 --lon 8.68 --interval 30
  kpc3-setup.py digi          N0CALL-11 /dev/ttyUSB1 --alias RELAY
  kpc3-setup.py kiss          N0CALL-11 /dev/ttyUSB1
  kpc3-setup.py pbbs          N0CALL-11 /dev/ttyUSB1 --pbbs-call N0CALL-1
  kpc3-setup.py show          -         /dev/ttyUSB1
  kpc3-setup.py fillin        N0CALL-11 -  --dry-run --firmware 9.1
  kpc3-setup.py fillin        N0CALL-11 /dev/ttyUSB1 --remote N0CALL-8    (asks for the password)
  kpc3-setup.py remote        N0CALL-11 /dev/ttyUSB1 --remote N0CALL-8    (no reset)
  kpc3-setup.py remote        N0CALL-11 /dev/ttyUSB1 --remote off

Every configuring mode does: find the TNC (any baud, also leaves KISS mode),
RESTORE DEFAULT, autobaud, set MYCALL, then apply the mode's settings.
The remote mode and --beacon-only change a running TNC without a reset.

The firmware version is read from the RESET banner and the parameter list from
DISPLAY: settings the firmware has (e.g. UIDUPE and PBUSERS on 9.x) are added,
settings it does not have are skipped and reported.
"""

import argparse
import getpass
import re
import sys

import serial

from kpc3lib import BAUDS, KNOWN_PARAMS, TNC, Firmware, TNCError, identify, mask, set_clock

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


def trap_list(value):
    """--trap: up to 3 paths that UIDIGI answers once and marks as used."""
    traps = [check_call(t.strip()) for t in value.split(",") if t.strip()]
    if len(traps) > 3:
        raise argparse.ArgumentTypeError("at most 3 trap paths (UIDIGI takes 4 calls, one is WIDE1-1)")
    if "WIDE1-1" in traps:
        raise argparse.ArgumentTypeError("WIDE1-1 is always answered, do not list it as a trap")
    return traps


def remote_call(value):
    return "off" if value.lower() == "off" else check_call(value)


def uidupe_secs(value):
    n = int(value)
    if not 0 <= n <= 255:
        raise argparse.ArgumentTypeError("UIDUPE must be 0-255 seconds")
    return n


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
    # Tested setup: only answer WIDE1-1, no plain digipeating, no ID packets.
    # UIDUPE (9.x only) is the window in which UIDIGI drops duplicates.
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
        f"UIDUPE {args.uidupe}",
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


def wide_settings(args):
    # Wide-area (high site) APRS digi, New-N paradigm, as at a mountaintop:
    # - UIDIGI answers WIDE1-1 (first hop of mobile/home paths) and the trap
    #   paths: those are repeated once and marked used, so e.g. WIDE3-3 gets
    #   one hop here instead of three
    # - UITRACE WIDE handles WIDEn-N: decrement and insert MYCALL (traceable)
    # - UIFLOOD off: two rules for the same alias are ambiguous
    # - UIDWAIT OFF: a high site repeats at once, fill-ins are the ones waiting
    # - DIGIPEAT ON: also plain digipeating via MYCALL or MYALIAS
    return [
        "UIDIGI ON " + ",".join(["WIDE1-1"] + args.trap),
        "UITRACE WIDE,30",
        "UIFLOOD %",
        f"DWAIT {args.dwait}",
        "UIDWAIT OFF",
        "DIGIPEAT ON",
        f"MYALIAS {args.alias or '%'}",
        "HID OFF",
        "BEACON EVERY 0",
        "MONITOR ON",
        "MRPT ON",
        "PBBS 0",
        f"UIDUPE {args.uidupe}",
    ]


def remote_settings(args):
    # Remote control: a station connecting to MYREMOTE must authenticate with
    # RTEXT (ACCESS GRANTED / DENIED), then gets the command prompt
    if args.remote == "off":
        return ["MYREMOTE %", "RTEXT %"]
    return [f"MYREMOTE {args.remote}", f"RTEXT {args.remote_pass}"]


def check_remote(args, taken):
    """MYREMOTE must not be a callsign the TNC already answers to."""
    if not args.remote or args.remote == "off":
        return
    for name, call in taken.items():
        if call and call == args.remote:
            raise TNCError(f"--remote {args.remote} is already {name}, pick another SSID")


def beacon_settings(args):
    # LT/LTP/BLT location beacon: unlike BTEXT (always sent to BEACON), LTP sets
    # the APRS destination and via path. Works without a GPS attached.
    sym = args.symbol
    comment = args.comment if args.comment is not None else (
        "Wide-area Digi" if args.mode == "wide" else "WIDE1-1 Fill-in Digi")
    if len(sym) != 2:
        raise TNCError("--symbol must be 2 characters (table + code), e.g. /# or 1#")
    text = f"!{aprs_lat(args.lat)}{sym[0]}{aprs_lon(args.lon)}{sym[1]}{comment}"
    if len(text) > 128:
        raise TNCError(f"beacon text too long ({len(text)} > 128 chars)")
    return [
        "BEACON EVERY 0",
        "BTEXT %",
        f"LT 1 {text}",
        "LTP 1 APN383" + (f" VIA {args.path}" if args.path else ""),
        f"BLT 1 EVERY 00:{args.interval:02d}:00",
    ]


TEXT_MAX = 127  # PTEXT, RTEXT: longer input is refused ("Input ignored")


def default_ptext(pbbs_call, call):
    """Greeting with the commands a visitor needs; at most 114 chars for any callsign."""
    sysop = call.partition("-")[0]
    return (f"Welcome to {pbbs_call} PBBS, sysop {sysop}. L=list LM=mine R n=read "
            "S call=send SB ALL=bulletin K n=kill H=help B=bye")


def pbbs_settings(args):
    pbbs_call = args.pbbs_call or next_ssid(args.call)
    if pbbs_call == args.call:
        raise TNCError("PBBS callsign must differ from MYCALL")
    ptext = default_ptext(pbbs_call, args.call) if args.ptext is None else args.ptext
    if len(ptext) > TEXT_MAX:
        raise TNCError(f"--ptext too long ({len(ptext)} > {TEXT_MAX} chars)")
    cmds = [
        f"PBBS {args.size}",
        f"MYPBBS {pbbs_call}",
        "HID OFF",
        "BEACON EVERY 0",
        f"PTEXT {ptext or '%'}",  # '' leaves the greeting empty
    ]
    if args.pbbs_users is not None:
        cmds.append(f"PBUSERS {args.pbbs_users}")  # 9.x only
    return cmds


def for_firmware(fw, cmds, log):
    """Drop the commands this firmware does not have, saying so."""
    keep, drop = fw.split(cmds)
    for c in drop:
        log(f"skip  {c}   (not in firmware {fw})")
    return keep


def with_beacon(settings):
    # The beacon's own BEACON EVERY 0 replaces the mode's
    return lambda a: [c for c in settings(a) if not c.startswith("BEACON")] + beacon_settings(a)


def mode_settings(args):
    wide = with_beacon(wide_settings) if args.lat is not None else wide_settings
    cmds = common_settings(args) + {
        "fillin": fillin_settings,
        "fillin-beacon": with_beacon(fillin_settings),
        "wide": wide,
        "digi": digi_settings,
        "kiss": lambda a: [],
        "pbbs": pbbs_settings,
    }[args.mode](args)
    if args.remote:
        cmds += remote_settings(args)
    return cmds


def dry_run(args, fw):
    keep, drop = fw.split(mode_settings(args))
    print(f"# firmware {fw}" if fw.params is not None else "# firmware unknown, nothing filtered")
    print("\n".join(mask(c) for c in ["RESTORE DEFAULT"] + base_settings(args) + ["RESET", "XMITOK OFF"] + keep
                    + (["INTFACE KISS", "RESET"] if args.mode == "kiss" else ["XMITOK ON"])))
    for c in drop:
        print(f"# skipped, not in firmware {fw.version}: {mask(c)}")


def live_change(tnc, args, cmds):
    """Apply cmds to a running TNC, no reset; warn if MYCALL is not the expected one."""
    mycall = tnc.cmd("MYCALL").split()[-1]
    if mycall != args.call:
        print(f"warning: TNC MYCALL is {mycall}, not {args.call}")
    for c in cmds:
        tnc.cmd(c)


def run(args):
    if args.mode == "fillin-beacon" and (args.lat is None or args.lon is None):
        raise TNCError("fillin-beacon needs --lat and --lon")
    if (args.lat is None) != (args.lon is None):
        raise TNCError("--lat and --lon go together")
    if args.beacon_only and (args.mode not in ("fillin-beacon", "wide") or args.lat is None):
        raise TNCError("--beacon-only works with fillin-beacon or wide, and needs --lat/--lon")
    if args.mode == "show" and args.firmware:
        raise TNCError("show needs a TNC, not --firmware")
    if args.mode == "remote" and not args.remote:
        raise TNCError("remote mode needs --remote CALL (or --remote off)")
    if args.mode == "kiss" and args.remote:
        raise TNCError("remote control does not work in KISS mode")
    pbbs_call = (args.pbbs_call or next_ssid(args.call)) if args.mode == "pbbs" else None
    check_remote(args, {"MYCALL": args.call, "MYALIAS": args.alias, "MYPBBS": pbbs_call})

    if args.firmware:
        if not args.dry_run:
            raise TNCError("--firmware only works with --dry-run (a TNC reports its own)")
        if args.beacon_only:
            print("\n".join(beacon_settings(args)))
        elif args.mode == "remote":
            print("\n".join(mask(c) for c in remote_settings(args)))
        else:
            dry_run(args, Firmware.offline(args.firmware))
        return

    tnc = TNC(args.port)
    tnc.find(args.baud)

    if args.mode == "show":
        tnc.verbose = False
        print("\n".join(mask(l) for l in tnc.cmd("DISPLAY", timeout=40).splitlines()))
        return

    if args.beacon_only or args.mode == "remote":
        # No reset, nothing else touched: only the beacon or the remote access
        cmds = beacon_settings(args) if args.beacon_only else remote_settings(args)
        if args.mode == "remote" and args.remote != "off":
            # Also check against what the running TNC already answers to
            def value(name):
                return tnc.cmd(name, quiet=True).split()[1]
            taken = {"MYCALL": value("MYCALL"), "MYALIAS": value("MYALIAS")}
            # MYPBBS / MYNODE only answer while the PBBS / KA-Node is on
            if value("PBBS") != "0":
                taken["MYPBBS"] = value("MYPBBS")
            if value("NUMNODES") != "0":
                taken["MYNODE"] = value("MYNODE")
            check_remote(args, taken)
        if args.dry_run:
            print("\n".join(mask(c) for c in cmds))
            return
        live_change(tnc, args, cmds)
        if args.mode == "remote":
            print_remote(tnc)
        return

    mode_cmds = mode_settings(args)

    if args.dry_run:
        # A soft RESET shows the version; the configuration is not touched
        tnc.verbose = False
        dry_run(args, identify(tnc))
        return

    if not args.no_restore:
        tnc.factory_reset(args.baud, args.call)
    elif tnc.baud != args.baud:
        raise TNCError(f"TNC runs at {tnc.baud} baud; --no-restore cannot change it to {args.baud}")

    for c in base_settings(args):
        tnc.cmd(c)
    # Factory default may be NEWUSER mode; TERMINAL only takes effect after a reset
    fw = identify(tnc, banner=tnc.reset())
    tnc.log(f"Firmware {fw}")
    mode_cmds = for_firmware(fw, mode_cmds, tnc.log)
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
    keys = ("MYCALL", "MYALIAS", "MYPBBS", "MYREMOTE", "RTEXT", "INTFACE", "ABAUD", "DIGIPEAT", "UIDIGI",
            "UIDWAIT", "UIFLOOD", "UITRACE", "UIDUPE", "HID", "DWAIT", "CD ", "BEACON", "BTEXT", "UNPROTO",
            "PBBS ", "PTEXT", "TXDELAY")
    beacon = ("LT ", "LTP ", "BLT ")
    current = None
    for line in out.splitlines():
        if line.startswith(keys):
            print(mask(line))
        elif line.startswith(beacon):
            current = line.split()[0]
        elif current and line.startswith("1"):
            print(f"{current:<9}{line}")  # only slot 1 is used
            current = None


def print_remote(tnc):
    tnc.verbose = False
    remote = tnc.cmd("MYREMOTE", quiet=True)
    rtext = tnc.cmd("RTEXT", quiet=True).replace("RTEXT", "", 1).strip()
    print(f"\n{remote}\nRTEXT    " + (f"set ({len(rtext)} chars)" if rtext else "empty"))


def ask_password():
    if not sys.stdin.isatty():
        raise TNCError("no --remote-pass given and no terminal to ask for one")
    pw = getpass.getpass("Remote password (RTEXT): ")
    if pw != getpass.getpass("Repeat: "):
        raise TNCError("passwords do not match")
    return pw


def check_password(pw):
    if pw != pw.strip() or not pw:
        raise TNCError("password must not be empty or start/end with spaces")
    if pw.startswith("%"):
        raise TNCError("password must not start with % (that clears RTEXT)")
    if len(pw) > TEXT_MAX:
        raise TNCError(f"password too long ({len(pw)} > {TEXT_MAX} chars, the RTEXT limit)")
    if not all(32 <= ord(c) < 127 for c in pw):
        raise TNCError("password must be printable ASCII")
    if len(pw) < 20:
        print(f"warning: short password ({len(pw)} chars). The login goes over the air "
              "unencrypted; a long random RTEXT (40+ chars) is much safer.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["fillin", "fillin-beacon", "wide", "digi", "kiss", "pbbs", "remote", "show"])
    p.add_argument("call", help="callsign (MYCALL), e.g. N0CALL-11 ('-' for show)")
    p.add_argument("port", help="serial port, e.g. /dev/ttyUSB1")
    p.add_argument("--baud", type=int, default=9600, choices=BAUDS, help="host serial baud (default 9600)")
    p.add_argument("--txdelay", type=int, help="TXDELAY in 10 ms units (default: firmware default 30)")
    p.add_argument("--cd", choices=["software", "internal", "external"], default="software",
                   help="carrier detect (default software; factory default is internal)")
    p.add_argument("--no-restore", action="store_true", help="skip the factory reset")
    p.add_argument("--dry-run", action="store_true", help="only print the commands")
    p.add_argument("--firmware", choices=sorted(KNOWN_PARAMS),
                   help="with --dry-run: plan for this firmware without a TNC (port can be '-')")
    p.add_argument("--beacon-only", action="store_true",
                   help="fillin-beacon, wide: only update the beacon (no reset, digi settings untouched)")
    d = p.add_argument_group("digipeater")
    d.add_argument("--dwait", type=dwait_ms, default=0, metavar="MS",
                   help="fillin, wide: delay before repeating, 0-2550 ms in 10 ms steps (default 0)")
    d.add_argument("--uidupe", type=uidupe_secs, default=30, metavar="SECS",
                   help="fillin, wide, firmware 9.x: duplicate window for UIDIGI (default 30; factory 0 = off)")
    d.add_argument("--alias", type=check_call, help="digi, wide: MYALIAS, a second digipeat name (default none)")
    d.add_argument("--trap", type=trap_list, default=["WIDE3-3", "WIDE3-2"], metavar="PATHS",
                   help="wide: paths repeated only once, comma-separated, up to 3 "
                        "(default WIDE3-3,WIDE3-2; '' for none)")
    b = p.add_argument_group("beacon (fillin-beacon; wide when --lat/--lon are given)")
    b.add_argument("--lat", type=float, help="latitude, decimal degrees (south negative)")
    b.add_argument("--lon", type=float, help="longitude, decimal degrees (west negative)")
    b.add_argument("--comment", help="beacon comment (default 'WIDE1-1 Fill-in Digi' or 'Wide-area Digi')")
    b.add_argument("--symbol", default="/#", help="APRS table+symbol (default /#, fill-in overlay: 1#)")
    b.add_argument("--path", default="WIDE2-1", help="beacon via path (default WIDE2-1, '' for direct)")
    b.add_argument("--interval", type=beacon_minutes, default=30, help="beacon interval, 1-30 minutes (default 30)")
    s = p.add_argument_group("pbbs")
    s.add_argument("--pbbs-call", type=check_call, help="PBBS callsign (default: MYCALL with SSID+1)")
    s.add_argument("--size", type=int, default=100, help="PBBS memory in KB (default 100)")
    s.add_argument("--ptext", help="PBBS greeting, up to 127 chars (default: welcome line with the "
                                   "main commands; '' for none)")
    s.add_argument("--pbbs-users", type=int, choices=range(1, 11), metavar="N",
                   help="firmware 9.x: users connected to the PBBS at once (PBUSERS)")
    r = p.add_argument_group("remote control (any mode but kiss; the remote mode changes only this)")
    r.add_argument("--remote", type=remote_call, metavar="CALL",
                   help="MYREMOTE: callsign for remote access, e.g. N0CALL-8; 'off' disables it")
    r.add_argument("--remote-pass", metavar="TEXT",
                   help="RTEXT password, up to 127 chars (default: asked for; on the command line "
                        "it ends up in the shell history)")
    args = p.parse_args()

    if args.mode != "show":
        try:
            args.call = check_call(args.call)
        except argparse.ArgumentTypeError as e:
            p.error(str(e))

    try:
        if args.remote and args.remote != "off":
            if args.remote_pass is None:
                args.remote_pass = ask_password()
            check_password(args.remote_pass)
        elif args.remote_pass is not None:
            p.error("--remote-pass needs --remote CALL")
        run(args)
    except (TNCError, ValueError, serial.SerialException) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
