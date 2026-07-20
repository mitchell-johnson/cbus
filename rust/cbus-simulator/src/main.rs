//! Fake C-Bus PCI TCP server. Port of
//! `cbus/protocol/pciserverprotocol.py` semantics: power-on notification on
//! connect, basic-mode local echo, reset / smart-connect / DM interface
//! options handling, confirmation of any command carrying a confirmation
//! char, and binary StandardCAL replies to master-application status
//! requests.
//!
//! Deliberate divergence from the Python module: clock updates do NOT
//! trigger random debug lighting events (`pciserverprotocol.py:296-308`
//! fires two random on/off SALs per clock update as debug junk).

use cbus_protocol::common::add_cbus_checksum;
use cbus_protocol::packet::Packet;
use cbus_protocol::report::StatusReport;
use cbus_protocol::sal::Sal;
use cbus_transport::framing::FrameBuffer;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

#[derive(Debug, Clone)]
struct SimState {
    basic_mode: bool,
    connect: bool,
    checksum: bool,
    monitor: bool,
    idmon: bool,
    // stored (and reset) like Python, but the simulator never reads them
    #[allow(dead_code)]
    application_addr1: u8,
    #[allow(dead_code)]
    application_addr2: u8,
}

impl Default for SimState {
    fn default() -> Self {
        SimState {
            basic_mode: true,
            connect: false,
            checksum: false,
            monitor: false,
            idmon: false,
            application_addr1: 0xff,
            application_addr2: 0xff,
        }
    }
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();
    let mut args = std::env::args().skip(1);
    let address = args.next().unwrap_or_else(|| "127.0.0.1".to_string());
    let port: u16 = args
        .next()
        .map(|p| p.parse().expect("invalid port"))
        .unwrap_or(10001);

    let listener = TcpListener::bind((address.as_str(), port))
        .await
        .expect("bind");
    println!("Starting fake PCI on {address}:{port}");
    loop {
        match listener.accept().await {
            Ok((stream, peer)) => {
                tracing::info!("client connected: {peer}");
                tokio::spawn(handle_conn(stream));
            }
            Err(e) => tracing::warn!("accept error: {e}"),
        }
    }
}

async fn handle_conn(stream: tokio::net::TcpStream) {
    let (mut rd, mut wr) = stream.into_split();
    let mut st = SimState::default();
    let mut fb = FrameBuffer::new_server();

    // power-up notification (PUN): PowerOnPacket + CRLF
    let _ = wr.write_all(b"++\r\n").await;

    let mut buf = [0u8; 4096];
    loop {
        let n = match rd.read(&mut buf).await {
            Ok(0) | Err(_) => break,
            Ok(n) => n,
        };
        fb.set_checksum(st.checksum);
        for ev in fb.feed(&buf[..n]) {
            // local echo in basic mode (before handling, like handle_data)
            if st.basic_mode && wr.write_all(&ev.raw).await.is_err() {
                return;
            }
            if let Some(p) = ev.packet {
                let reply = handle_packet(&mut st, &p);
                fb.set_checksum(st.checksum);
                if !reply.is_empty() && wr.write_all(&reply).await.is_err() {
                    return;
                }
            }
        }
    }
    tracing::info!("client disconnected");
}

fn handle_packet(st: &mut SimState, p: &Packet) -> Vec<u8> {
    let mut out = Vec::new();
    match p {
        Packet::Invalid => return out,
        Packet::Reset => {
            // reset state to defaults
            tracing::debug!("recv: PCI hard reset");
            *st = SimState::default();
            return out;
        }
        Packet::SmartConnect => {
            st.basic_mode = false;
            st.connect = true;
            return out;
        }
        Packet::BareCal(_) => return out,
        Packet::PointToMultipoint { meta, sals, .. } => {
            for s in sals {
                match s {
                    Sal::LightingOn { group_address, .. } => {
                        tracing::debug!("recv: lighting on: {group_address}");
                    }
                    Sal::LightingOff { group_address, .. } => {
                        tracing::debug!("recv: lighting off: {group_address}");
                    }
                    Sal::LightingRamp {
                        group_address,
                        duration,
                        level,
                        ..
                    } => {
                        tracing::debug!(
                            "recv: lighting ramp: {group_address}, {duration}s to {level}"
                        );
                    }
                    Sal::LightingTerminateRamp { group_address, .. } => {
                        tracing::debug!(
                            "recv: lighting terminate ramp: {group_address}"
                        );
                    }
                    Sal::ClockUpdateTime { .. } | Sal::ClockUpdateDate { .. } => {
                        tracing::debug!("recv: clock update");
                    }
                    Sal::ClockRequest => tracing::debug!("recv: clock request"),
                    Sal::StatusRequest {
                        level_request,
                        group_address,
                        child_application,
                    } => {
                        if *child_application == 0xff && !level_request {
                            match master_application_status(st, *group_address) {
                                Some(reply) => out.extend(reply),
                                // Python raises NotImplementedError outside
                                // basic mode: no reply, no confirmation
                                None => {
                                    out.clear();
                                    return out;
                                }
                            }
                        } else {
                            // unhandled: no confirmation (like Python)
                            tracing::debug!("unhandled status request SAL");
                            return out;
                        }
                    }
                    _ => {
                        tracing::debug!("unhandled SAL type");
                        return out;
                    }
                }
            }
            confirm(meta.confirmation, &mut out);
        }
        Packet::DeviceManagement {
            meta,
            parameter,
            value,
        } => {
            match parameter {
                0x21 | 0x22 | 0x3e | 0x42 => { /* recorded but unimplemented */ }
                0x30 | 0x41 => {
                    // interface options 1 / power up options 1
                    st.connect = false;
                    st.checksum = false;
                    st.monitor = false;
                    st.idmon = false;
                    st.basic_mode = true;
                    if value & 0x01 != 0 {
                        st.connect = true;
                    }
                    if value & 0x08 != 0 {
                        st.checksum = true; // srchk
                    }
                    if value & 0x10 != 0 {
                        st.basic_mode = false; // smart mode
                    }
                    if value & 0x20 != 0 {
                        st.monitor = true;
                    }
                    if value & 0x40 != 0 {
                        st.idmon = true;
                    }
                }
                _ => {
                    tracing::debug!(
                        "unhandled DeviceManagementPacket ({parameter:#x} = {value:#x})"
                    );
                    return out;
                }
            }
            confirm(meta.confirmation, &mut out);
        }
        _ => {
            tracing::debug!("unhandled packet type: {p:?}");
            return out;
        }
    }
    out
}

/// `<code>.` — confirmations have no CR/LF terminator (s4.3.3.3).
fn confirm(confirmation: Option<u8>, out: &mut Vec<u8>) {
    if let Some(code) = confirmation {
        out.push(code);
        out.push(b'.');
    }
}

/// `on_master_application_status`: binary presence report as StandardCAL
/// blocks (basic mode only; None outside basic mode, where Python raises).
fn master_application_status(st: &SimState, _group_address: u8) -> Option<Vec<u8>> {
    if !st.basic_mode {
        tracing::error!("master application status only implemented in basic mode");
        return None;
    }
    // unit 0 missing; 1-10 present; 253 present (pciserverprotocol.py:322)
    let mut states = vec![0u8]; // MISSING
    states.extend(std::iter::repeat(1).take(10)); // ON
    states.extend(std::iter::repeat(0).take(0xfe - 12)); // MISSING
    states.push(1); // ON
    let mut out = Vec::new();
    let mut x = 0usize;
    while x < 0xff {
        let block: Vec<u8> = states.iter().skip(x).take(0x58).copied().collect();
        if block.is_empty() {
            break;
        }
        out.extend(standard_cal_packet(0xff, x as u8, &StatusReport::Binary(block)));
        x += 0x58;
    }
    Some(out)
}

/// `StandardCAL.encode_packet`: header 0xC0|(len+3), app, block, report;
/// checksummed (StandardCAL defaults checksum=True) + base16 + CRLF.
fn standard_cal_packet(child_application: u8, block_start: u8, report: &StatusReport) -> Vec<u8> {
    let rep = report.encode();
    let mut p = vec![
        0xc0u8 | (rep.len() as u8).wrapping_add(3),
        child_application,
        block_start,
    ];
    p.extend_from_slice(&rep);
    let p = add_cbus_checksum(&p);
    let mut out = hex::encode_upper(&p).into_bytes();
    out.extend_from_slice(b"\r\n");
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use cbus_protocol::packet::Meta;

    fn dm(parameter: u8, value: u8, conf: Option<u8>) -> Packet {
        let mut meta = Meta::new(false, 2);
        meta.confirmation = conf;
        Packet::DeviceManagement {
            meta,
            parameter,
            value,
        }
    }

    #[test]
    fn dm_interface_options_bits() {
        let mut st = SimState::default();
        // 0x79 = CONNECT | SRCHK | SMART | MONITOR | IDMON
        let out = handle_packet(&mut st, &dm(0x30, 0x79, Some(b'h')));
        assert!(st.connect && st.checksum && st.monitor && st.idmon);
        assert!(!st.basic_mode);
        assert_eq!(out, b"h.");
        // 0x00 resets everything to basic
        handle_packet(&mut st, &dm(0x41, 0x00, None));
        assert!(st.basic_mode && !st.connect && !st.checksum);
    }

    #[test]
    fn reset_restores_defaults() {
        let mut st = SimState {
            basic_mode: false,
            connect: true,
            checksum: true,
            monitor: true,
            idmon: true,
            application_addr1: 1,
            application_addr2: 2,
        };
        handle_packet(&mut st, &Packet::Reset);
        assert!(st.basic_mode && !st.checksum);
        assert_eq!(st.application_addr1, 0xff);
        assert_eq!(st.application_addr2, 0xff);
    }

    #[test]
    fn unknown_dm_not_confirmed() {
        let mut st = SimState::default();
        let out = handle_packet(&mut st, &dm(0x99, 0x01, Some(b'h')));
        assert!(out.is_empty());
    }
}
