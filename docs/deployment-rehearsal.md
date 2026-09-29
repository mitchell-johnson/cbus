# Staging rehearsal

This is an offline rehearsal of the P11.03 deployment checks (issue #70). It
is not closure evidence. It exercises the image, broker, CNI transport and
rollback paths against the Rust PCI simulator and a throwaway Mosquitto
broker. It cannot replace the live coexistence checks, physical CNI fault
injection, long PP activity or power-loss recovery that the issue requires.

## In-process system tests

`rust/cmqttd/tests/system_resilience.rs` runs the real `cmqttd` binary against
the in-process mini broker and scripted fake PCI:

| Test | Behavior pinned |
|---|---|
| `broker_restart_resubscribes_and_republishes_discovery` | The broker crashes and returns with no sessions, subscriptions or retained messages. cmqttd reconnects, resubscribes `homeassistant/light/+/set`, republishes byte-identical meta and light discovery, and retains bridge state `ON`. The fake PCI answers no sweep, so cmqttd has observed no light state; it publishes none and repeats no startup sweep. A post-restart bus event is retained, and a post-restart command reaches the PCI exactly once. |
| `broker_restart_republishes_observed_light_state` | After bus observations of a labelled and an unlabelled group and a PCI-confirmed command echo, the broker crashes with its retained store. On reconnect cmqttd republishes the unlabelled group's lazy discovery and exactly those six light and binary-sensor states, retained and byte-identical, once each. It fabricates no state for unobserved groups and repeats no startup sweep. |
| `cni_tcp_drop_exits_and_supervisor_restart_recovers` | Plain `-t` CNI mode has no in-process reconnect. When TCP is lost, cmqttd retains bridge state `OFF` and exits 0. The Docker `restart: always` policy supplies recovery. A fresh process with the same arguments re-initializes the PCI, repeats the configured sweep and retains `ON`. Discovery is unchanged, and commands resume. ESP32 discovery modes reconnect in-process; `esp32_wifi_mode_reconnects_and_reinitialises` covers that path. |
| `two_client_mqtt_fanout_under_event_burst` | Two independent MQTT subscribers each receive all 120 light-state publishes from a back-to-back burst of 120 bus events, in bus order and identical to the daemon's publish sequence. The events are 60 instant ramps of one group, interleaved with 60 ON/OFF toggles of another. |

`MiniBroker::restart` in `cbus-test-support` simulates the crash. It reuses
`disconnect_clients` to drop client sockets without DISCONNECT, then discards
retained messages and subscriptions while the listener stays on the same
port.

After an MQTT reconnect, cmqttd republishes the last retained light and
binary-sensor state it published for each group. Only bus observations and
PCI-confirmed command echoes produce that state, so nothing is fabricated.
Groups it never observed stay absent until the next observation or the periodic
`-S` status resync (300 s by default in the container). C-Bus transport loss
clears this cache along with the lazy-discovery record, because the reconnect
sweep re-observes the bus.

The deployed Python daemon gives no precedent here. Its dispatcher exited on
an MQTT error and never reconnected in-process, and a supervisor restart
re-swept the bus. cmqttd stays up and keeps observing C-Bus while the broker
is away, so its last published states are current evidence. Republishing them
restores what the broker held without adding bus traffic.

## Docker staging stack

`deploy/staging/docker-compose.staging.yml` defines the following services on
an `internal` compose network:

- **cmqttd**, from an image built by `git archive` of the candidate revision.
  It uses `restart: always`, a named state volume for `cgate.json`, and the
  committed synthetic `rust/testdata/fixtures/project.xml`.
- **Mosquitto** with anonymous access and persistence disabled.
- **`cbus-simulator`** on TCP port 10001.

The stack has no `container_name`, published ports, `env_file` or credentials.
`deploy/staging/rehearse.sh` always passes a unique project name
(`cbus-staging-<utc>-<pid>`) and refuses any other prefix. Its containers,
network, volume and image tags therefore cannot collide with the production
`cbus` stack.

```sh
deploy/staging/rehearse.sh --dry-run   # print the plan, touch nothing
deploy/staging/rehearse.sh             # needs a responsive Docker daemon
PREVIOUS_IMAGE=cmqttd:rollback-tag deploy/staging/rehearse.sh
```

The script runs four phases and removes the stack, volume and built tags on
exit:

1. It builds the candidate (`CANDIDATE_REV`, default `HEAD`) and previous
   (`PREVIOUS_REV`, default `HEAD~1`) images, then starts the candidate. It
   checks for retained bridge state, meta and light discovery, `/set` receipt
   by cmqttd and the C-Gate `201` banner, then records the `cgate.json`
   SHA-256.
2. It kills and restarts the broker. It then checks that discovery and bridge
   state are republished, that after one resync interval the retained light
   state matches the set held before the kill exactly (republished, none
   fabricated), and that the command wildcard is live.
3. It restarts the simulator, which drops the CNI TCP connection. It checks
   that Docker's restart count increases and repeats the phase 1 checks.
4. It rolls back to the previous image on the same state volume, then rolls
   forward to the candidate. Phase 1 checks run after each step, and the
   `cgate.json` hash must match phase 1.

The receipt defaults to a file in `$TMPDIR`. It records revisions, image IDs,
restart counts, state hashes and `PASS`/`FAIL`/`XFAIL`/`XPASS` results. It
contains no hostnames or credentials. The exit status is non-zero on any
`FAIL`.

### Resolved simulator confirmation gap

`cbus-simulator` locally echoes basic-mode input terminated by CR only, such
as `~\r` and `|\r`, before cmqttd's smart connect takes effect. cmqttd's
from-PCI framer used to wait for CRLF, so the echo stayed buffered. The
simulator answers no lighting status sweep, so no CRLF frame arrived to flush
it. Every later PCI confirmation, such as `h.`, was lost, and commands ended
`delivery: uncertain` after three attempts.

The framer was wrong. Native C-Gate 3.4's PCI receiver thread ends a line at
CR or LF, whichever comes first, and discards empty lines. It also recognizes
confirmations anywhere in the stream. cmqttd now ends from-PCI lines the same
way. A CR that is the last buffered byte waits for one more byte, so a CRLF
split across reads still counts as one terminator. The `fp-cr-*` and `fp-lf-*`
rows of `rust/testdata/vectors/decode_from_pci.jsonl` pin this. The in-process
`basic_mode_echo_does_not_hold_back_command_confirmation` test in
`cmqttd/tests/system_commands.rs` runs cmqttd against a fake PCI with
simulator-style echo. The command is confirmed on its first transmission. The
simulator's echo bytes stay pinned by `cbus-simulator/tests/system_sim.rs`.
Real-PCI echo bytes remain uncaptured here.

PCI-confirmed delivery is therefore a hard check by default.
`EXPECT_SIM_CONFIRM_GAP=1` restores `XFAIL` handling for an image built before
the fix, such as a rollback target. This change has not yet been rehearsed
with Docker.

## Recorded runs

| Date (UTC) | Revision | Mode | Result |
|---|---|---|---|
| 2026-09-29 | worktree `work/resilience-staging` on `8f128b21` | `--dry-run` | 25 check lines printed, 4 of them expected `XFAIL`s. Docker was unavailable at the time. |
| 2026-09-29 | candidate `fd1d6e6b`, previous `a901ff0a` | Docker 29.6.1 (aarch64), Compose v5.3.0 | 21 `PASS`, 4 `XFAIL` (the known confirmation gap), 0 `FAIL`, exit 0. The broker kill republished discovery and bridge state without fabricating light state, and the command wildcard was live. The simulator restart raised cmqttd's Docker restart count from 0 to 1 and recovered. The rollback container ran the previous image ID, and the roll forward ran the candidate. The `cgate.json` SHA-256 was the same after first start, rollback and roll forward. Teardown left no `cbus-staging-*` containers, networks, volumes or `cmqttd-staging` tags. Other containers on the host kept running. |

Two earlier real runs on the same day failed only the C-Gate banner check. The
cause was a script bug: `grep -q` closed the pipe early, and under `pipefail`
the resulting SIGPIPE failed the `docker exec` pipeline. The check now captures
the greeting before matching it. The in-process tests passed 25/25 in
`system_resilience`, and the three new tests passed three consecutive runs
after rebasing onto `a901ff0a`.
