# Connecting a GPS to the KPC-3+

With a GPS connected, the fill-in digipeater beacons its real position instead of a fixed
one. This page covers the hardware you need, the wiring and the TNC settings for
firmware **8.3**. None of this is automated by `kpc3-setup.py` yet.

## Two ways to connect

| | Radio port, pin 2 (XCD) | Computer port, DB-25 pin 2 |
|---|---|---|
| Firmware | 8.3 or later | any |
| Enabled by | `GPSPORT 4800 NORMAL CHECKSUM` | `INTFACE GPS` + `ABAUD 4800` |
| Computer port | stays free for a laptop / these tools | taken by the GPS |
| Leaving GPS mode | `GPSPORT 0` | three `Ctrl-C` at the GPS baud rate |

**Use the radio port.** It keeps the serial port free, so the tools in this repo (and a
laptop in the field) keep working with the GPS plugged in. The computer-port method
dates back to older firmware and is not covered further here.

## What you need

1. **A GPS receiver with a serial NMEA-0183 output**, 4800 baud, sending `$GPRMC`
   (or `$GNRMC` on newer multi-GNSS modules, see the gotchas). Typical choices:
   - an RS-232 GPS "puck" with a DB-9 plug (e.g. GlobalSat BR-355 serial version),
   - a Garmin GPS 18x LVC or similar bare-wire marine GPS,
   - a cheap UART module (u-blox NEO-6M/7M/8M). These have 3.3 V TTL output, so they
     need either `GPSPORT ... INVERTED` or a small MAX3232 level-shifter board
     (see polarity below).

   A **USB** GPS mouse does not work: the TNC has no USB host.
2. **Power for the GPS.** The KPC-3+ does not supply power on the radio or computer port
   (jumpers J6/J7 make pin 7 / pin 13 a power *input* to the TNC, not an output).
   Feed the GPS from the same 12 V battery through a 5 V regulator (a 7805 or a small
   buck module), or use a GPS that takes 12 V directly.
3. **A Y cable on the radio port DE-9.** Pin 2 is in the same connector as the radio
   audio and PTT, so the GPS data wire has to join the existing radio cable.
4. A GPS antenna with a view of the sky.

## Wiring

KPC-3+ radio port (female DE-9 on the TNC, from the Kantronics pinout sheet):

| Pin | Signal | Use |
|---|---|---|
| 1 | TXA | audio to radio (existing) |
| **2** | **XCD** | **GPS data in** (external carrier detect, or GPS input with `GPSPORT`) |
| 3 | PTT | to radio (existing) |
| 5 | RXA | audio from radio (existing) |
| **6** | **GND** | **GPS signal ground** |
| 7 | EXT-IN | power/reset input (J6/J7), leave alone |
| 9 | GND / RESET | ground by default (J5) |

Connect:

```
GPS  TX / "NMEA out" / "data out"  ->  radio port pin 2 (XCD)
GPS  signal ground                 ->  radio port pin 6 (GND)
GPS  RX (if any)                   ->  leave unconnected
GPS  power                         ->  your 5 V / 12 V supply, not the TNC
```

The TNC only listens. It cannot send anything to the GPS on this pin, so the GPS must
already be set to 4800 baud with `RMC` output (most are by default; a u-blox module can
be set once with u-center and saved to flash).

If the GPS has a DB-9 plug: on a GPS (DCE wired) the data comes out on DB-9 **pin 2**
and ground is **pin 5**. On some pucks it is pin 3; check with the GPS manual or a
multimeter (the data pin flickers around -5 V idle on RS-232 units).

### Polarity: NORMAL or INVERTED

- `NORMAL`: RS-232 polarity (idle negative, e.g. -5 V). Use for real RS-232 GPS units.
- `INVERTED`: "true TTL" polarity (idle high, e.g. +3.3 V or +5 V). Use for bare UART
  modules like the NEO-6M, or put a MAX3232 in between and keep `NORMAL`.

If the setting is wrong, nothing arrives (or only garbage), and the `CHECKSUM` option
drops it all.

## TNC settings

On top of the current fill-in digipeater setup (`fillin-beacon`):

```
XMITOK OFF
GPSPORT 4800 NORMAL CHECKSUM   GPS on radio port pin 2, 4800 baud, valid checksums only
GPSHEAD 1 $GPRMC               copy each $GPRMC sentence into LT 1
LTP 1 APN391 VIA WIDE2-1       (already set) destination and path of LT 1
BLT 1 EVERY 00:30:00           (already set) beacon LT 1 every 30 minutes
GPSTIME VALID RMC              (factory default) set the TNC clock from valid RMC
CD SOFTWARE                    (already set) pin 2 must not be used as carrier detect
XMITOK ON
```

Notes on these:

- `APN391` is the Kantronics destination for firmware 9.1; on 8.3 it is `APN383`
  (`kpc3-setup.py` picks the right one).
- With `GPSHEAD 1` set, the GPS overwrites `LT 1` each time an RMC sentence arrives.
  The fixed `!5233.26N/...` text that `fillin-beacon` writes there is replaced as
  soon as the GPS has a fix, so no need to clear it first.
- The beacon is then the raw NMEA sentence (`$GPRMC,...`). That is a valid APRS
  position format, but it carries no symbol and no comment. The APRS spec lets a raw
  NMEA station pick its symbol through a `GPSxyz` destination instead of `APN391`
  (look up the code for the digi symbol in the APRS 1.0.1 spec, chapter 20, before
  using it).
- `CD` must stay `SOFTWARE` (or `INTERNAL`). With `CD EXTERNAL` pin 2 is read as
  carrier detect, which clashes with the GPS input.
- The GPS also keeps the TNC clock on UTC (`GPSTIME`). `kpc3-clock.py set` is then
  only needed without GPS; note the GPS sets UTC, not local time.
- To turn the GPS input off again: `GPSPORT 0`.
- In KISS mode the TNC does not beacon on its own, so the GPS input makes no sense
  there; keep `GPSPORT 0`.

## Checking it works

```sh
./kpc3-setup.py show - /dev/ttyUSB0 | grep -A4 -E '^(GPSPORT|GPSHEAD|LT )'
```

With a fix, `LT 1` shows a fresh `$GPRMC,...,A,...` sentence (the `A` means valid
data; `V` means no fix yet) and `DAYTIME` follows UTC. Then watch for the beacon on
aprs.fi or with a second receiver.

## Gotchas

- **`$GNRMC` vs `$GPRMC`**: newer u-blox and other multi-GNSS modules send `$GNRMC`.
  Firmware 8.3 (1999 era) may only match `GPSHEAD` exactly, so either set
  `GPSHEAD 1 $GNRMC` or configure the module to GPS-only / NMEA 2.x talker ID `GP`.
  Untested here.
- No checksum from the GPS: use `GPSPORT 4800 NORMAL NOCHECK`.
- Any GPS baud rate other than 4800 has to be set on both sides.
- `GPSHEAD n %` stores a literal `%`; to clear it send `GPSHEAD n` with no value
  (see the firmware quirks in the README).

## Sources

- [Kantronics KPC-3+ port pinout sheet](https://kantronics.com/wp-content/uploads/2018/08/kpc3ppinout.pdf)
  (radio port pin 2 = XCD / alternate GPS input, jumpers J5 to J10)
- [KPC-3 Plus User's Guide, "Connecting to a GPS device"](https://www.manualslib.com/manual/907164/Kantronics-Kpc-3-Plus.html?page=53)
  (alternate input on the radio port with firmware 8.3, `GPSPORT`)
- [KPC-3 Plus User's Guide, GPS operations](https://www.manualslib.com/manual/907164/Kantronics-Kpc-3-Plus.html?page=95)
  (`INTFACE GPS`, `GPSINIT`, LT buffers updated from NMEA)
- [KC APRS TNC settings](https://kcaprs.org/Config.html)
  (8.3/9.0: GPS on DE-9 pins 2 and 6, `GPSPORT 4800 NORMAL CHECKSUM`, `INTFACE TERMINAL`)
- [KPC-3 / KPC-3+ for APRS (UA6HJQ)](http://goryham.qrz.ru/pr/aprs/aprs-kpc.htm)
  (`GPSHEAD 1 $GPRMC` example)
- [N4OB: Streetfinder GPS on a KPC-3](https://www.qsl.net/n4ob/street.htm)
  (external 5 V regulator for GPS power)
