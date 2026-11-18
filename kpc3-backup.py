#!/usr/bin/env python3
"""Back up and restore the configuration of a Kantronics TNC.

Usage:
  kpc3-backup.py backup  /dev/ttyUSB1 [--dir backups]
  kpc3-backup.py restore /dev/ttyUSB1 backups/kantronics-KPC3P-8.3-2026-10-28.txt

backup:  soft RESET to read model and firmware from the banner, then save the
         DISPLAY output to kantronics-<MODEL>-<VER>-<YYYY-MM-DD>.txt
restore: RESTORE DEFAULT, then replay every setting from the file. ABAUD,
         INTFACE and XMITOK are applied last. Rejected lines are reported.
         Settings the TNC firmware does not have (e.g. UIDUPE from a 9.1 backup
         on an 8.3 TNC) are skipped and listed.

Restoring onto a different firmware needs --force. Raw DISPLAY captures (from a
terminal program, without the "# MODEL" header) can be restored the same way.
"""

import argparse
import os
import re
import sys
import time

import serial

from kpc3lib import (BAUDS, KNOWN_PARAMS, TEXT, TNC, Firmware, TNCError, display_params,
                     mask, norm, parse, parse_banner, set_clock)

LAST = ("XMITOK", "ABAUD", "INTFACE")


def read_banner(tnc):
    model, version = parse_banner(tnc.reset())
    if not model:
        raise TNCError("could not read firmware version from the RESET banner")
    return model, version


def backup(args):
    tnc = TNC(args.port)
    tnc.find(args.baud)
    model, version = read_banner(tnc)
    tnc.log(f"Model {model}, firmware {version}")
    tnc.verbose = False
    display = tnc.cmd("DISPLAY", timeout=40)
    if "MYCALL" not in display:
        raise TNCError("DISPLAY output looks incomplete")
    if "INTFACE  NEWUSER" in display:
        print("warning: TNC is in NEWUSER mode, DISPLAY lists only a few settings; "
              "set INTFACE TERMINAL and RESET for a full backup")

    os.makedirs(args.dir, exist_ok=True)
    stem = os.path.join(args.dir, f"kantronics-{model}-{version}-{time.strftime('%Y-%m-%d')}")
    path, n = stem + ".txt", 2
    while os.path.exists(path):
        path, n = f"{stem}-{n}.txt", n + 1
    with open(path, "w") as f:
        f.write(f"# MODEL {model}\n# VERSION {version}\n# DATE {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(display.rstrip() + "\n")
    print(f"saved {path}")


def commands_for(key, raw):
    """Translate one DISPLAY entry into the command(s) that set it."""
    name, _, sub = key.partition(" ")
    if name in TEXT or name in ("LT", "GPSHEAD"):
        if raw.strip():
            return [f"{key} {raw}"]
        if name == "CWIDTEXT":
            raise TNCError("empty CWIDTEXT cannot be set on this firmware, left at default")
        # GPSHEAD stores '%' literally; an empty argument clears it
        return [key] if name == "GPSHEAD" else [f"{key} %"]
    val = re.sub(r"\s*\([^)]*\)$", "", raw.strip())  # "4 (4 sec)" -> "4"
    val = re.sub(r"\s+min$", "", val)  # "EVERY 30 min" -> "EVERY 30"
    val = re.sub(r"\s+", " ", val)
    if name == "CTRL":  # "A OFF B OFF": one port per command
        return [f"CTRL {p}" for p in re.findall(r"[AB] \S+", val)]
    if name in ("UIFLOOD", "UITRACE") and val.startswith("disabled,"):
        # Set the numbers with a placeholder alias, then disable the alias
        return [f"{name} NONE,{val.split(',', 1)[1]}", f"{name} %"]
    if val == "disabled":
        return [f"{key} %"]
    return [f"{key} {val}".rstrip()]


def restore(args):
    with open(args.file) as f:
        meta, wanted = parse(f.read())
    if "MYCALL" not in wanted or "ABAUD" not in wanted:
        raise TNCError(f"{args.file} does not look like a backup (no MYCALL/ABAUD)")
    mycall = wanted["MYCALL"].split()[0]
    baud = int(wanted["ABAUD"].split()[0])
    if baud not in BAUDS:
        raise TNCError(f"unsupported ABAUD {baud} in backup")

    source = f"{meta['MODEL']} {meta['VERSION']}" if "VERSION" in meta else None

    if args.dry_run:
        fw = Firmware.offline(args.firmware) if args.firmware else Firmware("?", "?", None)
        for key, raw in wanted.items():
            if not fw.supports(key):
                print(f"# {key}: skipped, not in firmware {fw.version}")
                continue
            try:
                print("\n".join(mask(c) for c in commands_for(key, raw)))
            except TNCError as e:
                print(f"# {key}: {e}")
        return

    tnc = TNC(args.port)
    tnc.find(baud)
    model, version = read_banner(tnc)
    if (model, version) != (meta.get("MODEL"), meta.get("VERSION")):
        if source:
            msg = f"backup is from {source}, TNC is {model} {version}"
        else:
            msg = f"backup has no MODEL/VERSION header, TNC is {model} {version}"
        if not args.force:
            raise TNCError(msg + " (use --force to restore anyway)")
        print("warning: " + msg)

    tnc.factory_reset(baud, mycall)
    tnc.cmd("INTFACE TERMINAL")
    tnc.reset()
    tnc.cmd("XMITOK OFF")
    set_clock(tnc)

    # Only send what differs from the factory defaults; the same DISPLAY tells
    # which parameters this firmware has
    display = tnc.cmd("DISPLAY", timeout=40, quiet=True)
    _, defaults = parse(display)
    fw = Firmware(model, version, display_params(display))
    failed, skipped = [], []
    for key, raw in wanted.items():
        if key in LAST or norm(raw) == norm(defaults.get(key, "")):
            continue
        if not fw.supports(key):
            skipped.append(key)
            continue
        try:
            for c in commands_for(key, raw):
                tnc.cmd(c)
                time.sleep(0.2)
        except TNCError as e:
            failed.append(str(e))

    tnc.cmd(f"XMITOK {norm(wanted.get('XMITOK', 'ON'))}")
    tnc.cmd(f"ABAUD {baud}")
    intface = norm(wanted.get("INTFACE", "TERMINAL"))
    if intface != "TERMINAL":
        tnc.cmd(f"INTFACE {intface}")
        tnc.ser.write(b"RESET\r")
        tnc.log(f"> RESET   (INTFACE {intface})")

    if skipped:
        print(f"\nskipped, not in firmware {version}: {', '.join(skipped)}")
    if failed:
        print(f"\n{len(failed)} setting(s) not restored:")
        for f in failed:
            print("  " + f)
        sys.exit(1)
    print("\nrestore complete")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="action", required=True)
    b = sub.add_parser("backup", help="save the TNC configuration to a file")
    b.add_argument("port")
    b.add_argument("--dir", default="backups", help="output directory (default: backups)")
    b.add_argument("--baud", type=int, default=9600, choices=BAUDS, help="baud to try first")
    r = sub.add_parser("restore", help="factory-reset the TNC and load a backup file")
    r.add_argument("port")
    r.add_argument("file")
    r.add_argument("--force", action="store_true", help="restore even if model/firmware differ")
    r.add_argument("--dry-run", action="store_true", help="only print the commands")
    r.add_argument("--firmware", choices=sorted(KNOWN_PARAMS),
                   help="with --dry-run: mark settings this firmware does not have")
    args = p.parse_args()

    try:
        backup(args) if args.action == "backup" else restore(args)
    except (TNCError, OSError, serial.SerialException) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
