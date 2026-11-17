"""Capture, replay, detection and the command line, all against emulated units."""

import asyncio
from typing import TYPE_CHECKING, override

import pytest

from mcintosh_serial import Timing, cli, detect as detect_module
from mcintosh_serial.capture import (
    Event,
    RecordingTransport,
    Report,
    events_from_jsonl,
    events_to_jsonl,
    redact,
)
from mcintosh_serial.detect import detect
from mcintosh_serial.testing import (
    FakeMA352,
    FakeMX119,
    ReplayMismatchError,
    ReplayTransport,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mcintosh_serial.transport import Transport

FAST = Timing(
    command=0.1, query=0.3, power=0.5, settle=0.02, settle_max=0.2, retry_delay=0.01
)


class Silent:
    """A unit that never says anything."""

    def __init__(self) -> None:
        self._out: asyncio.Queue[bytes] = asyncio.Queue()

    async def read(self) -> bytes:
        return await self._out.get()

    async def write(self, data: bytes) -> None:
        """Accept and ignore everything."""

    async def close(self) -> None:
        await self._out.put(b"")


@pytest.fixture(autouse=True)
def fast_probe_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect_module, "_PROBE_TIMING", FAST)
    monkeypatch.setattr(cli, "_CAPTURE_TIMING", FAST)


# ----------------------------------------------------------------- captures
def test_events_survive_a_round_trip_including_odd_bytes() -> None:
    events = (Event("tx", "(QRY)"), Event("rx", "\x00(PON Z1)\r\n\xff", 1.25))
    assert events_from_jsonl(events_to_jsonl(events)) == events


def test_serial_numbers_are_redacted() -> None:
    assert redact("(Serial Number: AFP1234)") == "(Serial Number: <redacted>)"
    assert redact("(PWR 1)") == "(PWR 1)"


async def test_a_recording_transport_notes_both_directions() -> None:
    unit = FakeMX119(rs232_enabled=True)
    recorder = RecordingTransport(unit)
    await recorder.write(b"(QRY)")
    assert (await asyncio.wait_for(recorder.read(), 1)).startswith(b"(PON Z1)")
    await recorder.close()
    assert await recorder.read() == b""  # EOF is not recorded as data
    assert [e.direction for e in recorder.events] == ["tx", "rx"]
    assert recorder.events[0].data == "(QRY)"


def test_the_report_hides_serial_numbers_unless_asked() -> None:
    report = Report(
        "1.0",
        "ma352",
        "simple",
        115200,
        "socket",
        "ok",
        (Event("rx", "(Serial Number: A1)"),),
    )
    assert "A1" not in report.render()
    assert "A1" in report.render(redact_serial=False)
    empty = Report("1.0", "x", "simple", 9600, "serial device", "no answer", ())
    assert "nothing was sent" in empty.render()


# ------------------------------------------------------------------- replay
async def test_replay_delivers_a_banner_and_then_answers_each_command() -> None:
    replay = ReplayTransport(
        (Event("rx", "(MA352)\r\n"), Event("tx", "(QRY)"), Event("rx", "(PWR 1)\r\n"))
    )
    assert await replay.read() == b"(MA352)\r\n"
    assert not replay.finished
    await replay.write(b"(QRY)")
    assert await replay.read() == b"(PWR 1)\r\n"
    assert replay.finished
    assert "0 steps left" in repr(replay)
    await replay.close()
    assert await replay.read() == b""


async def test_replay_accepts_a_command_split_across_writes() -> None:
    replay = ReplayTransport((Event("tx", "(QRY)"), Event("rx", "ok")))
    await replay.write(b"(QR")
    await replay.write(b"Y)")
    assert await replay.read() == b"ok"


async def test_replay_names_what_it_expected_when_the_command_differs() -> None:
    replay = ReplayTransport((Event("tx", "(QRY)"), Event("rx", "ok")))
    with pytest.raises(ReplayMismatchError, match=r"expects '\(QRY\)'"):
        await replay.write(b"(PON Z1)")


async def test_replay_rejects_commands_after_the_capture_ended() -> None:
    replay = ReplayTransport((Event("tx", "(QRY)"),))
    await replay.write(b"(QRY)")
    with pytest.raises(ReplayMismatchError, match="after the capture ended"):
        await replay.write(b"(QRY)")


# ---------------------------------------------------------------- detection
async def test_detect_finds_the_zoned_dialect_at_the_right_baud_rate() -> None:
    async def open_at(baud: int) -> Transport:
        return FakeMX119() if baud == 9600 else Silent()

    hits = await detect(open_at, (115200, 9600))
    assert [(h.dialect, h.baudrate) for h in hits] == [("zoned", 9600)]


async def test_detect_finds_the_simple_dialect_and_not_the_others() -> None:
    async def open_at(_baud: int) -> Transport:
        return FakeMA352()

    hits = await detect(open_at, (115200,))
    assert [h.dialect for h in hits] == ["simple"]
    assert "MA352" in hits[0].reply or "PWR" in hits[0].reply


async def test_detect_counts_an_error_reply_as_an_answer() -> None:
    async def open_at(_baud: int) -> Transport:
        return FakeMA352()

    unit = FakeMA352()
    unit.values["PWR"] = (
        0  # standby: the unit answers (QRY), and rejects other commands
    )

    async def standby(_baud: int) -> Transport:
        return unit

    hits = await detect(standby, (115200,), ("simple",))
    assert hits
    zoned_on_simple = await detect(open_at, (115200,), ("zoned",))
    assert zoned_on_simple == []  # an MA352 does not echo (CTL 1); it rejects it


async def test_detect_counts_an_error_reply_as_an_answer_and_says_so() -> None:
    class Rejecting(Silent):
        @override
        async def write(self, data: bytes) -> None:
            await self._out.put(b"!ERR(5)\r")

    async def open_at(_baud: int) -> Transport:
        return Rejecting()

    hits = await detect(open_at, (115200,), ("bang",))
    assert [(h.dialect, h.reply) for h in hits] == [("bang", "error reply: 5")]


# --------------------------------------------------------------- command line
def test_the_models_command_lists_every_profile(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["models"]) == 0
    out = capsys.readouterr().out
    assert "mx119" in out
    assert "verified" in out
    assert "ma5300" in out


def test_detect_command_reports_a_hit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_open(_url: str, _baud: int) -> Transport:
        return FakeMX119()

    monkeypatch.setattr(cli, "open_serial", fake_open)
    assert cli.main(["detect", "x", "--baud", "9600", "--dialect", "zoned"]) == 0
    out = capsys.readouterr().out
    assert "ANSWERED  dialect=zoned  baud=9600" in out
    assert "mx119" in out


def test_detect_command_explains_what_to_check_when_nothing_answers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_open(_url: str, _baud: int) -> Transport:
        return Silent()

    monkeypatch.setattr(cli, "open_serial", fake_open)
    assert cli.main(["detect", "x", "--baud", "9600", "--dialect", "zoned"]) == 1
    assert "TX/RX switch" in capsys.readouterr().out


def test_capture_command_writes_a_redacted_report_and_a_capture_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    async def fake_open(_url: str, _baud: int) -> Transport:
        return FakeMA352()

    monkeypatch.setattr(cli, "open_serial", fake_open)
    out_file = tmp_path / "cap.jsonl"
    assert (
        cli.main(
            [
                "capture",
                "socket://example:4001",
                "--model",
                "ma352",
                "--listen",
                "0.01",
                "--out",
                str(out_file),
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert "AHW0001" not in printed
    assert "<redacted>" in printed
    assert "Link: socket" in printed
    assert "example" not in printed  # the host name is not revealed
    assert (
        "AHW0001" in out_file.read_text()
    )  # the file attached to the issue keeps raw bytes
    assert events_from_jsonl(out_file.read_text())


def test_capture_command_can_show_the_serial_number(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    async def fake_open(_url: str, _baud: int) -> Transport:
        return FakeMA352()

    monkeypatch.setattr(cli, "open_serial", fake_open)
    args = [
        "capture",
        "x",
        "--model",
        "ma352",
        "--listen",
        "0",
        "--out",
        str(tmp_path / "c.jsonl"),
        "--no-redact",
    ]
    assert cli.main(args) == 0
    assert "AHW0001" in capsys.readouterr().out


def test_capture_command_reports_a_unit_that_does_not_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    async def fake_open(_url: str, _baud: int) -> Transport:
        return Silent()

    monkeypatch.setattr(cli, "open_serial", fake_open)
    args = [
        "capture",
        "x",
        "--dialect",
        "zoned",
        "--baud",
        "9600",
        "--listen",
        "0",
        "--out",
        str(tmp_path / "c.jsonl"),
    ]
    assert cli.main(args) == 0
    assert "Startup failed" in capsys.readouterr().out


def test_capture_command_needs_a_model_or_a_dialect_and_baud(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["capture", "x"]) == 2
    assert "--model" in capsys.readouterr().out


def test_python_dash_m_runs_the_command_line(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import runpy  # noqa: PLC0415
    import sys  # noqa: PLC0415

    monkeypatch.setattr(sys, "argv", ["mcintosh-serial", "models"])
    with pytest.raises(SystemExit) as info:
        runpy.run_module("mcintosh_serial", run_name="__main__")
    assert info.value.code == 0
    assert "mx119" in capsys.readouterr().out
