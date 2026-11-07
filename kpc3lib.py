"""Shared serial access for the Kantronics KPC-3 Plus tools (firmware 8.3)."""

import time

import serial

BAUDS = (9600, 1200, 19200, 4800, 2400, 300)
KISS_EXIT = b"\xc0\xff\xc0"


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
        if not quiet:
            self.log(f"> {line}" + (f"   [{' | '.join(lines)}]" if lines else ""))
        if check and any(l.strip().startswith(("?", "EH?")) or "not available" in l or "Input ignored" in l or "out of range" in l for l in lines):
            raise TNCError(f"TNC rejected '{line}': {' | '.join(lines)}")
        if "cmd:" not in resp and check:
            raise TNCError(f"no prompt after '{line}'")
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
