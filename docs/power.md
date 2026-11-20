# Power and batteries

The KPC-3 Plus can hold two batteries, and they do different jobs:

| Battery | Holder | Keeps | Fitted |
|---|---|---|---|
| CR2032 lithium coin cell | clip holder on the board | RAM (settings, PBBS messages) and the optional real-time clock | yes, from the factory |
| 9 V block | clip soldered to the `+BATT-` pads near the power jack | the whole TNC (modem, CPU, LEDs) | no, optional |

The clock and the settings only need the coin cell. **No jumper makes the 9 V
battery a clock-only backup**: when it is connected it always runs the whole
unit, which empties a 9 V block within hours.

## Jumpers J1 and J2 (9 V battery)

| J1 | J2 | Behaviour |
|---|---|---|
| OFF (one leg) | ON (both legs), factory default | The 9 V battery runs the TNC when the external power plug is removed; jack P3 cuts it off while the plug is in. |
| ON | OFF | Backup supply: whichever is higher (battery or external) runs the TNC. Diode CR2 keeps the external voltage off the battery. |

With the default setting the battery starts draining as soon as the plug is
pulled. For a TNC that lives on a mains supply, leave the 9 V battery
disconnected. Use J1 ON / J2 OFF only to keep a digi on the air through power
cuts, and then with a battery much bigger than a 9 V block.

## Coin cell

- Healthy at about 3 V. A weak cell can lose settings or corrupt the clock
  (e.g. an hour reading `45`; `kpc3-clock.py set` fixes the value, a recurring
  fault points to the cell).
- Removing it erases everything: the TNC reverts to factory defaults and the
  PBBS messages are gone. Before replacing it:

```sh
./kpc3-backup.py backup /dev/ttyUSB0
# replace the CR2032, positive side against the top clip of the holder
./kpc3-backup.py restore /dev/ttyUSB0 backups/kantronics-KPC3P-9.1-<date>.txt
./kpc3-clock.py set /dev/ttyUSB0 --utc
```

## Sources

- KPC-3 Plus User's Guide (v8.2): "Internal Power, from a Battery" (p. 39),
  jumpers J1/J2 in "KPC-3 Plus Jumpers", "Replacing the Lithium Battery" (p. 275),
  [PDF](https://www.rigpix.com/textandimaging/kantronics_kpc3plus_manual.pdf)
