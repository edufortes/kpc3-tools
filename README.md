# kpc3-tools

Command-line tools to factory-reset, configure, back up, restore and set the clock of a
**Kantronics KPC-3 Plus** TNC over its serial port. Tested against firmware **8.3** and **9.1** (see
[Firmware versions](#firmware-versions)).

- `kpc3-setup.py`: factory reset plus a ready-made setup: APRS fill-in digipeater (with
  or without beacon), plain packet digipeater, KISS TNC, or PBBS.
- `kpc3-backup.py`: save the full TNC configuration to a text file and restore it later.
- `kpc3-clock.py`: show the TNC clock or set it from the host clock (NTP).
- `kpc3lib.py`: shared serial and firmware-detection code used by the three tools; keep
  it in the same folder.

> **Warning:** every setup mode of `kpc3-setup.py` and every `kpc3-backup.py restore` starts
> with `RESTORE DEFAULT`, which wipes the TNC's current configuration (and PBBS
> messages). Take a backup first.

## Requirements

- Python 3.8+
- [pyserial](https://pypi.org/project/pyserial/): `pip install -r requirements.txt`
- Read/write access to the serial port (on Linux usually the `uucp` or `dialout` group)

## kpc3-setup.py: setup modes

```
kpc3-setup.py MODE CALLSIGN PORT [options]
```

| Mode | What it sets up |
|---|---|
| `fillin` | WIDE1-1 fill-in digipeater, no beacon |
| `fillin-beacon` | WIDE1-1 fill-in digipeater plus an APRS position beacon |
| `wide` | Wide-area (high site) APRS digipeater: WIDE1-1 and WIDEn-N, optional beacon |
| `digi` | Plain AX.25 packet digipeater (e.g. to reach a Winlink gateway), no APRS, no beacon |
| `kiss` | KISS mode, for Dire Wolf, APRX, `kissattach`, Xastir, etc. |
| `pbbs` | Personal mailbox (PBBS) |
| `remote` | Only enable, change or disable remote control on a running TNC, no reset |
| `show` | Print the current configuration (`DISPLAY`, password hidden), changes nothing |

Examples:

```sh
./kpc3-setup.py fillin        N0CALL-10 /dev/ttyUSB0
./kpc3-setup.py fillin-beacon N0CALL-10 /dev/ttyUSB0 --lat 50.1000 --lon 8.6800 \
    --comment "WIDE1-1 Fill-in Digi" --interval 30
./kpc3-setup.py wide          N0CALL-10 /dev/ttyUSB0 --alias CITY \
    --lat 50.1000 --lon 8.6800 --interval 30
./kpc3-setup.py digi          N0CALL-10 /dev/ttyUSB0 --alias RELAY
./kpc3-setup.py kiss          N0CALL-10 /dev/ttyUSB0
./kpc3-setup.py pbbs          N0CALL-10 /dev/ttyUSB0 --pbbs-call N0CALL-1
./kpc3-setup.py show          -         /dev/ttyUSB0

# Change only the beacon of a running digi (no reset)
./kpc3-setup.py fillin-beacon N0CALL-10 /dev/ttyUSB0 --lat 50.1000 --lon 8.6800 \
    --interval 15 --beacon-only

# Remote control: with any setup mode, or alone on a running TNC (asks for the password)
./kpc3-setup.py fillin        N0CALL-10 /dev/ttyUSB0 --remote N0CALL-8
./kpc3-setup.py remote        N0CALL-10 /dev/ttyUSB0 --remote N0CALL-8
./kpc3-setup.py remote        N0CALL-10 /dev/ttyUSB0 --remote off
```

What a setup run does:

1. Finds the TNC at any baud rate. It also gets the TNC out of KISS mode or out of a
   connected session.
2. `RESTORE DEFAULT`, then answers the autobaud (`*`) and callsign prompts.
3. Switches from the factory `NEWUSER` mode to `TERMINAL` and resets, reading the
   firmware version from the banner and the supported parameters from `DISPLAY`.
4. With `XMITOK OFF`, sets the clock and the mode's settings, then `XMITOK ON`.
5. For `kiss`, finishes with `INTFACE KISS` and a reset.

### Options

| Option | Default | Description |
|---|---|---|
| `--baud` | 9600 | Host serial speed (300 to 19200) |
| `--cd` | `software` | Carrier detect: `software`, `internal` or `external` |
| `--txdelay` | firmware (30) | TXDELAY in 10 ms units |
| `--no-restore` | | Skip the factory reset and apply the settings on top |
| `--dry-run` | | Only print the commands (does a soft `RESET` to read the firmware) |
| `--firmware VER` | | With `--dry-run`: plan for `8.3` or `9.1` without a TNC (port `-`) |
| `--dwait MS` | 0 | `fillin`, `wide`: delay before repeating, 0 to 2550 ms |
| `--uidupe SECS` | 30 | `fillin`, `wide`, 9.x only: UIDIGI duplicate window, 0 to 255 s |
| `--alias` | none | `digi`, `wide`: `MYALIAS`, a second name stations can digipeat through |
| `--trap PATHS` | `WIDE3-3,WIDE3-2` | `wide`: up to 3 paths repeated only once, `''` for none |
| `--lat`, `--lon` | | Beacon position, decimal degrees (south/west negative); `wide` beacons only with these |
| `--comment` | `WIDE1-1 Fill-in Digi` / `Wide-area Digi` | Beacon comment |
| `--symbol` | `/#` | APRS table + symbol, e.g. `1#` for the fill-in overlay |
| `--path` | `WIDE2-1` | Beacon via path, `''` for direct |
| `--interval` | 30 | Beacon interval, 1 to 30 minutes |
| `--beacon-only` | | `fillin-beacon`, `wide`: only replace the beacon, no reset |
| `--pbbs-call` | MYCALL with SSID+1 | PBBS callsign |
| `--size` | 100 | PBBS memory in KB |
| `--ptext` | welcome line with the main commands | PBBS greeting, up to 127 characters; `''` for none |
| `--pbbs-users N` | firmware (1) | 9.x only: users on the PBBS at once (`PBUSERS`) |
| `--remote CALL` | off | `MYREMOTE`, callsign for remote control; `off` disables it (any mode but `kiss`) |
| `--remote-pass TEXT` | asked for | `RTEXT` password, up to 127 printable characters |

### Fill-in digipeater settings

```
UIDIGI ON WIDE1-1     only answer WIDE1-1
UIDWAIT ON            UI repeats honour DWAIT
DWAIT 0               (--dwait)
DIGIPEAT OFF          no plain callsign/alias digipeating
HID OFF               no ID packets
PBBS 0                the factory default enables a PBBS (100 KB on 8.3, 480 KB on 9.1)
CD SOFTWARE           (--cd)
MONITOR ON, MRPT ON
```

### Wide-area digipeater settings (`wide`)

For a high site (mountaintop, tower) that covers a large area, following the
New-N paradigm:

```
UIDIGI ON WIDE1-1,WIDE3-3,WIDE3-2   WIDE1-1 plus the trap paths (--trap)
UITRACE WIDE,30       WIDEn-N: decrement and insert MYCALL
UIFLOOD %             off (two rules for the same alias are ambiguous)
UIDWAIT OFF           repeat at once; fill-ins are the ones that wait
DWAIT 0               (--dwait)
DIGIPEAT ON           plain digipeating via MYCALL / MYALIAS too
MYALIAS               (--alias, cleared if not given)
UIDUPE 30             (--uidupe, 9.x only; the 9.1 factory default 0 is off)
HID OFF, BEACON EVERY 0, PBBS 0, CD SOFTWARE, MONITOR ON, MRPT ON
```

- **WIDE1-1** is the first hop of most mobile and home paths (`WIDE1-1,WIDE2-1`);
  a wide digi answers it as well as WIDE2-N.
- **Trap paths**: `UIDIGI` repeats a frame once and marks that hop used, so a
  `WIDE3-3` packet gets one hop from this site instead of three and does not
  flood the area. `UIDIGI` takes 4 calls, so up to 3 traps fit next to WIDE1-1.
- With `--lat`/`--lon` it also sends a position beacon like `fillin-beacon`
  (default path `WIDE2-1`; from a high site, more is rarely needed).

### Remote control (`--remote`, `remote` mode)

A station that connects to the `MYREMOTE` callsign has to authenticate with the
`RTEXT` password; then the TNC replies `ACCESS GRANTED` and accepts commands over
the air. Both are off by default.

Login (tested over the air on 9.1): the TNC sends three groups of digits, e.g.
`451432 453245 511132`. Each digit is a position in `RTEXT` (1 = first
character); answer with those characters. With `RTEXT` `EduS#`, `451432` is
`S#ESud`. Details in [docs/firmware-9.1.md](docs/firmware-9.1.md).

- Use a callsign the TNC does not already answer to, e.g. SSID `-8`; the tool
  refuses `MYCALL`, `MYALIAS`, an active `MYPBBS` and an active `MYNODE`.
- The password is asked for (typed twice) unless `--remote-pass` is given; on
  the command line it ends up in the shell history.
- It is never printed: the TNC echoes the old value on every change, so the
  tools hide all `RTEXT` output (`show` too). Backups do contain it in clear
  text, because restore needs it: keep backup files private.
- `RTEXT` holds up to 127 characters. Each login sends characters of the
  password in the clear (amateur radio may not be encrypted); with a short
  `RTEXT` one login can reveal all of it. Use a long random one; the tool warns
  below 20. (The challenge digits seen were 1-9, so possibly only the first 9
  characters are ever used; not verified.)
- Changing `MYREMOTE` reboots the TNC, the tools wait for it.

### Personal mailbox (`pbbs`)

```
PBBS 100              (--size, KB of battery-backed RAM for messages)
MYPBBS N0CALL-11      (--pbbs-call, default MYCALL with SSID+1)
PTEXT ...             (--ptext, default below)
PBUSERS n             (--pbbs-users, 9.x only)
HID OFF, BEACON EVERY 0, CD SOFTWARE
```

The default greeting (at most 114 characters, the limit is 127):

```
Welcome to N0CALL-11 PBBS, sysop N0CALL. L=list LM=mine R n=read S call=send SB ALL=bulletin K n=kill H=help B=bye
```

Stations connect to `MYPBBS` over the air. Locally, type `C N0CALL-11` at the
`cmd:` prompt: this goes straight to the mailbox, nothing is transmitted.

PBBS commands (from the 9.1 firmware help):

| Command | What it does |
|---|---|
| `L [x [y]]`, `LL n` | List messages (x to y), the last n |
| `L < call`, `L > call` | List messages from / to a callsign |
| `LM`, `RM`, `KM` | List / read / delete (read ones) your own messages |
| `LB`, `LT`, `LC [cat]` | List bulletins, traffic, categories |
| `R n`, `RH n` | Read message n, with full headers |
| `S call`, `SP call` | Send a message, a private message |
| `SB cat`, `ST addr` | Send a bulletin (e.g. `SB ALL`), NTS traffic (e.g. `ST 10117@NTSBE`) |
| `K n` | Delete message n |
| `E n ...` | Edit a message header (type, flags, to, from, `@BBS`) |
| `J [S\|L]`, `U` | Stations heard, users connected to the PBBS |
| `LT1`..`LT4`, `LTRACK n` | Location texts, tracking buffer |
| `NL n`, `LO [+\|-]` | Page size, listing order |
| `B` | Log off |

Messages end with Ctrl-Z or `/EX` on a line of its own. Other `PB*` parameters:
`PBSIZE` (max message size), `PBPERSON` (only mail for MYCALL/MYPBBS),
`PBHOLD`, `PBMAIL` ("YOU HAVE MAIL"), `PBLIST` (allowed/refused callsigns),
`PBFORWRD` / `PBKILLFW` / `PBREVERS` / `PBHEADER` (forwarding to another BBS).

It is a personal mailbox: one message area, text only. Messages live in the
battery-backed RAM; `RESTORE DEFAULT` (every setup run and every restore) or a
flat battery deletes them. Messages written locally are `FROM` the base call
(`N0CALL`, without the SSID of MYCALL).

### Plain digipeater settings (`digi`)

```
DIGIPEAT ON           repeat any frame whose next unused hop is MYCALL or MYALIAS
MYALIAS               (--alias, cleared if not given)
UIDIGI OFF            no APRS WIDE1-1 digipeating
HID OFF               no ID packets
BEACON EVERY 0        no beacon
PBBS 0
CD SOFTWARE           (--cd)
MONITOR ON, MRPT ON
```

This also repeats connected-mode frames, so a Winlink client can reach a gateway
through it: in the client, connect to the gateway's callsign with `N0CALL-10`
(or the alias) as the digipeater path.

The beacon uses the location-text beacon (`LT 1` / `LTP 1` / `BLT 1`), not
`BTEXT`. `BTEXT` beacons are always sent to the destination `BEACON`, while `LTP`
lets you set the proper APRS destination and path, e.g.
`N0CALL-10>APN383,WIDE2-1`. It works without a GPS connected.

## kpc3-backup.py: backup and restore

```sh
./kpc3-backup.py backup  /dev/ttyUSB0 [--dir backups]
./kpc3-backup.py restore /dev/ttyUSB0 backups/kantronics-KPC3P-8.3-2026-10-28.txt [--dry-run] [--force]
```

- **backup** does a soft `RESET` to read model and firmware version from the
  startup banner (8.3 has no `VERSION` command), then saves the `DISPLAY` output
  as `kantronics-<MODEL>-<VERSION>-<YYYY-MM-DD>.txt`. Further backups on the same
  day get `-2`, `-3`, ...
- **restore** checks that model and firmware match the file (override with
  `--force`, e.g. to move a 9.1 setup to an 8.3 TNC), does `RESTORE DEFAULT` at the baud rate stored in the backup, reads
  the factory defaults and sends only the settings that differ. `XMITOK`, `ABAUD`
  and `INTFACE` are applied last. Settings the target firmware does not have are
  skipped and listed. Any rejected setting is listed and the exit code is 1.
- **restore** also reads raw `DISPLAY` captures from a terminal program (no
  `# MODEL` header, so `--force` is needed) and hand-written one-line entries such
  as `LT 1 text` or `BLT 2 EVERY 00:15:00`.
- `restore --dry-run --firmware 8.3` shows what would be skipped on that firmware.

A backup followed by a restore and a second backup gives an identical file
(except the clock).

## kpc3-clock.py: TNC clock

```sh
./kpc3-clock.py show /dev/ttyUSB0          # TNC clock, host clock and the offset
./kpc3-clock.py set  /dev/ttyUSB0          # set to host local time
./kpc3-clock.py set  /dev/ttyUSB0 --utc    # set to UTC
```

- **set** checks that the host clock is NTP-synchronized (`timedatectl`), refuses
  otherwise unless `--force`, then sends `DAYTIME yymmddhhmmss` exactly at a
  second boundary and reads the clock back to verify it.
- Changes nothing else on the TNC, no reset.
- The TNC has no time zone. With local time, run `set` again after each DST
  change; `--utc` avoids that.
- Without the optional RTC chip the clock restarts on every power-up. With the
  RTC installed it keeps running, so one `set` is enough (plus an occasional
  check with `show` for drift).
- `kpc3-setup.py` and `kpc3-backup.py restore` also set the clock (host local time).
- Options: `--baud` (baud to try first), `--force`, `--dry-run`.

## GPS, telemetry and firmware notes

- [docs/gps.md](docs/gps.md): beacon a live position instead of a fixed one (e.g. a
  portable digi): GPS receiver, power, wiring to radio port pin 2 and the
  `GPSPORT` / `GPSHEAD` settings.
- [docs/telemetry.md](docs/telemetry.md): APRS telemetry from the two analog inputs
  (battery voltage, temperature): jumpers J8/J10, sensor circuits and the
  `TELEMTRY` / `PARM` / `UNIT` / `EQNS` settings.
- [docs/firmware-9.1.md](docs/firmware-9.1.md): what was learned from a 9.1 TNC and
  its EPROM: CPU and ROM layout, factory defaults, limits, the remote login
  challenge, PBBS behaviour, and APRS lessons from a real site.

## Firmware versions

The tools do not hard-code one firmware. After a `RESET` they read the version
from the banner (`KANTRONICS KPC3P VERSION 9.1`) and take the list of parameters
from `DISPLAY`; commands for parameters the TNC does not list are skipped and
reported instead of failing. A version not listed below still works this way,
with a note that it is untested.

Parameters in 9.1 that 8.3 does not have (from real `DISPLAY` dumps):

| Parameter | Used by the tools |
|---|---|
| `UIDUPE` | fill-in modes, `--uidupe` |
| `PBUSERS` | `pbbs`, `--pbbs-users` |
| `PBMAIL`, `PBSIZE` | restore only |
| `RANGE` (telemetry ranges) | restore only |
| `NETCALL`, `NETALIAS`, `NETBUFFS`, `NETCIRCS`, `NETDESTS`, `NETLINKS`, `NETROUTE`, `NETUSERS` (K-Net node) | restore only |

Tested on a 9.1 TNC: setup (`fillin`, `fillin-beacon`, `wide`), remote control
(enable, change password, disable), backup, restore, the backup-restore-backup
round trip, and restoring an 8.3 backup onto 9.1 with `--force`.

### Firmware 9.1 notes

- `VERSION` exists (8.3 has none) and answers e.g. `KPC3P-F7FC05160-9.1`.
- The model in the banner and in `VERSION` flips between `KPC3P` and `KPC3PMX`
  from one reset to the next on the same TNC; the tools treat both as `KPC3P`.
- Factory defaults differ from what many 9.1 setups show: `UIDUPE 0` (UIDIGI
  duplicate checking off; the fill-in modes set 30), `PBBS 480`, `DIGIPEAT ON`,
  `HID ON`, `UIDIGI OFF`, `UNPROTO CQ`.
- A backup from 8.3 has no `UIDUPE`, so after restoring one onto 9.1 it stays at
  0; set `UIDUPE 30` by hand or rerun `kpc3-setup.py`.
- As on 8.3, `RESTORE DEFAULT` waits for `*` and asks for the callsign, the TNC
  starts in `NEWUSER`, and changing `PBBS` or `MYREMOTE` reboots it; on 9.1
  `PBUSERS` does too.
- `RTEXT` and `PTEXT` take at most 127 characters (128 gives `Input ignored`).
- The PBBS identifies itself as `[KPC3P-9.1-HM$]`.

In `NEWUSER` mode `DISPLAY` lists only about a dozen parameters, so it cannot
tell what the firmware supports; the tools then filter nothing and warn, and
`backup` warns that the file will be incomplete.

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
- `DAYTIME yymmddhhmm[ss]` sets the clock; `DAYTIME` alone reads it in the
  `DAYSTR` format. A fresh RTC reads `01/00/2000 00:00:00`.
- Errors come as `EH?`, `?...`, `Input ignored`, `Value out of range` or
  `Command not available in NEWUSER mode`.

## License

MIT, see [LICENSE](LICENSE).
