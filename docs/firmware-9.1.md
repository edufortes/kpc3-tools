# KPC-3 Plus firmware 9.1: notes

Findings from a real 9.1 TNC (an 8.3 unit upgraded by EPROM swap) and from the
9.1 EPROM image, collected while making the tools firmware-aware. The image
itself is Kantronics' copyright and is not part of this repository.

## Hardware and ROM

- CPU: Motorola **MC68HC11F1CFN3**: ROM-less 68HC11, 1 KB RAM, 512 bytes
  EEPROM, 8-channel A/D (the two telemetry inputs), SCI (the serial port),
  timers, COP watchdog, 4 chip selects; PLCC-68, 3 MHz bus clock.
- EPROM image: 128 KB (`md5 e23061a5fd09f0f495d5bcb8b96c40c2`), **4 banks of
  32 KB**, each mapped at `$8000-$FFFF`. A write to `$8000-$8003` selects the bank.
  All banks share `$F811-$FFFF` (common code and vectors).
- Reset vector `$818C`. Start-up clears `INIT` (`$103D`), so RAM and the register
  block both start at `$0000`, then sets the stack to `$00FF` and configures
  `CONFIG`, the chip selects, `OPTION` and ports A, D, G.
- Interrupts in use: SCI `$8118`, TOC1-TOC5, TIC1-TIC2, RTI `$8004`,
  XIRQ `$8557`. The firmware is heavily interrupt-driven (serial port, bit timing).
- Command table: bank 3 `$E8CD`, 173 commands, 8-character names, followed by a
  table of handler addresses. Many parameters share generic handlers
  (`$A961` ON/OFF, `$B6D3` 0-255 numbers).
- Help texts: pointer table in bank 1 `$D839`. PBBS commands and their help are
  in bank 2 (from `$12B85` in the image).
- Commands not shown by `DISPLAY` include `ANALOG`, `CALIBRAT`, `VERSION`,
  `WEFAX`, `MHEARD`, `RPRINT`, `STATUS`.

### Emulation

Possible in principle (MAME has a 68HC11 core), but needs a board driver: the
bank latch, external RAM, the modem/HDLC side, RTC and port pins, with
interrupts delivered. Stock Ghidra (11.x here) has no 68HC11 processor; a
community extension or MAME's debugger is needed for disassembly. Ghidra's
P-code emulator does not deliver interrupts, so it is no help for watching the
serial output.

## Identification

- `VERSION` exists on 9.1 (not on 8.3): `KPC3P-F7FC05160-9.1`. `kpc3-setup.py
  --beacon-only` uses it to find the version without a reset.
- APRS destination (tocall): `APN391` for 9.1, `APN383` for 8.3.
- The banner and `VERSION` say `KPC3P` or `KPC3PMX` seemingly at random from one
  reset to the next on the same TNC. The "MX" suffix depends on RAM flag
  `$0258`. The tools treat both as `KPC3P`.
- `DISPLAY` in `NEWUSER` mode lists only about a dozen parameters; in
  `TERMINAL` mode it lists all 154. 9.1 has these 13 that 8.3 lacks:
  `UIDUPE`, `PBUSERS`, `PBMAIL`, `PBSIZE`, `RANGE`, `NETCALL`, `NETALIAS`,
  `NETBUFFS`, `NETCIRCS`, `NETDESTS`, `NETLINKS`, `NETROUTE`, `NETUSERS`.

## Factory defaults that matter

`backups/kantronics-KPC3P-9.1-2026-11-18.txt` is the complete factory state
(`INTFACE TERMINAL` set). Compared with a configured 8.3 fill-in:

| Parameter | 9.1 factory | Note |
|---|---|---|
| `UIDUPE` | `0` (disabled) | no UIDIGI duplicate check: set 30 for any digi |
| `UIDIGI` | `OFF NONE` | |
| `DIGIPEAT` | `ON` | repeats anything addressed via MYCALL |
| `HID` | `ON` | ID packets every 9.5 min while digipeating |
| `PBBS` | `480` | a 480 KB mailbox is on |
| `UNPROTO` | `CQ` | |
| `UIFLOOD`, `UITRACE` | disabled, 30 | |
| `MYNODE`, `MYPBBS` | base call `-7`, `-1` | active only with `NUMNODES` > 0 / `PBBS` > 0 |
| `MYREMOTE`, `RTEXT` | disabled, empty | remote control off |

## Limits and quirks

- `RTEXT` and `PTEXT`: at most 127 characters; 128 gives `Input ignored`.
- `UIDUPE` 0-255 s, `XMITLVL` 0-502, `TELEMTRY` in 10 s units (0-255).
- Changing `PBBS`, `MYREMOTE` or `PBUSERS` reboots the TNC (the banner is printed,
  then `cmd:` again).
- Every change of a text parameter echoes the old value (`RTEXT was ...`); the
  tools hide all `RTEXT` output for that reason.
- As on 8.3: `RESTORE DEFAULT` waits for `*` (autobaud) and asks for the
  callsign; the TNC then starts in `NEWUSER`.

## Remote control login (tested over the air)

1. Connect to the `MYREMOTE` callsign.
2. The TNC sends a challenge: three groups of six digits, e.g.
   `451432 453245 511132`.
3. Each digit is a position (1 = first character) in `RTEXT`. Answer with the
   characters at those positions. With `RTEXT` `EduS#`, `451432` is `S#ESud`.
4. `ACCESS GRANTED` and the command prompt follow; a wrong answer gives
   `ACCESS DENIED`.

Consequences:

- One login sends a large part of the password in the clear; with a short
  `RTEXT`, every character can appear in a single challenge.
- The positions seen were single digits. If the challenge never goes beyond 9,
  only the first 9 characters of a longer `RTEXT` are ever used. Not verified.
- Use a callsign the TNC does not otherwise answer to (e.g. SSID `-8`).

## PBBS (tested locally and over the air)

- Identifies itself as `[KPC3P-9.1-HM$]`; prompt
  `ENTER COMMAND:  B,J,K,L,R,S, or Help >`.
- Local access without transmitting: `C <MYPBBS>` at the `cmd:` prompt.
- Message types: `P` personal (also from `SP`), `B` bulletin, `T` traffic;
  `H` = held (`PBHOLD ON` is the factory default).
- TO and FROM hold the base callsign only: a message to `N0CALL-10` is stored to
  `N0CALL`, and local messages are `FROM` the base call of MYCALL.
- Listings cut the subject after 28 characters; `R n` shows it in full.
- `PBUSERS 2` allows a local and a radio session at the same time.
- The messages live in battery-backed RAM: `RESTORE DEFAULT` deletes them.

## APRS lessons (from LU5VQV-1 / LU5VQV-2, Bariloche)

- After moving a configuration to a new TNC, check `LTP 1..4`: left at the
  factory `GPS`, the position goes out with no path.
- A high site does not need `WIDE1-1` in its own path (`UNPROTO`).
- `BTEXT` always goes to the destination `BEACON`; objects belong in `LT` slots.
- Spread `BLT` timers with `START` offsets so beacons do not go out together.
- APRS-IS drops duplicates within 30 s, so digipeater faults that repeat a
  packet twice on RF do not show on aprs.fi; use an RF log to check.
