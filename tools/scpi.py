# /// script
# requires-python = ">=3.10"
# dependencies = ["pyserial>=3.5"]
# ///
"""SCPI terminal for the nanovolt divider over USB serial.

    uv run tools/scpi.py                      # interactive, COM8
    uv run tools/scpi.py -p COM8 "*IDN?" "SYST:MODE?"
    uv run tools/scpi.py --errors "RANG 1E-6" # also drain SYST:ERR? after each command
    uv run tools/scpi.py --fetch /nvd/cal_history.txt cal_history.txt   # copy a file off the SD card

Lines the firmware prints starting with '#' (boot banner, DIAG:TRAC pulse trace) are shown as
comments, never taken as a query's response. Opening the port resets the ESP32 on most CYD
boards (DTR/RTS wiring), so the tool waits for the '# ready' banner before sending anything.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import serial


class Instrument:
    def __init__(self, port: str, timeout: float = 3.0):
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = 115200
        self.ser.timeout = timeout
        # The CYD's auto-reset circuit pulls EN low while RTS is asserted and DTR is not. Opening
        # must never pass through that state (a reset re-runs the boot safe state):
        # - Windows applies both lines together at open; released/released has been verified.
        # - Linux asserts both at open(), then pyserial updates DTR before RTS, so releasing them
        #   passes through RTS-only = reset. Leave both asserted there (no transition at all).
        #   Unverified on the Pi yet: check SYST:BOOT:COUNT? across reconnects.
        asserted = os.name == "posix"
        self.ser.dtr = asserted
        self.ser.rts = asserted
        self.ser.open()
        self.wait_ready()

    def wait_ready(self, seconds: float = 8.0) -> None:
        """Waits for '# ready' if the board is booting; returns early if it is already running."""
        deadline = time.monotonic() + seconds
        saw_output = False
        while time.monotonic() < deadline:
            line = self._readline(0.5)
            if line is None:
                if not saw_output:
                    return  # quiet: already booted
                continue
            saw_output = True
            print(line, file=sys.stderr)
            if line.strip() == "# ready":
                return

    def _readline(self, timeout: float) -> str | None:
        self.ser.timeout = timeout
        raw = self.ser.readline()
        if not raw:
            return None
        return raw.decode("utf-8", "replace").rstrip("\r\n")

    def write(self, cmd: str) -> None:
        self.ser.write((cmd + "\n").encode())

    def query(self, cmd: str, timeout: float = 5.0) -> str:
        self.write(cmd)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._readline(deadline - time.monotonic())
            if line is None:
                break
            if line.startswith("#"):
                print(line, file=sys.stderr)
                continue
            return line
        raise TimeoutError(f"no response to {cmd!r}")

    def send(self, cmd: str) -> str | None:
        """Query if the header ends in '?' (any command in a ';' line), otherwise write, then
        sync with *OPC? so the command has finished before returning."""
        if "?" in cmd:
            return self.query(cmd)
        self.query(cmd + ";*OPC?")
        return None

    def query_block(self, cmd: str, timeout: float = 10.0) -> bytes:
        """Query returning an IEEE 488.2 definite-length block (#<n><len><bytes>).

        Unsolicited comment lines are '# ...' (hash, space); a block starts with '#' and a digit,
        so the two cannot be confused even though the payload may itself contain newlines.
        """
        self.write(cmd)
        self.ser.timeout = timeout
        while True:
            b = self.ser.read(1)
            if not b:
                raise TimeoutError(f"no block in response to {cmd!r}")
            if b != b"#":
                raise ValueError(f"unexpected byte {b!r} in response to {cmd!r}")
            d = self.ser.read(1)
            if d.isdigit():
                n = int(self.ser.read(int(d)))
                data = self.ser.read(n)
                if len(data) != n:
                    raise TimeoutError(f"block truncated: {len(data)} of {n} bytes")
                self.ser.readline()  # the terminating newline
                return data
            print("#" + (d + self.ser.readline()).decode("utf-8", "replace").rstrip(), file=sys.stderr)

    def fetch(self, path: str, chunk: int = 65536) -> bytes:
        """Reads a whole file from the SD card in chunks of MMEM:DATA?."""
        out = b""
        while True:
            part = self.query_block(f'MMEM:DATA? "{path}",{len(out)},{chunk}')
            out += part
            if len(part) < chunk:
                return out

    def errors(self) -> list[str]:
        out = []
        while True:
            e = self.query("SYST:ERR?")
            if e.startswith("0,"):
                return out
            out.append(e)

    def drain(self) -> None:
        """Prints any unsolicited '#' lines (pulse trace) waiting in the buffer."""
        while (line := self._readline(0.1)) is not None:
            print(line, file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--port", default="COM8")
    ap.add_argument("--errors", action="store_true", help="drain SYST:ERR? after each command")
    ap.add_argument("--fetch", nargs=2, metavar=("REMOTE", "LOCAL"), help="copy a file off the SD card")
    ap.add_argument("commands", nargs="*")
    args = ap.parse_args()

    inst = Instrument(args.port)

    def run(cmd: str) -> None:
        try:
            r = inst.send(cmd)
        except TimeoutError as e:
            print(f"!! {e}")
            return
        if r is not None:
            print(r)
        inst.drain()
        if args.errors:
            for e in inst.errors():
                print(f"!! {e}")

    if args.fetch:
        remote, local = args.fetch
        try:
            data = inst.fetch(remote)
        except TimeoutError:  # a missing file answers with an error, not a block
            data = b""
        errs = inst.errors()
        if errs:
            for e in errs:
                print(f"!! {e}")
            return 1
        with open(local, "wb") as f:
            f.write(data)
        print(f"{remote}: {len(data)} bytes -> {local}", file=sys.stderr)
        return 0

    if args.commands:
        for c in args.commands:
            print(f"> {c}", file=sys.stderr)
            run(c)
        return 0

    print("SCPI terminal, empty line or Ctrl-C to quit", file=sys.stderr)
    args.errors = True
    try:
        while cmd := input("> ").strip():
            run(cmd)
    except (EOFError, KeyboardInterrupt):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
