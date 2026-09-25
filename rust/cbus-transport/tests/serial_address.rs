//! P3b one-shot selected-serial address transport over loopback TCP.

use cbus_transport::serial_address::{SerialAddressOptions, SerialAddressTransport};
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

fn opts(response_ms: u64, overall_ms: u64) -> SerialAddressOptions {
    SerialAddressOptions {
        response_timeout: Duration::from_millis(response_ms),
        overall_timeout: Duration::from_millis(overall_ms),
        ..Default::default()
    }
}

#[tokio::test]
async fn serial_address_matched_receipt() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut sock, _) = listener.accept().await.unwrap();
        let mut req = Vec::new();
        loop {
            let mut byte = [0u8; 1];
            sock.read_exact(&mut byte).await.unwrap();
            req.push(byte[0]);
            if byte[0] == b'\r' {
                break;
            }
        }
        assert_eq!(req, b"\\05FF000F0018B106160615g\r");
        sock.write_all(b"g.86060300870018B10616000005\r")
            .await
            .unwrap();
        // Hold the connection past the response window so the client
        // terminates via response_window_elapsed with a complete capture.
        tokio::time::sleep(Duration::from_millis(1500)).await;
    });
    let transport = SerialAddressTransport::new("127.0.0.1", port, 3, opts(500, 4000)).unwrap();
    let exchange = transport
        .send_serial_address("101136.1558", 6)
        .await
        .unwrap();
    assert_eq!(exchange.request, b"\\05FF000F0018B106160615g\r");
    assert!(exchange.send_completed);
    assert!(exchange.connection_closed);
    assert!(exchange.receipt.matched());
    assert_eq!(exchange.receipt.status.as_str(), "matched");
    assert_eq!(exchange.termination.as_str(), "response_window_elapsed");
    assert!(exchange.capture_complete);
    server.await.unwrap();
}

#[tokio::test]
async fn serial_address_response_window_elapsed_when_silent() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut sock, _) = listener.accept().await.unwrap();
        // Drain the request, then stay silent past the response window.
        let mut buf = vec![0u8; 64];
        let _ = sock.read(&mut buf).await.unwrap();
        tokio::time::sleep(Duration::from_millis(800)).await;
    });
    let transport = SerialAddressTransport::new("127.0.0.1", port, 3, opts(200, 2000)).unwrap();
    let exchange = transport
        .send_serial_address("101136.1558", 6)
        .await
        .unwrap();
    assert!(exchange.send_completed);
    assert_eq!(exchange.termination.as_str(), "response_window_elapsed");
    assert!(exchange.capture_complete);
    server.await.unwrap();
}

#[tokio::test]
async fn serial_address_disconnected_when_server_closes() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut sock, _) = listener.accept().await.unwrap();
        // Drain the request so the client's send completes, then close:
        // the client must observe EOF as `disconnected`.
        let mut buf = vec![0u8; 64];
        let _ = sock.read(&mut buf).await;
    });
    let transport = SerialAddressTransport::new("127.0.0.1", port, 3, opts(500, 4000)).unwrap();
    let exchange = transport
        .send_serial_address("101136.1558", 6)
        .await
        .unwrap();
    assert!(exchange.send_completed);
    assert_eq!(exchange.termination.as_str(), "disconnected");
    assert!(!exchange.capture_complete);
    server.await.unwrap();
}

#[tokio::test]
async fn serial_address_byte_limit_when_reply_exceeds_max_bytes() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut sock, _) = listener.accept().await.unwrap();
        let mut buf = vec![0u8; 64];
        let _ = sock.read(&mut buf).await.unwrap();
        // Multi-byte reply against max_bytes=1 saturates on the first reads.
        sock.write_all(b"g.86060300870018B10616000005\r")
            .await
            .unwrap();
        // Hold past the response window so saturation, not EOF, ends capture.
        tokio::time::sleep(Duration::from_millis(1500)).await;
    });
    let transport = SerialAddressTransport::new(
        "127.0.0.1",
        port,
        3,
        SerialAddressOptions {
            max_bytes: 1,
            ..opts(500, 4000)
        },
    )
    .unwrap();
    let exchange = transport
        .send_serial_address("101136.1558", 6)
        .await
        .unwrap();
    assert!(exchange.send_completed);
    assert_eq!(exchange.termination.as_str(), "byte_limit");
    assert!(!exchange.capture_complete);
    assert!(exchange.bytes_received > 1);
    assert_eq!(exchange.received.len(), 1);
    server.await.unwrap();
}

#[tokio::test]
async fn serial_address_insufficient_response_budget_when_window_cannot_fit() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (sock, _) = listener.accept().await.unwrap();
        // The client never sends: no response window can fit, so just
        // observe the close.
        drop(sock);
    });
    // 1ns of headroom: connect always consumes far more, so the pre-send
    // budget check deterministically reports insufficient budget with no send.
    let transport = SerialAddressTransport::new(
        "127.0.0.1",
        port,
        3,
        SerialAddressOptions {
            response_timeout: Duration::from_secs(2),
            overall_timeout: Duration::from_secs(2) + Duration::from_nanos(1),
            ..Default::default()
        },
    )
    .unwrap();
    let exchange = transport
        .send_serial_address("101136.1558", 6)
        .await
        .unwrap();
    assert!(!exchange.send_attempted);
    assert!(!exchange.send_completed);
    assert_eq!(
        exchange.termination.as_str(),
        "insufficient_response_budget"
    );
    assert!(!exchange.capture_complete);
    server.await.unwrap();
}

#[tokio::test]
async fn serial_address_transport_is_one_shot() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        for _ in 0..1 {
            let (sock, _) = listener.accept().await.unwrap();
            drop(sock);
        }
    });
    let transport = SerialAddressTransport::new("127.0.0.1", port, 3, opts(300, 2000)).unwrap();
    let _ = transport
        .send_serial_address("101136.1558", 6)
        .await
        .unwrap();
    let second = transport.send_serial_address("101136.1558", 6).await;
    assert!(second.is_err());
    server.await.unwrap();
}
