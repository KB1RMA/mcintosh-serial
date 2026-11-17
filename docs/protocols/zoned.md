# Zoned dialect (MX119 and similar)

Observed on a McIntosh MX119 A/V control center on 2026-11-16. Nothing here is from
a McIntosh document for this model; it comes from probing a unit. Newer gear that
shares the dialect is described in McIntosh's RS-232 application note (RX0001).

## Link
- DB9, pin 2 TXD (from unit), pin 3 RXD (to unit), pin 5 GND. FTDI USB adapter worked straight through.
- 9600 8N1, no flow control.
- Commands are wrapped in `(` `)`. A trailing CR or CRLF is accepted but not required.
  Unframed input (no parentheses) is silently ignored. A partial command is held until
  the closing `)` arrives, so never leave one dangling.
- Case-insensitive; extra parameters are ignored.
- Replies end in CR/LF. The unit sends one stray `\x00` when power drops.

## Enabling
`(CTL 1)` is echoed back and enables the port. `(QRY)` before it returned `(ERR 1)`. RS232 stayed
enabled across a short power cycle. An `(ERR 1)` to one `(QRY)` right after power-up is transient: retry.

## Commands that work
| Command | Effect | Reply |
|---|---|---|
| `(QRY)` | Full status, 18 lines, ~560 ms to finish | `(PON Z1)` ... |
| `(PON Z1)` / `(POF Z1)` | Zone power | Mute, then status |
| `(VUP Z1)` / `(VDN Z1)` | Volume one step | `(VST Z1 n)` only |
| `(VST Z1 n)` | Set volume | `(VST Z1 n)` only |
| `(MUT Z1 0|1)` | Mute | `(MUT Z1 n)` only |
| `(INP Z1 n)` | Input 0-7 (8, 9 ignored) | Mute, status dump x2, unmute |

Inputs on the MX119 follow the manual: 0 Tuner, 1 PH/AUX, 2 CD(2), 3 SAT, 4 TV, 5 DVD, 6 VCR 1, 7 Tape 1.
They can be relabeled in the unit's menu, so names are per-installation.

## Behavior to design around
- **Push updates:** volume, mute, input and power changes made by hand are pushed immediately; no polling needed after the initial `(QRY)`.
- **Transient mute:** the unit mutes itself around input changes (about 1.5 s) and power-on (about 6 s). Do not treat that as a user mute.
- **Duplicates:** status dumps and mute lines often arrive twice. Compare with current state.
- **Timing:** a command sent while the unit is still sending a reply can be dropped. Wait for the reply to go quiet (about 300 ms) before the next command; allow ~0.6 s after `(QRY)`.
- **Power-on:** `(PON Z1)` works with one send. About 6 s of silence follows. After a power cycle the unit returns in standby.
- **Errors:** `(ERR 1)` unknown command or empty; `(ERR 3)` invalid zone. (The application note says ERR 2 for a bad zone; this unit does not.)
- **Standby:** `(QRY)` still answers in standby.

## Not tested
`(SY0)`, `(HLP)` (answers ERR 1), `(OP1)`/`(OP2)`, `(TRU)`/`(TRD)`, `(KEY)`, Zone 2 commands, volume ceiling, behavior after a long power loss.
