# kpc3-tools

Command-line tools to factory-reset, configure, back up and restore a
**Kantronics KPC-3 Plus** TNC over its serial port. Tested against firmware **8.3**.

- `kpc3.py`: factory reset plus a ready-made setup: APRS fill-in digipeater (with
  or without beacon), KISS TNC, or PBBS.
- `kpcbackup.py`: save the full TNC configuration to a text file and restore it later.

> **Warning:** every setup mode of `kpc3.py` and every `kpcbackup.py restore` starts
> with `RESTORE DEFAULT`, which wipes the TNC's current configuration (and PBBS
> messages). Take a backup first.

## Requirements

- Python 3.8+
- [pyserial](https://pypi.org/project/pyserial/): `pip install -r requirements.txt`
- Read/write access to the serial port (on Linux usually the `uucp` or `dialout` group)

## kpc3.py: setup modes

```
kpc3.py MODE CALLSIGN PORT [options]
```

| Mode | What it sets up |
|---|---|
| `fillin` | WIDE1-1 fill-in digipeater, no beacon |
| `fillin-beacon` | WIDE1-1 fill-in digipeater plus an APRS position beacon |
| `kiss` | KISS mode, for Dire Wolf, APRX, `kissattach`, Xastir, etc. |
| `pbbs` | Personal mailbox (PBBS) |
| `show` | Print the current configuration (`DISPLAY`), changes nothing |

Examples:

```sh
./kpc3.py fillin        N0CALL-10 /dev/ttyUSB0
./kpc3.py fillin-beacon N0CALL-10 /dev/ttyUSB0 --lat 50.1000 --lon 8.6800 \
    --comment "WIDE1-1 Fill-in Digi" --interval 30
./kpc3.py kiss          N0CALL-10 /dev/ttyUSB0
./kpc3.py pbbs          N0CALL-10 /dev/ttyUSB0 --pbbs-call N0CALL-1
./kpc3.py show          -         /dev/ttyUSB0

# Change only the beacon of a running digi (no reset)
./kpc3.py fillin-beacon N0CALL-10 /dev/ttyUSB0 --lat 50.1000 --lon 8.6800 \
    --interval 15 --beacon-only
```

What a setup run does:

1. Finds the TNC at any baud rate. It also gets the TNC out of KISS mode or out of a
   connected session.
2. `RESTORE DEFAULT`, then answers the autobaud (`*`) and callsign prompts.
3. Switches from the factory `NEWUSER` mode to `TERMINAL` and resets.
4. With `XMITOK OFF`, sets the clock and the mode's settings, then `XMITOK ON`.
5. For `kiss`, finishes with `INTFACE KISS` and a reset.

### Options

| Option | Default | Description |
|---|---|---|
| `--baud` | 9600 | Host serial speed (300 to 19200) |
| `--cd` | `software` | Carrier detect: `software`, `internal` or `external` |
| `--txdelay` | firmware (30) | TXDELAY in 10 ms units |
| `--no-restore` | | Skip the factory reset and apply the settings on top |
| `--dry-run` | | Only print the commands |
| `--dwait MS` | 0 | Fill-in modes: delay before repeating, 0 to 2550 ms |
| `--lat`, `--lon` | | Beacon position, decimal degrees (south/west negative) |
| `--comment` | `WIDE1-1 Fill-in Digi` | Beacon comment |
| `--symbol` | `/#` | APRS table + symbol, e.g. `1#` for the fill-in overlay |
| `--path` | `WIDE2-1` | Beacon via path, `''` for direct |
| `--interval` | 30 | Beacon interval, 1 to 30 minutes |
| `--beacon-only` | | `fillin-beacon`: only replace the beacon, no reset |
| `--pbbs-call` | MYCALL with SSID+1 | PBBS callsign |
| `--size` | 100 | PBBS memory in KB |
| `--ptext` | | PBBS greeting text |

### Fill-in digipeater settings

```
UIDIGI ON WIDE1-1     only answer WIDE1-1
UIDWAIT ON            UI repeats honour DWAIT
DWAIT 0               (--dwait)
DIGIPEAT OFF          no plain callsign/alias digipeating
HID OFF               no ID packets
PBBS 0                the factory default enables a 100 KB PBBS
CD SOFTWARE           (--cd)
MONITOR ON, MRPT ON
```

The beacon uses the location-text beacon (`LT 1` / `LTP 1` / `BLT 1`), not
`BTEXT`. `BTEXT` beacons are always sent to the destination `BEACON`, while `LTP`
lets you set the proper APRS destination and path, e.g.
`N0CALL-10>APN383,WIDE2-1`. It works without a GPS connected.

## kpcbackup.py: backup and restore

```sh
./kpcbackup.py backup  /dev/ttyUSB0 [--dir backups]
./kpcbackup.py restore /dev/ttyUSB0 backups/kantronics-KPC3P-8.3-2026-10-28.txt [--dry-run] [--force]
```

- **backup** does a soft `RESET` to read model and firmware version from the
  startup banner (8.3 has no `VERSION` command), then saves the `DISPLAY` output
  as `kantronics-<MODEL>-<VERSION>-<YYYY-MM-DD>.txt`. Further backups on the same
  day get `-2`, `-3`, ...
- **restore** checks that model and firmware match the file (override with
  `--force`), does `RESTORE DEFAULT` at the baud rate stored in the backup, reads
  the factory defaults and sends only the settings that differ. `XMITOK`, `ABAUD`
  and `INTFACE` are applied last. Any rejected setting is listed and the exit code
  is 1.

A backup followed by a restore and a second backup gives an identical file
(except the clock).

## Firmware 8.3 quirks

Things found while writing these tools, useful when configuring a KPC-3+ by hand:

- No `VERSION` command; the version is only shown in the banner after `RESET`.
- After `RESTORE DEFAULT` the TNC waits for `*` (autobaud), then asks
  `ENTER YOUR CALLSIGN=>`. It starts in `INTFACE NEWUSER`, which refuses some
  commands (e.g. `XMITOK`) until `INTFACE TERMINAL` and a `RESET`.
- `UIDUPE` does not exist in 8.3 (it was added in 9.x).
- `DWAIT` maximum is 255 (2550 ms).
- `BTEXT` beacons always go to the destination `BEACON`; use `LT`/`LTP`/`BLT`
  for a proper APRS destination.
- Clearing values: `%` clears callsign and most text parameters (`MYALIAS %`,
  `BTEXT %`, `LT n %`), but `GPSHEAD n %` and `CWIDTEXT %` store a literal `%`.
  `GPSHEAD n` without a value clears it; `CWIDTEXT` cannot really be emptied.
- `UIFLOOD %` / `UITRACE %` disable the alias but keep the other fields; to set
  the numbers while disabled, first set e.g. `UIFLOOD NONE,25,ID`, then `UIFLOOD %`.
- `CTRL A OFF B OFF` is ignored; send `CTRL A OFF` and `CTRL B OFF` separately.
- Changing `PBBS` or `MYREMOTE` reboots the TNC (the banner is printed).
- To leave KISS mode send the bytes `C0 FF C0`.
- Errors come as `EH?`, `?...`, `Input ignored`, `Value out of range` or
  `Command not available in NEWUSER mode`.

## License

MIT, see [LICENSE](LICENSE).
