# Bang dialect (MX160, MX170, MX180)

**Status: not yet confirmed on hardware with this library, and partly guessed.** Built from the command names and
reply formats in the hass-mcintosh project, which marks the MX160 as tested and the MX170 and MX180 as untested.
We found no McIntosh document for this protocol. Everything about how the unit answers *set* commands and
errors is an assumption, and is flagged so below.

## Link
- RS-232 at 115200 baud (9600 is also reported to work), or the network port, TCP 84. Lines end with CR.
- Commands start with `!`; parameters sit in parentheses.

## Commands the library uses
| Command | Reply |
|---|---|
| `!DEVICE?` | `!DEVICE(MX160)` |
| `!POWER?` | `!POWER(1)` |
| `!VOL?` | `!VOL(40)` |
| `!MUTE?` | `!MUTE(0)` |
| `!SRC?` | `!SRC(1) "HDMI 2"` |
| `!ZVOL?`, `!ZMUTE?`, `!ZSRC?` | the same for zone 2, with a `Z` prefix |
| `!PING?` | `!PONG` |
| `!VERB(2)` | sent once when connecting, as the other project does; reply unknown |
| `!PON`, `!POFF` | power (reply unknown) |
| `!VOL(n)`, `!VOL+`, `!VOL-` | volume (reply unknown) |
| `!MUTEON`, `!MUTEOFF` | mute (reply unknown) |
| `!SRC(n)` | input (reply unknown) |
| `!ZVOL(n)`, `!ZMUTEON`, `!ZSRC(n)` | zone 2 |

## What is assumed
- **Set commands accept any reply line.** The library completes a set command on whichever line the unit sends
  next, because the reply format is not documented. The state still updates from the lines it understands.
- **Errors look like `!ERR(n)`.** Nothing confirms this.
- **Only the power query is required.** The other queries are optional, so a unit that does not answer one still starts.
- **Zone 2 power is refused.** The other project reads zone 2 power with `!POWERZONE2?` but parses the reply as
  `!POWER(`, which would collide with zone 1, so the library raises `ValueError` until someone captures the real reply.
- **No full-status command is known**, so the state is loaded with one query per value.

## Not implemented
Bass and treble trim, loudness, lip-sync, channel trims, maximum-volume query (MX170/MX180).
