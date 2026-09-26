# /// script
# requires-python = ">=3.10"
# dependencies = ["pyserial>=3.5"]
# ///
"""SCPI terminal for the nanovolt divider over USB serial.

    uv run tools/scpi.py                      # interactive, COM8
    uv run tools/scpi.py -p COM8 "*IDN?" "SYST:MODE?"
    uv run tools/scpi.py --errors "RANG 1E-6" # also drain SYST:ERR? after each command

Lines the firmware prints starting with '#' (boot banner, DIAG:TRAC pulse trace) are shown as
comments, never taken as a query's response. Opening the port resets the ESP32 on most CYD
boards (DTR/RTS wiring), so the tool waits for the '# ready' banner before sending anything.
"""
from __future__ import annotations

import argparse
import sys
import time

import serial


class Instrument:
    def __init__(self, port: str, timeout: float = 3.0):
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = 115200
        self.ser.timeout = timeout
        # Keep EN / IO0 released so opening the port does not hold the chip in reset.
        self.ser.dtr = False
        self.ser.rts = False
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
