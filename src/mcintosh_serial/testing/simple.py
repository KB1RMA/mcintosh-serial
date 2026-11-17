"""In-process emulation of an MA352/MA5300-style amplifier (the simple dialect).

Modeled on the behavior reported for the MA352 (firmware 1.07) and on McIntosh's
MA5300 external control document, not on a unit we have: it is as good as those
sources. In standby only (QRY) and (PWR) are answered, the unit is unresponsive
for a while after power-on, volume changes ramp in 1 % steps that are each pushed,
and a set to the value the unit already has is not acknowledged for some commands.
"""

import re
from typing import override

from mcintosh_serial.testing._base import FakeUnit

_COMMAND_RE = re.compile(r"\(([^()]*)\)")
_INFO = ("MA352", "Serial Number: AHW0001", "FW Version: 1.07")
_RANGES = {"PWR": (0, 1), "VOL": (0, 100), "MUT": (0, 1), "INP": (1, 6), "STA": (0, 1)}
_SILENT_WHEN_UNCHANGED = frozenset({"VOL", "STA"})
_BOOT_SECONDS = 16.0
_RAMP_GAP = 0.02
_ERR_COMMAND = "ERROR - Invalid Command"
_ERR_PARAMETER = "ERROR - Invalid Parameter"
_STEPS = {"U": 1, "D": -1}


class FakeMA352(FakeUnit):
    """A fake MA352 that implements the client's transport interface."""

    drops_when_busy = (
        False  # no rate limit: back-to-back commands are processed in order
    )

    def __init__(self, time_scale: float = 0.01) -> None:
        super().__init__(time_scale)
        self.values = {"PWR": 1, "VOL": 22, "MUT": 0, "INP": 1, "STA": 1}
        self.received: list[str] = []

    @override
    def _split(self, text: str) -> tuple[list[str], str]:
        commands = _COMMAND_RE.findall(text)
        return commands, text[text.rfind(")") + 1 :] if commands else text

    async def _emit(self, *frames: str) -> None:
        for frame in frames:
            await self._emit_raw(f"({frame})\r\n")

    def _status_frames(self) -> list[str]:
        return [f"{name} {value}" for name, value in self.values.items()]

    # ------------------------------------------------- front-panel actions
    async def front_panel_volume(self, level: int) -> None:
        """Simulate turning the knob: the unit pushes the new level if status reporting is on."""
        self.values["VOL"] = level
        if self.values["STA"]:
            await self._emit(f"VOL {level}")

    # ------------------------------------------------------------ commands
    @override
    async def _dispatch(self, command: str) -> None:
        self.received.append(command)
        tokens = command.split()
        name = tokens[0].upper() if tokens else ""
        parameter = tokens[1] if len(tokens) > 1 else None
        if name == "QRY":
            await self._emit(*_INFO)
            if self.values["PWR"]:
                await self._emit(*self._status_frames())
            else:
                await self._emit("PWR 0")
        elif name == "PWR":
            await self._power(parameter)
        elif not self.values["PWR"] or name not in _RANGES:
            await self._emit(_ERR_COMMAND)
        else:
            await self._set(name, parameter)

    async def _power(self, parameter: str | None) -> None:
        if parameter is None:
            await self._emit(f"PWR {self.values['PWR']}")
        elif parameter in ("0", "1"):
            turning_on = parameter == "1" and not self.values["PWR"]
            self.values["PWR"] = int(parameter)
            await self._emit(f"PWR {parameter}")
            if turning_on:
                self.values["MUT"] = 0
                await self._emit(*_INFO, *self._status_frames())
                await self._sleep(_BOOT_SECONDS)  # commands sent meanwhile queue up
        else:
            await self._emit(_ERR_PARAMETER)

    async def _set(self, name: str, parameter: str | None) -> None:
        if parameter is None:
            await self._emit(f"{name} {self.values[name]}")
            return
        target = self._target(name, parameter)
        low, high = _RANGES[name]
        if target is None or not low <= target <= high:
            await self._emit(_ERR_PARAMETER)
        elif target == self.values[name]:
            if name not in _SILENT_WHEN_UNCHANGED:
                await self._emit(f"{name} {target}")
        elif name == "VOL":
            await self._ramp(target)
        else:
            self.values[name] = target
            await self._emit(f"{name} {target}")

    def _target(self, name: str, parameter: str) -> int | None:
        if name in ("VOL", "INP") and parameter in _STEPS:
            return self.values[name] + _STEPS[parameter]
        return int(parameter) if parameter.lstrip("-").isdigit() else None

    async def _ramp(self, target: int) -> None:
        """Volume moves in 1 % steps and every step is pushed."""
        step = 1 if target > self.values["VOL"] else -1
        while self.values["VOL"] != target:
            self.values["VOL"] += step
            await self._emit(f"VOL {self.values['VOL']}")
            await self._sleep(_RAMP_GAP)
