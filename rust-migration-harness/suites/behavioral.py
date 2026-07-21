#!/usr/bin/env python3
"""Behavioral/integration parity suite for cmqttd.

Boots a scripted fake PCI (TCP) and a minimal MQTT 3.1.1 broker, then runs
a cmqttd implementation against both and asserts on observable behaviour:
the PCI init sequence (codeless, and strictly before any other traffic),
HA discovery publishes, the configured codeless status sweep (binary then
level per block), retransmission on missing confirmation, C-Bus event ->
MQTT state flow, level report -> MQTT state flow, clock request handling,
and MQTT command -> C-Bus frame flow.

The oracle is the DEPLOYED (production) daemon's behaviour as verified
against the real CNI: init frames and status requests carry no
confirmation chars, the status sweep covers only the blocks holding the
project file's labelled groups, and non-init traffic waits for init.

Pure stdlib (plus the `cbus` venv only when --impl python is selected).

Usage:
    python3 suites/behavioral.py --impl python
    python3 suites/behavioral.py --impl rust [--rust-bin PATH]

Exit codes: 0 = all assertions passed; 1 = assertion failure(s);
3 = implementation missing / could not start.

NOTE ON TIMING: cmqttd throttles C-Bus commands at one per 0.2s behind
the startup status sweep (4 requests for the fixture project). The
`mqtt-cmd-*` assertions keep generous ceilings but normally complete in
seconds. `--skip-slow` skips them.
"""
import argparse
import asyncio
import json
import os
import sys
import time

HARNESS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(HARNESS_DIR)
sys.path.insert(0, os.path.join(HARNESS_DIR, 'lib'))

from fake_pci import FakePCI  # noqa: E402
from mini_broker import MiniBroker  # noqa: E402

EXPECT = json.load(open(os.path.join(
    HARNESS_DIR, 'fixtures', 'behavioral_expectations.json')))
PROJECT_XML = os.path.join(HARNESS_DIR, 'fixtures', 'project.xml')
LOG_DIR = os.path.join(HARNESS_DIR, 'logs')


class Results:
    def __init__(self):
        self.results = []  # (name, ok, detail)

    def record(self, name, ok, detail=''):
        self.results.append((name, ok, detail))
        status = 'PASS' if ok else 'FAIL'
        msg = f'  [{status}] {name}'
        if detail and not ok:
            msg += f' -- {detail}'
        print(msg, flush=True)

    @property
    def failed(self):
        return [r for r in self.results if not r[1]]


async def wait_for(pred, timeout, interval=0.1):
    """Polls pred() until truthy or timeout. Returns final value."""
    deadline = time.monotonic() + timeout
    while True:
        v = pred()
        if v:
            return v
        if time.monotonic() > deadline:
            return pred()
        await asyncio.sleep(interval)


def latest_publish(broker, topic):
    pubs = broker.find_publishes(topic)
    return pubs[-1] if pubs else None


def json_payload_equals(pub, expected: dict) -> bool:
    if pub is None:
        return False
    try:
        return json.loads(pub.payload) == expected
    except (ValueError, UnicodeDecodeError):
        return False


async def run(impl: str, rust_bin: str, skip_slow: bool) -> int:
    res = Results()
    fake = FakePCI(withhold_first_conf=True)
    broker = MiniBroker()
    await fake.start()
    await broker.start()
    print(f'  fake PCI on 127.0.0.1:{fake.port}, '
          f'mini broker on 127.0.0.1:{broker.port}', flush=True)

    # ---- spawn the implementation under test -----------------------------
    common_args = [
        '-b', '127.0.0.1', '-p', str(broker.port), '--broker-disable-tls',
        '-t', f'127.0.0.1:{fake.port}',
        '-T', '0',
        '-S', '0',  # deterministic single sweep for the assertions below
        '-P', PROJECT_XML,
        '-v', 'DEBUG',
    ]
    if impl == 'python':
        py = os.path.join(REPO_ROOT, '.venv', 'bin', 'python')
        if not os.path.exists(py):
            py = sys.executable
        argv = [py, '-m', 'cbus.daemon.cmqttd'] + common_args
    else:
        if not os.path.exists(rust_bin):
            print(f'  MISSING: Rust implementation not found at {rust_bin}')
            await fake.stop()
            await broker.stop()
            return 3
        argv = [rust_bin] + common_args

    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f'cmqttd-{impl}.log')
    log_fh = open(log_path, 'wb')
    print(f'  spawning: {" ".join(argv)}', flush=True)
    print(f'  cmqttd log: {log_path}', flush=True)
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=REPO_ROOT, stdout=log_fh, stderr=log_fh)

    def proc_alive():
        return proc.returncode is None

    try:
        # ---- PCI init sequence -------------------------------------------
        ok = await wait_for(lambda: fake.connections >= 1, 20)
        res.record('pci-connect', bool(ok),
                   'client never connected to fake PCI')
        if not ok or not proc_alive():
            raise RuntimeError('startup failed')

        ok = await wait_for(lambda: fake.reset_count >= 3, 20)
        res.record('pci-init-reset-x3', bool(ok),
                   f'saw {fake.reset_count} resets, expected >= 3')

        ok = await wait_for(lambda: fake.smart_connect_count >= 1, 10)
        res.record('pci-init-smart-connect', bool(ok),
                   'no | smart-connect shortcut seen')

        def dm_sequence():
            want = [f['payload'] for f in EXPECT['init_frames']
                    if f['payload'].startswith('A3')]
            got = [(r.payload, r.conf) for r in fake.frames
                   if r.payload in want]
            payloads = [g[0] for g in got]
            if payloads[:4] != want:
                return None
            # deployed-faithful: init DM frames carry NO confirmation
            if any(c is not None for _, c in got[:4]):
                return None
            return True
        ok = await wait_for(dm_sequence, 15)
        res.record('pci-init-dm-sequence', bool(ok),
                   f'frames seen: '
                   f'{[(r.payload, r.conf) for r in fake.frames[:12]]}')

        # ---- MQTT startup ------------------------------------------------
        ok = await wait_for(
            lambda: any(c.connected for c in broker.clients), 20)
        res.record('mqtt-connect', bool(ok),
                   f'broker errors: {broker.errors}')
        if not ok:
            raise RuntimeError('mqtt connect failed')

        ok = await wait_for(
            lambda: broker.has_subscription('homeassistant/light/+/set'),
            15)
        res.record('mqtt-subscribe-wildcard', bool(ok),
                   f'subscriptions: {broker.subscriptions[:10]}')

        meta = EXPECT['meta_config']
        ok = await wait_for(
            lambda: json_payload_equals(
                latest_publish(broker, meta['topic']), meta['config']), 15)
        pub = latest_publish(broker, meta['topic'])
        detail = ''
        if not ok:
            detail = f'got: {pub!r}'
        elif not (pub.qos == 1 and pub.retain):
            ok = False
            detail = f'qos={pub.qos} retain={pub.retain}, expected 1/True'
        res.record('meta-config-publish', bool(ok), detail)

        async def check_config(lc):
            got = await wait_for(
                lambda: json_payload_equals(
                    latest_publish(broker, lc['config_topic']),
                    lc['config']), 20)
            return bool(got)
        all_ok, details = True, []
        for lc in EXPECT['label_configs']:
            good = await check_config(lc)
            if not good:
                all_ok = False
                pub = latest_publish(broker, lc['config_topic'])
                details.append(f"{lc['config_topic']}: got {pub!r}")
        res.record('label-configs-publish', all_ok, '; '.join(details))

        # ---- status request traffic --------------------------------------
        # Deployed-faithful: the sweep covers exactly the blocks holding
        # the project file's labelled groups, binary before level per
        # block, apps ascending, all without confirmation chars.
        sweep = EXPECT['configured_sweep']

        def is_status(p):
            return p.startswith('05FF0073') or p.startswith('05FF007A')

        def sweep_done():
            seen = [p for p in fake.payloads() if is_status(p)]
            return True if len(seen) >= len(sweep) else None
        ok = await wait_for(sweep_done, 40)
        seen = [r for r in fake.frames if is_status(r.payload)]
        if ok:
            got = [r.payload for r in seen[:len(sweep)]]
            if got != sweep:
                ok = False
            elif any(r.conf is not None for r in seen):
                ok = False
        res.record('status-requests-configured-sweep', bool(ok),
                   f'expected {sweep}, got '
                   f'{[(r.payload, r.conf) for r in seen[:6]]}')

        # ---- init strictly precedes all other traffic --------------------
        # (a faithful port of the repo Python interleaved status requests
        # into the init sequence, garbling replies on the real CNI)
        def frame_kind(r):
            if r.frame.is_reset or r.frame.is_smart_connect \
                    or r.payload.startswith('A3'):
                return 'init'
            return 'other'
        kinds = [frame_kind(r) for r in fake.frames]
        if 'other' in kinds:
            first_other = kinds.index('other')
            ok = (kinds[:first_other].count('init') >= 8
                  and 'init' not in kinds[first_other:])
        else:
            ok = True
        res.record('init-before-all-traffic', bool(ok),
                   f'frame kinds: {kinds[:16]}')

        # ---- C-Bus event -> MQTT state -----------------------------------
        for key, name in [('inject_lighting_on', 'pci-event-on-to-mqtt'),
                          ('inject_lighting_ramp',
                           'pci-event-ramp-to-mqtt')]:
            exp = EXPECT[key]
            fake.inject(exp['wire'].encode('latin-1'))
            ok = await wait_for(
                lambda: json_payload_equals(
                    latest_publish(broker, exp['state_topic']),
                    exp['state_payload']), 15)
            detail = ''
            if not ok:
                detail = (f"state: got "
                          f"{latest_publish(broker, exp['state_topic'])!r}")
            else:
                sp = latest_publish(broker, exp['sensor_topic'])
                if sp is None or sp.payload.decode() != exp['sensor_payload']:
                    ok = False
                    detail = f'binary sensor: got {sp!r}'
            res.record(name, bool(ok), detail)

        # ---- level report -> MQTT states ---------------------------------
        exp = EXPECT['inject_level_report']
        fake.inject(exp['wire'].encode('latin-1'))

        def all_states():
            for st in exp['expect_states']:
                if not json_payload_equals(
                        latest_publish(broker, st['topic']), st['payload']):
                    return None
            return True
        ok = await wait_for(all_states, 15)
        detail = '' if ok else '; '.join(
            f"{st['topic']}: {latest_publish(broker, st['topic'])!r}"
            for st in exp['expect_states'])
        res.record('level-report-to-mqtt', bool(ok), detail)

        lazy = EXPECT['lazy_config_ga2']
        ok = await wait_for(
            lambda: json_payload_equals(
                latest_publish(broker, lazy['topic']), lazy['config']), 10)
        res.record('lazy-discovery-config', bool(ok),
                   f"got {latest_publish(broker, lazy['topic'])!r}")

        # ---- clock request -> clock update -------------------------------
        exp = EXPECT['inject_clock_request']
        mark = len(fake.frames)
        fake.inject(exp['wire'].encode('latin-1'))

        def clock_reply():
            for r in fake.frames[mark:]:
                pb = r.frame.payload_bytes()
                if pb and len(pb) >= 2 and pb[1] == 0xDF:
                    return True
            return None
        ok = await wait_for(clock_reply, 15)
        res.record('clock-request-response', bool(ok),
                   'no clock update frame (app 0xDF) sent in response')

        # ---- retransmission when confirmation is withheld ---------------
        # The fake PCI withholds the confirmation of the first confirmed
        # frame: status requests are codeless, so that is the clock
        # reply just above. The client must retransmit it
        # byte-identically (and give up benignly after 3 attempts, like
        # the deployed daemon's timesync).
        ok = await wait_for(lambda: fake.withheld_seen >= 2, 25)
        res.record('retry-unconfirmed-frame', bool(ok),
                   f'withheld frame sent {fake.withheld_seen} time(s), '
                   f'expected >= 2 (retransmit)')

        # ---- MQTT command -> C-Bus frame ---------------------------------
        cmd_off = EXPECT['mqtt_cmd_off_default_app']
        cmd_alt = EXPECT['mqtt_cmd_on_alt_app']
        if skip_slow:
            print('  (skipping slow mqtt-cmd assertions: --skip-slow)',
                  flush=True)
        else:
            broker.inject(cmd_off['topic'],
                          json.dumps(cmd_off['payload']).encode())
            broker.inject(cmd_alt['topic'],
                          json.dumps(cmd_alt['payload']).encode())
            ok = await wait_for(
                lambda: fake.count_payload(
                    cmd_off['expect_pci_payload']) >= 1, 170, interval=0.5)
            detail = ''
            if not ok:
                detail = (f"payload {cmd_off['expect_pci_payload']} never "
                          f"sent to PCI")
            else:
                echo_ok = await wait_for(
                    lambda: json_payload_equals(
                        latest_publish(broker, cmd_off['echo_state_topic']),
                        cmd_off['echo_state_payload']), 10)
                if not echo_ok:
                    ok = False
                    detail = 'PCI frame ok but MQTT state echo missing/wrong'
            res.record('mqtt-cmd-off-to-pci', bool(ok), detail)

            ok = await wait_for(
                lambda: fake.count_payload(
                    cmd_alt['expect_pci_payload']) >= 1, 40, interval=0.5)
            detail = ''
            if not ok:
                detail = (f"payload {cmd_alt['expect_pci_payload']} never "
                          f"sent to PCI (alt app topic "
                          f"{cmd_alt['topic']})")
            else:
                echo_ok = await wait_for(
                    lambda: json_payload_equals(
                        latest_publish(broker, cmd_alt['echo_state_topic']),
                        cmd_alt['echo_state_payload']), 10)
                if not echo_ok:
                    ok = False
                    detail = 'PCI frame ok but MQTT state echo missing/wrong'
            res.record('mqtt-cmd-alt-app-to-pci', bool(ok), detail)

        if not proc_alive():
            res.record('process-stayed-up', False,
                       f'cmqttd exited with {proc.returncode}')
    except RuntimeError as e:
        res.record('fatal', False, str(e))
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 10)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        log_fh.close()
        await fake.stop()
        await broker.stop()

    total = len(res.results)
    passed = total - len(res.failed)
    print(f'behavioral-{impl}: {passed}/{total} PASS', flush=True)
    if res.failed:
        print(f'  failed: {", ".join(n for n, _, _ in res.failed)}',
              flush=True)
        print(f'  cmqttd log tail ({log_path}):', flush=True)
        try:
            with open(log_path, 'rb') as f:
                tail = f.read()[-2000:].decode('utf-8', 'replace')
            for line in tail.splitlines()[-20:]:
                print(f'    {line}', flush=True)
        except OSError:
            pass
    return 0 if not res.failed else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--impl', choices=('python', 'rust'), required=True)
    ap.add_argument('--rust-bin',
                    default=os.path.join(REPO_ROOT, 'rust', 'target',
                                         'debug', 'cmqttd'))
    ap.add_argument('--skip-slow', action='store_true',
                    help='skip the (~2 min) throttle-queue drain assertions')
    args = ap.parse_args()
    rc = asyncio.run(run(args.impl, args.rust_bin, args.skip_slow))
    sys.exit(rc)


if __name__ == '__main__':
    main()
