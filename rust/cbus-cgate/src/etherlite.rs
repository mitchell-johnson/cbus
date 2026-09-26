//! Digi EtherLite FAS serial-over-TCP transport.
//!
//! C-Gate's `PORT PROBE etherlite` path does not speak raw serial bytes on
//! TCP port 10001.  It uses Digi's eight-byte FAS command protocol, including
//! a challenge/response unit inquiry, before opening one of the EtherLite's
//! serial ports.  This adapter reproduces that protocol and presents the
//! selected port as the ordinary asynchronous byte stream expected by the
//! PCI client.

use cbus_transport::pci::{BoxedRead, BoxedWrite};
use std::{io, time::Duration};
use tokio::{
    io::{split, AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt, ReadHalf, WriteHalf},
    net::{tcp::OwnedReadHalf, TcpStream},
    sync::mpsc,
    time::{self, Instant, MissedTickBehavior},
};

const ETHERLITE_PORT: u16 = 10_001;
const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
const IO_TIMEOUT: Duration = Duration::from_secs(10);
const KEEPALIVE_INTERVAL: Duration = Duration::from_secs(90);
const FAS_COMMAND_SIZE: usize = 8;
const SERIAL_BUFFER_SIZE: usize = 96;
const BRIDGE_BUFFER_SIZE: usize = 8192;
const MAX_INQUIRY_BYTES: usize = 4096;
const MAX_IGNORED_SETUP_FRAMES: usize = 128;

const ENABLE: u8 = 1;
const DISABLE: u8 = 2;
const SEND: u8 = 3;
const RECEIVE: u8 = 4;
const PURGE_SEND: u8 = 6;
const PURGE_RECEIVE: u8 = 7;
const SET_MODEM: u8 = 8;
const STATUS_CHANGE: u8 = 9;
const SET_PARAMS: u8 = 11;
const FLOW_CONTROL: u8 = 12;
const RESET: u8 = 15;
const WAIT_SEND: u8 = 17;
const UNIT_POLL: u8 = 21;
const HEARTBEAT: u8 = 22;
const UNIT_INQUIRY: u8 = 23;

/// Connect to a Digi EtherLite and expose one zero-based serial-port index as
/// a raw byte stream.
pub(crate) async fn connect(host: &str, port_index: u32) -> io::Result<(BoxedRead, BoxedWrite)> {
    connect_to(host, ETHERLITE_PORT, port_index).await
}

async fn connect_to(
    host: &str,
    tcp_port: u16,
    port_index: u32,
) -> io::Result<(BoxedRead, BoxedWrite)> {
    let mut stream = time::timeout(CONNECT_TIMEOUT, TcpStream::connect((host, tcp_port)))
        .await
        .map_err(|_| {
            io::Error::new(
                io::ErrorKind::TimedOut,
                format!("connect to EtherLite {host}:{tcp_port} timed out"),
            )
        })??;
    stream.set_nodelay(true)?;

    let mut early_serial = Vec::new();
    let port_index = initialise_device(&mut stream, port_index, &mut early_serial).await?;

    let (client, bridge) = tokio::io::duplex(BRIDGE_BUFFER_SIZE);
    let (client_read, client_write) = split(client);
    let (bridge_read, bridge_write) = split(bridge);
    tokio::spawn(run_bridge(
        stream,
        port_index,
        bridge_read,
        bridge_write,
        early_serial,
    ));

    Ok((Box::new(client_read), Box::new(client_write)))
}

async fn initialise_device(
    stream: &mut TcpStream,
    port_index: u32,
    early_serial: &mut Vec<u8>,
) -> io::Result<u8> {
    write_command(stream, command(HEARTBEAT, 0)).await?;
    let heartbeat = read_header(stream).await?;
    if heartbeat[0] != HEARTBEAT {
        return Err(protocol_error(format!(
            "EtherLite heartbeat returned opcode {}",
            heartbeat[0]
        )));
    }

    let challenge: [u8; 6] = heartbeat[2..8]
        .try_into()
        .expect("six-byte heartbeat challenge");
    let answer = heartbeat_answer(challenge);
    let mut inquiry = command(UNIT_INQUIRY, 0);
    inquiry[2..5].copy_from_slice(&answer);
    write_command(stream, inquiry).await?;

    let inquiry_reply = read_header(stream).await?;
    if inquiry_reply[0] != UNIT_INQUIRY {
        return Err(protocol_error(format!(
            "EtherLite unit inquiry returned opcode {}",
            inquiry_reply[0]
        )));
    }
    let inquiry_len = u16::from_le_bytes([inquiry_reply[6], inquiry_reply[7]]) as usize;
    if !(2..=MAX_INQUIRY_BYTES).contains(&inquiry_len) {
        return Err(protocol_error(format!(
            "invalid EtherLite unit inquiry length {inquiry_len}"
        )));
    }
    let mut inquiry_payload = vec![0; inquiry_len];
    read_exact_timeout(stream, &mut inquiry_payload).await?;
    let serial_count = inquiry_payload[0];
    if port_index >= u32::from(serial_count) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!(
                "EtherLite serial port {port_index} is out of range (device has {serial_count})"
            ),
        ));
    }
    let port_index = u8::try_from(port_index).expect("port below the u8 serial count");

    // The native receiver starts a keepalive immediately after inquiry.
    // UNIT_POLL does not have a response that the caller needs to await.
    write_command(stream, command(UNIT_POLL, 0)).await?;

    exchange_status(stream, command(RESET, port_index), early_serial).await?;
    exchange_status(stream, command(ENABLE, port_index), early_serial).await?;
    exchange_status(stream, command(WAIT_SEND, port_index), early_serial).await?;

    // Native SerialPortParams defaults: 9600 baud, 8N1, receiver enabled.
    // Changing the initial output baud from zero also installs the 96-byte
    // output buffer and XON/XOFF characters, while leaving flow control off.
    let mut params = command(SET_PARAMS, port_index);
    params[2] = 3; // eight data bits
    params[5] = 1; // receiver enabled
    params[6] = 0xaa; // 9600 output (low nibble), 9600 input (high nibble)
    let mut flow = command(FLOW_CONTROL, port_index);
    flow[4] = 17;
    flow[5] = 19;
    flow[6..8].copy_from_slice(&(SERIAL_BUFFER_SIZE as u16).to_le_bytes());
    write_command(stream, params).await?;
    write_command(stream, flow).await?;
    await_parameter_responses(stream, port_index, early_serial).await?;

    write_command(stream, receive_command(port_index)).await?;
    let mut receive_completed = false;

    let mut modem = command(SET_MODEM, port_index);
    modem[2] = 1; // assert RTS
    modem[3] = 1; // assert DTR
    exchange_status_tracking_receive(stream, modem, early_serial, &mut receive_completed).await?;

    let mut status = command(STATUS_CHANGE, port_index);
    status[2] = 0x87; // immediate report + CTS/DSR/DCD subscription
    exchange_status_tracking_receive(stream, status, early_serial, &mut receive_completed).await?;

    let mut status_subscription = command(STATUS_CHANGE, port_index);
    status_subscription[2] = 7;
    write_command(stream, status_subscription).await?;
    if receive_completed {
        write_command(stream, receive_command(port_index)).await?;
        receive_completed = false;
    }

    // CBusEtherliteNetwork applies its network parameters after SerialPort's
    // constructor has completed the setup above. The default
    // pci-flow-control=yes changes only output flow control, producing this
    // second FLOW_CONTROL request with software/XON-XOFF enabled.
    let mut pci_flow = flow;
    pci_flow[3] = 1;
    exchange_status_tracking_receive(stream, pci_flow, early_serial, &mut receive_completed)
        .await?;
    if receive_completed {
        write_command(stream, receive_command(port_index)).await?;
    }

    // SerialPort::purge(true, true) sends both commands without waiting for
    // acknowledgements. Bytes 2 and 4 select a full buffer purge.
    for opcode in [PURGE_SEND, PURGE_RECEIVE] {
        let mut purge = command(opcode, port_index);
        purge[2] = 1;
        purge[4] = 1;
        write_command(stream, purge).await?;
    }
    Ok(port_index)
}

async fn await_parameter_responses(
    stream: &mut TcpStream,
    port_index: u8,
    early_serial: &mut Vec<u8>,
) -> io::Result<()> {
    let mut got_params = false;
    let mut got_flow = false;
    for _ in 0..MAX_IGNORED_SETUP_FRAMES {
        let frame = read_frame(stream).await?;
        if frame.header[1] != port_index {
            continue;
        }
        match frame.header[0] {
            SET_PARAMS => {
                require_ok(&frame.header)?;
                got_params = true;
            }
            FLOW_CONTROL => {
                require_ok(&frame.header)?;
                got_flow = true;
            }
            RECEIVE => early_serial.extend_from_slice(&frame.payload),
            _ => {}
        }
        if got_params && got_flow {
            return Ok(());
        }
    }
    Err(protocol_error(
        "EtherLite did not acknowledge serial parameters",
    ))
}

async fn exchange_status(
    stream: &mut TcpStream,
    request: [u8; FAS_COMMAND_SIZE],
    early_serial: &mut Vec<u8>,
) -> io::Result<[u8; FAS_COMMAND_SIZE]> {
    let mut ignored_receive = false;
    exchange_status_tracking_receive(stream, request, early_serial, &mut ignored_receive).await
}

async fn exchange_status_tracking_receive(
    stream: &mut TcpStream,
    request: [u8; FAS_COMMAND_SIZE],
    early_serial: &mut Vec<u8>,
    receive_completed: &mut bool,
) -> io::Result<[u8; FAS_COMMAND_SIZE]> {
    let opcode = request[0];
    let port = request[1];
    write_command(stream, request).await?;
    for _ in 0..MAX_IGNORED_SETUP_FRAMES {
        let frame = read_frame(stream).await?;
        if frame.header[0] == RECEIVE && frame.header[1] == port {
            early_serial.extend_from_slice(&frame.payload);
            *receive_completed = true;
            continue;
        }
        if frame.header[0] == opcode && frame.header[1] == port {
            require_ok(&frame.header)?;
            return Ok(frame.header);
        }
    }
    Err(protocol_error(format!(
        "EtherLite did not acknowledge opcode {opcode}"
    )))
}

fn heartbeat_answer(mut challenge: [u8; 6]) -> [u8; 3] {
    let (mut first, mut second, mut third) = (0usize, 1usize, 2usize);
    for _ in 0..31 {
        challenge[first] ^= challenge[second];
        challenge[third] = challenge[third].rotate_left(1);
        first = (first + 1) % challenge.len();
        second = (second + first) % challenge.len();
        third = (third + second) % challenge.len();
    }
    [
        challenge[0].wrapping_add(challenge[4]),
        challenge[2].wrapping_add(challenge[1]),
        challenge[3]
            .wrapping_add(challenge[5])
            .wrapping_add(challenge[0]),
    ]
}

fn command(opcode: u8, port: u8) -> [u8; FAS_COMMAND_SIZE] {
    let mut frame = [0; FAS_COMMAND_SIZE];
    frame[0] = opcode;
    frame[1] = port;
    frame
}

fn receive_command(port: u8) -> [u8; FAS_COMMAND_SIZE] {
    let mut frame = command(RECEIVE, port);
    frame[2..4].copy_from_slice(&1024u16.to_le_bytes());
    frame
}

fn send_frame(port: u8, bytes: &[u8]) -> Vec<u8> {
    let mut frame = command(SEND, port);
    frame[2..4].copy_from_slice(&(bytes.len() as u16).to_le_bytes());
    let mut wire = Vec::with_capacity(FAS_COMMAND_SIZE + bytes.len());
    wire.extend_from_slice(&frame);
    wire.extend_from_slice(bytes);
    wire
}

fn require_ok(header: &[u8; FAS_COMMAND_SIZE]) -> io::Result<()> {
    if header[2] == 0 {
        Ok(())
    } else {
        Err(protocol_error(format!(
            "EtherLite opcode {} failed with status {}",
            header[0], header[2]
        )))
    }
}

fn protocol_error(message: impl Into<String>) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message.into())
}

struct FasFrame {
    header: [u8; FAS_COMMAND_SIZE],
    payload: Vec<u8>,
}

async fn read_frame<R>(reader: &mut R) -> io::Result<FasFrame>
where
    R: AsyncRead + Unpin,
{
    let header = read_header(reader).await?;
    let payload_len = if header[0] == RECEIVE {
        u16::from_le_bytes([header[4], header[5]]) as usize
    } else {
        0
    };
    let mut payload = vec![0; payload_len];
    if payload_len != 0 {
        read_exact_timeout(reader, &mut payload).await?;
    }
    Ok(FasFrame { header, payload })
}

async fn read_live_frame<R>(reader: &mut R) -> io::Result<FasFrame>
where
    R: AsyncRead + Unpin,
{
    let mut header = [0; FAS_COMMAND_SIZE];
    reader.read_exact(&mut header).await?;
    let payload_len = if header[0] == RECEIVE {
        u16::from_le_bytes([header[4], header[5]]) as usize
    } else {
        0
    };
    let mut payload = vec![0; payload_len];
    if payload_len != 0 {
        reader.read_exact(&mut payload).await?;
    }
    Ok(FasFrame { header, payload })
}

async fn read_header<R>(reader: &mut R) -> io::Result<[u8; FAS_COMMAND_SIZE]>
where
    R: AsyncRead + Unpin,
{
    let mut header = [0; FAS_COMMAND_SIZE];
    read_exact_timeout(reader, &mut header).await?;
    Ok(header)
}

async fn read_exact_timeout<R>(reader: &mut R, bytes: &mut [u8]) -> io::Result<()>
where
    R: AsyncRead + Unpin,
{
    time::timeout(IO_TIMEOUT, reader.read_exact(bytes))
        .await
        .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "EtherLite read timed out"))??;
    Ok(())
}

async fn write_command<W>(writer: &mut W, bytes: [u8; FAS_COMMAND_SIZE]) -> io::Result<()>
where
    W: AsyncWrite + Unpin,
{
    write_all_timeout(writer, &bytes).await
}

async fn write_all_timeout<W>(writer: &mut W, bytes: &[u8]) -> io::Result<()>
where
    W: AsyncWrite + Unpin,
{
    time::timeout(IO_TIMEOUT, writer.write_all(bytes))
        .await
        .map_err(|_| io::Error::new(io::ErrorKind::TimedOut, "EtherLite write timed out"))??;
    Ok(())
}

enum NetworkEvent {
    DisableComplete,
    SendComplete,
    ReceiveComplete(u8),
    StatusChange(u8),
    End(io::Error),
}

async fn run_bridge(
    stream: TcpStream,
    port: u8,
    mut serial_output: ReadHalf<tokio::io::DuplexStream>,
    serial_input: WriteHalf<tokio::io::DuplexStream>,
    early_serial: Vec<u8>,
) {
    let (network_read, mut network_write) = stream.into_split();
    let (events_tx, mut events_rx) = mpsc::channel(16);
    let reader = tokio::spawn(read_network(
        network_read,
        port,
        serial_input,
        early_serial,
        events_tx,
    ));

    let mut serial_buffer = [0u8; SERIAL_BUFFER_SIZE];
    let mut send_pending = false;
    let mut keepalive = time::interval_at(Instant::now() + KEEPALIVE_INTERVAL, KEEPALIVE_INTERVAL);
    keepalive.set_missed_tick_behavior(MissedTickBehavior::Delay);

    loop {
        tokio::select! {
            event = events_rx.recv() => {
                match event {
                    Some(NetworkEvent::DisableComplete) => {}
                    Some(NetworkEvent::SendComplete) => send_pending = false,
                    Some(NetworkEvent::ReceiveComplete(status)) => {
                        let status = status & 0x7f;
                        if status != 8 && status != 10
                            && write_command(&mut network_write, receive_command(port)).await.is_err()
                        {
                            break;
                        }
                    }
                    Some(NetworkEvent::StatusChange(status)) => {
                        if status == 0 {
                            let mut subscribe = command(STATUS_CHANGE, port);
                            subscribe[2] = 7;
                            if write_command(&mut network_write, subscribe).await.is_err() {
                                break;
                            }
                        }
                    }
                    Some(NetworkEvent::End(error)) => {
                        tracing::debug!(%error, "EtherLite reader stopped");
                        break;
                    }
                    None => break,
                }
            }
            result = serial_output.read(&mut serial_buffer), if !send_pending => {
                match result {
                    Ok(0) | Err(_) => break,
                    Ok(count) => {
                        if write_all_timeout(
                            &mut network_write,
                            &send_frame(port, &serial_buffer[..count]),
                        )
                        .await
                        .is_err()
                        {
                            break;
                        }
                        send_pending = true;
                    }
                }
            }
            _ = keepalive.tick() => {
                if write_command(&mut network_write, command(UNIT_POLL, 0)).await.is_err() {
                    break;
                }
            }
        }
    }

    if write_command(&mut network_write, command(DISABLE, port))
        .await
        .is_ok()
    {
        // Native SerialPort::close waits for the DISABLE callback before it
        // releases the transport. Continue draining interleaved responses so
        // the acknowledgement cannot be hidden behind a pending receive.
        let _ = time::timeout(IO_TIMEOUT, async {
            while let Some(event) = events_rx.recv().await {
                match event {
                    NetworkEvent::DisableComplete => return,
                    NetworkEvent::End(error) => {
                        tracing::debug!(%error, "EtherLite reader stopped during disable");
                        return;
                    }
                    NetworkEvent::SendComplete
                    | NetworkEvent::ReceiveComplete(_)
                    | NetworkEvent::StatusChange(_) => {}
                }
            }
        })
        .await;
    }
    let _ = network_write.shutdown().await;
    reader.abort();
}

async fn read_network(
    mut network: OwnedReadHalf,
    port: u8,
    mut serial_input: WriteHalf<tokio::io::DuplexStream>,
    early_serial: Vec<u8>,
    events: mpsc::Sender<NetworkEvent>,
) {
    if !early_serial.is_empty() && serial_input.write_all(&early_serial).await.is_err() {
        let _ = events
            .send(NetworkEvent::End(io::Error::new(
                io::ErrorKind::BrokenPipe,
                "EtherLite serial reader closed",
            )))
            .await;
        return;
    }

    loop {
        // An opened serial port may legitimately be idle for much longer
        // than the setup timeout. UNIT_POLL keeps the device session alive;
        // the read itself therefore waits until a FAS response or EOF.
        let frame = match read_live_frame(&mut network).await {
            Ok(frame) => frame,
            Err(error) => {
                let _ = events.send(NetworkEvent::End(error)).await;
                return;
            }
        };
        if frame.header[1] != port {
            continue;
        }
        let event = match frame.header[0] {
            DISABLE => Some(NetworkEvent::DisableComplete),
            SEND => Some(NetworkEvent::SendComplete),
            RECEIVE => {
                if !frame.payload.is_empty()
                    && serial_input.write_all(&frame.payload).await.is_err()
                {
                    let _ = events
                        .send(NetworkEvent::End(io::Error::new(
                            io::ErrorKind::BrokenPipe,
                            "EtherLite serial reader closed",
                        )))
                        .await;
                    return;
                }
                Some(NetworkEvent::ReceiveComplete(frame.header[2]))
            }
            STATUS_CHANGE => Some(NetworkEvent::StatusChange(frame.header[2])),
            _ => None,
        };
        if let Some(event) = event {
            if events.send(event).await.is_err() {
                return;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::{TcpListener, TcpStream};

    async fn server_read_command(stream: &mut TcpStream) -> ([u8; 8], Vec<u8>) {
        let mut header = [0; 8];
        stream.read_exact(&mut header).await.unwrap();
        let payload_len = if header[0] == SEND {
            u16::from_le_bytes([header[2], header[3]]) as usize
        } else {
            0
        };
        let mut payload = vec![0; payload_len];
        stream.read_exact(&mut payload).await.unwrap();
        (header, payload)
    }

    async fn server_reply(stream: &mut TcpStream, opcode: u8, port: u8) {
        stream.write_all(&command(opcode, port)).await.unwrap();
    }

    async fn fake_etherlite(listener: TcpListener) {
        let (mut stream, _) = listener.accept().await.unwrap();

        let (request, payload) = server_read_command(&mut stream).await;
        assert_eq!(request, command(HEARTBEAT, 0));
        assert!(payload.is_empty());
        stream
            .write_all(&[HEARTBEAT, 0, 1, 2, 3, 4, 5, 6])
            .await
            .unwrap();

        let (request, _) = server_read_command(&mut stream).await;
        assert_eq!(request, [UNIT_INQUIRY, 0, 8, 156, 166, 0, 0, 0]);
        let mut device = vec![0; 32];
        device[0] = 2; // two serial ports
        let mut inquiry_reply = command(UNIT_INQUIRY, 0);
        inquiry_reply[6..8].copy_from_slice(&(device.len() as u16).to_le_bytes());
        stream.write_all(&inquiry_reply).await.unwrap();
        stream.write_all(&device).await.unwrap();

        let (request, _) = server_read_command(&mut stream).await;
        assert_eq!(request, command(UNIT_POLL, 0));

        for opcode in [RESET, ENABLE, WAIT_SEND] {
            let (request, _) = server_read_command(&mut stream).await;
            assert_eq!(request, command(opcode, 1));
            server_reply(&mut stream, opcode, 1).await;
        }

        let (params, _) = server_read_command(&mut stream).await;
        assert_eq!(params, [SET_PARAMS, 1, 3, 0, 0, 1, 0xaa, 0]);
        let (flow, _) = server_read_command(&mut stream).await;
        assert_eq!(flow, [FLOW_CONTROL, 1, 0, 0, 17, 19, 96, 0]);
        // The device may acknowledge the two back-to-back commands in either
        // order; exercising the reverse order catches single-response waits.
        server_reply(&mut stream, FLOW_CONTROL, 1).await;
        server_reply(&mut stream, SET_PARAMS, 1).await;

        let (receive, _) = server_read_command(&mut stream).await;
        assert_eq!(receive, receive_command(1));
        let (modem, _) = server_read_command(&mut stream).await;
        assert_eq!(modem, [SET_MODEM, 1, 1, 1, 0, 0, 0, 0]);

        let early = b"early";
        let mut receive_reply = command(RECEIVE, 1);
        receive_reply[4..6].copy_from_slice(&(early.len() as u16).to_le_bytes());
        stream.write_all(&receive_reply).await.unwrap();
        stream.write_all(early).await.unwrap();
        server_reply(&mut stream, SET_MODEM, 1).await;

        let (status, _) = server_read_command(&mut stream).await;
        assert_eq!(status, [STATUS_CHANGE, 1, 0x87, 0, 0, 0, 0, 0]);
        server_reply(&mut stream, STATUS_CHANGE, 1).await;
        let (subscription, _) = server_read_command(&mut stream).await;
        assert_eq!(subscription, [STATUS_CHANGE, 1, 7, 0, 0, 0, 0, 0]);
        let (receive, _) = server_read_command(&mut stream).await;
        assert_eq!(receive, receive_command(1));

        let (flow, _) = server_read_command(&mut stream).await;
        assert_eq!(flow, [FLOW_CONTROL, 1, 0, 1, 17, 19, 96, 0]);
        server_reply(&mut stream, FLOW_CONTROL, 1).await;

        let (purge_send, _) = server_read_command(&mut stream).await;
        assert_eq!(purge_send, [PURGE_SEND, 1, 1, 0, 1, 0, 0, 0]);
        let (purge_receive, _) = server_read_command(&mut stream).await;
        assert_eq!(purge_receive, [PURGE_RECEIVE, 1, 1, 0, 1, 0, 0, 0]);

        let (send, payload) = server_read_command(&mut stream).await;
        assert_eq!(send, [SEND, 1, 3, 0, 0, 0, 0, 0]);
        assert_eq!(payload, b"@A\r");
        server_reply(&mut stream, SEND, 1).await;

        let mut status_reply = command(STATUS_CHANGE, 1);
        status_reply[3] = 7;
        stream.write_all(&status_reply).await.unwrap();
        let (subscription, _) = server_read_command(&mut stream).await;
        assert_eq!(subscription, [STATUS_CHANGE, 1, 7, 0, 0, 0, 0, 0]);

        let serial_reply = b"B\r";
        let mut receive_reply = command(RECEIVE, 1);
        receive_reply[4..6].copy_from_slice(&(serial_reply.len() as u16).to_le_bytes());
        stream.write_all(&receive_reply).await.unwrap();
        stream.write_all(serial_reply).await.unwrap();
        let (receive, _) = server_read_command(&mut stream).await;
        assert_eq!(receive, receive_command(1));

        let (disable, _) = time::timeout(Duration::from_secs(2), server_read_command(&mut stream))
            .await
            .unwrap();
        assert_eq!(disable, command(DISABLE, 1));
        let mut eof = [0; 1];
        assert!(
            time::timeout(Duration::from_millis(100), stream.read(&mut eof))
                .await
                .is_err()
        );
        server_reply(&mut stream, DISABLE, 1).await;
        assert_eq!(
            time::timeout(Duration::from_secs(2), stream.read(&mut eof))
                .await
                .unwrap()
                .unwrap(),
            0
        );
    }

    #[test]
    fn native_heartbeat_transform() {
        assert_eq!(heartbeat_answer([1, 2, 3, 4, 5, 6]), [8, 156, 166]);
        assert_eq!(heartbeat_answer([0; 6]), [0; 3]);
    }

    #[tokio::test]
    async fn opens_and_proxies_native_fas_frames() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let tcp_port = listener.local_addr().unwrap().port();
        let server = tokio::spawn(fake_etherlite(listener));

        let (mut reader, mut writer) = connect_to("127.0.0.1", tcp_port, 1).await.unwrap();
        let mut early = [0; 5];
        reader.read_exact(&mut early).await.unwrap();
        assert_eq!(&early, b"early");

        writer.write_all(b"@A\r").await.unwrap();
        let mut reply = [0; 2];
        reader.read_exact(&mut reply).await.unwrap();
        assert_eq!(&reply, b"B\r");

        drop(writer);
        drop(reader);
        server.await.unwrap();
    }
}
