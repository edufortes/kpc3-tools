"""Shared serial access and firmware detection for the Kantronics KPC-3 Plus tools."""

import re
import time

import serial

BAUDS = (9600, 1200, 19200, 4800, 2400, 300)
KISS_EXIT = b"\xc0\xff\xc0"
# Parameters holding a password: never printed (the TNC echoes the old value too)
SECRET = {"RTEXT"}
ERROR_MARKS = ("not available", "Input ignored", "out of range")


def is_secret(line):
    name, _, value = line.strip().partition(" ")
    return name.upper() in SECRET and value.strip() not in ("", "%")


def mask(line):
    """A command or DISPLAY line as it may be shown, password hidden."""
    if is_secret(line):
        return f"{line.split()[0]} ********"
    return line


class TNCError(Exception):
    pass


class TNC:
    def __init__(self, port, verbose=True):
        self.port = port
        self.verbose = verbose
        self.ser = None

    def log(self, msg):
        if self.verbose:
            print(msg, flush=True)

    def open(self, baud):
        if self.ser:
            self.ser.close()
        self.ser = serial.Serial(self.port, baud, timeout=0.2)
        self.baud = baud

    def read_for(self, seconds, until=None):
        """Read for up to `seconds`, stop early when a pattern in `until` shows up."""
        buf = b""
        end = time.time() + seconds
        while time.time() < end:
            data = self.ser.read(4096)
            if data:
                buf += data
                text = buf.decode("latin1")
                if until and any(p in text for p in until):
                    # Give the TNC a moment to finish the line
                    time.sleep(0.1)
                    buf += self.ser.read(4096)
                    break
        return buf.decode("latin1")

    def probe(self, baud):
        self.open(baud)
        self.ser.reset_input_buffer()
        self.ser.write(b"\r")
        return "cmd:" in self.read_for(1.0, until=["cmd:"])

    def find(self, preferred):
        """Locate the TNC's command prompt, whatever state it is in."""
        bauds = [preferred] + [b for b in BAUDS if b != preferred]
        for baud in bauds:
            if self.probe(baud):
                self.log(f"TNC found at {baud} baud")
                return
        # Maybe in KISS mode or a connected/converse session: try to break out
        for baud in bauds:
            self.open(baud)
            self.ser.write(KISS_EXIT)
            time.sleep(0.3)
            self.ser.write(b"\x03")
            time.sleep(2.5)
            if self.probe(baud):
                self.log(f"TNC found at {baud} baud (after KISS exit / Ctrl-C)")
                return
        # Maybe waiting for autobaud
        self.open(preferred)
        if self.autobaud(timeout=8):
            return
        raise TNCError(f"no response from TNC on {self.port}")

    def autobaud(self, timeout=30, mycall=None):
        """After a default restore the TNC waits for '*' to learn the baud rate."""
        self.log(f"Autobaud: sending '*' at {self.baud} baud")
        end = time.time() + timeout
        buf = ""
        while time.time() < end:
            self.ser.write(b"*")
            buf += self.read_for(1.0, until=["cmd:", "callsign", "CALLSIGN"])
            if "callsign" in buf.lower() and mycall:
                self.log("TNC asks for callsign")
                self.ser.write(mycall.encode() + b"\r")
                buf += self.read_for(3, until=["cmd:"])
            if "cmd:" in buf:
                self.log(buf.strip())
                # Settle and make sure we have a clean prompt
                time.sleep(0.5)
                self.ser.reset_input_buffer()
                return self.probe(self.baud)
        return False

    def cmd(self, line, timeout=3, check=True, quiet=False):
        self.ser.reset_input_buffer()
        self.ser.write(line.encode("latin1") + b"\r")
        resp = self.read_for(timeout, until=["cmd:"])
        body = resp.replace("\r", "").replace("cmd:", "").strip()
        # Drop the echoed command line
        lines = [l for l in body.split("\n") if l.strip() and l.strip() != line]
        errors = [l for l in lines if l.strip().startswith(("?", "EH?")) or any(e in l for e in ERROR_MARKS)]
        # For a password only error messages are shown, never the echoed old value
        hide = line.split()[0].upper() in SECRET if line.strip() else False
        shown, shown_lines = mask(line), (errors if hide else lines)
        if not quiet:
            self.log(f"> {shown}" + (f"   [{' | '.join(shown_lines)}]" if shown_lines else ""))
        if check and errors:
            raise TNCError(f"TNC rejected '{shown}': {' | '.join(errors)}")
        if "cmd:" not in resp and check:
            raise TNCError(f"no prompt after '{shown}'")
        return "\n".join(lines)

    def reset(self):
        """Soft reset (needed for INTFACE changes), wait for the prompt, return the banner."""
        self.ser.reset_input_buffer()
        self.ser.write(b"RESET\r")
        self.log("> RESET")
        banner = self.read_for(6, until=["cmd:"])
        for _ in range(5):
            if self.probe(self.baud):
                return banner
            time.sleep(1)
        raise TNCError("TNC did not come back after RESET")

    def factory_reset(self, baud, mycall):
        self.log("> RESTORE DEFAULT")
        self.ser.write(b"RESTORE DEFAULT\r")
        time.sleep(4)
        self.read_for(1)
        self.open(baud)
        if not self.autobaud(timeout=40, mycall=mycall):
            raise TNCError("autobaud after RESTORE DEFAULT failed")


def send_clock(tnc, utc=False):
    """Send DAYTIME yymmddhhmmss right at a second boundary, so the TNC clock
    starts in step with the host. Returns the time that was sent."""
    now = time.time()
    target = int(now) + 1 if now % 1 < 0.8 else int(now) + 2
    time.sleep(max(0.0, target - time.time()))
    stamp = time.gmtime(target) if utc else time.localtime(target)
    tnc.cmd("DAYTIME " + time.strftime("%y%m%d%H%M%S", stamp))
    return stamp


def set_clock(tnc, utc=False):
    # Not fatal during setup if the firmware disagrees
    try:
        send_clock(tnc, utc)
    except TNCError as e:
        tnc.log(f"warning: could not set clock ({e})")


# --- firmware detection --------------------------------------------------------

BANNER_RE = re.compile(r"KANTRONICS\s+(\S+)\s+VERSION\s+(\S+)")
NAME_RE = re.compile(r"^([0-9A-Z]{2,8})( +|$)")
# Parameters whose value is free text: taken verbatim, never trimmed
TEXT = {"BTEXT", "CTEXT", "HTEXT", "NTEXT", "PTEXT", "RTEXT", "CWIDTEXT", "GPSINIT", "DAYSTR"}
# Parameters shown as numbered sub-lines (1..4)
MULTI = {"BLT", "GPSHEAD", "LT", "LTP"}

# DISPLAY parameter names per firmware, taken from real dumps. Only used offline
# (--dry-run --firmware); with a TNC attached its own DISPLAY is the reference.
PARAMS_83 = frozenset("""
    8BITCONV ABAUD AUTOLF AX25L2V2 AXDELAY AXHANG BEACON BKONDEL BLT BREAK BTEXT
    BUDLIST CANLINE CANPAC CD CHECK CMDTIME CMSG COMMAND CONLIST CONMODE CONOK
    CONPERM CPACTIME CR CRSUP CSTAMP CTEXT CTRL CWID CWIDTEXT DAMA DAMACHCK DAYSTR
    DAYTIME DAYTWEAK DBLDISC DELETE DIGIPEAT DWAIT ECHO ESCAPE FILTER FLOW FRACK
    FULLDUP GPSHEAD GPSINIT GPSPORT GPSTIME HBAUD HEADERLN HID HTEXT INTFACE
    KNTIMER LCOK LEDS LFADD LFSUP LGETCHAR LLIST LT LTP LTRACK MALL MAXFRAME
    MAXUSERS MBEACON MCOM MCON MHEADER MONITOR MRESP MRPT MSTAMP MXMIT MYALIAS
    MYCALL MYDGPS MYDROP MYNODE MYPBBS MYREMOTE NDWILD NEWMODE NOMODE NTEXT
    NUMNODES PACLEN PACTIME PASS PASSALL PBBS PBFORWRD PBHEADER PBHOLD PBKILLFW
    PBLIST PBLO PBPERSON PBREVERS PERSIST PID PMODE PTEXT REDISPLA RELINK RETRY
    RING RNRTIME RTEXT SCREENL SENDPAC SLOTTIME START STOP STREAMCA STREAMEV
    STREAMSW SUPLIST SWP TELEMTRY TRACE TRFLOW TRIES TXDELAY TXFLOW UIDIGI UIDWAIT
    UIFLOOD UITRACE UNPROTO USERS XFLOW XKCHKSUM XKPOLLED XMITLVL XMITOK XOFF XON
""".split())
# 9.1 adds the K-Net node, extra PBBS options, telemetry ranges and UIDUPE
PARAMS_91 = PARAMS_83 | {
    "NETALIAS", "NETBUFFS", "NETCALL", "NETCIRCS", "NETDESTS", "NETLINKS", "NETROUTE",
    "NETUSERS", "PBMAIL", "PBSIZE", "PBUSERS", "RANGE", "UIDUPE",
}
KNOWN_PARAMS = {"8.3": PARAMS_83, "9.1": PARAMS_91}


class Firmware:
    """What a TNC firmware understands: model, version and its DISPLAY parameters.
    params is None when unknown, then nothing is filtered."""

    def __init__(self, model, version, params):
        self.model, self.version, self.params = model, version, params

    def __str__(self):
        return f"{self.model} {self.version}"

    @classmethod
    def offline(cls, version, model="KPC3P"):
        if version not in KNOWN_PARAMS:
            raise TNCError(f"unknown firmware {version} (known: {', '.join(KNOWN_PARAMS)})")
        return cls(model, version, KNOWN_PARAMS[version])

    def supports(self, command):
        return self.params is None or command.split()[0].upper() in self.params

    def split(self, cmds):
        """Return (supported, unsupported) commands."""
        return [c for c in cmds if self.supports(c)], [c for c in cmds if not self.supports(c)]


def display_params(display):
    return {m.group(1) for m in map(NAME_RE.match, display.splitlines()) if m}


# 9.1 prints "KPC3PMX" or "KPC3P" seemingly at random from one reset to the
# next (the suffix depends on a RAM flag), so both mean the same TNC
MODEL_ALIASES = {"KPC3PMX": "KPC3P"}


def parse_banner(banner):
    m = BANNER_RE.search(banner)
    if not m:
        return None, None
    return MODEL_ALIASES.get(m.group(1), m.group(1)), m.group(2)


def identify(tnc, banner=None, reset=True):
    """Detect model, version and supported parameters. The version is only shown
    in the RESET banner (8.3 has no VERSION command); pass reset=False to skip the
    reset, then only the parameter list is known."""
    if banner is None and reset:
        banner = tnc.reset()
    model, version = parse_banner(banner or "")
    display = tnc.cmd("DISPLAY", timeout=40, quiet=True)
    params = display_params(display)
    if "INTFACE  NEWUSER" in display or "UIDIGI" not in params:
        # NEWUSER mode lists only a few parameters: not a usable reference
        tnc.log("warning: TNC is in NEWUSER mode, firmware parameters unknown")
        params = None
    fw = Firmware(model or "?", version or "?", params)
    if version and params is not None and version not in KNOWN_PARAMS:
        tnc.log(f"note: firmware {version} not tested, using the parameters it reports")
    return fw


def parse(text):
    """Turn DISPLAY output into (meta, {key: raw value}); sub-lines get keys like 'LT 1'.
    Also reads hand-written files with one-line entries such as 'LT 1 text'."""
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
        m = re.match(r"^(BLT|GPSHEAD|LTP|LT) ([1-4])(?: (.*))?$", line)
        if m:
            current = None
            settings[f"{m.group(1)} {m.group(2)}"] = m.group(3) or ""
            continue
        m = NAME_RE.match(line)
        if not m:
            continue  # e.g. "A Link state is: ...", "cmd:", monitored packets
        name = current = m.group(1)
        if name in MULTI or name == "DAYTIME":
            continue
        # DISPLAY pads names to 9 columns; keep text values verbatim after that
        settings[name] = line[9:] if m.end() == 9 else line[m.end():]
    return meta, settings


def norm(raw):
    return re.sub(r"\s+", " ", raw.strip())
