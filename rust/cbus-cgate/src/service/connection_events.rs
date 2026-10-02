//! Event delivery while one connection executes its serial command. There is
//! no application command backlog: later socket input remains under TCP
//! backpressure until the active request completes. Service broadcast keeps
//! its existing fixed capacity; subscribers that fall behind fail explicitly.

use super::*;
use std::future::Future;

pub(super) struct CommandEventDelivery {
    mode: EventMode,
    global_level: u8,
    display_oids: bool,
    command_session: u64,
    channels: HashSet<String>,
}

impl CommandEventDelivery {
    pub(super) fn new(
        service: &Service,
        mode: EventMode,
        client: &ClientState,
        command_session: u64,
    ) -> Self {
        Self {
            mode,
            global_level: service.global_event_level,
            display_oids: service.event_display_oids,
            command_session,
            channels: client.event_channels.clone(),
        }
    }

    pub(super) async fn write<W: tokio::io::AsyncWrite + Unpin>(
        &self,
        writer: &mut W,
        event: &str,
    ) -> io::Result<()> {
        let line = if let Some(reply) = event.strip_prefix(PROGRAMMER_REPLY_MARKER) {
            reply.split_once(' ').and_then(|(session, line)| {
                (session.parse::<u64>().ok() == Some(self.command_session)).then_some(line)
            })
        } else if is_own_command_trace(event, self.command_session) {
            None
        } else {
            deploy_queue_event_channel(event).map_or_else(
                || cgate_event_delivery(self.mode, self.global_level, event),
                |channel| self.channels.contains(channel).then_some(event),
            )
        };
        if let Some(line) = line {
            let line = event_oid_column(line, self.display_oids);
            tokio::time::timeout(
                Duration::from_secs(10),
                writer.write_all(format!("{line}\r\n").as_bytes()),
            )
            .await
            .map_err(|_| {
                io::Error::new(
                    io::ErrorKind::TimedOut,
                    "C-Gate event client is not reading",
                )
            })??;
        }
        Ok(())
    }

    fn lagged(&self) -> io::Result<()> {
        if !self.mode.is_off() || !self.channels.is_empty() {
            Err(io::Error::other("C-Gate event queue overflow"))
        } else {
            Ok(())
        }
    }

    pub(super) async fn wait<F, W>(
        &self,
        response: F,
        writer: &mut W,
        events: &mut broadcast::Receiver<String>,
    ) -> io::Result<Response>
    where
        F: Future<Output = Response>,
        W: tokio::io::AsyncWrite + Unpin,
    {
        tokio::pin!(response);
        let mut events_open = true;
        loop {
            tokio::select! {
                // Always poll command progress first. An endless event stream
                // cannot postpone an already-completed command response.
                biased;
                response = &mut response => {
                    // Deliver the finite prefix queued at completion before
                    // its receipt. New arrivals cannot extend this drain.
                    let pending = events.len().min(SERVICE_EVENT_CAPACITY + 1);
                    for _ in 0..pending {
                        match events.try_recv() {
                            Ok(event) => self.write(writer, &event).await?,
                            Err(broadcast::error::TryRecvError::Lagged(_)) => self.lagged()?,
                            Err(_) => break,
                        }
                    }
                    return Ok(response);
                }
                event = events.recv(), if events_open => match event {
                    Ok(event) => self.write(writer, &event).await?,
                    Err(broadcast::error::RecvError::Lagged(_)) => self.lagged()?,
                    Err(broadcast::error::RecvError::Closed) => events_open = false,
                },
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::AsyncReadExt;

    fn delivery() -> CommandEventDelivery {
        CommandEventDelivery {
            mode: {
                let mut mode = EventMode::OFF;
                mode.apply_native("e7s1c0").unwrap();
                mode
            },
            global_level: 7,
            display_oids: false,
            command_session: 4,
            channels: HashSet::new(),
        }
    }

    #[tokio::test]
    async fn ready_response_drains_only_queued_events_in_order() {
        let (tx, mut rx) = broadcast::channel(512);
        for group in [1, 2, 3] {
            tx.send(format!(
                "#s# lighting on //TEST/254/56/{group} #sourceunit=7"
            ))
            .unwrap();
        }
        let (mut writer, mut reader) = tokio::io::duplex(4096);
        let response = delivery()
            .wait(async { ok("save", vec![], "200 OK") }, &mut writer, &mut rx)
            .await
            .unwrap();
        assert_eq!(response.tag, "save");
        drop(writer);
        let mut wire = String::new();
        reader.read_to_string(&mut wire).await.unwrap();
        assert_eq!(wire, "#s# lighting on //TEST/254/56/1 #sourceunit=7\r\n#s# lighting on //TEST/254/56/2 #sourceunit=7\r\n#s# lighting on //TEST/254/56/3 #sourceunit=7\r\n");
    }

    #[tokio::test]
    async fn bounded_event_overflow_fails_active_connection() {
        let (tx, mut rx) = broadcast::channel(512);
        for _ in 0..513 {
            tx.send("#s# lighting on //TEST/254/56/1".to_string())
                .unwrap();
        }
        let (mut writer, _reader) = tokio::io::duplex(4096);
        let error = delivery()
            .wait(std::future::pending::<Response>(), &mut writer, &mut rx)
            .await
            .unwrap_err();
        assert!(error.to_string().contains("C-Gate event queue overflow"));
        assert_eq!(rx.len(), 512, "overflow is explicit; queue never grows");
    }

    #[tokio::test(start_paused = true)]
    async fn blocked_event_writer_times_out_and_drops_active_command() {
        let (tx, mut rx) = broadcast::channel(512);
        tx.send("#s# lighting on //TEST/254/56/1".to_string())
            .unwrap();
        let (mut writer, _reader) = tokio::io::duplex(1);
        let dropped = Arc::new(std::sync::atomic::AtomicBool::new(false));
        struct DropFlag(Arc<std::sync::atomic::AtomicBool>);
        impl Drop for DropFlag {
            fn drop(&mut self) {
                self.0.store(true, Ordering::SeqCst);
            }
        }
        let flag = DropFlag(dropped.clone());
        let response = async move {
            let _flag = flag;
            std::future::pending::<Response>().await
        };
        let error = delivery()
            .wait(response, &mut writer, &mut rx)
            .await
            .unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::TimedOut);
        assert!(
            dropped.load(Ordering::SeqCst),
            "no detached command task survives its connection"
        );
    }
}

#[cfg(test)]
mod ownership_tests {
    use super::*;
    use tokio::io::AsyncReadExt;

    #[tokio::test]
    async fn async_programmer_receipts_remain_owner_only_even_with_events_off() {
        let delivery = CommandEventDelivery {
            mode: EventMode::OFF,
            global_level: 7,
            display_oids: false,
            command_session: 4,
            channels: HashSet::new(),
        };
        let (tx, mut rx) = broadcast::channel(SERVICE_EVENT_CAPACITY);
        for (owner, tag) in [(3, "foreign"), (4, "own")] {
            tx.send(format!("{PROGRAMMER_REPLY_MARKER}{owner} [{tag}] 200 OK"))
                .unwrap();
        }
        tx.send("#s# lighting on //TEST/254/56/1".to_string())
            .unwrap();
        let (mut writer, mut reader) = tokio::io::duplex(4096);
        delivery
            .wait(async { ok("save", vec![], "200 OK") }, &mut writer, &mut rx)
            .await
            .unwrap();
        drop(writer);
        let mut wire = String::new();
        reader.read_to_string(&mut wire).await.unwrap();
        assert_eq!(wire, "[own] 200 OK\r\n");
    }

    #[tokio::test]
    async fn continuous_ready_events_do_not_starve_a_pending_command_poll() {
        let mut mode = EventMode::OFF;
        mode.apply_native("e7s1c0").unwrap();
        let delivery = CommandEventDelivery {
            mode,
            global_level: 7,
            display_oids: false,
            command_session: 4,
            channels: HashSet::new(),
        };
        let (tx, mut rx) = broadcast::channel(SERVICE_EVENT_CAPACITY);
        tx.send("#s# lighting on //TEST/254/56/1".to_string())
            .unwrap();
        let (mut writer, mut reader) = tokio::io::duplex(65536);
        let polls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let command = std::future::poll_fn({
            let polls = polls.clone();
            let tx = tx.clone();
            move |cx| {
                // The event branch is ready on every poll, including when this
                // command becomes ready; only a finite completion prefix drains.
                tx.send("#s# lighting on //TEST/254/56/1".to_string())
                    .unwrap();
                if polls.fetch_add(1, Ordering::SeqCst) == 8 {
                    std::task::Poll::Ready(ok("save", vec![], "200 OK"))
                } else {
                    cx.waker().wake_by_ref();
                    std::task::Poll::Pending
                }
            }
        });
        let response = tokio::time::timeout(
            Duration::from_secs(1),
            delivery.wait(command, &mut writer, &mut rx),
        )
        .await
        .unwrap()
        .unwrap();
        assert_eq!(response.tag, "save");
        assert_eq!(polls.load(Ordering::SeqCst), 9);
        drop(writer);
        let mut wire = String::new();
        reader.read_to_string(&mut wire).await.unwrap();
        assert_eq!(
            wire.lines().count(),
            10,
            "initial event plus one on each command poll"
        );
    }
}
