"""The ``mcintosh-serial`` command: list models, detect a unit's command style, record a capture.

Everything here sends only the library's startup commands and harmless queries, never a
command that changes volume, input, mute or power. The ``capture`` output is meant to be
pasted into a "new device" issue, so serial numbers are hidden unless you ask otherwise.
"""

import argparse
import asyncio
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

from mcintosh_serial.capture import (
    RecordingTransport,
    Report,
    events_to_jsonl,
    redact_events,
)
from mcintosh_serial.client import Client, Timing
from mcintosh_serial.detect import COMMON_BAUDRATES, detect
from mcintosh_serial.dialects import DIALECTS, get_dialect
from mcintosh_serial.errors import McIntoshConnectionError, McIntoshError
from mcintosh_serial.profiles import get_profile, load_profiles
from mcintosh_serial.transport import Transport, open_serial

if TYPE_CHECKING:
    from collections.abc import Sequence

_CAPTURE_TIMING = Timing(command=2.0, query=4.0, power=4.0, settle=0.4, settle_max=2.0)


def _version() -> str:
    try:
        return metadata.version("mcintosh-serial")
    except metadata.PackageNotFoundError:  # pragma: no cover - not installed
        return "unknown"


def _describe_link(url: str) -> str:
    """Name the kind of link without revealing a host name or device path."""
    return url.split("://", 1)[0] if "://" in url else "serial device"


async def _open(url: str, baudrate: int) -> Transport:
    return await open_serial(url, baudrate)


def _models() -> int:
    print(f"{'ID':<8} {'STATUS':<9} {'DIALECT':<7} NAME")
    for profile in load_profiles().values():
        print(
            f"{profile.id:<8} {profile.status:<9} {profile.dialect:<7} {profile.name}"
        )
    return 0


async def _detect(url: str, baudrates: Sequence[int], dialects: Sequence[str]) -> int:
    print(
        f"Trying {len(baudrates) * len(dialects)} combinations (harmless commands only)..."
    )
    found = await detect(lambda baud: _open(url, baud), baudrates, dialects or None)
    if not found:
        print(
            "No answer. Check the cable (try the TX/RX switch or a null-modem adapter),"
        )
        print("that RS-232 control is enabled on the unit, and the baud rate.")
        return 1
    for hit in found:
        print(
            f"ANSWERED  dialect={hit.dialect}  baud={hit.baudrate}  reply={hit.reply!r}"
        )
    models = sorted(
        p.id
        for p in load_profiles().values()
        if p.dialect in {h.dialect for h in found}
    )
    print(f"Models using these command styles: {', '.join(models)}")
    return 0


async def _capture(args: argparse.Namespace) -> int:
    if args.model:
        profile = get_profile(args.model)
        dialect_name, baudrate, model = (
            profile.dialect,
            args.baud or profile.baudrate,
            profile.id,
        )
        timing = profile.timing
    else:
        if not args.dialect or not args.baud:
            print("Give either --model, or both --dialect and --baud.")
            return 2
        dialect_name, baudrate, model, timing = (
            args.dialect,
            args.baud,
            "unknown",
            _CAPTURE_TIMING,
        )

    recorder = RecordingTransport(await _open(args.url, baudrate))
    client = Client(recorder, get_dialect(dialect_name), timing)
    client.begin()
    await asyncio.sleep(args.listen)  # listen first: some units announce themselves
    try:
        await client.start()
        zones = ", ".join(
            f"zone {n}: {state}" for n, state in sorted(client.state.zones.items())
        )
        outcome = f"The unit answered and its state loaded. {zones}"
    except McIntoshConnectionError:
        # The OSError text can name the host or device path, which the report must not show.
        outcome = "Startup failed: the connection failed or was closed."
    except McIntoshError as err:
        outcome = f"Startup failed: {err}"
    await client.stop()

    raw = tuple(recorder.events)
    events = raw if args.no_redact else redact_events(raw)
    out = Path(args.out or f"mcintosh-capture-{model}.jsonl")
    await asyncio.to_thread(out.write_text, events_to_jsonl(events), encoding="utf-8")
    report = Report(
        _version(),
        model,
        dialect_name,
        baudrate,
        _describe_link(args.url),
        outcome,
        events,
    )
    print(
        report.render(redact_serial=False)
    )  # events are already redacted unless asked
    print(f"Capture file (attach it to the issue): {out}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line."""
    parser = argparse.ArgumentParser(prog="mcintosh-serial", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "models", help="list the supported models and how well each is tested"
    )

    find = commands.add_parser("detect", help="find which command style a unit speaks")
    find.add_argument(
        "url", help="serial device path or URL, e.g. /dev/ttyUSB0 or socket://host:port"
    )
    find.add_argument(
        "--baud", type=int, action="append", help="baud rate to try (repeatable)"
    )
    find.add_argument(
        "--dialect",
        action="append",
        choices=sorted(DIALECTS),
        help="only try this style",
    )

    cap = commands.add_parser(
        "capture", help="record a safe session to share in an issue"
    )
    cap.add_argument("url", help="serial device path or URL")
    cap.add_argument(
        "--model", help="a known model id (see `models`) to use its settings"
    )
    cap.add_argument(
        "--dialect",
        choices=sorted(DIALECTS),
        help="command style, for a model not listed",
    )
    cap.add_argument("--baud", type=int, help="baud rate (defaults to the model's)")
    cap.add_argument(
        "--listen",
        type=float,
        default=3.0,
        help="seconds to listen before sending (default 3)",
    )
    cap.add_argument(
        "--out", help="capture file to write (default mcintosh-capture-<model>.jsonl)"
    )
    cap.add_argument(
        "--no-redact",
        action="store_true",
        help="keep the serial number in the report and the capture file",
    )

    args = parser.parse_args(argv)
    if args.command == "models":
        return _models()
    if args.command == "detect":
        return asyncio.run(
            _detect(args.url, args.baud or COMMON_BAUDRATES, args.dialect or ())
        )
    return asyncio.run(_capture(args))
