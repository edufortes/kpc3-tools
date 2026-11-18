# APRS telemetry on the KPC-3+

Firmware 8.2 and later (so also 8.3) can send APRS telemetry on its own: the
`TELEMTRY` command (spelled like that, 8 letters) beacons the readings of the two
analog inputs at a fixed interval. Use it to report e.g. the battery voltage and the
temperature of a portable digipeater. None of this is automated by `kpc3-setup.py` yet.

## What the TNC offers

- **Two analog inputs, AN0 and AN1**: 0 to 5 V DC, 8 bits, read as a number 0 to 255
  (one step is 5 / 255 = 19.6 mV).
- **`ANALOG`** reads all 8 A/D lines now: `AN0/AN1/AN2/AN3/AN4/AN5/AN6/AN7`. Only the
  first two are external inputs; the others are unused or internal (AN6/AN7 are the RTS
  and DTR lines of the serial port). There is no built-in channel for the TNC's own
  supply voltage or temperature: both need an external connection.
- **`TELEMTRY n`** (0 to 255, default 0 = off) sends a telemetry beacon every
  n x 10 seconds, so at most every 2550 s (42.5 min). Examples: `TELEMTRY 60` = 10 min,
  `TELEMTRY 180` = 30 min.

The beacon is a UI frame to the destination `BEACON`, sent via the digipeater path of
`UNPROTO` (the destination part of `UNPROTO` is ignored), with the data:

```
T#nnn,an0,an1,an2,an3,an5,bbbbbbbb
```

`nnn` counts 001 to 999 and wraps to 000 (restarts at 001 after a reset). The 8 bits
are the logic levels of the CPU's PORT E, which is the same port as the analog inputs,
so they carry no extra information here. This is the standard APRS telemetry format,
so aprs.fi and other clients decode and graph it.

## Hardware: enable the inputs

Out of the box the inputs read nothing useful: jumpers **J8** (AN0) and **J10** (AN1)
are parked "off to the side". A quick `ANALOG` on this TNC returned
`26/29/24/...` and `25/28/24/...`, which looks like floating, unconnected inputs.

Open the case and set each jumper:

| Input | Jumper on centre + pin 1 | Jumper on centre + pin 2 |
|---|---|---|
| AN0 | J8: radio port DE-9 **pin 4** | J8: computer port DB-25 **pin 18** |
| AN1 | J10: radio port DE-9 **pin 8** | J10: computer port DB-25 **pin 11** |

Ground: radio port pin 6, or DB-25 pin 7.

Which side to use:

- **Radio port (pins 4 and 8)**: these pins are also the `CTRL B` / `CTRL A` open-drain
  outputs. Keep `CTRL A OFF` and `CTRL B OFF` (the default), otherwise the input is
  pulled to ground and reads 0. If the GPS is also on the radio port, all sensor and GPS
  wires end up in one DE-9 Y cable.
- **Computer port (pins 18 and 11)**: free on a normal serial cable, so a DB-25
  breakout or pass-through adapter between the TNC and the USB-serial cable works and
  keeps the radio cable untouched.

Rules for every input:

- **Never more than 5 V, never negative.** Put a 1 kΩ resistor in series and a 5.1 V
  zener (or a BAT54S clamp to 0 V / 5 V) at the pin when the source can exceed 5 V.
- Keep the source impedance low (a few kΩ) and add a 100 nF capacitor from the pin to
  ground against RF pickup from the transmitter.
- Sensors need power from outside: the TNC has no 5 V output. The same 5 V regulator
  that powers the GPS (see [gps.md](gps.md)) works.
- The A/D reference is the TNC's internal 5 V, so calibrate against a multimeter
  rather than trusting the nominal scale.

## Example sensors

### Battery voltage (AN0)

A voltage divider from the 12 V supply: **10 kΩ** to the input, **2.4 kΩ** from the
input to ground.

```
+12 V ──[10k]──┬──[1k]── AN0
               │
             [2.4k]   (+100 nF across the 2.4k)
               │
              GND
```

The divider factor is 2.4 / 12.4 = 0.1935, so 25.5 V gives 4.94 V (count 252):

```
volts = count x 0.101     (0.1 V per step, 0 to 25.5 V)
```

Measure the battery with a multimeter, compare with the `ANALOG` count and adjust the
0.101.

### Temperature (AN1)

A **TMP36** (or MCP9700A) is the simplest: 3 pins (+5 V, output, GND), output
0.5 V at 0 °C plus 10 mV per °C, range -40 to +125 °C, no negative voltages.

```
count x 19.6 mV = V ;  temp °C = (V - 0.5) x 100
temp °C = count x 1.961 - 50
```

The 8-bit converter gives about **2 °C per step**. That is fine for "is the box
overheating", not for a weather station. For 1 °C or better, amplify the sensor
output with an op-amp (gain 2 to 3), or use a 10 kΩ NTC thermistor in a divider and a
quadratic fit in `EQNS`.

Avoid the LM35 (it needs a negative supply below 0 °C) and the LM335 (2.73 V at 0 °C
leaves only ~2 °C per step anyway and needs a bias resistor).

## TNC settings

With battery on AN0, temperature on AN1, and the callsign `DL7EDU-10`:

```
XMITOK OFF
UNPROTO BEACON VIA WIDE2-1                     path for the telemetry frames
TELEMTRY 180                                   T# frame every 30 minutes
LT 2 :DL7EDU-10:PARM.Battery,Temp              channel names
LT 3 :DL7EDU-10:UNIT.Volts,deg.C               channel units
LT 4 :DL7EDU-10:EQNS.0,0.101,0,0,1.961,-50,0,1,0,0,1,0,0,1,0
LTP 2 APN383 VIA WIDE2-1
LTP 3 APN383 VIA WIDE2-1
LTP 4 APN383 VIA WIDE2-1
BLT 2 EVERY 02:00:00 START 00:05:00            definitions every 2 hours
BLT 3 EVERY 02:00:00 START 00:06:00
BLT 4 EVERY 02:00:00 START 00:07:00
XMITOK ON
```

How it fits together:

- The `T#` frame only carries raw counts. APRS clients get names, units and scaling
  from three messages the station sends **to itself** (addressee padded to 9
  characters; `DL7EDU-10` is exactly 9): `PARM.`, `UNIT.` and `EQNS.`.
  The TNC has no command for these, but the location-text buffers `LT 2` to `LT 4`
  send any text as the packet data, so they carry the messages. `LT 1` stays the
  position beacon from `fillin-beacon`.
- `EQNS` has 5 triples `a,b,c` (value = a x count² + b x count + c), one per channel in
  frame order: AN0, AN1, AN2, AN3, AN5. Above: battery `0,0.101,0`, temperature
  `0,1.961,-50`, the three unused channels `0,1,0`.
- `PARM` and `UNIT` can list fewer than 5 names; the unused channels still appear in
  the frame (with noise), clients just show them without a name. An optional
  `BITS.` message is not useful here since the bits mirror the analog port.
- With a GPS (see [gps.md](gps.md)), only `GPSHEAD 1` is set, so `LT 2` to `LT 4` are
  not overwritten. Do not set `GPSHEAD 2` to `4` together with this.
- Mind the channel load: with this setup the digi sends one position and one
  telemetry frame every 30 minutes, plus three short messages every 2 hours.

## Checking it works

```
ANALOG          raw counts now, compare with a multimeter
TELEMTRY        shows the interval
```

Then search the callsign on aprs.fi: the "telemetry" link shows the graphs once at
least one `T#` frame and the `PARM`/`UNIT`/`EQNS` messages have been heard.

## Sources

- KPC-3 Plus User's Guide (v8.2), command reference for
  [`ANALOG`, `TELEMTRY`, `CTRL` and jumpers J8/J10](https://www.rigpix.com/textandimaging/kantronics_kpc3plus_manual.pdf)
- [Kantronics KPC-3+ port pinout sheet](https://kantronics.com/wp-content/uploads/2018/08/kpc3ppinout.pdf)
- [WB4APR: KPC-3+ telemetry channels and battery monitor](https://www.aprs.org/kpc3/kpc3-tlm.txt)
  (10k/2.4k divider for 0.1 V per count)
- [WB4APR: KPC-3 telemetry on RAFT/ANDE](https://www.aprs.org/ande/KPC3-telemetry.txt)
  (frame format, PORT E bits)
- [APRS protocol spec, chapter 13: telemetry](https://aprs-protocol-specification.pages.dev/markitdown/18-telemetry-data)
  (`T#`, `PARM`, `UNIT`, `EQNS`, `BITS`)
