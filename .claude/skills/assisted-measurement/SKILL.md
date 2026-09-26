---
name: assisted-measurement
description: Start an assisted bench measurement session with the Raspberry Pi workbench and the Pico probe. Checks the tools first, connects over ssh, starts the workbench server, watches the Pico, and guides the operator through curves and algorithm runs. Use when the user wants to measure panels on the real converter, start a bench session, or check the bench before a session.
---

# Assisted measurement

You guide an operator through one bench session. The operator does all
physical work (wires, jumpers, lamp, panel tilt). You do the checks, the
server, the monitors and the analysis.

## Rules

1. **No private data in files, commits or PRs.** Never write a host name, IP
   address, user name, home path, key path, serial number, place name or
   session id into a repo file, commit message or PR text. Refer to the Pi
   only as `$PI` (an ssh alias that lives in the operator's own ssh config).
   Ask for the alias once. Do not print it into the repo.
2. **Ask before any action that changes hardware or state**: flashing the
   Pico, restarting the server, deleting data, pulling code on the Pi.
   Approval for one action is not approval for the next.
3. **Never raise a limit.** `v_max` 40 V, `i_max` 1 A, `v_out_max` 25 V and the
   sweep cutoffs (700 mA, 16.1 W) protect the board. If a limit trips, find
   the cause. A debounce or a filter is a separate, agreed change.
4. **Do not run the hardware yourself.** The operator starts sweeps and
   runs in the workbench. You watch and report.
5. Keep replies short. Report facts, then one recommendation.

## Step 0: ask the operator

- The ssh alias for the Pi (`$PI`).
- Setup: **Single** (one panel) or **Full** (two panels in series).
- Which panels, the output load (ohm and watt rating), the light.
- The ADC jumpers: all four shorted = `Low`, one per side shorted = `Mid`,
  none = `Full` (see `docs/hardware_v1/calibration.md`).

Power limit: all panel power ends in the load. Keep the peak power at the
MPP under 80 % of the load's watt rating. For a 10 W resistor that is 8 W.

## Step 1: check the tools on the laptop

Run this and report each line. Do not install anything without asking.

```bash
for t in ssh rsync curl python3 uv gh cargo rustup probe-rs; do
  command -v "$t" >/dev/null && echo "ok      $t" || echo "MISSING $t"
done
rustup target list --installed 2>/dev/null | grep -q thumbv6m-none-eabi \
  && echo "ok      rust target thumbv6m-none-eabi" || echo "MISSING rust target thumbv6m-none-eabi"
probe-rs list 2>&1 | head -5
```

Hints if something is missing: `cargo install probe-rs-tools`,
`rustup target add thumbv6m-none-eabi`, `uv` from its install page. No
debug probe listed: ask the operator to check the USB cable and the probe
wires.

## Step 2: ssh to the Pi

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI" 'echo connected'
```

"Permission denied (publickey)" from a Claude Code shell usually means the
shell does not see the ssh agent. Look for its socket
(`ls "$XDG_RUNTIME_DIR"/keyring/`) and prefix the command with
`SSH_AUTH_SOCK=<socket>`. Do not print or copy any key.

Send multi-line work as a script on stdin: `ssh "$PI" 'bash -s' < script.sh`.

## Step 3: check the Pi

Find the repo checkout on the Pi first (`ls -d ~/*/mpp_sdk ~/mpp_sdk`), then:

```bash
vcgencmd get_throttled            # must be 0x0
command -v uv git                 # both needed
ls /dev/spidev0.0                 # SPI must exist
cd <repo> && git status --short && git fetch -q && git log --oneline -1 && git rev-list --count HEAD..origin/main
```

- `get_throttled` not `0x0`: stop. Under-voltage can stall SPI and abort
  runs. The operator must fix the supply. The lamp needs its own supply.
- Repo behind `origin/main`: ask, then `git pull --ff-only`.
- Local changes on the Pi: name them to the operator. Never discard them.

## Step 4: the workbench server

It is started by hand, not as a service. A Pi reboot stops it.

```bash
ss -ltn | grep :8000; curl -s -m 3 localhost:8000/api/data | head -c 200
```

Start it (first start is slow, wait up to about a minute):

```bash
cd <repo>
setsid nohup ~/.local/bin/uv run mpp-sdk curve-tracer-web > ~/curve_tracer_web.log 2>&1 < /dev/null &
```

Restart only when idle: `/api/runs/live` status is not `running` and
`/api/data` `active` is false. Check again right before you stop it, and ask
the operator first: a run started in that gap is lost. Never put
`pkill -f "mpp-sdk curve-tracer-web"` in the ssh command string, because it
matches its own shell. Send it on stdin with the bracket trick
`pkill -f "[m]pp-sdk curve-tracer-web"`.

Tell the operator to open the workbench on port 8000 of the Pi.

## Step 5: the Pico and the probe

The probe is on the laptop. Firmware sources are in
`firmware/pipico_board`.

1. The constant `ADC_DIVIDER_RANGE` in `src/main.rs` must match the jumpers.
   A mismatch makes the on-chip ADC and V out read wrong (about 32 % low
   for Full jumpers with a Mid constant). V and I come from the INA229 and
   stay right.
2. To flash (only after the operator says yes, and after you stop any
   `probe-rs attach` monitor):
   `cargo build --release --locked` then
   `timeout 25 probe-rs run --chip RP2040 target/thumbv6m-none-eabi/release/mpp-firmware`.
   Read the boot log: range line, INA229 ready.
3. Check: the log line `ADC_PWR=... (INA229 V=...)` must agree within 1 %.
   Then `probe-rs read b32 --chip RP2040 0xE000EDF0 1`: the core must not
   be halted (bit 17 clear).
4. The firmware has no version readout. Write the commit you flashed, and
   any local edit, in the session's firmware field.

A killed `probe-rs run` can leave the core halted: check DHCSR as above.
The probe sometimes drops with an ARM error. The board keeps running. Use
a loop that reattaches.

## Step 6: monitors

Use narrow filters. A filter that passes every log line floods and is
stopped.

- Pico log: `probe-rs attach ... | grep -E "ERROR|panic|fault|booted|sweep aborted|[2-9] consecutive"`
  in a `while true` loop with `sleep 5`.
- Pi: every 5 s print `vcgencmd get_throttled` and the run status and abort
  reason from `/api/runs/live`; print only when the text changes.

One "1 consecutive" SPI frame timeout warning at idle is normal.

## Step 7: the session, curve then run

1. Header on Single or Full. New session from the matching template. Fill
   the fields (panel, light, load, ADC range, firmware commit, operator).
2. Do the check steps. Set skipped steps to skipped with a reason.
3. Light check: one sweep. Isc under 0.7 A and peak power under the
   watt-rating limit above. Dim the light if not. Then keep the light and
   the lamp distance fixed for the whole session.
4. Alternate: a fresh curve, then one algorithm run on that curve.
   - Pick the **Reference curve** in the run form every time. It resets.
   - Start duty: near the MPP duty, not 0.5. From the curve, take the MPP
     V and I, then `R_in = V / I` and `D = 1 / (1 + sqrt(R_in / R_load))`.
   - Record panel tilt in the tilt form before each Full-mode sweep.
5. After each run, report: aborted or not and why, held power over the last
   30 % against the reference curve's MPP power, the duty range, and the
   number of `ignored ... suspect reading` lines the server log gained.
6. Stop and tell the operator if: a sweep aborts at a cutoff, a run aborts
   as `link-down`, the load or Q3 is too hot to touch, or the input voltage
   collapses. Do not retry until the cause is known.

Known problems (see `data/bench/` reports if present): corrupted readings
that trip the limits, P&O oscillating at a very fast step rate, InCond and
Fuzzy collapsing to the duty floor. Mention them when the results look bad.

## Step 8: wrap up

1. The operator exports the session file and downloads full runs from the
   Runs list (the export cuts each run to 2000 samples).
2. Copy the needed `data/curves` and `data/runs` files to a scratch folder
   on the laptop. Do not delete data on the Pi without asking.
3. Undo any temporary edit you made on the Pi (`git status` there).
4. Before sharing anything, follow `data/README.md` and `AGENTS.md`:
   - Keep only what is needed. Do not commit under `data/curves`, `data/runs`
     or `data/sessions` (git-ignored). Use a new folder under `data/bench/`.
   - Cut time stamps to the date, rewrite labels, empty the notes, null the
     session ids, drop time stamps from file names.
   - Grep the staged diff for `API_KEY`, `password`, `token`, `secret`, IP
     addresses, `.local`, `/home/`.
   - Write PR text without host names, users, paths or bench layout.
