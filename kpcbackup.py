#!/usr/bin/env python3
"""Back up and restore the configuration of a Kantronics TNC.

Usage:
  kpcbackup.py backup  /dev/ttyUSB1 [--dir backups]
  kpcbackup.py restore /dev/ttyUSB1 backups/kantronics-KPC3P-8.3-2026-10-28.txt

backup:  soft RESET to read model and firmware from the banner, then save the
         DISPLAY output to kantronics-<MODEL>-<VER>-<YYYY-MM-DD>.txt
restore: RESTORE DEFAULT, then replay every setting from the file. ABAUD,
         INTFACE and XMITOK are applied last. Rejected lines are reported.
"""

import argparse
import os
import re
import sys
import time

import serial

from kpc3 import BAUDS, TNC, TNCError, set_clock

BANNER_RE = re.compile(r"KANTRONICS\s+(\S+)\s+VERSION\s+(\S+)")
# Parameters whose value is free text: taken verbatim, never trimmed
TEXT = {"BTEXT", "CTEXT", "HTEXT", "NTEXT", "PTEXT", "RTEXT", "CWIDTEXT", "GPSINIT", "DAYSTR"}
# Parameters shown as numbered sub-lines (1..4)
MULTI = {"BLT", "GPSHEAD", "LT", "LTP"}
# Read-only, or handled separately
SKIP = {"DAYTIME"}
LAST = ("XMITOK", "ABAUD", "INTFACE")


def read_banner(tnc):
    banner = tnc.reset()
    m = BANNER_RE.search(banner)
    if not m:
        raise TNCError(f"could not read firmware version from banner: {banner!r}")
    return m.group(1), m.group(2)


def backup(args):
    tnc = TNC(args.port)
    tnc.find(args.baud)
    model, version = read_banner(tnc)
    tnc.log(f"Model {model}, firmware {version}")
    tnc.verbose = False
    display = tnc.cmd("DISPLAY", timeout=40)
    if "MYCALL" not in display:
        raise TNCError("DISPLAY output looks incomplete")

    os.makedirs(args.dir, exist_ok=True)
    stem = os.path.join(args.dir, f"kantronics-{model}-{version}-{time.strftime('%Y-%m-%d')}")
    path, n = stem + ".txt", 2
    while os.path.exists(path):
        path, n = f"{stem}-{n}.txt", n + 1
    with open(path, "w") as f:
        f.write(f"# MODEL {model}\n# VERSION {version}\n# DATE {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(display.rstrip() + "\n")
    print(f"saved {path}")


def parse(text):
    """Turn DISPLAY output into (meta, {key: raw value}); sub-lines get keys like 'LT 1'."""
    meta, settings, current = {}, {}, None
    for line in text.splitlines():
        if line.startswith("# "):
            key, _, val = line[2:].partition(" ")
            meta[key] = val
            continue
        if not line.strip():
            continue
        m = re.match(r"^([1-4])(?: (.*))?$", line)
        if current in MULTI and m:
            settings[f"{current} {m.group(1)}"] = m.group(2) or ""
            continue
        name = line[:9].strip()
        if not re.match(r"^[0-9A-Z]{2,8}$", name):
            continue  # e.g. "A Link state is: ..."
        current = name
        if name not in MULTI and name not in SKIP:
            settings[name] = line[9:]
    return meta, settings


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
        return [f"{name} %"]
    return [f"{name} {val}".rstrip()]


def restore(args):
    with open(args.file) as f:
        meta, wanted = parse(f.read())
    if "MYCALL" not in wanted or "ABAUD" not in wanted:
        raise TNCError(f"{args.file} does not look like a backup (no MYCALL/ABAUD)")
    mycall = wanted["MYCALL"].split()[0]
    baud = int(wanted["ABAUD"].split()[0])
    if baud not in BAUDS:
        raise TNCError(f"unsupported ABAUD {baud} in backup")

    if args.dry_run:
        for key, raw in wanted.items():
            try:
                print("\n".join(commands_for(key, raw)))
            except TNCError as e:
                print(f"# {key}: {e}")
        return

    tnc = TNC(args.port)
    tnc.find(baud)
    model, version = read_banner(tnc)
    if (model, version) != (meta.get("MODEL"), meta.get("VERSION")):
        msg = f"backup is from {meta.get('MODEL')} {meta.get('VERSION')}, TNC is {model} {version}"
        if not args.force:
            raise TNCError(msg + " (use --force to restore anyway)")
        print("warning: " + msg)

    tnc.factory_reset(baud, mycall)
    tnc.cmd("INTFACE TERMINAL")
    tnc.reset()
    tnc.cmd("XMITOK OFF")
    set_clock(tnc)

    # Only send what differs from the factory defaults
    _, defaults = parse(tnc.cmd("DISPLAY", timeout=40, quiet=True))
    failed = []
    for key, raw in wanted.items():
        if key in LAST or norm(raw) == norm(defaults.get(key, "")):
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

    if failed:
        print(f"\n{len(failed)} setting(s) not restored:")
        for f in failed:
            print("  " + f)
        sys.exit(1)
    print("\nrestore complete")


def norm(raw):
    return re.sub(r"\s+", " ", raw.strip())


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
    args = p.parse_args()

    try:
        backup(args) if args.action == "backup" else restore(args)
    except (TNCError, OSError, serial.SerialException) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
