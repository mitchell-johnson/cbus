//! Full-system tests for the adaptive flow controller: ack-clocked
//! pacing against a slow CNI, `!` congestion pause + window collapse +
//! additive recovery, timeout release of lost status replies, a
//! 20-command scene burst outranking a queued sweep while holding the
//! inter-frame floor, and the untouched fixed-pace init sequence.

mod util;

use cbus_protocol::common::add_cbus_checksum;
use std::time::{Duration, Instant};
use util::*;

/// Payload hex of "lighting ON <group>" on the default app 0x38.
fn on_payload(group: u8) -> String {
    hex::encode_upper(add_cbus_checksum(&[0x05, 0x38, 0x00, 0x79, group]))
}

/// Publish a full-brightness ON /set for `group` (default app).
fn inject_on(sys: &System, group: u8) {
    sys.broker.inject(
        &format!("homeassistant/light/cbus_{group}/set"),
        br#"{"state": "ON"}"#,
    );
}

/// Arrival timestamps of the ON frames for `groups`, in wire order.
fn on_frame_ts(sys: &System, groups: std::ops::RangeInclusive<u8>) -> Vec<Instant> {
    let payloads: Vec<String> = groups.map(on_payload).collect();
    sys.pci
        .frames()
        .into_iter()
        .filter(|f| payloads.contains(&f.payload))
        .map(|f| f.ts)
        .collect()
}

// ---------------------------------------------------- (a) slow-ack CNI

#[tokio::test]
async fn slow_cni_acks_self_clock_the_send_rate_without_losses() {
    let sys = start_no_project().await;
    wait_started(&sys).await;
    // the CNI takes 350ms to confirm anything (loaded-device emulation)
    sys.pci.set_conf_delay(Duration::from_millis(350));
    for g in 1..=12 {
        inject_on(&sys, g);
    }
    require(Duration::from_secs(30), "all 12 command frames", || {
        (1..=12).all(|g| sys.pci.count_payload(&on_payload(g)) >= 1)
    })
    .await;
    // no losses and no retransmits: every frame exactly once (the 350ms
    // confirmations land well inside the 0.8s retransmit jitter floor)
    for g in 1..=12 {
        assert_eq!(sys.pci.count_payload(&on_payload(g)), 1, "group {g}");
    }
    // ack-clocked: with W in 2..=3 the burst is paced by ~350ms ack
    // round trips (>= ~1.75s), nowhere near the 30ms floor rate (330ms)
    let ts = on_frame_ts(&sys, 1..=12);
    let span = *ts.last().unwrap() - ts[0];
    assert!(
        span >= Duration::from_millis(1200),
        "12-frame burst spanned only {span:?}: not ack-clocked"
    );
}

// ------------------------------------- (b) `!` pause, collapse, recovery

#[tokio::test]
async fn pci_error_pauses_sends_collapses_window_then_recovers() {
    let sys = start_no_project().await;
    wait_started(&sys).await;
    // prime: prove commands flow normally before the congestion signal
    inject_on(&sys, 1);
    require(Duration::from_secs(10), "prime command frame", || {
        sys.pci.count_payload(&on_payload(1)) >= 1
    })
    .await;

    let error_at = Instant::now();
    sys.pci.inject(b"!");
    // let the daemon process the `!` so the 250ms pause is running
    // before the next command can possibly reach the wire
    tokio::time::sleep(Duration::from_millis(150)).await;
    inject_on(&sys, 2);
    require(Duration::from_secs(10), "post-error command frame", || {
        sys.pci.count_payload(&on_payload(2)) >= 1
    })
    .await;
    let frame = sys
        .pci
        .frames()
        .into_iter()
        .find(|f| f.payload == on_payload(2))
        .unwrap();
    let waited = frame.ts - error_at;
    assert!(
        waited >= Duration::from_millis(230),
        "send resumed {waited:?} after '!': pause not applied"
    );
    require(Duration::from_secs(5), "window-collapse log line", || {
        sys.daemon.stderr().contains("window collapsed")
    })
    .await;

    // additive recovery: >=10 clean acks (instant confirmations) regrow
    // the window and log the one-line INFO summary
    for g in 3..=13 {
        inject_on(&sys, g);
    }
    require(
        Duration::from_secs(30),
        "post-collapse command frames",
        || (3..=13).all(|g| sys.pci.count_payload(&on_payload(g)) >= 1),
    )
    .await;
    require(Duration::from_secs(5), "window-recovery log line", || {
        sys.daemon.stderr().contains("window recovering")
    })
    .await;
}

// -------------------------------------- (c) lost replies release slots

#[tokio::test]
async fn lost_status_replies_release_slots_pipeline_never_stalls() {
    // fixture project: a 4-request sweep the fake PCI never answers, so
    // every status slot must be released by its response timeout
    let mut sys = start_default().await;
    wait_started(&sys).await;
    require(Duration::from_secs(10), "sweep starts", || {
        sys.pci.payloads().iter().any(|p| is_status_request(p))
    })
    .await;
    // a command injected while status slots are timing out must still
    // get through promptly: the 5s ceiling IS the no-stall assertion
    sys.broker
        .inject("homeassistant/light/cbus_10/set", br#"{"state": "OFF"}"#);
    require(
        Duration::from_secs(5),
        "command frame despite lost replies",
        || sys.pci.count_payload("053800010AB8") >= 1,
    )
    .await;
    // the whole sweep still drains, each request exactly once (codeless
    // status requests are never retransmitted)
    let sweep = configured_sweep();
    require(Duration::from_secs(15), "full sweep delivered", || {
        sweep.iter().all(|p| sys.pci.count_payload(p) >= 1)
    })
    .await;
    for p in &sweep {
        assert_eq!(sys.pci.count_payload(p), 1, "{p} retransmitted");
    }
    assert!(sys.daemon.is_running());
}

// ------------------------------- (d) scene burst vs sweep, floor intact

/// A project whose one app (56) has groups in all 8 status blocks:
/// a 16-request sweep that takes many seconds when nothing replies.
fn eight_block_project() -> std::path::PathBuf {
    let path = cbus_test_support::proc::temp_path("flow-project.xml");
    let mut groups = String::new();
    for block in 0u16..8 {
        let ga = block * 32 + 1;
        groups.push_str(&format!(
            "<Group><TagName>G{ga}</TagName><Address>{ga}</Address></Group>"
        ));
    }
    let xml = format!(
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\
         <Installation><Project><TagName>FLOW</TagName>\
         <Network><TagName>Flow Network</TagName><Address>254</Address>\
         <Application><TagName>Lighting</TagName><Address>56</Address>\
         {groups}</Application></Network></Project></Installation>"
    );
    std::fs::write(&path, xml).unwrap();
    path
}

/// Expected sweep payload for one block of app 0x38.
fn sweep_payload(block: u8, level: bool) -> String {
    let body: &[u8] = &if level {
        vec![0x05, 0xFF, 0x00, 0x73, 0x07, 0x38, block]
    } else {
        vec![0x05, 0xFF, 0x00, 0x7A, 0x38, block]
    };
    hex::encode_upper(add_cbus_checksum(body))
}

#[tokio::test]
async fn scene_burst_outranks_sweep_all_delivered_with_floor_gaps() {
    let project = eight_block_project();
    let sys = start_with(Options {
        project: false,
        extra: vec!["-P".into(), project.to_string_lossy().into_owned()],
        ..Default::default()
    })
    .await;
    wait_started(&sys).await;
    require(Duration::from_secs(10), "sweep starts", || {
        sys.pci.payloads().iter().any(|p| is_status_request(p))
    })
    .await;
    // 20-command scene burst against the in-progress 16-request sweep
    for g in 1..=20 {
        inject_on(&sys, g);
    }
    require(Duration::from_secs(15), "all 20 command frames", || {
        (1..=20).all(|g| sys.pci.count_payload(&on_payload(g)) >= 1)
    })
    .await;
    // the commands overtook the sweep: with every status reply lost the
    // sweep needs ~500ms per request, so it must still be incomplete
    // the moment the last command frame lands
    let sweep_seen = sys
        .pci
        .payloads()
        .iter()
        .filter(|p| is_status_request(p))
        .count();
    assert!(
        sweep_seen < 16,
        "sweep already complete ({sweep_seen}/16): commands did not outrank it"
    );
    // no starvation: the whole sweep still drains afterwards, in order
    require(Duration::from_secs(60), "full sweep delivered", || {
        sys.pci
            .payloads()
            .iter()
            .filter(|p| is_status_request(p))
            .count()
            >= 16
    })
    .await;
    let observed: Vec<String> = sys
        .pci
        .payloads()
        .into_iter()
        .filter(|p| is_status_request(p))
        .collect();
    let expected: Vec<String> = (0u8..8)
        .flat_map(|b| [sweep_payload(b * 32, false), sweep_payload(b * 32, true)])
        .collect();
    assert_eq!(observed, expected, "sweep order must survive the burst");
    // floor: 20 command frames cannot beat the 30ms/frame line rate
    let cmd_ts = on_frame_ts(&sys, 1..=20);
    assert_eq!(cmd_ts.len(), 20, "every command exactly once");
    let span = *cmd_ts.last().unwrap() - cmd_ts[0];
    assert!(
        span >= Duration::from_millis(450),
        "20 frames in {span:?} beats the 30ms floor"
    );
    // adjacent gaps respect the floor; tolerate a few short readings
    // from recv-side timestamping (frames coalesced into one TCP read
    // share an arrival timestamp)
    let all_ts: Vec<Instant> = sys
        .pci
        .frames()
        .iter()
        .filter(|f| !f.is_reset && !f.is_smart_connect && !f.payload.starts_with("A3"))
        .map(|f| f.ts)
        .collect();
    let violations = all_ts
        .windows(2)
        .filter(|w| w[1] - w[0] < Duration::from_millis(20))
        .count();
    assert!(violations <= 3, "{violations} inter-frame gaps under 20ms");
    std::fs::remove_file(&project).ok();
}

// ----------------------------------------- (e) init pacing is untouched

#[tokio::test]
async fn init_sequence_keeps_fixed_pacing_before_flow_traffic() {
    let sys = start_default().await;
    wait_started(&sys).await;
    let frames = sys.pci.frames();
    let is_init = |f: &cbus_test_support::pci::ClientFrame| {
        f.is_reset || f.is_smart_connect || f.payload.starts_with("A3")
    };
    let init: Vec<_> = frames.iter().filter(|f| is_init(f)).collect();
    assert_eq!(init.len(), 8, "3 resets + | + 4 DM frames");
    // the deployed-proven fixed 100ms pre-write delay still paces every
    // init frame (80ms floor allows for transit/timer jitter)
    for pair in init.windows(2) {
        let gap = pair[1].ts - pair[0].ts;
        assert!(
            gap >= Duration::from_millis(80),
            "init frames only {gap:?} apart: fixed pacing lost"
        );
    }
    // and nothing flow-controlled slips in before init completes
    let first_other = frames.iter().position(|f| !is_init(f));
    if let Some(idx) = first_other {
        assert!(
            frames[..idx].iter().filter(|f| is_init(f)).count() >= 8,
            "full init must precede all flow-controlled traffic"
        );
    }
}
