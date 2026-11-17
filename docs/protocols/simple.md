# Simple dialect (MA352, MA5300)

**Status: not yet confirmed on hardware with this library.** Built from McIntosh's "MA5300 External Control Rev A"
and the notes of the mcintosh-ma352-hass project, whose author tested a real MA352 (firmware 1.07). Anything
marked *reported* below comes from those, not from us.

## Link
- 3.5 mm TRS jack: tip = TX (from the unit), ring = RX (to the unit), sleeve = ground. 8N1, no flow control.
- Baud rate is set in the unit's setup menu: 9600, 19200, 38400, 57600 or 115200 (default 115200).

## Framing
- Commands are `(NAME parameter)`. A trailing CR is accepted (the library sends one).
- The unit echoes the command as its acknowledgement and pushes the same frames when its state changes, if status
  reporting is on (`(STA 1)`). On first power-up it announces itself: `(MA5300)`, `(Serial Number: ...)`,
  `(FW Version: ...)`.
- Errors are `(ERROR - Invalid Command)`, `(ERROR - Invalid Parameter)`, `(ERROR - Invalid Input)`,
  `(ERROR - In Passthru)` or `(ERROR - Unknown Error)`. The library reports the text after the dash as the error code.

## Commands the library uses
| Command | Effect |
|---|---|
| `(QRY)` | Full status. In standby only product information and `(PWR 0)` are returned. |
| `(PWR 1)` / `(PWR 0)` | Power. |
| `(VOL n)` / `(VOL U)` / `(VOL D)` | Volume 0-100 %, or one step up or down. |
| `(MUT 1)` / `(MUT 0)` | Mute. |
| `(INP n)` | Input; numbers depend on the model (see the model files). |
| `(STA 1)` | Push status changes. The library sends it only if `(QRY)` reported `(STA 0)`. |

## Behavior to design around (reported for the MA352)
- After power-on the unit is unresponsive for about 16 s. Commands sent meanwhile are queued, not dropped.
- Absolute volume changes ramp in 1 % steps and every step is pushed, so the library waits for the target value.
- A `VOL` set that leaves the value unchanged is not acknowledged, so the library does not send one.
- Relative commands are acknowledged with the resulting absolute value.
- Back-to-back commands are all processed in order; there is no rate limit.
- There is no passthrough status, and the unit ignores volume while in passthrough.
- In standby every command except `PWR` returns `(ERROR - Invalid Command)`.
- Meter lights use `TML` on firmware 1.07, not `TTM` as documented (the library does not use either).

## Not implemented
Trim, tone, balance, phono settings, display brightness, output switches, headphone state.
