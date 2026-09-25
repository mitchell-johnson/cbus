//! C-Gate command model and hardware-backed service for cmqttd.
//!
//! Bounded, synchronous command handling compatible with C-Gate manual
//! section 4.3.1.5: a space terminates a reply, a hyphen
//! continues it, commands carry `[tag]` prefixes so asynchronous events
//! cannot complete a command, and no command is retried automatically.
//!
//! The synchronous model dispatches every
//! public-manual and bytecode-registered C-Gate 3.4 command, with detailed
//! project/network/unit lifecycle plus deterministic stateful models for the
//! remaining application and private command families. It builds on
//! `cbus-protocol` level validation. The
//! access-level matrix reproduces observed native roles: a default
//! `Program` interface grants DB/PROJECT/NET but denies `PP` programming sessions
//! with `420`, while an operator-provisioned handle with programming-lock
//! rights allows them.
//!
//! [`service`] embeds a bounded TCP listener, persistent database and actual
//! shared PCI operations. It explicitly rejects physical command families
//! without a backend; the mock's command coverage is not hardware parity.

use std::collections::{HashMap, HashSet, VecDeque};
use std::path::PathBuf;

pub mod auth;
pub mod capability_matrix;
pub mod manual;
pub mod service;
pub mod unitspec;

/// C-Gate service-ready greeting prefix.
pub const GREETING_PREFIX: &str = "201 ";
/// Overflow marker queued when the event buffer is full.
pub const EVENT_OVERFLOW: &str = "###!!!Event buffer overflow. Events have been missed.!!!###";
/// Default bound for queued events.
pub const DEFAULT_MAX_EVENTS: usize = 4096;

pub mod status {
    //! Observed native status codes.
    pub const SERVICE_READY: u16 = 201;
    pub const OK: u16 = 200;
    pub const BAD_REQUEST: u16 = 400;
    pub const UNAUTHORIZED: u16 = 401;
    /// Missing database/runtime objects read back as 401 natively (not
    /// 404): label research, conversion move verification and the
    /// addressing optional-read helpers all treat 401 as absent. Scope
    /// errors (no/foreign project selected) stay 404.
    pub const ABSENT: u16 = 401;
    pub const NOT_FOUND: u16 = 404;
    pub const CONFLICT_STATE: u16 = 408;
    pub const CONFLICT_EXISTS: u16 = 409;
    pub const ACCESS_DENIED: u16 = 420;
    pub const CONNECTION_REFUSED: u16 = 421;
}

/// Interface role. Roles are disjoint: each grants a fixed command set.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AccessLevel {
    /// Broad DB/PROJECT/NET grants; `PP` sessions denied with 420.
    Program,
    /// Refuses the whole connection with 421 (observed native behaviour).
    Config,
    /// Greets but denies even `NET LOAD DB`.
    Admin,
    /// Denies even `PROJECT NEW`.
    Monitor,
}

/// A parsed client command line: `[tag] VERB args...`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TaggedCommand {
    /// Client-assigned tag; echoed on every reply line.
    pub tag: String,
    /// Upper-cased verb line without the tag.
    pub body: String,
}

/// A complete server reply before wire formatting.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Response {
    /// Echoed client tag.
    pub tag: String,
    /// Intermediate lines (without status prefix handling by caller).
    pub lines: Vec<String>,
    /// Final line text after the status prefix.
    pub final_text: String,
    /// Numeric status.
    pub status: u16,
}

/// Validate and split one client command line.
pub fn parse_command(line: &str) -> Result<TaggedCommand, String> {
    if line.is_empty() || line.len() > 1024 * 1024 {
        return Err("C-Gate command must be a nonempty bounded line".to_string());
    }
    if line
        .bytes()
        .any(|b| b == b'\r' || b == b'\n' || (b < 0x20 && b != b'\t'))
    {
        return Err("C-Gate command must be a single line without control characters".to_string());
    }
    let rest = line
        .strip_prefix('[')
        .and_then(|s| s.find(']').map(|i| (i, s)));
    let Some((end, s)) = rest else {
        return Err("C-Gate command IDs are assigned by the client".to_string());
    };
    let tag = s[..end].to_string();
    if tag.is_empty() || tag.contains(['\r', '\n', ']', '[']) {
        return Err("C-Gate command IDs are assigned by the client".to_string());
    }
    let body = s[end + 1..].trim_start().to_string();
    if body.is_empty() {
        return Err("C-Gate command must be a nonempty string".to_string());
    }
    Ok(TaggedCommand { tag, body })
}

/// Format a reply: intermediate lines use `-`, the final line uses ` `.
///
/// `final_text` retains its native status prefix (e.g. `"200 OK"`), matching
/// the C-Gate response convention; the tag is the only part removed.
/// A reply with an empty tag (only produced for a tagless client line, which
/// carries no command ID to echo) is emitted untagged.
///
/// Intermediate lines that already carry a native envelope prefix
/// (`134`, `300`, `343` or `347`; e.g. DBGETXML snippet rows) pass through
/// untouched; bare payloads gain `resp.status`. Final lines always travel
/// under the reply's own status and never pass through here.
pub fn format_response(resp: &Response) -> String {
    let mut out = String::new();
    for line in &resp.lines {
        if has_status_prefix(line) {
            if resp.tag.is_empty() {
                out.push_str(&format!("{line}\n"));
            } else {
                out.push_str(&format!("[{}] {line}\n", resp.tag));
            }
        } else if resp.tag.is_empty() {
            out.push_str(&format!("{}-{}\n", resp.status, line));
        } else {
            out.push_str(&format!("[{}] {}-{}\n", resp.tag, resp.status, line));
        }
    }
    let prefix = format!("{} ", resp.status);
    let dash = format!("{}-", resp.status);
    if resp.final_text.starts_with(&prefix) || resp.final_text.starts_with(&dash) {
        if resp.tag.is_empty() {
            out.push_str(&format!("{}\n", resp.final_text));
        } else {
            out.push_str(&format!("[{}] {}\n", resp.tag, resp.final_text));
        }
    } else if resp.tag.is_empty() {
        out.push_str(&format!("{} {}\n", resp.status, resp.final_text));
    } else {
        out.push_str(&format!(
            "[{}] {} {}\n",
            resp.tag, resp.status, resp.final_text
        ));
    }
    out
}

/// C-Gate event subscription mode (`EVENT ON|OFF|e[+0-9]s[01]c[01]`,
/// manual 4.5.83).
///
/// `ON` is `e+s0c0` and `OFF` is `e0s0c0`. The `e` level caps delivery
/// by event level; this model emits unlevelled `#e#` lines, so any `e`
/// but `e0` delivers them while `e0` silences them (documented). `s`/`c`
/// gate `#s#` status and `#c#` configuration lines. A bare `EVENT`
/// query reports the connection's mode as `306 <mode>`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventMode {
    /// Event delivery: `+` (default levels) or maximum level 0–9.
    pub events: EventLevel,
    /// Status-change (`#s#`) delivery.
    pub status: bool,
    /// Configuration-change (`#c#`) delivery.
    pub config: bool,
}

/// Event-level selector of an `EVENT` mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EventLevel {
    /// `e+`: default levels, no prefix stripping.
    Plus,
    /// `e0`–`e9`: maximum delivered event level.
    Capped(u8),
}

impl EventMode {
    /// Native console default: `e+s0c0` (manual 4.5.83).
    pub const DEFAULT: Self = Self {
        events: EventLevel::Plus,
        status: false,
        config: false,
    };

    /// `OFF` is `e0s0c0`: nothing is delivered.
    pub const OFF: Self = Self {
        events: EventLevel::Capped(0),
        status: false,
        config: false,
    };

    /// Parse `ON`, `OFF` or an `e[+0-9]s[01]c[01]` mode (the `e` form is
    /// lowercase, mirroring `valid_event_mode`).
    pub fn parse(word: &str) -> Option<Self> {
        if word.eq_ignore_ascii_case("on") {
            return Some(Self::DEFAULT);
        }
        if word.eq_ignore_ascii_case("off") {
            return Some(Self::OFF);
        }
        if !valid_event_mode(word) || word.len() != 6 {
            return None;
        }
        let b = word.as_bytes();
        Some(Self {
            events: if b[1] == b'+' {
                EventLevel::Plus
            } else {
                EventLevel::Capped(b[1] - b'0')
            },
            status: b[3] == b'1',
            config: b[5] == b'1',
        })
    }

    /// True when `OFF`-equivalent: no category can be delivered.
    pub fn is_off(&self) -> bool {
        *self == Self::OFF
    }

    /// True when an event line reaches a connection holding this mode.
    pub fn delivers(&self, category: EventCategory) -> bool {
        match category {
            EventCategory::Event => !matches!(self.events, EventLevel::Capped(0)),
            EventCategory::Status => self.status,
            EventCategory::Config => self.config,
        }
    }
}

impl std::fmt::Display for EventMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self.events {
            EventLevel::Plus => write!(f, "e+"),
            EventLevel::Capped(n) => write!(f, "e{n}"),
        }?;
        write!(f, "s{}c{}", u8::from(self.status), u8::from(self.config))
    }
}

/// Delivery category of an event line.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EventCategory {
    Event,
    Status,
    Config,
}

/// Delivery category of an event line: `#s#` is status, `#c#` is
/// configuration, and everything else (including `#e#`, timestamped, and
/// overflow lines) is an event.
pub fn event_category(line: &str) -> EventCategory {
    if line.starts_with("#s#") {
        EventCategory::Status
    } else if line.starts_with("#c#") {
        EventCategory::Config
    } else {
        EventCategory::Event
    }
}

/// True for accepted C-Gate event subscription modes.
///
/// Accepts `ON`/`OFF` case-insensitively, otherwise the literal
/// `e[+0-9]s[01]c[01]`
/// shape (lowercase, six characters).
pub fn valid_event_mode(mode: &str) -> bool {
    if mode.eq_ignore_ascii_case("on") || mode.eq_ignore_ascii_case("off") {
        return true;
    }
    let b = mode.as_bytes();
    b.len() == 6
        && b[0] == b'e'
        && (b[1] == b'+' || b[1].is_ascii_digit())
        && b[2] == b's'
        && (b[3] == b'0' || b[3] == b'1')
        && b[4] == b'c'
        && (b[5] == b'0' || b[5] == b'1')
}

/// True for asynchronous event lines (never completes a command).
///
/// `#e#`/`#s#`/`#c#` markers require end-of-line or a trailing space, and timestamped events
/// require the exact `YYYYMMDD-HHMMSS[.mmm] SP [789]xx SP` shape. All
/// indexing uses byte slices so non-character-boundary input cannot panic.
pub fn is_event_line(line: &str) -> bool {
    for marker in ["#e#", "#s#", "#c#"] {
        if line == marker || line.starts_with(&format!("{marker} ")) {
            return true;
        }
    }
    if line == EVENT_OVERFLOW {
        return true;
    }
    // `YYYYMMDD-HHMMSS[.mmm] 7xx/8xx ...` — byte-indexed, exact shape.
    let b = line.as_bytes();
    if b.len() < 19 || b[8] != b'-' {
        return false;
    }
    if !b[0..8].iter().all(|c| c.is_ascii_digit()) {
        return false;
    }
    if !b[9..15].iter().all(|c| c.is_ascii_digit()) {
        return false;
    }
    let mut i = 15;
    if b.get(i) == Some(&b'.') {
        // Millis are exactly three digits when present.
        if b.len() < i + 4 || !b[i + 1..i + 4].iter().all(|c| c.is_ascii_digit()) {
            return false;
        }
        i += 4;
    }
    // Exactly one space, then `[789]xx`, then a trailing space.
    if b.get(i) != Some(&b' ') {
        return false;
    }
    i += 1;
    if b.len() < i + 4 {
        return false;
    }
    if !matches!(b[i], b'7' | b'8' | b'9') {
        return false;
    }
    if !b[i + 1..i + 3].iter().all(|c| c.is_ascii_digit()) {
        return false;
    }
    b.get(i + 3) == Some(&b' ')
}

fn ok(tag: &str, lines: Vec<String>, final_text: &str) -> Response {
    Response {
        tag: tag.to_string(),
        lines,
        final_text: final_text.to_string(),
        status: status::OK,
    }
}

/// Native parameter replies complete on the last 315 row, without a
/// trailing 200. The empty, spec-free mock namespace has no parameter
/// row to emit and retains its explicit 200 completion.
fn parameter_reply(tag: &str, mut values: Vec<String>) -> Response {
    let Some(last) = values.pop() else {
        return ok(tag, vec![], "200 OK");
    };
    Response {
        tag: tag.to_string(),
        lines: values
            .into_iter()
            .map(|value| format!("315-{value}"))
            .collect(),
        final_text: format!("315 {last}"),
        status: 315,
    }
}

fn err(tag: &str, code: u16, text: &str) -> Response {
    Response {
        tag: tag.to_string(),
        lines: Vec::new(),
        final_text: text.to_string(),
        status: code,
    }
}

fn tag_of(cmd: &TaggedCommand) -> &str {
    &cmd.tag
}

/// Empty strings become `None` (absent database identity fields).
fn non_empty(value: String) -> Option<String> {
    if value.is_empty() {
        None
    } else {
        Some(value)
    }
}

/// Minimal XML escaping for generated documents, including attribute
/// values (`&quot;` is safe inside text nodes too).
fn xml_escape(text: &str) -> String {
    text.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

/// Decode C-Gate mK quoting: `"a\ b\"c\\d"` to raw text.
/// Only the three emitted escapes (`\\`, `\"`, `\ `) de-escape; any other
/// backslash is preserved so hand-crafted input cannot lose backslashes.
/// Unquoted tails store verbatim (documented tolerance for non-client use).
fn dequote_value(raw: &str) -> String {
    let Some(inner) = raw.strip_prefix('"').and_then(|s| s.strip_suffix('"')) else {
        return raw.to_string();
    };
    let mut out = String::with_capacity(inner.len());
    let mut chars = inner.chars();
    while let Some(c) = chars.next() {
        if c == '\\' {
            match chars.clone().next() {
                Some(next @ ('\\' | '"' | ' ')) => {
                    chars.next();
                    out.push(next);
                }
                _ => out.push('\\'),
            }
        } else {
            out.push(c);
        }
    }
    out
}
/// Status codes that may prefix intermediate reply lines in native
/// multi-status envelopes (calculator `134`, cached-property `300`,
/// parameter `315`, database `342`/`233`, snippet/JSON `343`/`345`/`346`/`347`,
/// PINGU `302`, multiplicity `120`).
const ENVELOPE_CODES: [u16; 11] = [120, 134, 233, 300, 302, 315, 342, 343, 345, 346, 347];

/// True when a reply line already carries a native multi-status envelope.
///
/// Only the envelopes this model emits pass through: anything else —
/// including user-controlled text such as project names — gains the reply
/// status, so a project literally named `200-foo` can never spoof a code.
fn has_status_prefix(line: &str) -> bool {
    let b = line.as_bytes();
    if b.len() <= 4 || (b[3] != b'-' && b[3] != b' ') {
        return false;
    }
    let Ok(code): Result<u16, _> = line[..3].parse() else {
        return false;
    };
    ENVELOPE_CODES.contains(&code)
}
/// Network runtime state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, serde::Serialize, serde::Deserialize)]
pub enum NetworkState {
    #[default]
    Closed,
    Open,
    Syncing,
    Ok,
}

/// One database unit.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Unit {
    /// Programming address 0..=255.
    pub address: u8,
    /// Catalogue type, e.g. `KEYE1`.
    pub unit_type: String,
    /// Decimal-dot serial, e.g. `101136.1558`.
    pub serial: String,
    /// Firmware text, e.g. `2.5.00`.
    pub firmware: String,
    /// Database field overrides via `DBSETSAFE` (e.g. `UnitName`).
    pub fields: HashMap<String, String>,
    /// Stable object identity issued at creation (also resolvable).
    pub oid: String,
}

impl Unit {
    fn blank(address: u8, name: &str) -> Self {
        let mut fields = HashMap::new();
        fields.insert("UnitName".to_string(), name.to_string());
        Self {
            address,
            unit_type: String::new(),
            serial: String::new(),
            firmware: String::new(),
            fields,
            oid: fresh_oid(),
        }
    }

    fn field(&self, name: &str) -> String {
        // Case-sensitive store, like the native database: `Type` and
        // `UnitType` are distinct keys (the serials aliases resolve
        // through the fallback match below, not through folding).
        if let Some(v) = self.fields.get(name) {
            return v.clone();
        }
        match name {
            "UnitType" | "Type" => self.unit_type.clone(),
            "FirmwareVersion" => self.firmware.clone(),
            // Serials flows query these database names; the mock reports
            // the record address, the firmware as Version, and a healthy
            // State (no faults are modeled — documented mock posture).
            "Address" => self.address.to_string(),
            "Version" => self.firmware.clone(),
            "State" => "ok".to_string(),
            "SerialNumber" => self.serial.clone(),
            "UnitAddress" => self.address.to_string(),
            _ => String::new(),
        }
    }
}

/// One in-memory programming session (`PP START name lock` … `PP END`).
///
/// Sessions hold staged parameter values plus the loaded/new identity.
/// There is no catalogue, memory image or hardware behind them: `NEW`
/// seeds identity parameters, `LOAD` of a `/db/` unit seeds from the
/// database record, and `SAVE` writes staged values back to it. Anything
/// requiring catalogue data, raw memory or live hardware answers with an
/// explicit error instead of invented content.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PpSession {
    /// Session name (`PP <OP> name …`).
    pub name: String,
    /// Lock the session was started under.
    pub lock: String,
    /// Loaded source (`LOAD`) or `None` after `NEW`.
    pub source: Option<String>,
    /// Identity from `NEW` or `/db/` `LOAD`.
    pub unit_type: Option<String>,
    /// Identity from `NEW` or `/db/` `LOAD`.
    pub firmware: Option<String>,
    /// Identity from `NEW` or `/db/` `LOAD`.
    pub catalog_number: Option<String>,
    /// Staged parameter values.
    pub params: HashMap<String, String>,
    /// Parameters changed since the last successful load or save.
    pub dirty: HashSet<String>,
}

/// One project network.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Network {
    /// Network address.
    pub address: u8,
    /// Display name.
    pub name: String,
    /// Interface type as given to `DBCREATENET` (`Serial`/`Cni`/`Bridge`).
    pub iface_type: String,
    /// Interface address as given to `DBCREATENET`.
    pub iface_addr: String,
    /// Runtime state.
    #[serde(skip)]
    pub state: NetworkState,
    /// Database units keyed by address.
    pub units: HashMap<u8, Unit>,
    /// Physical bus units keyed by address.
    ///
    /// The mock keeps native layering: `DBADDSAFE` introduces a unit on
    /// both layers, database verbs (`DBSETSAFE`, PP sessions, `DBCOPYSAFE`,
    /// `DBDELETE`) touch only the database layer, and scalar `SET` moves
    /// only the physical layer — so a physical readdress leaves
    /// `database_unchanged` true for verification, exactly like native.
    /// Serials, PINGU/CHECKUNIT, `GET` field reads, `Units` snapshots and
    /// `TREE` observe the physical layer; `DBGET`, `DBGETXML` and PP
    /// observe the database.
    #[serde(skip)]
    pub physical: HashMap<u8, Unit>,
    /// Live group levels keyed by (application, group).
    ///
    /// This is explicitly mock behavior, not native fidelity: levels apply
    /// instantly (no ramp timing emulation) so write-then-observe flows
    /// such as scene record can run end to end. Untouched groups read 0.
    #[serde(skip)]
    pub levels: HashMap<(u8, u8), u8>,
}

/// One project.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Project {
    /// Project name.
    pub name: String,
    /// Networks keyed by address.
    pub networks: HashMap<u8, Network>,
}

/// One database level (or NetVar) created via `DBADDSAFE`.
///
/// Native `DBADDSAFE` sets `Level/Address` but leaves `Level/Value` NULL
/// (the caller initializes it with `DBSETSAFE !oid/Value`, otherwise the
/// native SQLite constraint fails at save); `DBGETXML` on the parent
/// group reports the `<Group>`/`<NetVar>` document of `<Level
/// Value="n"><TagName>t</TagName></Level>` rows that tag resolution
/// parses. Only this evidenced shape is modeled: no other level fields
/// are claimed.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct DbLevel {
    /// Issued object identity (`!oid` addressing).
    pub oid: String,
    /// Parent group path exactly as given to `DBADDSAFE`.
    pub parent: String,
    /// Level selector/address byte.
    pub address: u8,
    /// Tag name.
    pub tag: String,
    /// Initialized byte value (`None` = native NULL).
    pub value: Option<u8>,
    /// True for `NetVar` records (different document root, no Value init).
    pub netvar: bool,
}

/// In-memory C-Gate server.
#[derive(Clone)]
pub struct Server {
    access: AccessLevel,
    allow_programming: bool,
    projects: HashMap<String, Project>,
    current: Option<String>,
    events: VecDeque<String>,
    events_lost: bool,
    max_events: usize,
    /// Opaque `DBSETSAFE`/`DBSETXML` field store by full path.
    db_fields: HashMap<String, String>,
    /// Objects created via `DBADDSAFE` (unit paths and level OID paths).
    objects: std::collections::HashSet<String>,
    /// OIDs issued for `Level`/`NetVar` creation, resolvable via `!oid/OID`.
    known_oids: std::collections::HashSet<String>,
    /// Database levels by OID (`DBADDSAFE ... Level/NetVar ...` records).
    db_levels: HashMap<String, DbLevel>,
    /// Programming locks (`PP LOCK name address`).
    locks: HashMap<String, String>,
    /// Open programming sessions (`PP START name lock`).
    sessions: HashMap<String, PpSession>,
    /// Optional unit-specification directory for catalogue-backed
    /// sessions (native C-Gate serves its catalogue the same way).
    unitspec_dir: Option<PathBuf>,
    /// Parsed specifications by unit type (`None` = absent/unreadable,
    /// cached so failing lookups are not re-parsed per command).
    spec_cache: HashMap<String, Option<Vec<unitspec::SpecParam>>>,
    /// Last successfully encoded command for application-family commands.
    application_state: HashMap<String, String>,
    /// Mutable CONFIG values (global keys and object-qualified keys).
    config_values: HashMap<String, String>,
    /// General advisory locks (`LOCK`/`UNLOCK`), separate from PP locks.
    advisory_locks: std::collections::HashSet<String>,
    /// Human-readable label attached by `SESSION_ID TAG`.
    session_tag: Option<String>,
    /// Named scene snapshots recorded by `SCENE RECORD`.
    scene_snapshots: HashMap<String, Vec<(String, u8)>>,
    /// Two-phase shutdown state used by `SHUTDOWN`/`CONFIRM`.
    shutdown_pending: bool,
    /// Named in-memory database snapshots used by `DBSAVE`/`DBLOAD`.
    database_files: HashMap<String, Project>,
    /// Server-side files addressed by the private `FILE` command family.
    file_store: HashMap<String, Vec<u8>>,
}

impl Server {
    /// New server with the given interface role.
    pub fn new(access: AccessLevel) -> Self {
        Self {
            access,
            allow_programming: false,
            projects: HashMap::new(),
            current: None,
            events: VecDeque::new(),
            events_lost: false,
            max_events: DEFAULT_MAX_EVENTS,
            db_fields: HashMap::new(),
            objects: std::collections::HashSet::new(),
            known_oids: std::collections::HashSet::new(),
            db_levels: HashMap::new(),
            locks: HashMap::new(),
            sessions: HashMap::new(),
            unitspec_dir: None,
            spec_cache: HashMap::new(),
            application_state: HashMap::new(),
            config_values: HashMap::new(),
            advisory_locks: std::collections::HashSet::new(),
            session_tag: None,
            scene_snapshots: HashMap::new(),
            shutdown_pending: false,
            database_files: HashMap::new(),
            file_store: HashMap::new(),
        }
    }

    /// Point sessions at a unit-specification directory (mirrors native
    /// catalogue service; enables spec-backed INFO and default seeding).
    pub fn with_unitspec_dir(mut self, dir: PathBuf) -> Self {
        self.unitspec_dir = Some(dir);
        self
    }

    /// Parsed specification for a unit type, if a directory is configured
    /// and the file loads (cached, including failures).
    fn spec_for(&mut self, unit_type: &str) -> Option<Vec<unitspec::SpecParam>> {
        let dir = self.unitspec_dir.clone()?;
        if let Some(cached) = self.spec_cache.get(unit_type) {
            return cached.clone();
        }
        let parsed = unitspec::load_spec(&dir, unit_type).ok();
        self.spec_cache
            .insert(unit_type.to_string(), parsed.clone());
        parsed
    }

    /// Grant programming-lock rights (operator-provisioned handle).
    pub fn with_programming(mut self, allow: bool) -> Self {
        self.allow_programming = allow;
        self
    }

    /// Read the session-selected project.
    ///
    /// Hub plumbing: a shared `Server` serves many sessions, but project
    /// selection is session state, so transports swap each connection's
    /// selection in and out around its own commands.
    pub fn current_project(&self) -> Option<String> {
        self.current.clone()
    }

    /// Restore the session-selected project (hub plumbing).
    pub fn set_current_project(&mut self, project: Option<String>) {
        self.current = project;
    }

    /// Service-ready greeting.
    pub fn greeting() -> &'static str {
        "201 Service ready"
    }

    fn push_event(&mut self, line: String) {
        // Server-side overflow policy: the triggering event is dropped, a
        // single overflow marker is retained, and `events_lost` is set without
        // blocking command handling on a full queue.
        if self.events.len() >= self.max_events {
            self.events_lost = true;
            if !self.events.iter().any(|e| e == EVENT_OVERFLOW) {
                self.events.push_back(EVENT_OVERFLOW.to_string());
            }
            return;
        }
        self.events.push_back(line);
    }

    /// Override the event-queue bound (default `DEFAULT_MAX_EVENTS`).
    /// Primarily a test hook for overflow behaviour.
    pub fn set_max_events(&mut self, max: usize) {
        self.max_events = max.max(1);
    }

    /// Drain queued events.
    pub fn drain_events(&mut self) -> Vec<String> {
        std::mem::take(&mut self.events).into_iter().collect()
    }

    /// Whether events were lost to overflow.
    pub fn events_lost(&self) -> bool {
        self.events_lost
    }

    fn current_project_mut(&mut self) -> Option<&mut Project> {
        let name = self.current.clone()?;
        self.projects.get_mut(&name)
    }

    /// Handle one raw client line, returning the reply.
    ///
    /// A tagless line yields an untagged `400` reply (see
    /// [`format_response`]); every other reply echoes the client tag.
    pub fn handle(&mut self, line: &str) -> Response {
        let cmd = match parse_command(line) {
            Ok(c) => c,
            Err(e) => {
                return Response {
                    tag: String::new(),
                    lines: Vec::new(),
                    final_text: format!("400 {e}"),
                    status: status::BAD_REQUEST,
                }
            }
        };
        // Config refuses the whole connection; Admin/Monitor deny by verb.
        if self.access == AccessLevel::Config {
            return err(
                &cmd.tag,
                status::CONNECTION_REFUSED,
                "421 Access refused for interface level",
            );
        }
        let upper = cmd.body.to_ascii_uppercase();
        let words: Vec<&str> = cmd.body.split_whitespace().collect();
        if words.is_empty() {
            return err(&cmd.tag, status::BAD_REQUEST, "400 Empty command");
        }
        if let Some(response) = self.handle_manual_command(&cmd.tag, &words, &cmd.body) {
            return response;
        }
        match upper.as_str() {
            _ if eq_verb(&upper, "NOOP") => ok(&cmd.tag, vec![], "200 OK"),
            _ if eq_verb(&upper, "GET CGATE VERSION") => ok(
                &cmd.tag,
                vec!["C-Gate 3.4.0 (rust cbus-cgate 0.1.0)".to_string()],
                "200 OK",
            ),
            _ if starts_with(&upper, "PROJECT LIST") => self.project_list(&cmd.tag),
            _ if starts_with(&upper, "PROJECT NEW") => self.project_new(&cmd.tag, &words),
            _ if starts_with(&upper, "PROJECT USE") => self.project_use(&cmd.tag, &words),
            _ if starts_with(&upper, "PROJECT LOAD") => self.project_load(&cmd.tag, &words),
            _ if starts_with(&upper, "PROJECT CLOSE") => self.project_close(&cmd.tag),
            _ if starts_with(&upper, "PROJECT SAVE") => self.project_save(&cmd.tag, &words),
            _ if starts_with(&upper, "PROJECT DELETE") => self.project_delete(&cmd.tag, &words),
            _ if starts_with(&upper, "PROJECT COPY") => self.project_copy(&cmd.tag, &words),
            _ if starts_with(&upper, "PROJECT RENAME") => self.project_rename(&cmd.tag, &words),
            _ if starts_with(&upper, "PROJECT DIR") => self.project_dir(&cmd.tag, &words),
            _ if starts_with(&upper, "PROJECT ARCHIVE") => self.project_archive(&cmd.tag, &words),
            _ if starts_with(&upper, "PROJECT RESTORE") => self.project_restore(&cmd.tag, &words),
            _ if starts_with(&upper, "PROJECT REPAIR") => self.project_repair(&cmd.tag, &words),
            _ if starts_with(&upper, "REPOSITORY LIST") => self.repository_list(&cmd.tag, &words),
            _ if starts_with(&upper, "NET OPEN") => self.net_open(&cmd.tag, &words),
            _ if starts_with(&upper, "NET CLOSE") => self.net_close(&cmd.tag, &words),
            _ if starts_with(&upper, "NET SYNC") => self.net_sync(&cmd.tag, &words),
            _ if starts_with(&upper, "NET SYNCNEW") => self.net_syncnew(&cmd.tag, &words),
            _ if starts_with(&upper, "NET PINGU") => self.net_pingu(&cmd.tag, &words),
            _ if starts_with(&upper, "NET CHECKUNIT") => self.net_checkunit(&cmd.tag, &words),
            _ if starts_with(&upper, "NET UNRAVELUNIT") || starts_with(&upper, "NET UNRAVEL") => {
                self.net_unravel(&cmd.tag, &words)
            }
            _ if starts_with(&upper, "NET CLOCKS") => self.net_clocks(&cmd.tag, &words),
            _ if starts_with(&upper, "NET LIST_ALL") => self.net_list_all(&cmd.tag),
            _ if starts_with(&upper, "NET LIST") => self.net_list(&cmd.tag, &words),
            _ if starts_with(&upper, "NET RENAME") => self.net_rename(&cmd.tag, &words),
            _ if starts_with(&upper, "NET SET_PROJECT_IDENTIFY") => {
                self.net_set_identity(&cmd.tag, &words)
            }
            _ if starts_with(&upper, "NET STATE") => self.net_state(&cmd.tag, &words),
            _ if starts_with(&upper, "TREEXMLDETAIL")
                | starts_with(&upper, "TREEXML")
                | starts_with(&upper, "NET TREE")
                | starts_with(&upper, "TREE") =>
            {
                self.net_tree(&cmd.tag, &words)
            }
            _ if starts_with(&upper, "CALCULATOR TEST") => self.calculator(&cmd.tag, &words),
            _ if starts_with(&upper, "GET") => self.get(&cmd.tag, &words),
            _ if starts_with(&upper, "NET LOAD DB") => {
                if matches!(self.access, AccessLevel::Admin | AccessLevel::Monitor) {
                    err(&cmd.tag, status::ACCESS_DENIED, "420 Access denied")
                } else {
                    ok(&cmd.tag, vec![], "200 OK")
                }
            }
            _ if starts_with(&upper, "DBGET") || starts_with(&upper, "DBGETXML") => {
                self.dbget(&cmd.tag, &words)
            }
            _ if starts_with(&upper, "DBSETSAFE") || starts_with(&upper, "DBSETXML") => {
                self.dbset(&cmd.tag, &words)
            }
            _ if starts_with(&upper, "DBADDSAFE") => self.dbadd(&cmd.tag, &words),
            _ if starts_with(&upper, "DBCOPYSAFE") => self.dbcopy(&cmd.tag, &words),
            _ if starts_with(&upper, "DBRENAMENETSAFE") => self.dbrename_net(&cmd.tag, &words),
            _ if starts_with(&upper, "DBDELETE") => self.dbdelete(&cmd.tag, &words),
            _ if starts_with(&upper, "DBVALIDATE") => self.dbvalidate(&cmd.tag, &words),
            _ if starts_with(&upper, "CGL IMPORT") => self.cgl_import(&cmd.tag, &words),
            _ if starts_with(&upper, "CGL EXPORT") => self.cgl_export(&cmd.tag, &words),
            _ if starts_with(&upper, "DBCREATENET") => self.dbcreate_net(&cmd.tag, &words),
            // Every PP verb needs programming-lock rights; Admin and
            // Monitor roles never hold them (disjoint roles). Denied
            // callers get 420 before any verb parsing, mirroring the
            // observed native posture.
            _ if starts_with(&upper, "PP") => self.programming(&cmd.tag, &words),
            _ if starts_with(&upper, "SCENE") => err(
                &cmd.tag,
                status::UNAUTHORIZED,
                "401 Named SCENE commands are not supported",
            ),
            _ if is_lighting(&upper) => self.lighting(&cmd.tag, &words),
            _ if is_label_command(&upper) => self.lighting_label(&cmd.tag, &words),
            _ if starts_with(&upper, "TRIGGER EVENT") => self.trigger(&cmd.tag, &words),
            _ if starts_with(&upper, "TRIGGER INDICATORKILL") => {
                self.trigger_kill(&cmd.tag, &words)
            }
            _ if starts_with(&upper, "ENABLE SET") => self.enable_set(&cmd.tag, &words),
            _ if starts_with(&upper, "ENABLE REMOVE") => self.enable_remove(&cmd.tag, &words),
            _ if starts_with(&upper, "LABEL") => self.label_clear(&cmd.tag, &words),
            _ if starts_with(&upper, "SET") => self.scalar_set(&cmd.tag, &words),
            // Mock-only fixture verb (no native counterpart by design):
            // drop one physical-bus record so tests can stage
            // database-without-physical topologies.
            _ if starts_with(&upper, "MOCK BUS-DEL") => self.mock_bus_del(&cmd.tag, &words),
            _ if starts_with(&upper, "EVENT") || starts_with(&upper, "EVENTS") => {
                self.event_sub(&cmd.tag, &words)
            }
            _ if starts_with(&upper, "GETSTATE") => self.getstate(&cmd.tag, &words),
            _ if starts_with(&upper, "LOGIN") => ok(&cmd.tag, vec![], "200 OK"),
            _ if starts_with(&upper, "LOGOUT") || starts_with(&upper, "QUIT") => {
                ok(&cmd.tag, vec![], "200 OK")
            }
            _ => err(&cmd.tag, status::BAD_REQUEST, "400 Unknown command"),
        }
    }

    fn deny_new(&self) -> bool {
        self.access == AccessLevel::Monitor
    }

    fn project_list(&self, tag: &str) -> Response {
        let mut names: Vec<&String> = self.projects.keys().collect();
        names.sort();
        let lines = names.into_iter().cloned().collect();
        ok(tag, lines, "200 OK")
    }

    fn project_new(&mut self, tag: &str, words: &[&str]) -> Response {
        if self.deny_new() {
            return err(tag, status::ACCESS_DENIED, "420 Access denied");
        }
        if words.len() != 3 {
            return err(tag, status::BAD_REQUEST, "400 PROJECT NEW requires a name");
        }
        let name = words[2].to_string();
        if !valid_name(&name) {
            return err(tag, status::BAD_REQUEST, "400 Invalid project name");
        }
        if name.len() > 4
            && (name.as_bytes()[3] == b'-' || name.as_bytes()[3] == b' ')
            && name[..3]
                .parse::<u16>()
                .is_ok_and(|c| ENVELOPE_CODES.contains(&c))
        {
            // A coded name would spoof a status envelope in `PROJECT LIST`
            // bare payload lines.
            return err(tag, status::BAD_REQUEST, "400 Invalid project name");
        }
        if self.projects.contains_key(&name) {
            return err(tag, status::CONFLICT_EXISTS, "409 Project already exists");
        }
        self.projects.insert(
            name.clone(),
            Project {
                name: name.clone(),
                networks: HashMap::new(),
            },
        );
        self.current = Some(name.clone());
        // The name travels in the event so subscribed sessions (including
        // other connections) can identify what changed without a follow-up
        // query — the shape the native configuration stream relies on.
        self.push_event(format!("#e# project {name} created"));
        ok(tag, vec![], "200 OK")
    }

    fn project_use(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() == 2 {
            return if self.current.is_some() {
                ok(tag, vec![], "200 OK")
            } else {
                err(tag, status::NOT_FOUND, "404 No project selected")
            };
        }
        if words.len() != 3 {
            // Names the invoked verb so the PROJECT LOAD alias does not
            // leak "PROJECT USE" into diagnostics.
            return err(
                tag,
                status::BAD_REQUEST,
                &format!(
                    "400 PROJECT {} requires a name",
                    words[1].to_ascii_uppercase()
                ),
            );
        }
        let name = words[2];
        if !self.projects.contains_key(name) {
            return err(tag, status::NOT_FOUND, "404 Project not found");
        }
        self.current = Some(name.to_string());
        ok(tag, vec![], "200 OK")
    }

    fn project_load(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() <= 3 {
            return self.project_use(tag, words);
        }
        if words.len() != 4 || !valid_name(words[2]) || !valid_target(words[3]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PROJECT LOAD takes an optional project and server file",
            );
        }
        let Some(mut project) = self.database_files.get(words[3]).cloned() else {
            return err(tag, status::NOT_FOUND, "404 Project file not found");
        };
        project.name = words[2].to_string();
        self.projects.insert(words[2].to_string(), project);
        self.current = Some(words[2].to_string());
        ok(tag, vec![], "200 OK")
    }

    fn project_close(&mut self, tag: &str) -> Response {
        self.current = None;
        ok(tag, vec![], "200 OK")
    }

    fn project_save(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() > 3 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PROJECT SAVE takes an optional name",
            );
        }
        if let Some(name) = words.get(2) {
            if !self.projects.contains_key(*name) {
                return err(tag, status::NOT_FOUND, "404 Project not found");
            }
        } else if self.current.is_none() {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        }
        ok(tag, vec![], "200 OK")
    }

    fn project_delete(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(2..=3).contains(&words.len()) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PROJECT DELETE takes one optional name",
            );
        }
        let name = words
            .get(2)
            .map(|name| (*name).to_string())
            .or_else(|| self.current.clone());
        let Some(name) = name else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        if self.projects.remove(&name).is_none() {
            return err(tag, status::NOT_FOUND, "404 Project not found");
        }
        if self.current.as_deref() == Some(&name) {
            self.current = None;
        }
        ok(tag, vec![], "200 OK")
    }

    fn project_copy(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 4 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PROJECT COPY requires source and destination",
            );
        }
        let (src, dst) = (words[2], words[3]);
        let Some(project) = self.projects.get(src) else {
            return err(tag, status::NOT_FOUND, "404 Project not found");
        };
        if !valid_name(dst) {
            return err(tag, status::BAD_REQUEST, "400 Invalid project name");
        }
        if self.projects.contains_key(dst) {
            return err(tag, status::CONFLICT_EXISTS, "409 Project already exists");
        }
        let mut copy = project.clone();
        copy.name = dst.to_string();
        // Copied units are new database objects: mint one fresh OID per
        // address, shared across both layers like DBADDSAFE twins, so no
        // two live units share one identity.
        for network in copy.networks.values_mut() {
            let mut addrs: Vec<u8> = network.units.keys().copied().collect();
            addrs.extend(network.physical.keys().copied());
            addrs.sort();
            addrs.dedup();
            for addr in addrs {
                let oid = fresh_oid();
                if let Some(unit) = network.units.get_mut(&addr) {
                    unit.oid = oid.clone();
                }
                if let Some(unit) = network.physical.get_mut(&addr) {
                    unit.oid = oid;
                }
            }
        }
        let oids: Vec<String> = copy
            .networks
            .values()
            .flat_map(|n| {
                n.units
                    .values()
                    .chain(n.physical.values())
                    .map(|u| u.oid.clone())
            })
            .collect();
        self.projects.insert(dst.to_string(), copy);
        self.known_oids.extend(oids);
        // A copy duplicates database state, not just the project record.
        self.duplicate_prefix(&format!("//{src}"), &format!("//{dst}"));
        ok(tag, vec![], "200 OK")
    }

    /// Duplicate `db_fields`/`objects` keys under a new project prefix
    /// (project copy semantics), with the same boundary as moves.
    fn duplicate_prefix(&mut self, from: &str, to: &str) {
        let slash = format!("{from}/");
        let extra_fields: Vec<(String, String)> = self
            .db_fields
            .iter()
            .filter_map(|(k, v)| {
                if *k == from {
                    Some((to.to_string(), v.clone()))
                } else {
                    k.strip_prefix(&slash)
                        .map(|rest| (format!("{to}/{rest}"), v.clone()))
                }
            })
            .collect();
        self.db_fields.extend(extra_fields);
        let extra_objects: Vec<String> = self
            .objects
            .iter()
            .filter_map(|k| {
                if k == from {
                    Some(to.to_string())
                } else {
                    k.strip_prefix(&slash).map(|rest| format!("{to}/{rest}"))
                }
            })
            .collect();
        self.objects.extend(extra_objects);
        // Copied levels are new database objects: fresh OIDs with the
        // parent rewritten under the destination prefix.
        let extra_levels: Vec<DbLevel> = self
            .db_levels
            .values()
            .filter_map(|level| {
                let rest = if level.parent == from {
                    String::new()
                } else {
                    level.parent.strip_prefix(&slash)?.to_string()
                };
                let parent = if rest.is_empty() {
                    to.to_string()
                } else {
                    format!("{to}/{rest}")
                };
                Some(DbLevel {
                    oid: String::new(),
                    parent,
                    address: level.address,
                    tag: level.tag.clone(),
                    value: level.value,
                    netvar: level.netvar,
                })
            })
            .collect();
        for mut level in extra_levels {
            let oid = self.issue_oid();
            self.objects.insert(format!("!{oid}"));
            level.oid = oid.clone();
            self.db_levels.insert(oid, level);
        }
    }

    /// Native `PROJECT RENAME source destination`.
    fn project_rename(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 4 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PROJECT RENAME requires a source and destination",
            );
        }
        if self.deny_new() {
            return err(tag, status::ACCESS_DENIED, "420 Access denied");
        }
        let (src, dst) = (words[2], words[3]);
        if !valid_name(dst) {
            return err(tag, status::BAD_REQUEST, "400 Invalid project name");
        }
        let Some(mut project) = self.projects.remove(src) else {
            return err(tag, status::NOT_FOUND, "404 Project not found");
        };
        if self.projects.contains_key(dst) {
            self.projects.insert(src.to_string(), project);
            return err(tag, status::CONFLICT_EXISTS, "409 Project already exists");
        }
        project.name = dst.to_string();
        self.projects.insert(dst.to_string(), project);
        if self.current.as_deref() == Some(src) {
            self.current = Some(dst.to_string());
        }
        // Database keys travel with the project; otherwise field reads
        // under the new path miss while stale old-path entries leak.
        self.remap_prefix(&format!("//{src}"), &format!("//{dst}"));
        self.push_event(format!("#e# project {dst} renamed"));
        ok(tag, vec![], "200 OK")
    }

    /// Native `PROJECT DIR`: directory listing. The exact native entry
    /// shape is unmodeled, so this answers project names exactly like
    /// `PROJECT LIST` (documented approximation).
    fn project_dir(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() > 3
            || words
                .get(2)
                .is_some_and(|word| !word.eq_ignore_ascii_case("ALL"))
        {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PROJECT DIR takes only optional ALL",
            );
        }
        self.project_list(tag)
    }

    /// Native `PROJECT ARCHIVE name server-path`, backed by the model's
    /// process-local database snapshot store.
    fn project_archive(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 4 || !valid_name(words[2]) || !valid_target(words[3]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PROJECT ARCHIVE requires a project and server path",
            );
        }
        let Some(project) = self.projects.get(words[2]).cloned() else {
            return err(tag, status::NOT_FOUND, "404 Project not found");
        };
        self.database_files.insert(words[3].to_string(), project);
        ok(tag, vec![], "200 OK")
    }

    /// Native `PROJECT RESTORE name server-path` from the process-local
    /// archive store.
    fn project_restore(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 4 || !valid_name(words[2]) || !valid_target(words[3]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PROJECT RESTORE requires a project and server path",
            );
        }
        if self.projects.contains_key(words[2]) {
            return err(tag, status::CONFLICT_EXISTS, "409 Project already exists");
        }
        let Some(mut project) = self.database_files.get(words[3]).cloned() else {
            return err(tag, status::NOT_FOUND, "404 No such archived project");
        };
        project.name = words[2].to_string();
        self.projects.insert(words[2].to_string(), project);
        ok(tag, vec![], "200 OK")
    }

    /// Native `REPOSITORY LIST`: this mock models no server-side project
    /// repositories, so it answers the exact empty `124` reply the parser
    /// accepts for that case (documented — not a claim of repositories).
    fn repository_list(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 REPOSITORY LIST takes no arguments",
            );
        }
        Response {
            tag: tag.to_string(),
            lines: Vec::new(),
            final_text: "124 no repositories found".to_string(),
            status: 124,
        }
    }

    fn project_repair(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PROJECT REPAIR requires a name",
            );
        }
        let Some(project) = self.projects.get(words[2]) else {
            return err(tag, status::NOT_FOUND, "404 Project not found");
        };
        // The SQLite repository rejects native repair; model it by name.
        if project.networks.is_empty() && words[2].ends_with("_SQLITE") {
            return err(
                tag,
                status::CONFLICT_STATE,
                "408 Project repair not supported on SQLite repository",
            );
        }
        ok(tag, vec!["repaired=1".to_string()], "200 OK")
    }

    fn resolve_network_mut(&mut self, words: &[&str]) -> Result<(String, u8), Response> {
        if words.len() < 3 {
            return Err(err("", status::BAD_REQUEST, "400 Network address required"));
        }
        // Accept `//PROJECT/NET` or bare `NET`.
        let (project, net) = split_network(words[2]);
        let net: u8 = net
            .parse()
            .map_err(|_| err("", status::BAD_REQUEST, "400 Invalid network address"))?;
        Ok((project, net))
    }

    /// Create a closed database network in the current project.
    ///
    /// Mirrors native `DBCREATENET addr name Serial|Cni|Bridge iface-addr`
    /// (see `NativeDatabase.create_network`): networks come from the
    /// database layer, while `NET OPEN` only operates on existing ones.
    fn dbcreate_net(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 5 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 DBCREATENET requires address, name, interface type and interface address",
            );
        }
        let net: i64 = words[1].parse().unwrap_or(-1);
        if !(0..=255).contains(&net) {
            return err(tag, status::BAD_REQUEST, "400 Invalid network address");
        }
        if !valid_name(words[2]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid network name");
        }
        let iface = words[3].to_ascii_uppercase();
        if !matches!(iface.as_str(), "SERIAL" | "CNI" | "BRIDGE") {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 Interface type must be Serial, Cni or Bridge",
            );
        }
        if words[4].is_empty() {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 Interface address is required",
            );
        }
        let Some(proj) = self.current_project_mut() else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        let net = net as u8;
        if proj.networks.contains_key(&net) {
            return err(tag, status::CONFLICT_EXISTS, "409 Network already exists");
        }
        proj.networks.insert(
            net,
            Network {
                address: net,
                name: words[2].to_string(),
                iface_type: words[3].to_string(),
                iface_addr: words[4].to_string(),
                state: NetworkState::Closed,
                units: HashMap::new(),
                physical: HashMap::new(),
                levels: HashMap::new(),
            },
        );
        self.push_event(format!("#e# net {net} created"));
        ok(tag, vec![], "200 OK")
    }

    fn net_open(&mut self, tag: &str, words: &[&str]) -> Response {
        let (project, net) = match self.resolve_network_mut(words) {
            Ok(v) => v,
            Err(mut e) => {
                e.tag = tag.to_string();
                return e;
            }
        };
        let current = self.current.clone().unwrap_or_default();
        if !project.is_empty() && project != current {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let Some(proj) = self.current_project_mut() else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        // Networks are created by DBCREATENET; OPEN never invents one.
        let Some(entry) = proj.networks.get_mut(&net) else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        entry.state = NetworkState::Open;
        self.push_event(format!("#e# net {net} open"));
        ok(tag, vec![], "200 OK")
    }

    fn net_close(&mut self, tag: &str, words: &[&str]) -> Response {
        let (project, net) = match self.resolve_network_mut(words) {
            Ok(v) => v,
            Err(mut e) => {
                e.tag = tag.to_string();
                return e;
            }
        };
        let current = self.current.clone().unwrap_or_default();
        if !project.is_empty() && project != current {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let Some(proj) = self.current_project_mut() else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        let Some(entry) = proj.networks.get_mut(&net) else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        entry.state = NetworkState::Closed;
        ok(tag, vec![], "200 OK")
    }

    fn net_sync(&mut self, tag: &str, words: &[&str]) -> Response {
        // `NET SYNC address [fast] [retries]`, mirroring the native client.
        if !(3..=5).contains(&words.len()) {
            return err(tag, status::BAD_REQUEST, "400 NET SYNC requires an address");
        }
        let mut tail = &words[3..];
        if tail.first().is_some_and(|w| w.eq_ignore_ascii_case("fast")) {
            tail = &tail[1..];
        }
        if let Some((&retries, rest)) = tail.split_first() {
            if !valid_byte(retries) || !rest.is_empty() {
                return err(tag, status::BAD_REQUEST, "400 Invalid sync argument");
            }
        }
        let (project, net) = match self.resolve_network_mut(words) {
            Ok(v) => v,
            Err(mut e) => {
                e.tag = tag.to_string();
                return e;
            }
        };
        let current = self.current.clone().unwrap_or_default();
        if !project.is_empty() && project != current {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let Some(proj) = self.current_project_mut() else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        let Some(entry) = proj.networks.get_mut(&net) else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        if entry.state == NetworkState::Closed {
            return err(tag, status::CONFLICT_STATE, "408 Network is closed");
        }
        entry.state = NetworkState::Ok;
        self.push_event(format!("#e# net {net} sync ok"));
        ok(tag, vec![], "200 OK")
    }

    fn net_state(&mut self, tag: &str, words: &[&str]) -> Response {
        let (project, net) = match self.resolve_network_mut(words) {
            Ok(v) => v,
            Err(mut e) => {
                e.tag = tag.to_string();
                return e;
            }
        };
        let current = self.current.clone().unwrap_or_default();
        if !project.is_empty() && project != current {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let Some(proj) = self.current_project_mut() else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        let Some(entry) = proj.networks.get(&net) else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        let text = match entry.state {
            NetworkState::Closed => "closed",
            NetworkState::Open => "open",
            NetworkState::Syncing => "syncing",
            NetworkState::Ok => "ok",
        };
        ok(tag, vec![format!("state={text}")], "200 OK")
    }

    /// Native `TREE|TREEXML|TREEXMLDETAIL address [withsync ...]`
    /// (the `NET TREE` alias is also accepted).
    fn net_tree(&mut self, tag: &str, words: &[&str]) -> Response {
        let verb = words[0].to_ascii_uppercase();
        // `NET TREE addr` carries the target at words[2]; bare `TREE addr`
        // (and XML variants) carry it at words[1].
        let (target_index, xml, detail) = match verb.as_str() {
            "TREE" | "TREEXML" | "TREEXMLDETAIL" => (1, verb != "TREE", verb == "TREEXMLDETAIL"),
            _ => (2, false, false),
        };
        let Some(&target) = words.get(target_index) else {
            return err(tag, status::BAD_REQUEST, "400 Tree requires an address");
        };
        for flag in &words[target_index + 1..] {
            if !matches!(
                flag.to_ascii_uppercase().as_str(),
                "WITHSYNC" | "WITHPSYNC" | "WITHQSYNC"
            ) {
                return err(tag, status::BAD_REQUEST, "400 Unknown tree flag");
            }
        }
        let probe = ["TREE", "OP", target];
        let (project, net) = match self.resolve_network_mut(&probe) {
            Ok(v) => v,
            Err(mut e) => {
                e.tag = tag.to_string();
                return e;
            }
        };
        let current = self.current.clone().unwrap_or_default();
        if !project.is_empty() && project != current {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let Some(proj) = self.current_project_mut() else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        let Some(entry) = proj.networks.get(&net) else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        // The tree reports physically present units (discovery view).
        let mut addrs: Vec<u8> = entry.physical.keys().copied().collect();
        addrs.sort();
        if !xml {
            let lines = addrs.into_iter().map(|a| format!("unit={a}")).collect();
            return ok(tag, lines, "200 OK");
        }
        // Minimal XML tree: one document line per network plus unit lines.
        // Like every other multiline reply, rows travel as tagged
        // continuations; XML consumers strip envelopes via `_rows`
        // (the same convention as DBGETXML snippet lines).
        let mut lines = vec![format!(
            "<Tree project=\"{current}\" network=\"{net}\" detail=\"{detail}\"/>"
        )];
        lines.extend(
            addrs
                .into_iter()
                .map(|a| format!("<Unit address=\"{a}\"/>")),
        );
        ok(tag, lines, "200 OK")
    }

    fn dbget(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 {
            return err(tag, status::BAD_REQUEST, "400 DBGET requires a path");
        }
        let xml = words[0].eq_ignore_ascii_case("DBGETXML");
        let path = words[1];
        if path.is_empty() || path.contains('#') {
            return err(tag, status::BAD_REQUEST, "400 Invalid DBGET path");
        }
        // `!OID/...` identity paths address objects outside the
        // project/network tree. `!oid/OID` resolves issued OIDs with the
        // native 342 reply the level initializer requires; `!oid/Value`
        // reads a level's initialized byte (`null` while native NULL);
        // `DBGETXML !oid` reports the level document whose root tag the
        // copy flow probes. Anything else is accepted opaquely without
        // claiming resolution.
        if let Some(rest) = path.strip_prefix('!') {
            if rest.contains("/OID") {
                let oid = rest.split('/').next().unwrap_or("");
                if !self.known_oids.contains(oid) {
                    return err(tag, status::ABSENT, "401 Object not found");
                }
                // Single 342 line in the exact native shape: collectors
                // require exactly `342 !oid/OID=oid` as the only line.
                return Response {
                    tag: tag.to_string(),
                    lines: Vec::new(),
                    final_text: format!("342 !{oid}/OID={oid}"),
                    status: 342,
                };
            }
            if !xml {
                let mut segments = rest.splitn(2, '/');
                let oid = segments.next().unwrap_or("");
                if segments.next() == Some("Value") {
                    if let Some(level) = self.db_levels.get(oid) {
                        let value = level
                            .value
                            .map(|v| v.to_string())
                            .unwrap_or_else(|| "null".to_string());
                        // Space final like the `!oid/OID` probe: a
                        // dash-final would read as a continuation and
                        // never complete the reply on the wire.
                        return Response {
                            tag: tag.to_string(),
                            lines: Vec::new(),
                            final_text: format!("342 {path}={value}"),
                            status: 342,
                        };
                    }
                    return err(tag, status::ABSENT, "401 Object not found");
                }
            }
            if xml && !rest.contains('/') {
                if let Some(level) = self.db_levels.get(rest) {
                    return Self::level_xml(tag, level);
                }
                return err(tag, status::ABSENT, "401 Object not found");
            }
            return ok(tag, vec![format!("path={path}")], "200 OK");
        }
        let current = self.current.clone().unwrap_or_default();
        // `//PROJECT/NET[/APP[/GROUP]]`: the project and network must exist.
        let parts: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
        if parts.len() < 2 {
            return err(tag, status::BAD_REQUEST, "400 Invalid DBGET path");
        }
        let Some(proj) = self.projects.get(&current) else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        if parts[0] != current {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let net: i64 = parts[1].parse().unwrap_or(-1);
        if !(0..=255).contains(&net) || !proj.networks.contains_key(&(net as u8)) {
            return err(tag, status::ABSENT, "401 Network not found");
        }
        // XML first: DBGETXML on a unit path answers the 347 snippet, not
        // the 342 field rows below.
        if xml {
            // `xml_text` collects 347-tagged snippet rows; `copy()` parses
            // the root tag. Network paths report a real document built
            // from model state (address, interface, per-unit identity);
            // unit paths report their kind; group paths report the
            // `<Group>`/`<NetVar>` document of recorded levels (tag
            // resolution parses exactly this shape); anything else a
            // generic object.
            if parts.len() == 2 && Self::split_unit(path).is_none() {
                return self.network_xml(tag, parts[0], net as u8);
            }
            if parts.len() == 4 && Self::split_unit(path).is_none() {
                return self.group_xml(tag, path);
            }
            let snippet = if let Some((_, _, addr)) = Self::split_unit(path) {
                let name = proj.networks[&(net as u8)]
                    .units
                    .get(&addr)
                    .map(|u| u.field("UnitName"))
                    .unwrap_or_default();
                format!("<Unit address=\"{addr}\" name=\"{}\"/>", xml_escape(&name))
            } else {
                format!("<Object path=\"{}\"/>", xml_escape(path))
            };
            return Response {
                tag: tag.to_string(),
                lines: vec![format!("347-{snippet}")],
                final_text: "200 OK".to_string(),
                status: status::OK,
            };
        }
        // A bare unit path (`//P/N/p/A`) answers with one 342 row per
        // database field: session `/db/` LOAD identity seeding collects
        // UnitType/FirmwareVersion/CatalogNumber from exactly these rows.
        if parts.len() == 4 {
            if let Some((_, _, addr)) = Self::split_unit(path) {
                if let Some(unit) = proj.networks[&(net as u8)].units.get(&addr) {
                    let mut names: Vec<&String> = unit.fields.keys().collect();
                    names.sort();
                    // Rows carry their own 342 envelope (the formatter
                    // passes coded lines through untouched).
                    let mut lines: Vec<String> = names
                        .into_iter()
                        .map(|k| format!("342-{path}/{k}={}", unit.fields[k]))
                        .collect();
                    if !unit.fields.contains_key("CatalogNumber") {
                        lines.push(format!("342-{path}/CatalogNumber=null"));
                    }
                    return Response {
                        tag: tag.to_string(),
                        lines,
                        final_text: "200 OK".to_string(),
                        status: status::OK,
                    };
                }
                return err(tag, status::ABSENT, "401 Unit not found");
            }
        }
        // Unit-field paths (`//P/N/p/A/Field`) answer with a 342 row so
        // session SAVE binding and `/db/` LOAD identity seeding observe
        // database values; the final status stays 200.
        if parts.len() >= 5 {
            if let Some((_, _, addr)) = Self::split_unit(path) {
                if let Some(unit) = proj.networks[&(net as u8)].units.get(&addr) {
                    let field = parts[4..].join("/");
                    let mut value = unit.field(&field);
                    if value.is_empty()
                        && !self.db_fields.contains_key(path)
                        && field == "CatalogNumber"
                    {
                        value = "null".to_string();
                    }
                    return Response {
                        tag: tag.to_string(),
                        lines: vec![format!("342-{path}={value}")],
                        final_text: "200 OK".to_string(),
                        status: status::OK,
                    };
                }
                return err(tag, status::ABSENT, "401 Unit not found");
            }
        }
        ok(tag, vec![format!("path={path}")], "200 OK")
    }

    /// Native network document for `DBGETXML //PROJECT/NET`.
    ///
    /// A single-line document the addressing inventory and physical
    /// database checks parse: network address/interface plus one `Unit`
    /// element per database unit (address, type, serial, name, OID).
    /// Values come from model state; catalogue-backed details beyond
    /// these fields are not modeled (documented limit).
    fn network_xml(&self, tag: &str, proj_name: &str, net: u8) -> Response {
        let Some(network) = self
            .projects
            .get(proj_name)
            .and_then(|p| p.networks.get(&net))
        else {
            return err(tag, status::ABSENT, "401 Network not found");
        };
        let mut doc = format!(
            "<Network><Address>{net}</Address><InterfaceType>{}</InterfaceType><InterfaceAddress>{}</InterfaceAddress>",
            xml_escape(&network.iface_type),
            xml_escape(&network.iface_addr),
        );
        let mut addrs: Vec<u8> = network.units.keys().copied().collect();
        addrs.sort();
        for addr in addrs {
            let unit = &network.units[&addr];
            doc.push_str(&format!(
                "<Unit><Address>{addr}</Address><UnitType>{}</UnitType><FirmwareVersion>{}</FirmwareVersion><SerialNumber>{}</SerialNumber><UnitName>{}</UnitName><OID>{}</OID></Unit>",
                xml_escape(&unit.field("UnitType")),
                xml_escape(&unit.field("FirmwareVersion")),
                xml_escape(&unit.field("SerialNumber")),
                xml_escape(&unit.field("UnitName")),
                xml_escape(&unit.oid),
            ));
        }
        doc.push_str("</Network>");
        Response {
            tag: tag.to_string(),
            lines: vec![format!("347-{doc}")],
            final_text: "200 OK".to_string(),
            status: status::OK,
        }
    }

    /// Native group document for `DBGETXML //PROJECT/NET/APP/GROUP`.
    ///
    /// One `<Level>` row per recorded level under the parent path, in
    /// selector order, with the evidenced shape only (`Value` attribute
    /// plus `TagName` child). An uninitialized level carries no `Value`
    /// attribute (native NULL), which tag resolution rejects as having
    /// no valid byte value. The root is `NetVar` when every recorded row
    /// is a NetVar, else `Group`.
    fn group_xml(&self, tag: &str, path: &str) -> Response {
        let mut rows: Vec<&DbLevel> = self
            .db_levels
            .values()
            .filter(|l| l.parent == path)
            .collect();
        rows.sort_by_key(|l| (l.address, l.oid.clone()));
        let root = if !rows.is_empty() && rows.iter().all(|l| l.netvar) {
            "NetVar"
        } else {
            "Group"
        };
        let mut doc = format!("<{root}>");
        for level in rows {
            doc.push_str(&Self::level_row(level));
        }
        doc.push_str(&format!("</{root}>"));
        Response {
            tag: tag.to_string(),
            lines: vec![format!("347-{doc}")],
            final_text: "200 OK".to_string(),
            status: status::OK,
        }
    }

    /// Native level document for `DBGETXML !oid`: the single evidenced
    /// row as the document root (`Level`; `NetVar` wrapping the row for
    /// NetVar records, whose kind probe must not read `Level`).
    fn level_xml(tag: &str, level: &DbLevel) -> Response {
        let row = Self::level_row(level);
        let doc = if level.netvar {
            format!("<NetVar>{row}</NetVar>")
        } else {
            row
        };
        Response {
            tag: tag.to_string(),
            lines: vec![format!("347-{doc}")],
            final_text: "200 OK".to_string(),
            status: status::OK,
        }
    }

    /// One evidenced `<Level>` row: `Value` attribute (absent while
    /// native NULL) plus `TagName` child. No other level fields are
    /// modeled, so none are emitted.
    fn level_row(level: &DbLevel) -> String {
        let value = level
            .value
            .map(|v| format!(" Value=\"{v}\""))
            .unwrap_or_default();
        format!(
            "<Level{value}><TagName>{}</TagName></Level>",
            xml_escape(&level.tag)
        )
    }

    /// Native lighting verbs as sent by `SceneExecutor` and `NativeLabels`:
    /// `LIGHTING ON|OFF|STOP address`, `LIGHTING RAMP address level
    /// ramp-seconds`, and the `LIGHTING LABEL|UNICODELABEL ...` family with
    /// opaque trailing arguments.
    fn lighting(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 3 || !words[0].eq_ignore_ascii_case("LIGHTING") {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 Lighting command requires a verb and address",
            );
        }
        let verb = words[1].to_ascii_uppercase();
        if verb == "LABEL" || verb == "UNICODELABEL" {
            return self.lighting_label(tag, words);
        }
        if !matches!(verb.as_str(), "ON" | "OFF" | "RAMP" | "STOP") {
            return err(tag, status::BAD_REQUEST, "400 Unknown lighting verb");
        }
        if !valid_target(words[2]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid lighting address");
        }
        let Some((proj_name, net, app, group)) = Self::split_lighting(words[2]) else {
            return err(tag, status::BAD_REQUEST, "400 Invalid lighting address");
        };
        if proj_name != self.current.clone().unwrap_or_default() {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        // Levels apply instantly (documented mock behavior): ON=255,
        // OFF=0, RAMP=level, STOP holds the current level.
        let applied = match verb.as_str() {
            "ON" | "OFF" | "STOP" => {
                if words.len() != 3 {
                    return err(
                        tag,
                        status::BAD_REQUEST,
                        "400 Lighting command takes an address only",
                    );
                }
                None
            }
            _ => {
                // RAMP carries a byte level and native ramp seconds
                // (signed 32-bit range, mirroring `SceneAction`).
                if words.len() != 5 {
                    return err(
                        tag,
                        status::BAD_REQUEST,
                        "400 Lighting RAMP requires an address, level and ramp seconds",
                    );
                }
                let level: i64 = words[3].parse().unwrap_or(-1);
                if !valid_lighting_level(level) {
                    return err(tag, status::BAD_REQUEST, "400 Invalid lighting level");
                }
                let ramp: i64 = words[4].parse().unwrap_or(-1);
                if !(0..=2147483647).contains(&ramp) {
                    return err(tag, status::BAD_REQUEST, "400 Invalid ramp seconds");
                }
                Some(level as u8)
            }
        };
        let Some(network) = self
            .projects
            .get_mut(&proj_name)
            .and_then(|p| p.networks.get_mut(&net))
        else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        let level = match verb.as_str() {
            "ON" => 255,
            "OFF" => 0,
            "STOP" => match network.levels.get(&(app, group)).copied() {
                // A hold with no prior level is a no-op: no state is
                // created and no event is emitted for a transition that
                // never happened.
                None => return ok(tag, vec![], "200 OK"),
                Some(current) => current,
            },
            _ => applied.expect("RAMP level validated"),
        };
        network.levels.insert((app, group), level);
        // The event preserves the verb and ramp intent so observers can
        // distinguish `ON` from `RAMP 255` and instant from timed ramps
        // (state itself still applies instantly per the mock contract).
        let detail = if verb == "RAMP" {
            format!(" RAMP {} {}", level, words[4])
        } else {
            format!(" {verb} {level}")
        };
        self.push_event(format!("#e# lighting {}{detail}", words[2]));
        ok(tag, vec![], "200 OK")
    }

    /// Split a lighting address `//PROJECT/NET/APP/GROUP` into parts.
    ///
    /// Identity (`!oid`) paths are never lighting addresses natively, so a
    /// leading `!` is rejected up front with `400` rather than surfacing as
    /// a project mismatch further down.
    fn split_lighting(path: &str) -> Option<(String, u8, u8, u8)> {
        if path.starts_with('!') {
            return None;
        }
        let t = path.trim_start_matches('/');
        let parts: Vec<&str> = t.split('/').collect();
        if parts.len() != 4 {
            return None;
        }
        Some((
            parts[0].to_string(),
            parts[1].parse().ok()?,
            parts[2].parse().ok()?,
            parts[3].parse().ok()?,
        ))
    }

    /// `TRIGGER|ENABLE LABEL|UNICODELABEL application language group
    /// action Fvariant ...`: structural prefix check, opaque remainder.
    /// C-Gate 3.4 ENABLE has no UNICODELABEL command.
    fn lighting_label(&mut self, tag: &str, words: &[&str]) -> Response {
        let family = words[0].to_ascii_uppercase();
        let verb = words[1].to_ascii_uppercase();
        if words.len() < 7 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 Label command requires application, language, group, action and flags",
            );
        }
        if family == "ENABLE" && verb == "UNICODELABEL" {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 ENABLE has no UNICODELABEL command",
            );
        }
        for word in &words[2..7] {
            if word.is_empty() || word.contains('#') {
                return err(tag, status::BAD_REQUEST, "400 Invalid label address");
            }
        }
        ok(tag, vec![], "200 OK")
    }

    /// Native `TRIGGER EVENT group selector [FORCE]`.
    fn trigger(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(4..=5).contains(&words.len())
            || !words[0].eq_ignore_ascii_case("TRIGGER")
            || !words[1].eq_ignore_ascii_case("EVENT")
        {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 TRIGGER EVENT requires a group, selector and optional FORCE",
            );
        }
        if !valid_target(words[2]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid trigger group");
        }
        if !valid_byte(words[3]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid trigger selector");
        }
        if words.len() == 5 && !words[4].eq_ignore_ascii_case("FORCE") {
            return err(tag, status::BAD_REQUEST, "400 Unknown trigger argument");
        }
        self.push_event(format!("#e# trigger {}", words[2]));
        ok(tag, vec![], "200 OK")
    }

    /// Native `TRIGGER INDICATORKILL group`.
    fn trigger_kill(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 TRIGGER INDICATORKILL requires a group",
            );
        }
        if !valid_target(words[2]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid trigger group");
        }
        self.push_event(format!("#e# trigger-kill {}", words[2]));
        ok(tag, vec![], "200 OK")
    }

    /// Native `ENABLE SET address value [FORCE]`.
    fn enable_set(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(4..=5).contains(&words.len())
            || !words[0].eq_ignore_ascii_case("ENABLE")
            || !words[1].eq_ignore_ascii_case("SET")
        {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 ENABLE SET requires an address, value and optional FORCE",
            );
        }
        if !valid_target(words[2]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid enable address");
        }
        if !valid_byte(words[3]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid enable value");
        }
        if words.len() == 5 && !words[4].eq_ignore_ascii_case("FORCE") {
            return err(tag, status::BAD_REQUEST, "400 Unknown enable argument");
        }
        ok(tag, vec![], "200 OK")
    }

    /// Native programming verbs (`PP ...`).
    ///
    /// Session operations address open sessions (`PP <OP> <session>
    /// [tail]`); catalogue, raw-memory and patch verbs have no model
    /// behind them and answer with an explicit error rather than
    /// invented content.
    fn programming(&mut self, tag: &str, words: &[&str]) -> Response {
        if !self.allow_programming
            || matches!(self.access, AccessLevel::Admin | AccessLevel::Monitor)
        {
            return err(tag, status::ACCESS_DENIED, "420 Access denied");
        }
        let op = words.get(1).map(|w| w.to_ascii_uppercase());
        match op.as_deref() {
            Some("LOCK") => self.pp_lock(tag, words),
            Some("UNLOCK") => self.pp_unlock(tag, words),
            Some("CANCEL_LOCK") => self.pp_cancel_lock(tag, words),
            Some("LIST_LOCK") => self.pp_list_lock(tag, words),
            Some("UNITS") => self.pp_units(tag, words),
            Some("START") => self.pp_start(tag, words),
            Some("END") => self.pp_end(tag, words),
            Some("NEW") => self.pp_new(tag, words),
            Some("LOAD") => self.pp_load(tag, words),
            Some("LOAD_FROM_FILE") => self.pp_load_file(tag, words),
            Some("SAVE") => self.pp_save(tag, words),
            Some("SAVE_TO_SOURCE") => self.pp_save_to_source(tag, words),
            Some("GET") => self.pp_get(tag, words),
            Some("SET") => self.pp_set(tag, words),
            Some("INFO") => self.pp_info(tag, words),
            Some("RESET_TO_DEFAULTS") => self.pp_reset(tag, words),
            Some("QUICKGET") => self.pp_quickget(tag, words),
            Some("COPY") => self.pp_copy(tag, words),
            Some("LIST_CATALOG_NUMBERS") => {
                // The mock holds no catalogue data: answer explicitly
                // rather than fabricating an empty catalogue that callers
                // would misread as a native rejection.
                if words.len() != 4 {
                    return err(
                        tag,
                        status::BAD_REQUEST,
                        "400 PP LIST_CATALOG_NUMBERS requires a unit type and firmware",
                    );
                }
                err(
                    tag,
                    status::BAD_REQUEST,
                    "400 Catalogue data is not modeled by this mock",
                )
            }
            _ => err(
                tag,
                status::BAD_REQUEST,
                "400 PP verb is not emulated by this model",
            ),
        }
    }

    /// Native `PP LOCK name address`.
    fn pp_lock(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 4 || !valid_target(words[2]) || !valid_target(words[3]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP LOCK requires a name and address",
            );
        }
        if self.locks.contains_key(words[2]) {
            return err(tag, status::CONFLICT_EXISTS, "409 Lock already held");
        }
        self.locks
            .insert(words[2].to_string(), words[3].to_string());
        ok(tag, vec![], "200 OK")
    }

    /// Native `PP UNLOCK name`.
    fn pp_unlock(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 {
            return err(tag, status::BAD_REQUEST, "400 PP UNLOCK requires a name");
        }
        if self.locks.remove(words[2]).is_none() {
            return err(tag, status::NOT_FOUND, "404 Lock not found");
        }
        ok(tag, vec![], "200 OK")
    }

    /// Native `PP CANCEL_LOCK address`.
    fn pp_cancel_lock(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 || !valid_target(words[2]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP CANCEL_LOCK requires an address",
            );
        }
        let before = self.locks.len();
        self.locks.retain(|_, addr| addr != words[2]);
        ok(
            tag,
            vec![format!("cancelled={}", before - self.locks.len())],
            "200 OK",
        )
    }

    /// Native `PP LIST_LOCK`.
    fn pp_list_lock(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP LIST_LOCK takes no arguments",
            );
        }
        let mut names: Vec<&String> = self.locks.keys().collect();
        names.sort();
        let lines = names
            .into_iter()
            .map(|n| format!("lock={n} address={}", self.locks[n]))
            .collect();
        ok(tag, lines, "200 OK")
    }

    /// Native `PP UNITS`: sessions currently open (documented reading —
    /// the verb's exact native inventory is not modeled).
    fn pp_units(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 {
            return err(tag, status::BAD_REQUEST, "400 PP UNITS takes no arguments");
        }
        let mut names: Vec<&String> = self.sessions.keys().collect();
        names.sort();
        let lines = names.into_iter().map(|n| format!("session={n}")).collect();
        ok(tag, lines, "200 OK")
    }

    /// Native `PP START name lock`.
    fn pp_start(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 4 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP START requires a name and lock",
            );
        }
        if !self.locks.contains_key(words[3]) {
            return err(tag, status::NOT_FOUND, "404 Lock not found");
        }
        if self.sessions.contains_key(words[2]) {
            return err(tag, status::CONFLICT_EXISTS, "409 Session already open");
        }
        self.sessions.insert(
            words[2].to_string(),
            PpSession {
                name: words[2].to_string(),
                lock: words[3].to_string(),
                source: None,
                unit_type: None,
                firmware: None,
                catalog_number: None,
                params: HashMap::new(),
                dirty: HashSet::new(),
            },
        );
        ok(tag, vec![], "200 OK")
    }

    /// Native `PP END name`.
    fn pp_end(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 {
            return err(tag, status::BAD_REQUEST, "400 PP END requires a name");
        }
        if self.sessions.remove(words[2]).is_none() {
            return err(tag, status::NOT_FOUND, "404 Session not found");
        }
        ok(tag, vec![], "200 OK")
    }

    fn pp_session(&mut self, tag: &str, words: &[&str]) -> Result<(String, PpSession), Response> {
        if words.len() < 3 {
            return Err(err(
                tag,
                status::BAD_REQUEST,
                "400 PP command requires a session",
            ));
        }
        match self.sessions.get(words[2]) {
            // Mock strictness: the starting lock must still be held.
            // Correct flows always END before UNLOCK, so only misuse
            // (use-after-release, wrong-session reuse) hits this.
            Some(session) if self.locks.contains_key(&session.lock) => {
                Ok((tag.to_string(), session.clone()))
            }
            Some(_) => Err(err(tag, status::CONFLICT_EXISTS, "409 Lock not held")),
            None => Err(err(tag, status::NOT_FOUND, "404 Session not found")),
        }
    }

    fn pp_store(&mut self, tag: &str, session: PpSession) -> Response {
        self.sessions.insert(session.name.clone(), session);
        ok(tag, vec![], "200 OK")
    }

    /// Native `PP NEW name unit-type firmware [catalog-number]`.
    fn pp_new(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(5..=6).contains(&words.len()) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP NEW requires a session, unit type and firmware",
            );
        }
        let (_, mut session) = match self.pp_session(tag, words) {
            Ok(v) => v,
            Err(r) => return r,
        };
        session.source = None;
        session.unit_type = Some(words[3].to_string());
        session.firmware = Some(words[4].to_string());
        session.catalog_number = words.get(5).map(|s| s.to_string());
        // Identity lives in the session struct, not the parameter
        // namespace: native `PP GET *` carries no UnitType/
        // FirmwareVersion/CatalogNumber rows (the eDLT snapshotter
        // requires an exact parameter set), and export/snapshot flows
        // read identity from the session itself. Catalogue defaults seed
        // the namespace when a matching spec is configured.
        if let Some(spec) = self.spec_for(words[3]) {
            for param in &spec {
                if let Some(default) = param.get("DefaultValue") {
                    session
                        .params
                        .entry(param.name.clone())
                        .or_insert_with(|| default.to_string());
                }
            }
        }
        session.dirty = session.params.keys().cloned().collect();
        self.pp_store(tag, session)
    }

    /// Native `PP LOAD name source [tags...]`.
    fn pp_load(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 4 || !valid_target(words[3]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP LOAD requires a session and source",
            );
        }
        let (_, mut session) = match self.pp_session(tag, words) {
            Ok(v) => v,
            Err(r) => return r,
        };
        session.source = Some(words[3].to_string());
        session.params.clear();
        session.dirty.clear();
        session.unit_type = None;
        session.firmware = None;
        session.catalog_number = None;
        // A `/db/` source seeds identity and values from the database
        // record; anything else loads unverified (documented limit).
        if let Some(path) = words[3].strip_prefix("/db") {
            let path = if path.starts_with('/') || path.starts_with("!") {
                path.to_string()
            } else {
                format!("/{path}")
            };
            let Some((proj_name, net, addr)) = self.unit_of(&path) else {
                return err(tag, status::NOT_FOUND, "404 Unit not found");
            };
            let Some(unit) = self
                .projects
                .get(&proj_name)
                .and_then(|p| p.networks.get(&net))
                .and_then(|n| n.units.get(&addr))
                .cloned()
            else {
                return err(tag, status::NOT_FOUND, "404 Unit not found");
            };
            session.unit_type = non_empty(unit.field("UnitType"));
            session.firmware = non_empty(unit.field("FirmwareVersion"));
            session.catalog_number = non_empty(unit.field("CatalogNumber"));
            // Database identity fields are not PP parameters: keep them
            // out of the staged namespace (see pp_new) while preserving
            // every genuine parameter for the session.
            session.params = unit
                .fields
                .iter()
                .filter(|(k, _)| {
                    !matches!(k.as_str(), "UnitType" | "FirmwareVersion" | "CatalogNumber")
                })
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect();
            if session.unit_type.is_none() || session.firmware.is_none() {
                // Match the client's own guard with a clear server-side
                // error: identity-free records cannot seed a session.
                return err(
                    tag,
                    status::CONFLICT_STATE,
                    "408 Database source provides no unit identity",
                );
            }
            // Catalogue defaults fill whatever the record lacks, mirroring
            // native schema-backed loads; database values always win.
            // Without a matching spec the session stays sparse. Only
            // parameters declaring a DefaultValue seed (an absent default
            // is not invented).
            if let Some(unit_type) = session.unit_type.clone() {
                if let Some(spec) = self.spec_for(&unit_type) {
                    for param in &spec {
                        if let Some(default) = param.get("DefaultValue") {
                            session
                                .params
                                .entry(param.name.clone())
                                .or_insert_with(|| default.to_string());
                        }
                    }
                }
            }
        }
        self.pp_store(tag, session)
    }

    /// Native `PP LOAD_FROM_FILE name filename`: no server files exist in
    /// this model, so identity and values clear (documented limit).
    fn pp_load_file(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 4 || !valid_target(words[3]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP LOAD_FROM_FILE requires a session and filename",
            );
        }
        let (_, mut session) = match self.pp_session(tag, words) {
            Ok(v) => v,
            Err(r) => return r,
        };
        session.source = None;
        session.unit_type = None;
        session.firmware = None;
        session.catalog_number = None;
        session.params.clear();
        self.pp_store(tag, session)
    }

    /// Persist staged values to a `/db/` unit record.
    ///
    /// Database-only by design: physical transfer to the device is a
    /// separate unverified step, so programmed values stay invisible to
    /// scans until then (this asymmetry with the mirroring `DBSETSAFE`
    /// path is intentional, not a missing sync).
    fn pp_persist(&mut self, session: &PpSession) -> Result<(), Response> {
        let empty = String::new();
        let dest = session.source.as_ref().unwrap_or(&empty);
        let path = dest.strip_prefix("/db").unwrap_or(dest);
        let path = if path.starts_with('/') || path.starts_with('!') {
            path.to_string()
        } else {
            format!("/{path}")
        };
        let Some((proj_name, net, addr)) = self.unit_of(&path) else {
            return Err(err("", status::NOT_FOUND, "404 Unit not found"));
        };
        let Some(unit) = self
            .projects
            .get_mut(&proj_name)
            .and_then(|p| p.networks.get_mut(&net))
            .and_then(|n| n.units.get_mut(&addr))
        else {
            return Err(err("", status::NOT_FOUND, "404 Unit not found"));
        };
        for (key, value) in &session.params {
            unit.fields.insert(key.clone(), value.clone());
            // Keep the dedicated struct fields in step with the map so
            // direct struct readers never diverge from field reads.
            match key.as_str() {
                "UnitType" | "Type" => unit.unit_type = value.clone(),
                "FirmwareVersion" | "Version" => unit.firmware = value.clone(),
                "SerialNumber" => unit.serial = value.clone(),
                _ => {}
            }
            self.db_fields
                .insert(format!("{path}/{key}"), value.clone());
        }
        Ok(())
    }

    /// Native `PP SAVE name destination [tags...]`.
    fn pp_save(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 4 || !valid_target(words[3]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP SAVE requires a session and destination",
            );
        }
        let (_, session) = match self.pp_session(tag, words) {
            Ok(v) => v,
            Err(r) => return r,
        };
        if !words[3].starts_with("/db/") && !words[3].starts_with("/db//") {
            // Live-hardware programming has no model behind it; refuse
            // loudly rather than reporting a programming success.
            return err(
                tag,
                status::BAD_REQUEST,
                "400 SAVE destination must be a database path in this model",
            );
        }
        let mut session = session;
        session.source = Some(words[3].to_string());
        if let Err(mut e) = self.pp_persist(&session) {
            e.tag = tag.to_string();
            return e;
        }
        session.dirty.clear();
        self.push_event(format!("#e# pp save {}", session.name));
        self.pp_store(tag, session)
    }

    /// Native `PP SAVE_TO_SOURCE name [tags...]`.
    fn pp_save_to_source(&mut self, tag: &str, words: &[&str]) -> Response {
        let (_, mut session) = match self.pp_session(tag, words) {
            Ok(v) => v,
            Err(r) => return r,
        };
        let Some(source) = session.source.clone() else {
            return err(
                tag,
                status::CONFLICT_STATE,
                "408 Session has no loaded source",
            );
        };
        if !source.starts_with("/db/") {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 SAVE_TO_SOURCE needs a database source in this model",
            );
        }
        if let Err(mut e) = self.pp_persist(&session) {
            e.tag = tag.to_string();
            return e;
        }
        session.dirty.clear();
        self.push_event(format!("#e# pp save {}", session.name));
        self.pp_store(tag, session)
    }

    /// Native `PP GET name [parameter]`; parameter values travel as 315 rows.
    fn pp_get(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(3..=4).contains(&words.len()) {
            return err(tag, status::BAD_REQUEST, "400 PP GET requires a session");
        }
        let (_, session) = match self.pp_session(tag, words) {
            Ok(v) => v,
            Err(r) => return r,
        };
        let wanted = words.get(3).copied().unwrap_or("*");
        if wanted == "*" {
            let mut names: Vec<&String> = session.params.keys().collect();
            names.sort();
            let lines = names
                .into_iter()
                .map(|k| format!("{k}={}", session.params[k]))
                .collect();
            return parameter_reply(tag, lines);
        }
        match session.params.get(wanted) {
            Some(value) => parameter_reply(tag, vec![format!("{wanted}={value}")]),
            None => err(tag, status::NOT_FOUND, "404 Parameter not found"),
        }
    }

    /// Native `PP SET name parameter value...`.
    fn pp_set(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 5 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP SET requires a session, parameter and value",
            );
        }
        if words[3].is_empty() || words[3].contains('#') {
            return err(tag, status::BAD_REQUEST, "400 Invalid parameter name");
        }
        let (_, mut session) = match self.pp_session(tag, words) {
            Ok(v) => v,
            Err(r) => return r,
        };
        // Values arrive mK-quoted (`quote_value`: `"a\ b\"c\\d"`); native
        // dequotes on store, so readback observes the raw value. The
        // remainder of the line after the parameter name is the value.
        let raw = words[4..].join(" ");
        session
            .params
            .insert(words[3].to_string(), dequote_value(&raw));
        session.dirty.insert(words[3].to_string());
        self.pp_store(tag, session)
    }

    /// Native `PP INFO name [parameter]`: schema envelope.
    ///
    /// With a unitspec directory configured and a matching `<Type>.xml`,
    /// elements come from the real specification (names, types, layout
    /// and ranges verbatim); otherwise scalar-int elements are
    /// synthesized with no `Address`, so spaced-byte flows fail with an
    /// explicit schema error instead of guessing hardware layout.
    fn pp_info(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(3..=4).contains(&words.len()) {
            return err(tag, status::BAD_REQUEST, "400 PP INFO requires a session");
        }
        let (_, session) = match self.pp_session(tag, words) {
            Ok(v) => v,
            Err(r) => return r,
        };
        let wanted = words.get(3).copied().unwrap_or("*");
        if let Some(unit_type) = session.unit_type.clone() {
            if let Some(spec) = self.spec_for(&unit_type) {
                return self.spec_info(tag, &session, &spec, wanted);
            }
        }
        let mut names: Vec<&String> = if wanted == "*" {
            session.params.keys().collect()
        } else {
            match session.params.keys().find(|k| *k == wanted) {
                Some(k) => vec![k],
                None => return err(tag, status::NOT_FOUND, "404 Parameter not found"),
            }
        };
        names.sort();
        let mut xml = String::from("<Parameters>");
        for name in names {
            xml.push_str(&format!(
                "<Param><Name>{}</Name><Type>int</Type><BitSize>8</BitSize><ArraySize>1</ArraySize><BitAddress>0</BitAddress><MinValue>0</MinValue><MaxValue>255</MaxValue><Value>{}</Value></Param>",
                xml_escape(name),
                xml_escape(&session.params[name]),
            ));
        }
        xml.push_str("</Parameters>");
        Self::info_envelope(tag, &xml)
    }

    /// Schema envelope shared by both INFO sources.
    fn info_envelope(tag: &str, xml: &str) -> Response {
        Response {
            tag: tag.to_string(),
            lines: vec!["343-Begin XML snippet".to_string(), format!("347-{xml}")],
            final_text: "344 End XML snippet".to_string(),
            status: 344,
        }
    }

    /// INFO rows straight from a parsed specification document.
    fn spec_info(
        &self,
        tag: &str,
        session: &PpSession,
        spec: &[unitspec::SpecParam],
        wanted: &str,
    ) -> Response {
        let selected: Vec<&unitspec::SpecParam> = if wanted == "*" {
            spec.iter().collect()
        } else {
            match spec.iter().find(|p| p.name == wanted) {
                Some(p) => vec![p],
                None => {
                    return err(tag, status::NOT_FOUND, "404 Parameter not found");
                }
            }
        };
        let mut xml = String::from("<Parameters>");
        for param in selected {
            xml.push_str("<Param>");
            for (key, value) in &param.fields {
                xml.push_str(&format!("<{key}>{}</{key}>", xml_escape(value)));
            }
            // Current staged value rides along for readback coherence.
            if let Some(value) = session.params.get(&param.name) {
                xml.push_str(&format!("<Value>{}</Value>", xml_escape(value)));
            }
            xml.push_str("</Param>");
        }
        xml.push_str("</Parameters>");
        Self::info_envelope(tag, &xml)
    }

    /// Native `PP RESET_TO_DEFAULTS name`.
    ///
    /// With a matching specification configured, parameters reset to
    /// catalogue defaults (native behavior); otherwise the reset keeps
    /// identity only, since defaults are unknown (documented limit).
    fn pp_reset(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP RESET_TO_DEFAULTS requires a session",
            );
        }
        let (_, mut session) = match self.pp_session(tag, words) {
            Ok(v) => v,
            Err(r) => return r,
        };
        if let Some(unit_type) = session.unit_type.clone() {
            if let Some(spec) = self.spec_for(&unit_type) {
                session.params = spec
                    .iter()
                    .filter_map(|p| {
                        p.get("DefaultValue")
                            .map(|d| (p.name.clone(), d.to_string()))
                    })
                    .collect();
                session.dirty = session.params.keys().cloned().collect();
                return self.pp_store(tag, session);
            }
        }
        session
            .params
            .retain(|k, _| matches!(k.as_str(), "UnitType" | "FirmwareVersion" | "CatalogNumber"));
        session.dirty = session.params.keys().cloned().collect();
        self.pp_store(tag, session)
    }

    /// Native `PP QUICKGET database-unit [parameter]`.
    fn pp_quickget(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(3..=4).contains(&words.len()) || !valid_target(words[2]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP QUICKGET requires a database unit",
            );
        }
        let Some((proj_name, net, addr)) = self.unit_of(words[2]) else {
            return err(tag, status::ABSENT, "401 Unit not found");
        };
        if proj_name != self.current.clone().unwrap_or_default() {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let Some(unit) = self
            .projects
            .get(&proj_name)
            .and_then(|p| p.networks.get(&net))
            .and_then(|n| n.units.get(&addr))
        else {
            return err(tag, status::ABSENT, "401 Unit not found");
        };
        let wanted = words.get(3).copied().unwrap_or("*");
        if wanted == "*" {
            let mut names: Vec<&String> = unit.fields.keys().collect();
            names.sort();
            let lines = names
                .into_iter()
                .map(|k| format!("{k}={}", unit.fields[k]))
                .collect();
            return parameter_reply(tag, lines);
        }
        // Same fallback as database reads so both paths agree.
        let value = unit.field(wanted);
        if value.is_empty() && !unit.fields.contains_key(wanted) {
            if wanted == "CatalogNumber" {
                return parameter_reply(tag, vec!["CatalogNumber=null".to_string()]);
            }
            return err(tag, status::NOT_FOUND, "404 Parameter not found");
        }
        parameter_reply(tag, vec![format!("{wanted}={value}")])
    }

    /// Native `PP COPY lock source destination [tags...]`: lock-gated
    /// acceptance; byte-copy semantics are not modeled (documented).
    fn pp_copy(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 5 || !valid_target(words[3]) || !valid_target(words[4]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 PP COPY requires a lock, source and destination",
            );
        }
        if !self.locks.contains_key(words[2]) {
            return err(tag, status::NOT_FOUND, "404 Lock not found");
        }
        ok(tag, vec![], "200 OK")
    }

    /// Native `LABEL CLEAREDLT source`: guarded one-shot dynamic-label
    /// clear. The caller's coverage/identity guards run client-side; the
    /// accepted reply is exactly one `200 OK.` line (note the period),
    /// which the clear workflow requires verbatim.
    fn label_clear(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 || !words[1].eq_ignore_ascii_case("CLEAREDLT") {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 LABEL only supports CLEAREDLT in this model",
            );
        }
        if !valid_target(words[2]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid clear target");
        }
        self.push_event(format!("#e# labels cleared {}", words[2]));
        Response {
            tag: tag.to_string(),
            lines: Vec::new(),
            final_text: "200 OK.".to_string(),
            status: status::OK,
        }
    }

    /// Native scalar `SET source-path Address new-address`: the single
    /// physical-address mutation. The move is physical-only: the database
    /// record stays put, so verification observes `database_unchanged`,
    /// exactly like native. The reply confirms the destination in the
    /// exact native shape `200 OK: <destination>`.
    fn scalar_set(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 4 || !words[2].eq_ignore_ascii_case("Address") {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 SET requires a source path and Address destination",
            );
        }
        if !valid_target(words[1]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid source path");
        }
        let addr: i64 = words[3].parse().unwrap_or(-1);
        if !(0..=255).contains(&addr) {
            return err(tag, status::BAD_REQUEST, "400 Invalid destination address");
        }
        let Some((proj_name, net, src)) = self.unit_of(words[1]) else {
            return err(tag, status::NOT_FOUND, "404 Unit not found");
        };
        if proj_name != self.current.clone().unwrap_or_default() {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let addr = addr as u8;
        let parent = words[1]
            .rsplit_once('/')
            .map(|(p, _)| p)
            .unwrap_or(words[1]);
        let dest = format!("{parent}/{addr}");
        // Existence before occupancy so a missing source is never masked
        // by an occupied destination. The move is physical-only: the
        // database record stays put, so verification observes
        // `database_unchanged`, exactly like native.
        {
            let network = self
                .projects
                .get_mut(&proj_name)
                .and_then(|p| p.networks.get_mut(&net));
            match network {
                None => return err(tag, status::NOT_FOUND, "404 Network not found"),
                Some(network) => {
                    if !network.physical.contains_key(&src) {
                        return err(tag, status::ABSENT, "401 Unit not found");
                    }
                    if network.physical.contains_key(&addr) {
                        return err(tag, status::CONFLICT_EXISTS, "409 Destination occupied");
                    }
                    let mut unit = network
                        .physical
                        .remove(&src)
                        .expect("source presence checked");
                    unit.address = addr;
                    network.physical.insert(addr, unit);
                }
            }
        }
        self.push_event(format!("#e# unit moved {src} {addr}"));
        Response {
            tag: tag.to_string(),
            lines: Vec::new(),
            final_text: format!("200 OK: {dest}"),
            status: status::OK,
        }
    }

    /// Mock-only `MOCK BUS-DEL network-path address`: drop one
    /// physical-bus record while leaving the database untouched.
    ///
    /// There is deliberately no native counterpart — physical presence
    /// is physical reality, not a C-Gate command. Fixture setup (and the
    /// serial-commissioning topology, which needs a database unit with
    /// no physical counterpart) is its only use. The database record,
    /// if any, is left alone.
    fn mock_bus_del(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 4 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 MOCK BUS-DEL requires a network path and address",
            );
        }
        let addr: i64 = words[3].parse().unwrap_or(-1);
        if !(0..=255).contains(&addr) {
            return err(tag, status::BAD_REQUEST, "400 Invalid bus address");
        }
        let (project, net) = match self.resolve_network_mut(words) {
            Ok(v) => v,
            Err(mut e) => {
                e.tag = tag.to_string();
                return e;
            }
        };
        let current = self.current.clone().unwrap_or_default();
        if !project.is_empty() && project != current {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let Some(network) = self
            .projects
            .get_mut(&current)
            .and_then(|p| p.networks.get_mut(&net))
        else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        if network.physical.remove(&(addr as u8)).is_none() {
            return err(tag, status::NOT_FOUND, "404 No physical unit at address");
        }
        self.push_event(format!("#e# mock bus-del {addr}"));
        ok(tag, vec![], "200 OK")
    }

    /// Remap `db_fields`/`objects` keys from one unit path to another,
    /// using an exact-or-`/` boundary (shared by renames and moves).
    fn remap_prefix(&mut self, from: &str, to: &str) {
        let slash = format!("{from}/");
        self.db_fields = std::mem::take(&mut self.db_fields)
            .into_iter()
            .map(|(k, v)| {
                if k == from {
                    (to.to_string(), v)
                } else if let Some(rest) = k.strip_prefix(&slash) {
                    (format!("{to}/{rest}"), v)
                } else {
                    (k, v)
                }
            })
            .collect();
        self.objects = std::mem::take(&mut self.objects)
            .into_iter()
            .map(|k| {
                if k == from {
                    to.to_string()
                } else if let Some(rest) = k.strip_prefix(&slash) {
                    format!("{to}/{rest}")
                } else {
                    k
                }
            })
            .collect();
        // Level parents travel with the rename; identities are unchanged.
        for level in self.db_levels.values_mut() {
            if level.parent == from {
                level.parent = to.to_string();
            } else if let Some(rest) = level.parent.strip_prefix(&slash) {
                level.parent = format!("{to}/{rest}");
            }
        }
    }

    /// Native `ENABLE REMOVE address`.
    fn enable_remove(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 ENABLE REMOVE requires an address",
            );
        }
        if !valid_target(words[2]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid enable address");
        }
        ok(tag, vec![], "200 OK")
    }

    /// Native `EVENT ON|OFF|e[+0-9]s[01]c[01]`: accept a subscription.
    ///
    /// Setting is stateless here (200 on any valid mode); the per-
    /// connection mode lives with the transport, which filters delivery
    /// and answers a bare `EVENT` query (`306 <mode>`) from session
    /// state — this shared model holds no per-connection modes.
    fn event_sub(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 || !valid_event_mode(words[1]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 EVENT requires ON, OFF or e[+0-9]s[01]c[01]",
            );
        }
        ok(tag, vec![], "200 OK")
    }

    /// Native `GETSTATE address`: snapshot of an already loaded network.
    ///
    /// Lines are plain `state=`/`level=` observations (no consumer parses
    /// them structurally today); the reply status carries completion.
    fn getstate(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 || !valid_target(words[1]) {
            return err(tag, status::BAD_REQUEST, "400 GETSTATE requires an address");
        }
        let Some((proj_name, net)) = self.network_of(words[1]) else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        if proj_name != self.current.clone().unwrap_or_default() {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let Some(network) = self
            .projects
            .get(&proj_name)
            .and_then(|p| p.networks.get(&net))
        else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        let state = match network.state {
            NetworkState::Closed => "closed",
            NetworkState::Open => "open",
            NetworkState::Syncing => "syncing",
            NetworkState::Ok => "ok",
        };
        let mut lines = vec![format!("state={state}")];
        let mut levels: Vec<(&(u8, u8), &u8)> = network.levels.iter().collect();
        levels.sort();
        lines.extend(
            levels
                .into_iter()
                .map(|((app, group), level)| format!("level={app}/{group}={level}")),
        );
        ok(tag, lines, "200 OK")
    }

    /// Handle a here-document command: the `COMMAND << DELIMITER` line plus
    /// the already-collected document body (delimiter line excluded).
    /// Supports `DBSETXML path` (stores the document) and `CGL IMPORT
    /// project` (counts non-blank lines as an explicit mock metric).
    pub fn handle_document(&mut self, line: &str, document: &str) -> Response {
        let cmd = match parse_command(line) {
            Ok(c) => c,
            Err(e) => {
                return Response {
                    tag: String::new(),
                    lines: Vec::new(),
                    final_text: format!("400 {e}"),
                    status: status::BAD_REQUEST,
                }
            }
        };
        if self.access == AccessLevel::Config {
            return err(
                &cmd.tag,
                status::CONNECTION_REFUSED,
                "421 Access refused for interface level",
            );
        }
        let words: Vec<&str> = cmd.body.split_whitespace().collect();
        let upper: Vec<String> = words.iter().map(|w| w.to_ascii_uppercase()).collect();
        if upper.len() >= 2 && upper[0] == "DBSETXML" {
            if words.len() != 2 || !valid_target(words[1]) {
                return err(
                    tag_of(&cmd),
                    status::BAD_REQUEST,
                    "400 DBSETXML requires a path",
                );
            }
            self.db_fields
                .insert(words[1].to_string(), document.to_string());
            self.mirror_unit_field(words[1], document.trim_end_matches('\n'));
            return ok(tag_of(&cmd), vec![], "200 OK");
        }
        if upper.len() >= 3 && upper[0] == "CGL" && upper[1] == "IMPORT" {
            if words.len() != 3 || !valid_name(words[2]) {
                return err(
                    tag_of(&cmd),
                    status::BAD_REQUEST,
                    "400 CGL IMPORT requires a project",
                );
            }
            if !self.projects.contains_key(words[2]) {
                return err(tag_of(&cmd), status::NOT_FOUND, "404 Project not found");
            }
            let count = document.lines().filter(|l| !l.trim().is_empty()).count();
            self.push_event(format!("#e# cgl import {}", words[2]));
            return ok(tag_of(&cmd), vec![format!("imported={count}")], "200 OK");
        }
        err(
            tag_of(&cmd),
            status::BAD_REQUEST,
            "400 Command does not accept a document",
        )
    }

    /// Native `DBADDSAFE parent element address name`.
    fn dbadd(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 5 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 DBADDSAFE requires a parent, element, address and name",
            );
        }
        if !valid_target(words[1]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid parent path");
        }
        let element = words[2].to_ascii_uppercase();
        if !matches!(
            element.as_str(),
            "NETWORK" | "APPLICATION" | "GROUP" | "UNIT" | "LEVEL" | "NETVAR"
        ) {
            return err(tag, status::BAD_REQUEST, "400 Unknown database element");
        }
        let addr: i64 = words[3].parse().unwrap_or(-1);
        if !(0..=255).contains(&addr) {
            return err(tag, status::BAD_REQUEST, "400 Invalid database address");
        }
        if words[4].is_empty() || words[4].contains('#') {
            return err(tag, status::BAD_REQUEST, "400 Invalid tag name");
        }
        let Some((proj_name, net)) = self.network_of(words[1]) else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        if proj_name != self.current.clone().unwrap_or_default() {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let addr = addr as u8;
        if element == "UNIT" {
            let proj = self.projects.get_mut(&proj_name).expect("network resolved");
            let network = proj.networks.get_mut(&net).expect("network resolved");
            if network.units.contains_key(&addr) {
                return err(tag, status::CONFLICT_EXISTS, "409 Unit already exists");
            }
            let unit = Unit::blank(addr, words[4]);
            let oid = unit.oid.clone();
            network.units.insert(addr, unit.clone());
            // A new unit is both databased and physically present.
            network.physical.insert(addr, unit);
            self.known_oids.insert(oid);
            self.objects.insert(format!("{}-unit-{addr}", words[1]));
            self.push_event(format!("#e# db unit {addr} added"));
            return ok(tag, vec![], "200 OK");
        }
        if element == "LEVEL" || element == "NETVAR" {
            // Native answers Level creation with a single 301 OID line which
            // the caller resolves via `!oid/OID` (expecting a single 342
            // reply). Any continuation line would break the caller's
            // exactly-one-match check, so the reply carries no extra lines.
            // The record keeps the evidenced fields only: native sets
            // Level/Address here and leaves Level/Value NULL for the caller
            // to initialize (NetVar values are never initialized).
            let oid = self.issue_oid();
            self.objects.insert(format!("!{oid}"));
            self.db_levels.insert(
                oid.clone(),
                DbLevel {
                    oid: oid.clone(),
                    parent: words[1].to_string(),
                    address: addr,
                    tag: words[4].to_string(),
                    value: None,
                    netvar: element == "NETVAR",
                },
            );
            self.push_event("#e# db level added".to_string());
            return Response {
                tag: tag.to_string(),
                lines: Vec::new(),
                final_text: format!("301 OID={oid}"),
                status: 301,
            };
        }
        self.objects
            .insert(format!("{}-{element}-{addr}", words[1]));
        ok(tag, vec![], "200 OK")
    }

    /// Native `DBCOPYSAFE source parent address name`.
    ///
    /// Known unit records duplicate with their fields; known levels
    /// duplicate as fresh records (new OID, caller-supplied parent,
    /// address and tag, value NULL) with the native 301 OID flow so the
    /// caller's level initializer runs; other objects are accepted
    /// opaquely.
    fn dbcopy(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 5 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 DBCOPYSAFE requires a source, parent, address and name",
            );
        }
        if !valid_target(words[1]) || !valid_target(words[2]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid copy path");
        }
        let addr: i64 = words[3].parse().unwrap_or(-1);
        if !(0..=255).contains(&addr) {
            return err(tag, status::BAD_REQUEST, "400 Invalid database address");
        }
        if words[4].is_empty() || words[4].contains('#') {
            return err(tag, status::BAD_REQUEST, "400 Invalid tag name");
        }
        let Some((proj_name, net)) = self.network_of(words[2]) else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        if proj_name != self.current.clone().unwrap_or_default() {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        // Duplicate a known unit record when the source names one (a
        // known level source is handled below with the 301 OID flow).
        if let Some((_, _, src_addr)) = Self::split_unit(words[1]) {
            let snapshot = self
                .projects
                .get(&proj_name)
                .and_then(|p| p.networks.get(&net))
                .and_then(|n| n.units.get(&src_addr))
                .cloned();
            if let Some(mut unit) = snapshot {
                let addr = addr as u8;
                let proj = self.projects.get_mut(&proj_name).expect("network resolved");
                let network = proj.networks.get_mut(&net).expect("network resolved");
                if network.units.contains_key(&addr) {
                    return err(tag, status::CONFLICT_EXISTS, "409 Unit already exists");
                }
                unit.address = addr;
                unit.fields
                    .insert("UnitName".to_string(), words[4].to_string());
                // A copy is a new database object with its own identity
                // (no internal OID references exist to remap).
                unit.oid = fresh_oid();
                network.units.insert(addr, unit);
                let oid = network.units[&addr].oid.clone();
                self.known_oids.insert(oid);
                self.objects.insert(format!("{}-unit-{addr}", words[2]));
                return ok(tag, vec![], "200 OK");
            }
        }
        // A level source (`!oid`, whose kind the caller probes via the
        // level document) copies as a fresh level record with the native
        // 301 OID flow; anything else stays opaque.
        if let Some(src_oid) = words[1].strip_prefix('!') {
            if !src_oid.contains('/') {
                if let Some(source) = self.db_levels.get(src_oid).cloned() {
                    let oid = self.issue_oid();
                    self.objects.insert(format!("!{oid}"));
                    self.db_levels.insert(
                        oid.clone(),
                        DbLevel {
                            oid: oid.clone(),
                            parent: words[2].to_string(),
                            address: addr as u8,
                            tag: words[4].to_string(),
                            value: None,
                            netvar: source.netvar,
                        },
                    );
                    self.push_event("#e# db level added".to_string());
                    return Response {
                        tag: tag.to_string(),
                        lines: Vec::new(),
                        final_text: format!("301 OID={oid}"),
                        status: 301,
                    };
                }
            }
        }
        self.objects.insert(format!("{}-copy-{addr}", words[2]));
        ok(tag, vec![], "200 OK")
    }

    /// Native `DBRENAMENETSAFE net destination` (database layer only).
    fn dbrename_net(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 DBRENAMENETSAFE requires a network and destination",
            );
        }
        let src: i64 = words[1].parse().unwrap_or(-1);
        let dst: i64 = words[2].parse().unwrap_or(-1);
        if !(0..=255).contains(&src) || !(0..=255).contains(&dst) {
            return err(tag, status::BAD_REQUEST, "400 Invalid network address");
        }
        if src == dst {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 New network address must differ",
            );
        }
        let current = self.current.clone().unwrap_or_default();
        let Some(proj) = self.projects.get_mut(&current) else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        let Some(network) = proj.networks.remove(&(src as u8)) else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        if proj.networks.contains_key(&(dst as u8)) {
            proj.networks.insert(src as u8, network);
            return err(tag, status::CONFLICT_EXISTS, "409 Network already exists");
        }
        let mut network = network;
        network.address = dst as u8;
        proj.networks.insert(dst as u8, network);
        let project = self.current.clone().unwrap_or_default();
        self.remap_network_paths(&project, src as u8, dst as u8);
        self.push_event(format!("#e# net renamed {src} {dst}"));
        ok(tag, vec![], "200 OK")
    }

    /// Remap `db_fields`/`objects` keys across a network rename, using an
    /// exact-segment boundary so `//P/25/...` never matches `//P/254/...`.
    fn remap_network_paths(&mut self, project: &str, src: u8, dst: u8) {
        let from = format!("//{project}/{src}/");
        let to = format!("//{project}/{dst}/");
        let exact = format!("//{project}/{src}");
        self.db_fields = std::mem::take(&mut self.db_fields)
            .into_iter()
            .map(|(k, v)| {
                if k == exact {
                    (format!("//{project}/{dst}"), v)
                } else if let Some(rest) = k.strip_prefix(&from) {
                    (format!("{to}{rest}"), v)
                } else {
                    (k, v)
                }
            })
            .collect();
        self.objects = std::mem::take(&mut self.objects)
            .into_iter()
            .map(|k| {
                if k == exact {
                    format!("//{project}/{dst}")
                } else if let Some(rest) = k.strip_prefix(&from) {
                    format!("{to}{rest}")
                } else {
                    k
                }
            })
            .collect();
        // Level parents live under the renamed network too.
        for level in self.db_levels.values_mut() {
            if level.parent == exact {
                level.parent = format!("//{project}/{dst}");
            } else if let Some(rest) = level.parent.strip_prefix(&from) {
                level.parent = format!("{to}{rest}");
            }
        }
    }

    /// Native `DBDELETE path`.
    ///
    /// Database record only: bus presence remains, so scans keep
    /// reporting the unit while database reads go 401.
    fn dbdelete(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 || !valid_target(words[1]) {
            return err(tag, status::BAD_REQUEST, "400 DBDELETE requires a path");
        }
        if let Some((proj_name, net, addr)) = self.unit_of(words[1]) {
            if proj_name != self.current.clone().unwrap_or_default() {
                return err(tag, status::NOT_FOUND, "404 Project not selected");
            }
            let removed = self
                .projects
                .get_mut(&proj_name)
                .and_then(|p| p.networks.get_mut(&net))
                .and_then(|n| n.units.remove(&addr));
            // Boundary-checked prefix: `//P/252/p/20` must not wipe
            // `//P/252/p/200` or unrelated siblings.
            let prefix = format!("{}/", words[1]);
            self.db_fields
                .retain(|k, _| *k != words[1] && !k.starts_with(&prefix));
            self.objects.remove(words[1]);
            if let Some(unit) = removed {
                // Retire the identity: a deleted unit's OID must no
                // longer resolve, without lowering the OID high-water mark.
                self.known_oids.remove(&unit.oid);
                self.push_event(format!("#e# db unit {addr} deleted"));
                return ok(tag, vec![], "200 OK");
            }
            return err(tag, status::NOT_FOUND, "404 Object not found");
        }
        if self.objects.remove(words[1]) || self.db_fields.remove(words[1]).is_some() {
            // Retire level identities too so `!oid/OID` stops resolving
            // and the group document drops the row.
            if let Some(rest) = words[1].strip_prefix('!') {
                let oid = rest.split('/').next().unwrap_or("").to_string();
                self.known_oids.remove(&oid);
                self.db_levels.remove(&oid);
            }
            return ok(tag, vec![], "200 OK");
        }
        err(tag, status::NOT_FOUND, "404 Object not found")
    }

    /// Native `DBVALIDATE path`.
    ///
    /// The reply itself carries status 233 with every line (including the
    /// final) in the exact native shape `233[- ]<path>: Valid`, which
    /// database guards require on all rows.
    fn dbvalidate(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 2 || !valid_target(words[1]) {
            return err(tag, status::BAD_REQUEST, "400 DBVALIDATE requires a path");
        }
        Response {
            tag: tag.to_string(),
            lines: vec![format!("233-{}: Valid", words[1])],
            final_text: format!("233 {}: Valid", words[1]),
            status: 233,
        }
    }

    /// Native `DBSETSAFE path value` (field store).
    ///
    /// Non-unit paths store opaquely. A unit path addressing no record on
    /// either layer is 401 (deleted/absent object); otherwise the write
    /// stores and mirrors into whichever layers hold the unit, skipping
    /// the rest silently (half-mirror layers stay consistent because each
    /// read resolves against its own layer).
    fn dbset(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() < 3 || !valid_target(words[1]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 DBSETSAFE requires a path and value",
            );
        }
        let value = words[2..].join(" ");
        if value.is_empty() || value.contains('#') {
            return err(tag, status::BAD_REQUEST, "400 Invalid field value");
        }
        // Level Value initialization (`DBSETSAFE !oid/Value byte`): the
        // native column is a byte, so non-byte values are rejected rather
        // than stored. Unknown OIDs keep the opaque store below.
        if let Some(rest) = words[1].strip_prefix('!') {
            let mut segments = rest.splitn(2, '/');
            let oid = segments.next().unwrap_or("");
            if segments.next() == Some("Value") {
                if let Some(level) = self.db_levels.get_mut(oid) {
                    let byte: i64 = value.parse().unwrap_or(-1);
                    if !(0..=255).contains(&byte) {
                        return err(tag, status::BAD_REQUEST, "400 Invalid level value");
                    }
                    level.value = Some(byte as u8);
                    self.db_fields.insert(words[1].to_string(), value);
                    return ok(tag, vec![], "200 OK");
                }
            }
        }
        if self.unit_of(words[1]).is_some() && !self.unit_anywhere(words[1]) {
            return err(tag, status::ABSENT, "401 Unit not found");
        }
        self.mirror_unit_field(words[1], &value);
        self.db_fields.insert(words[1].to_string(), value);
        ok(tag, vec![], "200 OK")
    }

    /// True when a unit path resolves to a record on either layer.
    fn unit_anywhere(&self, path: &str) -> bool {
        let Some((proj_name, net, addr)) = self.unit_of(path) else {
            return false;
        };
        self.projects
            .get(&proj_name)
            .and_then(|p| p.networks.get(&net))
            .is_some_and(|n| n.units.contains_key(&addr) || n.physical.contains_key(&addr))
    }

    /// Mirror a field write into the addressed unit record so a later
    /// `GET` observes `DBSETSAFE`/`DBSETXML` writes (write-then-read flows
    /// in `serial_population` and `classic_replacement` depend on this).
    ///
    /// Only single-line values addressing a field segment mirror: a
    /// whole-unit path has no field to update, and a multi-line document
    /// cannot travel inside the single-line 300 envelope (it stays in the
    /// opaque document store instead of desynchronizing the stream).
    ///
    /// Both layers mirror identity writes: database and physical records
    /// describe the same device until a physical move separates their
    /// addresses (`SAVE` stays database-only — physical transfer is a
    /// separate unverified step).
    fn mirror_unit_field(&mut self, path: &str, value: &str) {
        if value.contains('\n') {
            return;
        }
        let parts: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
        if parts.len() < 5 {
            return;
        }
        if let Some((proj_name, net, addr)) = self.unit_of(path) {
            if let Some(field) = path.rsplit('/').next().map(str::to_string) {
                for store in [false, true] {
                    let record = self
                        .projects
                        .get_mut(&proj_name)
                        .and_then(|p| p.networks.get_mut(&net))
                        .and_then(|n| {
                            if store {
                                n.physical.get_mut(&addr)
                            } else {
                                n.units.get_mut(&addr)
                            }
                        });
                    if let Some(unit) = record {
                        unit.fields.insert(field.clone(), value.to_string());
                        // Keep the struct twins in step, exactly like SAVE
                        // (serials aliases included: Type/Version are the
                        // database names for unit_type/firmware).
                        match field.as_str() {
                            "UnitType" | "Type" => unit.unit_type = value.to_string(),
                            "FirmwareVersion" | "Version" => unit.firmware = value.to_string(),
                            "SerialNumber" => unit.serial = value.to_string(),
                            _ => {}
                        }
                    }
                }
            }
        }
    }

    /// Native `CGL IMPORT project` without a document: accepted only with an
    /// explicit empty import rather than invented content.
    fn cgl_import(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 || !valid_name(words[2]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 CGL IMPORT requires a project",
            );
        }
        if !self.projects.contains_key(words[2]) {
            return err(tag, status::NOT_FOUND, "404 Project not found");
        }
        ok(tag, vec!["imported=0".to_string()], "200 OK")
    }

    /// Native `CGL EXPORT project networks applications`.
    ///
    /// The reply carries the native 344 envelope (`343-` opener, one
    /// `347-` document line, `344` final) which export parsers require.
    /// The document line states the mock's honest inventory (project name
    /// plus network count) rather than a fabricated CGL document: flows
    /// that parse real CGL fail loudly on it instead of consuming fiction.
    fn cgl_export(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 5 || !valid_name(words[2]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 CGL EXPORT requires a project, networks and applications",
            );
        }
        let Some(proj) = self.projects.get(words[2]) else {
            return err(tag, status::NOT_FOUND, "404 Project not found");
        };
        let document = format!(
            "<CGL project=\"{}\" networks=\"{}\"/>",
            words[2],
            proj.networks.len()
        );
        Response {
            tag: tag.to_string(),
            lines: vec![
                "343-Begin CGL snippet".to_string(),
                format!("347-{document}"),
            ],
            final_text: "344 End CGL snippet".to_string(),
            status: 344,
        }
    }

    /// Native `GET address attribute` reads.
    ///
    /// Every property reply is a single `300 <address>: <name>=<value>`
    /// line: the serial, network and application parsers all require 300
    /// status, exactly one line, and the `addr: name=value` shape.
    fn get(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 || !valid_target(words[1]) || words[2].is_empty() {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 GET requires an address and attribute",
            );
        }
        let address = words[1];
        let attribute = words[2];
        // `!oid/...` identity reads resolve issued OIDs only.
        if let Some(rest) = address.strip_prefix('!') {
            let oid = rest.split('/').next().unwrap_or("");
            if !self.known_oids.contains(oid) {
                return err(tag, status::ABSENT, "401 Object not found");
            }
            if attribute.eq_ignore_ascii_case("OID") {
                return Response {
                    tag: tag.to_string(),
                    lines: Vec::new(),
                    final_text: format!("342 !{oid}/OID={oid}"),
                    status: 342,
                };
            }
            let value = self.db_fields.get(address).cloned().unwrap_or_default();
            return Self::property(tag, address, attribute, &value);
        }
        let Some((proj_name, net)) = self.network_of(address) else {
            return err(tag, status::ABSENT, "401 Network not found");
        };
        if proj_name != self.current.clone().unwrap_or_default() {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let network = self
            .projects
            .get(&proj_name)
            .and_then(|p| p.networks.get(&net))
            .expect("network resolved");
        // Bare two-segment paths address the network itself; longer
        // paths (units, lighting groups) must not match network state.
        let is_network_path = {
            let parts: Vec<&str> = address.split('/').filter(|s| !s.is_empty()).collect();
            parts.len() == 2
        };
        if attribute.eq_ignore_ascii_case("state") && is_network_path {
            let text = match network.state {
                NetworkState::Closed => "closed",
                NetworkState::Open => "open",
                NetworkState::Syncing => "syncing",
                NetworkState::Ok => "ok",
            };
            return Self::property(tag, address, "state", text);
        }
        if attribute.eq_ignore_ascii_case("TargetInterfaceState") && is_network_path {
            // `wait_ready` requires exactly one `300[- ]...` line carrying
            // `TargetInterfaceState=running|closed`.
            let target = match network.state {
                NetworkState::Closed => "closed",
                _ => "running",
            };
            return Self::property(tag, address, "TargetInterfaceState", target);
        }
        // Network runtime snapshot (`GET //P/N *`): the pinned inventory
        // physical guards require. Only bare two-segment network paths
        // land here (computed above); lighting and unit addresses fall
        // through below.
        // Interface values come from the stored `DBCREATENET` arguments
        // and live state; the remaining fields are documented
        // mock-inventory defaults (this model never auto-syncs, unravels,
        // updates, retries or fast-polls).
        if is_network_path {
            // The serials inventory reads `Units` (comma list) and the
            // refresh guards read single fields; `*` returns the table.
            if attribute.eq_ignore_ascii_case("Units") {
                let network = self
                    .projects
                    .get(&proj_name)
                    .and_then(|p| p.networks.get(&net))
                    .expect("network resolved");
                // Physical presence: the serials inventory works from what
                // the bus reports, not the database.
                let mut addrs: Vec<u8> = network.physical.keys().copied().collect();
                addrs.sort();
                let list = addrs
                    .into_iter()
                    .map(|a| a.to_string())
                    .collect::<Vec<_>>()
                    .join(", ");
                return Self::property(tag, address, attribute, &list);
            }
            if attribute != "*" {
                if let Some(value) = self.runtime_field(&proj_name, net, attribute) {
                    return Self::property(tag, address, attribute, &value);
                }
                return err(tag, status::ABSENT, "401 Object not found");
            }
            let Some(fields) = self.runtime_table(&proj_name, net) else {
                return err(tag, status::ABSENT, "401 Object not found");
            };
            let mut rows: Vec<String> = fields
                .iter()
                .map(|(k, v)| format!("300-{address}: {k}={v}"))
                .collect();
            let last = rows.pop().expect("runtime fields nonempty");
            return Response {
                tag: tag.to_string(),
                lines: rows,
                final_text: last.replacen("300-", "300 ", 1),
                status: 300,
            };
        }
        if attribute.eq_ignore_ascii_case("level") {
            // Cached group level for scene record flows: exactly one
            // `300 <addr>: level=<byte>` line. Lighting addresses carry
            // their network; untouched groups read 0 (mock default).
            let Some((proj_name, net, app, group)) = Self::split_lighting(address) else {
                return err(tag, status::BAD_REQUEST, "400 Invalid lighting address");
            };
            if proj_name != self.current.clone().unwrap_or_default() {
                return err(tag, status::NOT_FOUND, "404 Project not selected");
            }
            let level = self
                .projects
                .get(&proj_name)
                .and_then(|p| p.networks.get(&net))
                .map(|n| n.levels.get(&(app, group)).copied().unwrap_or(0));
            let Some(level) = level else {
                return err(tag, status::NOT_FOUND, "404 Network not found");
            };
            return Self::property(tag, address, "level", &level.to_string());
        }
        // Unit field reads (`//P/N/p/addr[/Field]`) observe the physical
        // layer, like serials scans and PINGU; database reads use DBGET.
        if let Some((_, _, addr)) = Self::split_unit(address) {
            if let Some(unit) = network.physical.get(&addr) {
                if attribute == "*" {
                    // Every row must match the 300 envelope, including the
                    // final line, so all but the last row travel as
                    // 300-prefixed continuations via the passthrough
                    // formatter.
                    let mut names: Vec<String> = unit
                        .fields
                        .keys()
                        .cloned()
                        .chain(
                            ["UnitType", "FirmwareVersion", "SerialNumber", "UnitAddress"]
                                .iter()
                                .map(|s| s.to_string()),
                        )
                        .collect::<std::collections::HashSet<_>>()
                        .into_iter()
                        .collect();
                    names.sort();
                    if names.is_empty() {
                        return err(tag, status::NOT_FOUND, "404 Object not found");
                    }
                    let mut rows: Vec<String> = names
                        .iter()
                        .map(|k| format!("300-{address}: {k}={}", unit.field(k)))
                        .collect();
                    let last = rows.pop().expect("names nonempty");
                    let final_text = last.replacen("300-", "300 ", 1);
                    return Response {
                        tag: tag.to_string(),
                        lines: rows,
                        final_text,
                        status: 300,
                    };
                }
                if unit.fields.contains_key(attribute)
                    || [
                        "UnitType",
                        "Type",
                        "FirmwareVersion",
                        "Version",
                        "SerialNumber",
                        "UnitName",
                        "UnitAddress",
                        "Address",
                        "State",
                        "CatalogNumber",
                    ]
                    .contains(&attribute)
                {
                    return Self::property(tag, address, attribute, &unit.field(attribute));
                }
                return err(tag, status::NOT_FOUND, "404 Parameter not found");
            }
            return err(tag, status::ABSENT, "401 Unit not found");
        }
        // Anything else resolves no readable object in this model.
        err(tag, status::ABSENT, "401 Object not found")
    }

    /// Full network runtime table backing `GET //P/N *` and single
    /// network-attribute reads. Interface values come from the stored
    /// `DBCREATENET` arguments and live state; the remaining fields are
    /// documented mock-inventory defaults (this model never auto-syncs,
    /// unravels, updates, retries or fast-polls).
    fn runtime_table(&self, proj_name: &str, net: u8) -> Option<Vec<(String, String)>> {
        let network = self.projects.get(proj_name)?.networks.get(&net)?;
        let running = network.state != NetworkState::Closed;
        let state = match network.state {
            NetworkState::Closed => "closed",
            NetworkState::Open => "open",
            NetworkState::Syncing => "syncing",
            NetworkState::Ok => "ok",
        };
        let wired = ["cni", "serial"].contains(&network.iface_type.to_ascii_lowercase().as_str());
        Some(vec![
            ("Name".to_string(), net.to_string()),
            ("Type".to_string(), network.iface_type.clone()),
            ("InterfaceAddress".to_string(), network.iface_addr.clone()),
            (
                "NetworkType".to_string(),
                if wired {
                    "Wired".to_string()
                } else {
                    "Bridge".to_string()
                },
            ),
            (
                "InterfaceState".to_string(),
                if running {
                    "running".to_string()
                } else {
                    "closed".to_string()
                },
            ),
            (
                "TargetInterfaceState".to_string(),
                if running {
                    "running".to_string()
                } else {
                    "closed".to_string()
                },
            ),
            ("SyncState".to_string(), "idle".to_string()),
            ("State".to_string(), state.to_string()),
            ("Options".to_string(), String::new()),
            ("AutoSync".to_string(), "no".to_string()),
            ("AutoUnravel".to_string(), "no".to_string()),
            ("AutoUpdate".to_string(), "no".to_string()),
            ("DefaultApplication".to_string(), "56".to_string()),
            ("EventLevel".to_string(), "7".to_string()),
            ("FastResponse".to_string(), "no".to_string()),
            ("QuickDetect".to_string(), "no".to_string()),
            ("ResponseDelay".to_string(), "0".to_string()),
            ("Retries".to_string(), "0".to_string()),
            ("ShortSync".to_string(), "no".to_string()),
            ("SyncTime".to_string(), "0".to_string()),
            ("TxEnable".to_string(), "yes".to_string()),
        ])
    }

    /// One runtime field by case-insensitive name.
    fn runtime_field(&self, proj_name: &str, net: u8, name: &str) -> Option<String> {
        self.runtime_table(proj_name, net)?
            .into_iter()
            .find(|(k, _)| k.eq_ignore_ascii_case(name))
            .map(|(_, v)| v)
    }

    /// One cached-property reply line in native 300 shape.
    fn property(tag: &str, address: &str, name: &str, value: &str) -> Response {
        Response {
            tag: tag.to_string(),
            lines: Vec::new(),
            final_text: format!("300 {address}: {name}={value}"),
            status: 300,
        }
    }

    /// Native `NET LIST_ALL`.
    fn net_list_all(&self, tag: &str) -> Response {
        let mut lines = Vec::new();
        let mut projects: Vec<&String> = self.projects.keys().collect();
        projects.sort();
        for project in projects {
            let mut nets: Vec<&u8> = self.projects[project].networks.keys().collect();
            nets.sort();
            for net in nets {
                lines.push(format!("//{project}/{net}"));
            }
        }
        ok(tag, lines, "200 OK")
    }

    /// Native `NET LIST project`.
    fn net_list(&self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 || !valid_name(words[2]) {
            return err(tag, status::BAD_REQUEST, "400 NET LIST requires a project");
        }
        let Some(proj) = self.projects.get(words[2]) else {
            return err(tag, status::NOT_FOUND, "404 Project not found");
        };
        let mut nets: Vec<&u8> = proj.networks.keys().collect();
        nets.sort();
        let lines = nets
            .into_iter()
            .map(|n| format!("//{}/{n}", words[2]))
            .collect();
        ok(tag, lines, "200 OK")
    }

    /// Native `NET SYNCNEW address [unit]`.
    fn net_syncnew(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(3..=4).contains(&words.len()) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 NET SYNCNEW requires an address",
            );
        }
        let (_, net) = match self.require_network(tag, words[2]) {
            Ok(v) => v,
            Err(r) => return r,
        };
        if words.len() == 4 && !valid_byte(words[3]) {
            return err(tag, status::BAD_REQUEST, "400 Invalid unit address");
        }
        self.push_event(format!("#e# net {net} syncnew"));
        ok(tag, vec![], "200 OK")
    }

    /// Native `NET PINGU address`: report responding units.
    ///
    /// Exactly two lines: a single `302-Units=a, b, c` row (sorted unique
    /// decimals of physically present units) and the literal final
    /// `200 OK.`, which coverage guards require verbatim.
    fn net_pingu(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 NET PINGU requires an address",
            );
        }
        let (_, net) = match self.require_network(tag, words[2]) {
            Ok(v) => v,
            Err(r) => return r,
        };
        let current = self.current.clone().unwrap_or_default();
        let mut addrs: Vec<u8> = self.projects[&current].networks[&net]
            .physical
            .keys()
            .copied()
            .collect();
        addrs.sort();
        let list = addrs
            .into_iter()
            .map(|a| a.to_string())
            .collect::<Vec<_>>()
            .join(", ");
        ok(tag, vec![format!("302-Units={list}")], "200 OK.")
    }

    /// Native `NET CHECKUNIT address units`.
    ///
    /// One `120-<status> at address: <n>` row per requested unit plus the
    /// literal final `200 OK.`, which the serials multiplicity check
    /// requires verbatim. Presence comes from the physical inventory:
    /// present units report `Single unit detected`, the rest `No units
    /// detected`.
    fn net_checkunit(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 4 || words[3].is_empty() {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 NET CHECKUNIT requires an address and units",
            );
        }
        let (_, net) = match self.require_network(tag, words[2]) {
            Ok(v) => v,
            Err(r) => return r,
        };
        let mut selected = Vec::new();
        if words[3] == "*" {
            // Whole-network scan: every physically present unit, ordered.
            let current = self.current.clone().unwrap_or_default();
            selected.extend(
                self.projects[&current].networks[&net]
                    .physical
                    .keys()
                    .copied(),
            );
            selected.sort();
        } else {
            for part in words[3].split(',') {
                if !valid_byte(part) {
                    return err(tag, status::BAD_REQUEST, "400 Invalid unit selection");
                }
                selected.push(part.parse::<u8>().expect("byte validated"));
            }
        }
        let current = self.current.clone().unwrap_or_default();
        let known = &self.projects[&current].networks[&net].physical;
        let lines = selected
            .into_iter()
            .map(|a| {
                if known.contains_key(&a) {
                    format!("120-Single unit detected at address: {a}")
                } else {
                    format!("120-No units detected at address: {a}")
                }
            })
            .collect();
        self.push_event(format!("#e# net {net} checkunit {}", words[3]));
        ok(tag, lines, "200 OK.")
    }

    /// Native `NET UNRAVEL[UNIT] address [units] [matchdb]`.
    fn net_unravel(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(3..=5).contains(&words.len()) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 NET UNRAVEL requires an address",
            );
        }
        let (_, net) = match self.require_network(tag, words[2]) {
            Ok(v) => v,
            Err(r) => return r,
        };
        // Optional tail is `[units] [matchdb]`, mirroring the native client.
        let mut tail = &words[3..];
        if let Some((&units, rest)) = tail.split_first() {
            if !units.eq_ignore_ascii_case("matchdb") {
                for part in units.split(',') {
                    if !valid_byte(part) {
                        return err(tag, status::BAD_REQUEST, "400 Invalid unit selection");
                    }
                }
                tail = rest;
            }
        }
        if let Some((&flag, rest)) = tail.split_first() {
            if !flag.eq_ignore_ascii_case("matchdb") || !rest.is_empty() {
                return err(tag, status::BAD_REQUEST, "400 Invalid unravel argument");
            }
        }
        self.push_event(format!("#e# net {net} unravel"));
        ok(tag, vec![], "200 OK")
    }

    /// Native `NET CLOCKS address [R|1..10]`.
    fn net_clocks(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(3..=4).contains(&words.len()) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 NET CLOCKS requires an address",
            );
        }
        let (_, net) = match self.require_network(tag, words[2]) {
            Ok(v) => v,
            Err(r) => return r,
        };
        let target = if words.len() == 4 {
            if words[3].eq_ignore_ascii_case("R") {
                "recover".to_string()
            } else {
                let n: i64 = words[3].parse().unwrap_or(-1);
                if !(1..=10).contains(&n) {
                    return err(
                        tag,
                        status::BAD_REQUEST,
                        "400 Clock target must be in 1..10",
                    );
                }
                n.to_string()
            }
        } else {
            "query".to_string()
        };
        self.push_event(format!("#e# net {net} clocks"));
        ok(tag, vec![format!("target={target}")], "200 OK")
    }

    /// Native `NET RENAME address new-address [nofixrefs]`.
    fn net_rename(&mut self, tag: &str, words: &[&str]) -> Response {
        if !(4..=5).contains(&words.len()) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 NET RENAME requires an address and destination",
            );
        }
        if words.len() == 5 && !words[4].eq_ignore_ascii_case("nofixrefs") {
            return err(tag, status::BAD_REQUEST, "400 Unknown rename argument");
        }
        let (project, net) = match self.resolve_network_mut(words) {
            Ok(v) => v,
            Err(mut e) => {
                e.tag = tag.to_string();
                return e;
            }
        };
        let current = self.current.clone().unwrap_or_default();
        if !project.is_empty() && project != current {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let dst: i64 = words[3].parse().unwrap_or(-1);
        if !(0..=255).contains(&dst) {
            return err(tag, status::BAD_REQUEST, "400 Invalid network address");
        }
        let Some(proj) = self.current_project_mut() else {
            return err(tag, status::NOT_FOUND, "404 No project selected");
        };
        if u16::from(net) as i64 == dst {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 New network address must differ",
            );
        }
        let Some(network) = proj.networks.remove(&net) else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        if proj.networks.contains_key(&(dst as u8)) {
            proj.networks.insert(net, network);
            return err(tag, status::CONFLICT_EXISTS, "409 Network already exists");
        }
        let mut network = network;
        network.address = dst as u8;
        proj.networks.insert(dst as u8, network);
        self.remap_network_paths(&current, net, dst as u8);
        self.push_event(format!("#e# net renamed {net} {dst}"));
        ok(tag, vec![], "200 OK")
    }

    /// Native `NET SET_PROJECT_IDENTIFY address project`.
    fn net_set_identity(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 4 || !valid_name(words[3]) {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 NET SET_PROJECT_IDENTIFY requires an address and project",
            );
        }
        match self.require_network(tag, words[2]) {
            Ok(_) => {}
            Err(r) => return r,
        }
        if !self.projects.contains_key(words[3]) {
            return err(tag, status::NOT_FOUND, "404 Project not found");
        }
        ok(tag, vec![], "200 OK")
    }

    /// Native `CALCULATOR TEST //PROJECT/NET`.
    fn calculator(&mut self, tag: &str, words: &[&str]) -> Response {
        if words.len() != 3 {
            return err(
                tag,
                status::BAD_REQUEST,
                "400 CALCULATOR TEST requires a network",
            );
        }
        let (project, net) = match self.resolve_network_mut(words) {
            Ok(v) => v,
            Err(mut e) => {
                e.tag = tag.to_string();
                return e;
            }
        };
        let current = self.current.clone().unwrap_or_default();
        if !project.is_empty() && project != current {
            return err(tag, status::NOT_FOUND, "404 Project not selected");
        }
        let Some(count) = self
            .projects
            .get(&current)
            .and_then(|p| p.networks.get(&net))
            .map(|n| n.physical.len())
        else {
            return err(tag, status::NOT_FOUND, "404 Network not found");
        };
        // Native calculator rows carry the 134 envelope on every line
        // (including `result: OK`), which `calculate` requires verbatim.
        Response {
            tag: tag.to_string(),
            lines: vec![
                "134-current_supply(mA)=0".to_string(),
                "134-current_consumption(mA)=0".to_string(),
                "134-impedance(ohms)=0".to_string(),
                format!("134-units_calculated={count}"),
                "134-units_not_calculated=0".to_string(),
            ],
            final_text: "134 result: OK".to_string(),
            status: 134,
        }
    }

    /// Shared `//PROJECT/NET` resolution for commands taking one address.
    fn require_network(&mut self, tag: &str, target: &str) -> Result<(String, u8), Response> {
        let words = ["NET", "OP", target];
        let (project, net) = match self.resolve_network_mut(&words) {
            Ok(v) => v,
            Err(mut e) => {
                e.tag = tag.to_string();
                return Err(e);
            }
        };
        let current = self.current.clone().unwrap_or_default();
        if !project.is_empty() && project != current {
            return Err(err(tag, status::NOT_FOUND, "404 Project not selected"));
        }
        if self
            .projects
            .get(&current)
            .and_then(|p| p.networks.get(&net))
            .is_none()
        {
            return Err(err(tag, status::NOT_FOUND, "404 Network not found"));
        }
        Ok((current, net))
    }

    /// Split `//PROJECT/NET` head from any address path.
    fn network_of(&self, path: &str) -> Option<(String, u8)> {
        let t = path.trim_start_matches('/');
        let mut parts = t.split('/');
        let project = parts.next()?.to_string();
        let net: u8 = parts.next()?.parse().ok()?;
        if !self
            .projects
            .get(&project)
            .is_some_and(|p| p.networks.contains_key(&net))
        {
            return None;
        }
        Some((project, net))
    }

    /// Split a unit path `//PROJECT/NET/p/ADDR[/...]` into parts.
    fn split_unit(path: &str) -> Option<(String, u8, u8)> {
        let t = path.trim_start_matches('/');
        let parts: Vec<&str> = t.split('/').collect();
        if parts.len() < 4 || !parts[2].eq_ignore_ascii_case("p") {
            return None;
        }
        let net: u8 = parts[1].parse().ok()?;
        let addr: u8 = parts[3].parse().ok()?;
        Some((parts[0].to_string(), net, addr))
    }

    /// Resolve a unit path against existing projects/networks.
    fn unit_of(&self, path: &str) -> Option<(String, u8, u8)> {
        let (project, net, addr) = Self::split_unit(path)?;
        self.projects
            .get(&project)
            .filter(|p| p.networks.contains_key(&net))
            .map(|_| (project, net, addr))
    }

    /// Issue a deterministic OID for `Level`/`NetVar` creation and units.
    ///
    /// The counter is process-global so parallel connections (each with
    /// their own `Server`) never issue colliding OIDs.
    fn issue_oid(&mut self) -> String {
        let oid = fresh_oid();
        self.known_oids.insert(oid.clone());
        oid
    }
}

/// Process-global OID source shared by units and levels.
fn fresh_oid() -> String {
    static NEXT_OID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
    let n = NEXT_OID.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    format!("00000000-0000-0000-0000-{n:012x}")
}

fn eq_verb(upper: &str, verb: &str) -> bool {
    upper == verb || upper.starts_with(&format!("{verb} "))
}

fn starts_with(upper: &str, prefix: &str) -> bool {
    upper == prefix
        || upper.starts_with(&format!("{prefix} "))
        || upper.starts_with(&format!("{prefix}/"))
}

fn is_lighting(upper: &str) -> bool {
    upper == "LIGHTING" || upper.starts_with("LIGHTING ") || upper.starts_with("LIGHTING/")
}

/// `TRIGGER|ENABLE LABEL|UNICODELABEL ...` families (see `NativeLabels`).
fn is_label_command(upper: &str) -> bool {
    upper.starts_with("TRIGGER LABEL")
        || upper.starts_with("TRIGGER UNICODELABEL")
        || upper.starts_with("ENABLE LABEL")
        || upper.starts_with("ENABLE UNICODELABEL")
}

/// Opaque native address token: nonempty with no comment marker.
/// Native addresses arrive as project paths, OID paths or saved tags.
fn valid_target(token: &str) -> bool {
    !token.is_empty() && !token.contains('#')
}

/// Decimal byte value.
fn valid_byte(word: &str) -> bool {
    word.parse::<i64>().is_ok_and(|v| (0..=255).contains(&v))
}

fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

fn split_network(target: &str) -> (String, String) {
    let t = target.trim_start_matches('/');
    let parts: Vec<&str> = t.split('/').collect();
    if parts.len() >= 2 {
        (parts[0].to_string(), parts[1].to_string())
    } else {
        (
            String::new(),
            parts.first().copied().unwrap_or("").to_string(),
        )
    }
}

/// Validate a lighting level byte through the shared wire codec range.
pub fn valid_lighting_level(level: i64) -> bool {
    (0..=255).contains(&level)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn greeting_prefix() {
        assert!(Server::greeting().starts_with(GREETING_PREFIX));
    }

    #[test]
    fn event_modes_parse_report_and_filter() {
        // Manual 4.5.83 equivalences and round-trip display.
        assert_eq!(EventMode::parse("ON"), Some(EventMode::DEFAULT));
        assert_eq!(EventMode::parse("off"), Some(EventMode::OFF));
        assert_eq!(EventMode::DEFAULT.to_string(), "e+s0c0");
        assert_eq!(EventMode::OFF.to_string(), "e0s0c0");
        let mode = EventMode::parse("e5s1c1").expect("valid mode");
        assert_eq!(mode.to_string(), "e5s1c1");
        assert!(EventMode::parse("e5s1c1").is_some());
        for bad in ["", "e", "e5s1c", "e5s1c12", "E5S1C1", "e+s2c1", "e+s1c"] {
            assert!(EventMode::parse(bad).is_none(), "{bad}");
        }
        assert!(EventMode::OFF.is_off());
        assert!(!EventMode::DEFAULT.is_off());
        // Delivery: unlevelled `#e#` lines pass any `e` but `e0`.
        assert!(EventMode::DEFAULT.delivers(EventCategory::Event));
        assert!(!EventMode::OFF.delivers(EventCategory::Event));
        assert!(!EventMode::DEFAULT.delivers(EventCategory::Status));
        assert!(!EventMode::DEFAULT.delivers(EventCategory::Config));
        assert!(mode.delivers(EventCategory::Status));
        assert!(mode.delivers(EventCategory::Config));
        // Categories use the default C-Gate event mapping.
        assert_eq!(event_category("#e# x"), EventCategory::Event);
        assert_eq!(event_category("#s# x"), EventCategory::Status);
        assert_eq!(event_category("#c# x"), EventCategory::Config);
        assert_eq!(
            event_category("20260914-100043 702 //X"),
            EventCategory::Event
        );
    }

    #[test]
    fn tagged_roundtrip() {
        let cmd = parse_command("[42] PROJECT LIST").unwrap();
        assert_eq!(cmd.tag, "42");
        let resp = ok(&cmd.tag, vec!["TEST".to_string()], "200 OK");
        let wire = format_response(&resp);
        assert!(wire.contains("[42] 200 TEST-") || wire.contains("[42] 200-TEST"));
        assert!(wire.contains("[42] 200 OK"));
    }

    #[test]
    fn rejects_missing_tag() {
        assert!(parse_command("PROJECT LIST").is_err());
    }

    #[test]
    fn project_lifecycle() {
        let mut s = Server::new(AccessLevel::Program);
        assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(s.handle("[2] PROJECT LIST").status, 200);
        assert_eq!(s.handle("[3] PROJECT USE TEST").status, 200);
        assert_eq!(s.handle("[4] PROJECT SAVE").status, 200);
        // Networks come from the database layer; OPEN of a missing one is 404.
        assert_eq!(s.handle("[5] NET OPEN //TEST/254").status, 404);
        assert_eq!(
            s.handle("[6] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        assert_eq!(s.handle("[7] NET OPEN //TEST/254").status, 200);
        assert_eq!(s.handle("[8] NET STATE //TEST/254").status, 200);
        assert_eq!(s.handle("[9] NET SYNC //TEST/254").status, 200);
        assert_eq!(s.handle("[10] NET CLOSE //TEST/254").status, 200);
        assert_eq!(s.handle("[11] PROJECT DELETE TEST").status, 200);
    }

    #[test]
    fn programming_denied_by_default() {
        let mut s = Server::new(AccessLevel::Program);
        let r = s.handle("[1] PP LOCK //TEST/254");
        assert_eq!(r.status, status::ACCESS_DENIED);
    }

    #[test]
    fn programming_allowed_with_rights() {
        let mut s = Server::new(AccessLevel::Program).with_programming(true);
        let r = s.handle("[1] PP LOCK mylock //TEST/254");
        assert_eq!(r.status, status::OK);
    }

    #[test]
    fn named_scene_fails_401() {
        let mut s = Server::new(AccessLevel::Program);
        let r = s.handle("[1] SCENE TRIGGER 1");
        assert_eq!(r.status, status::UNAUTHORIZED);
    }

    #[test]
    fn events_do_not_complete_commands() {
        assert!(is_event_line("#e# net 254 open"));
        assert!(is_event_line("#e#"));
        assert!(is_event_line("#s# sync done"));
        assert!(is_event_line("#c# clock tick"));
        assert!(!is_event_line("#e#x"));
        assert!(!is_event_line("[1] 200 OK"));
        assert!(is_event_line("20240101-120000 800 net sync ok"));
        assert!(is_event_line("20240101-120000.123 712 hello"));
        assert!(!is_event_line("20240101-120000.12 800 short millis"));
        assert!(!is_event_line("20240101-120000 600 out of range"));
        assert!(!is_event_line("20240101-120000 800missing space"));
    }

    #[test]
    fn tagless_line_gets_untagged_reply() {
        let mut s = Server::new(AccessLevel::Program);
        let r = s.handle("PROJECT LIST");
        assert_eq!(r.status, status::BAD_REQUEST);
        let wire = format_response(&r);
        assert!(!wire.contains('['));
        assert!(wire.starts_with("400 "));
    }

    #[test]
    fn database_and_observation_commands() {
        let mut s = Server::new(AccessLevel::Program);
        assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(
            s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        // Unit lifecycle through the native SAFE verbs.
        assert_eq!(
            s.handle("[3] DBADDSAFE //TEST/254 Unit 20 Lounge").status,
            200
        );
        assert_eq!(
            s.handle("[4] DBADDSAFE //TEST/254 Unit 20 Lounge").status,
            409
        );
        assert_eq!(
            s.handle("[5] DBSETSAFE //TEST/254/p/20/UnitName LOUNGE")
                .status,
            200
        );
        let g = s.handle("[6] GET //TEST/254/p/20 UnitName");
        assert_eq!(g.status, 300);
        assert!(g.final_text.contains("UnitName=LOUNGE"));
        // Level creation answers 301 + OID; the OID resolves with 342.
        let add = s.handle("[7] DBADDSAFE //TEST/254/56 Level 1 Evening");
        assert_eq!(add.status, 301);
        let oid = add.final_text.rsplit('=').next().unwrap().to_string();
        let resolve = s.handle(&format!("[8] DBGET !{oid}/OID"));
        assert_eq!(resolve.status, 342);
        assert!(resolve.final_text.ends_with(&oid));
        // Observation commands over the known network.
        assert_eq!(s.handle("[9] NET LIST_ALL").status, 200);
        assert_eq!(s.handle("[10] NET LIST TEST").status, 200);
        assert_eq!(s.handle("[11] NET OPEN //TEST/254").status, 200);
        let st = s.handle("[12] GET //TEST/254 state");
        assert_eq!(st.status, 300);
        assert!(st.final_text.contains("state=open"));
        let tgt = s.handle("[13] GET //TEST/254 TargetInterfaceState");
        assert_eq!(tgt.status, 300);
        assert!(tgt.final_text.contains("TargetInterfaceState=running"));
        assert_eq!(s.handle("[14] NET SYNC //TEST/254 fast 3").status, 200);
        assert_eq!(s.handle("[15] NET SYNCNEW //TEST/254").status, 200);
        let pingu = s.handle("[16] NET PINGU //TEST/254");
        assert_eq!(pingu.status, 200);
        assert!(pingu.lines.iter().any(|l| l == "302-Units=20"));
        assert_eq!(pingu.final_text, "200 OK.");
        assert_eq!(s.handle("[17] NET CHECKUNIT //TEST/254 20").status, 200);
        assert_eq!(
            s.handle("[18] NET UNRAVELUNIT //TEST/254 20 matchdb")
                .status,
            200
        );
        assert_eq!(s.handle("[19] NET CLOCKS //TEST/254 2").status, 200);
        assert_eq!(s.handle("[20] NET CLOCKS //TEST/254 R").status, 200);
        assert_eq!(s.handle("[21] TREEXML //TEST/254").status, 200);
        let calc = s.handle("[22] CALCULATOR TEST //TEST/254");
        assert_eq!(calc.status, 134);
        assert!(calc.lines.iter().any(|l| l == "134-units_calculated=1"));
        assert!(calc.final_text.contains("result: OK"));
        assert_eq!(s.handle("[23] DBVALIDATE //TEST/254/p/20").status, 233);
        assert_eq!(
            s.handle("[24] DBCOPYSAFE //TEST/254/p/20 //TEST/254 21 Hall")
                .status,
            200
        );
        assert_eq!(s.handle("[25] DBRENAMENETSAFE 254 253").status, 200);
        assert_eq!(s.handle("[26] NET RENAME //TEST/253 252").status, 200);
        assert_eq!(
            s.handle("[27] NET SET_PROJECT_IDENTIFY //TEST/252 TEST")
                .status,
            200
        );
        assert_eq!(s.handle("[28] DBDELETE //TEST/252/p/20").status, 200);
        assert_eq!(s.handle("[29] DBDELETE //TEST/252/p/20").status, 404);
        // 347 XML snippet for DBGETXML; write-then-read via DBSETXML.
        let xml = s.handle("[30] DBGETXML //TEST/252/p/21");
        assert_eq!(xml.status, 200);
        assert!(xml.lines.iter().any(|l| l.starts_with("347-")));
        assert_eq!(
            s.handle("[31] DBADDSAFE //TEST/252 Unit 30 Study").status,
            200
        );
        // Boundary-checked delete: removing p/3 must not touch p/30.
        assert_eq!(s.handle("[32] DBDELETE //TEST/252/p/3").status, 404);
        let star = s.handle("[33] GET //TEST/252/p/30 *");
        assert_eq!(star.status, 300);
        assert!(star
            .lines
            .iter()
            .chain(std::iter::once(&star.final_text))
            .any(|l| l.contains("UnitName=Study")));
        // Exact native validation + clear + scalar-move shapes.
        let valid = s.handle("[34] DBVALIDATE //TEST/252/p/30");
        assert_eq!(valid.status, 233);
        assert!(valid
            .lines
            .iter()
            .chain(std::iter::once(&valid.final_text))
            .all(|l| l.starts_with("233-") || l.starts_with("233 ")));
        let clear = s.handle("[35] LABEL CLEAREDLT //TEST/252/p/30");
        assert_eq!(clear.status, 200);
        assert!(clear.lines.is_empty() && clear.final_text == "200 OK.");
        let moved = s.handle("[36] SET //TEST/252/p/30 Address 31");
        assert_eq!(moved.status, 200);
        assert!(moved.lines.is_empty() && moved.final_text == "200 OK: //TEST/252/p/31");
        // The move is physical-only: the database record stays put while
        // physical reads observe the new address.
        assert_eq!(s.handle("[37] DBGET //TEST/252/p/30/UnitName").status, 200);
        assert_eq!(s.handle("[37b] GET //TEST/252/p/30 UnitName").status, 401);
        let moved_read = s.handle("[37c] GET //TEST/252/p/31 UnitName");
        assert_eq!(moved_read.status, 300);
        let oid_add = s.handle("[38] DBADDSAFE //TEST/252/56 Level 1 Evening");
        let oid = oid_add.final_text.rsplit('=').next().unwrap().to_string();
        let oid_get = s.handle(&format!("[39] DBGET !{oid}/OID"));
        assert_eq!(oid_get.status, 342);
        assert!(oid_get.lines.is_empty());
        assert_eq!(oid_get.final_text, format!("342 !{oid}/OID={oid}"));
        // Deleting retires the identity: the OID stops resolving.
        assert_eq!(s.handle(&format!("[40] DBDELETE !{oid}")).status, 200);
        assert_eq!(s.handle(&format!("[41] DBGET !{oid}/OID")).status, 401);
        // Unknown unit fields are 404 (QUICKGET parity); alias writes
        // land in both layers' struct twins (unit 40 is fresh below).
        assert_eq!(
            s.handle("[42] DBADDSAFE //TEST/252 Unit 40 Aux").status,
            200
        );
        assert_eq!(s.handle("[43] GET //TEST/252/p/40 NoSuchField").status, 404);
        assert_eq!(
            s.handle("[44] DBSETSAFE //TEST/252/p/40/Type KEYE1X")
                .status,
            200
        );
        let aliased = s.handle("[45] GET //TEST/252/p/40 UnitType");
        assert!(aliased.final_text.contains("UnitType=KEYE1X"));
    }

    #[test]
    fn lighting_levels_round_trip() {
        let mut s = Server::new(AccessLevel::Program);
        assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
        // Lighting to a missing network is 404, not an invented success.
        assert_eq!(s.handle("[2] LIGHTING ON //TEST/254/56/1").status, 404);
        assert_eq!(
            s.handle("[3] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        // Untouched groups read level 0.
        let fresh = s.handle("[4] GET //TEST/254/56/1 level");
        assert_eq!(fresh.status, 300);
        assert!(fresh.final_text.ends_with(": level=0"));
        assert_eq!(s.handle("[5] LIGHTING ON //TEST/254/56/1").status, 200);
        let on = s.handle("[6] GET //TEST/254/56/1 level");
        assert!(on.final_text.ends_with(": level=255"));
        assert_eq!(
            s.handle("[7] LIGHTING RAMP //TEST/254/56/1 128 20").status,
            200
        );
        let ramped = s.handle("[8] GET //TEST/254/56/1 level");
        assert!(ramped.final_text.ends_with(": level=128"));
        // STOP holds the current level; OFF clears it.
        assert_eq!(s.handle("[9] LIGHTING STOP //TEST/254/56/1").status, 200);
        let held = s.handle("[10] GET //TEST/254/56/1 level");
        assert!(held.final_text.ends_with(": level=128"));
        assert_eq!(s.handle("[11] LIGHTING OFF //TEST/254/56/1").status, 200);
        let off = s.handle("[12] GET //TEST/254/56/1 level");
        assert!(off.final_text.ends_with(": level=0"));
        // Groups are independent across applications.
        assert_eq!(
            s.handle("[13] LIGHTING RAMP //TEST/254/57/1 64 0").status,
            200
        );
        let other = s.handle("[14] GET //TEST/254/57/1 level");
        assert!(other.final_text.ends_with(": level=64"));
        let first = s.handle("[15] GET //TEST/254/56/1 level");
        assert!(first.final_text.ends_with(": level=0"));
        // Malformed lighting addresses stay 400.
        assert_eq!(s.handle("[16] LIGHTING ON //TEST/254/56").status, 400);
        assert_eq!(s.handle("[17] GET //TEST/254/56 level").status, 400);
        // STOP on a never-touched group is a side-effect-free no-op.
        assert_eq!(s.handle("[18] LIGHTING STOP //TEST/254/56/7").status, 200);
        let held_empty = s.handle("[19] GET //TEST/254/56/7 level");
        assert!(held_empty.final_text.ends_with(": level=0"));
    }

    #[test]
    fn pp_session_lifecycle() {
        let mut s = Server::new(AccessLevel::Program).with_programming(true);
        assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(
            s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        assert_eq!(
            s.handle("[3] DBADDSAFE //TEST/254 Unit 20 Lounge").status,
            200
        );
        assert_eq!(
            s.handle("[4] DBSETSAFE //TEST/254/p/20/UnitType KEY1")
                .status,
            200
        );
        assert_eq!(
            s.handle("[5] DBSETSAFE //TEST/254/p/20/FirmwareVersion 1.2.67")
                .status,
            200
        );
        // Lock/start/session verbs.
        assert_eq!(s.handle("[6] PP LOCK L1 //TEST/254").status, 200);
        assert_eq!(s.handle("[7] PP LOCK L1 //TEST/254").status, 409);
        assert_eq!(s.handle("[8] PP START S1 L1").status, 200);
        assert_eq!(s.handle("[9] PP START S1 L1").status, 409);
        // NEW keeps identity out of the parameter namespace (native
        // `PP GET *` carries no identity rows; export reads the struct).
        assert_eq!(s.handle("[10] PP NEW S1 KEY1 1.2.67").status, 200);
        assert_eq!(s.handle("[11] PP GET S1 UnitType").status, 404);
        // SET then read back the full table, including an mK-escaped
        // space end to end over the wire shapes.
        assert_eq!(s.handle("[12] PP SET S1 UnitName LOUNGE").status, 200);
        assert_eq!(
            s.handle("[12b] PP SET S1 Note \"Hello\\ World\"").status,
            200
        );
        assert_eq!(
            s.sessions["S1"].dirty,
            HashSet::from(["Note".to_string(), "UnitName".to_string()])
        );
        let all = s.handle("[13] PP GET S1 *");
        assert_eq!(all.status, 315);
        assert_eq!(all.final_text, "315 UnitName=LOUNGE");
        assert!(all.lines.iter().any(|l| l == "315-Note=Hello World"));
        // INFO envelope carries a parseable 347 schema row.
        let info = s.handle("[14] PP INFO S1 *");
        assert_eq!(info.status, 344);
        assert!(info.lines.iter().any(|l| l.starts_with("347-<Parameters>")));
        // SAVE persists staged values to the database record (physical
        // transfer is a separate unverified step, so read back via DBGET).
        assert_eq!(s.handle("[15] PP SAVE S1 /db//TEST/254/p/20").status, 200);
        assert!(s.sessions["S1"].dirty.is_empty());
        let back = s.handle("[16] DBGET //TEST/254/p/20/UnitName");
        assert!(back.lines.iter().any(|l| l.ends_with("UnitName=LOUNGE")));
        // LOAD seeds parameters but not identity rows; the struct
        // carries identity (see export_parameters).
        assert_eq!(s.handle("[17] PP START S2 L1").status, 200);
        assert_eq!(s.handle("[18] PP LOAD S2 /db//TEST/254/p/20").status, 200);
        assert!(s.sessions["S2"].dirty.is_empty());
        assert_eq!(s.handle("[19] PP GET S2 FirmwareVersion").status, 404);
        let reloaded = s.handle("[19b] PP GET S2 UnitName");
        assert_eq!(reloaded.final_text, "315 UnitName=LOUNGE");
        // QUICKGET reads database fields without a session.
        let quick = s.handle("[20] PP QUICKGET //TEST/254/p/20 UnitName");
        assert_eq!(quick.final_text, "315 UnitName=LOUNGE");
        // Lock inventory and teardown.
        let locks = s.handle("[21] PP LIST_LOCK");
        assert!(locks.lines.iter().any(|l| l.contains("lock=L1")));
        assert_eq!(s.handle("[22] PP END S1").status, 200);
        assert_eq!(s.handle("[23] PP END S2").status, 200);
        assert_eq!(s.handle("[24] PP UNLOCK L1").status, 200);
        assert_eq!(s.handle("[25] PP UNLOCK L1").status, 404);
        // Starts require a held lock; saves require database destinations.
        assert_eq!(s.handle("[26] PP START S3 L1").status, 404);
        assert_eq!(s.handle("[27] PP LOCK L2 //TEST/254").status, 200);
        assert_eq!(s.handle("[28] PP START S3 L2").status, 200);
        assert_eq!(s.handle("[29] PP NEW S3 KEY1 1.2.67").status, 200);
        assert_eq!(s.handle("[30] PP SAVE S3 //TEST/254/p/20").status, 400);
        assert_eq!(s.handle("[31] PP SAVE_TO_SOURCE S3").status, 408);
    }

    #[test]
    fn event_modes_mirror_native_validation() {
        assert!(valid_event_mode("ON"));
        assert!(valid_event_mode("on"));
        assert!(valid_event_mode("OFF"));
        assert!(valid_event_mode("e8s1c1"));
        assert!(valid_event_mode("e+s0c1"));
        assert!(!valid_event_mode("e10s1c1"));
        assert!(!valid_event_mode("e8s2c0"));
        assert!(!valid_event_mode("e8s1c2"));
        assert!(!valid_event_mode("E8S1C1"));
        assert!(!valid_event_mode(""));
        assert!(!valid_event_mode("e8s1c1 "));
        let mut s = Server::new(AccessLevel::Program);
        assert_eq!(s.handle("[1] EVENT e8s1c1").status, 200);
        assert_eq!(s.handle("[2] EVENT bogus").status, 400);
        assert_eq!(s.handle("[3] EVENT OFF").status, 200);
        // Subscription needs no programming rights, any role but Config.
        let mut m = Server::new(AccessLevel::Monitor);
        assert_eq!(m.handle("[1] EVENT e8s1c1").status, 200);
    }

    #[test]
    fn getstate_snapshots_network() {
        let mut s = Server::new(AccessLevel::Program);
        assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(
            s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        assert_eq!(s.handle("[3] GETSTATE //TEST/254").status, 200);
        let snap = s.handle("[4] GETSTATE //TEST/254");
        assert!(snap.lines.iter().any(|l| l == "state=closed"));
        assert_eq!(s.handle("[5] NET OPEN //TEST/254").status, 200);
        assert_eq!(s.handle("[6] LIGHTING ON //TEST/254/56/1").status, 200);
        let snap = s.handle("[7] GETSTATE //TEST/254");
        assert!(snap.lines.iter().any(|l| l == "state=open"));
        assert!(snap.lines.iter().any(|l| l == "level=56/1=255"));
        assert_eq!(s.handle("[8] GETSTATE //TEST/253").status, 404);
    }

    #[test]
    fn project_verbs_repositories_and_export() {
        let mut s = Server::new(AccessLevel::Program);
        assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(s.handle("[2] PROJECT DIR").status, 200);
        assert_eq!(s.handle("[3] PROJECT LOAD TEST").status, 200);
        assert_eq!(s.handle("[4] PROJECT LOAD NOPE").status, 404);
        // Manual 4.5.162 permits the current project to be implicit.
        assert_eq!(s.handle("[4b] PROJECT LOAD").status, 200);
        // State exists before the rename so key migration is exercised.
        assert_eq!(
            s.handle("[4b] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        assert_eq!(
            s.handle("[4c] DBADDSAFE //TEST/254 Unit 20 Lounge").status,
            200
        );
        assert_eq!(
            s.handle("[4d] DBSETSAFE //TEST/254/p/20/UnitName LOUNGE")
                .status,
            200
        );
        assert_eq!(s.handle("[5] PROJECT RENAME TEST TEST2").status, 200);
        assert_eq!(s.handle("[6] PROJECT USE TEST").status, 404);
        assert_eq!(s.handle("[7] PROJECT USE TEST2").status, 200);
        // Database keys followed the project: new-path reads hit.
        let moved = s.handle("[7b] GET //TEST2/254/p/20 UnitName");
        assert_eq!(moved.status, 300);
        assert!(moved.final_text.contains("UnitName=LOUNGE"));
        // ... and a copy duplicates them while the source keeps working.
        assert_eq!(s.handle("[7c] PROJECT COPY TEST2 TEST3").status, 200);
        assert_eq!(s.handle("[7d] PROJECT USE TEST3").status, 200);
        let cloned = s.handle("[7e] GET //TEST3/254/p/20 UnitName");
        assert_eq!(cloned.status, 300);
        assert!(cloned.final_text.contains("UnitName=LOUNGE"));
        // Copies mint fresh identities: no OID is shared across projects.
        // (Current selection is TEST3 here; TEST2 is read after USE.)
        let xml_new = s.handle("[7e1] DBGETXML //TEST3/254");
        assert_eq!(s.handle("[7e2] PROJECT USE TEST2").status, 200);
        let xml_old = s.handle("[7e3] DBGETXML //TEST2/254");
        let oids_of = |r: &Response| {
            r.lines
                .iter()
                .filter_map(|l| {
                    let (_, rest) = l.split_once("<OID>")?;
                    rest.split_once("</OID>").map(|(id, _)| id.to_string())
                })
                .collect::<Vec<_>>()
        };
        let (old_ids, new_ids) = (oids_of(&xml_old), oids_of(&xml_new));
        assert_eq!(old_ids.len(), 1);
        assert_eq!(new_ids.len(), 1);
        assert_ne!(old_ids, new_ids);
        assert_eq!(s.handle("[7f] PROJECT USE TEST2").status, 200);
        // The old project name is gone entirely (selection error, not a
        // stale hit); the copy below proves duplication while the source
        // keeps serving from its migrated keys.
        assert_eq!(s.handle("[7g] DBGET //TEST/254/p/20/UnitName").status, 404);
        assert_eq!(
            s.handle("[7h] DBSETSAFE //TEST3/254/p/20/UnitName CHANGED")
                .status,
            200
        );
        let source = s.handle("[7i] GET //TEST2/254/p/20 UnitName");
        assert!(source.final_text.contains("UnitName=LOUNGE"));
        // Process-local project archives round-trip under a new name.
        assert_eq!(s.handle("[8] PROJECT ARCHIVE TEST2 /tmp/x.zip").status, 200);
        assert_eq!(s.handle("[9] PROJECT RESTORE TEST4 /tmp/x.zip").status, 200);
        assert_eq!(s.handle("[9b] PROJECT USE TEST4").status, 200);
        assert_eq!(s.handle("[9c] GET //TEST4/254/p/20 UnitName").status, 300);
        assert_eq!(s.handle("[9d] PROJECT USE TEST2").status, 200);
        // The mock models no server repositories: exact empty 124 reply.
        let repos = s.handle("[10] REPOSITORY LIST");
        assert_eq!(repos.status, 124);
        assert!(repos.lines.is_empty());
        assert_eq!(repos.final_text, "124 no repositories found");
        // CGL EXPORT carries the native 344 envelope (network 254 was
        // created during the rename setup above).
        let export = s.handle("[12] CGL EXPORT TEST2 * *");
        assert_eq!(export.status, 344);
        assert!(export.lines[0].starts_with("343-"));
        assert!(export.lines.iter().any(|l| l.starts_with("347-")));
        assert_eq!(export.final_text, "344 End CGL snippet");
        // Pinned network runtime snapshot for physical guards.
        let runtime = s.handle("[13] GET //TEST2/254 *");
        assert_eq!(runtime.status, 300);
        let rows: Vec<&str> = runtime
            .lines
            .iter()
            .map(String::as_str)
            .chain(std::iter::once(runtime.final_text.as_str()))
            .collect();
        for expected in [
            "InterfaceState=closed",
            "TargetInterfaceState=closed",
            "SyncState=idle",
            "AutoUnravel=no",
            "AutoUpdate=no",
            "Retries=0",
            "NetworkType=Wired",
            "Name=254",
            "Type=Cni",
            "InterfaceAddress=127.0.0.1:10001",
        ] {
            assert!(rows.iter().any(|l| l.contains(expected)), "{expected}");
        }
        assert_eq!(runtime.lines.len() + 1, 21);
    }

    #[test]
    fn mock_bus_del_stages_db_without_physical() {
        let mut s = Server::new(AccessLevel::Program);
        assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(
            s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        assert_eq!(s.handle("[3] DBADDSAFE //TEST/254 Unit 6 Hall").status, 200);
        // Dropping bus presence keeps the database record: physical
        // reads go absent while database reads still hit.
        assert_eq!(s.handle("[4] MOCK BUS-DEL //TEST/254 6").status, 200);
        assert_eq!(s.handle("[5] MOCK BUS-DEL //TEST/254 6").status, 404);
        let pingu = s.handle("[6] NET PINGU //TEST/254");
        assert_eq!(pingu.status, 200);
        assert!(pingu.lines.iter().any(|l| l == "302-Units="));
        assert_eq!(pingu.final_text, "200 OK.");
        assert_eq!(s.handle("[7] DBGET //TEST/254/p/6/UnitName").status, 200);
        assert_eq!(s.handle("[8] GET //TEST/254/p/6 UnitName").status, 401);
    }

    #[test]
    fn network_xml_reports_model_state() {
        let mut s = Server::new(AccessLevel::Program);
        assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(
            s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        assert_eq!(s.handle("[3] DBADDSAFE //TEST/254 Unit 4 Key").status, 200);
        assert_eq!(
            s.handle("[4] DBSETSAFE //TEST/254/p/4/UnitType KEYE1")
                .status,
            200
        );
        assert_eq!(
            s.handle("[4b] DBSETSAFE //TEST/254/p/4/FirmwareVersion 2.5.00")
                .status,
            200
        );
        assert_eq!(
            s.handle("[5] DBSETSAFE //TEST/254/p/4/SerialNumber 101136.1558")
                .status,
            200
        );
        let xml = s.handle("[6] DBGETXML //TEST/254");
        assert_eq!(xml.status, 200);
        let doc = xml
            .lines
            .iter()
            .find(|l| l.starts_with("347-"))
            .expect("347 snippet");
        for fragment in [
            "<Network>",
            "<Address>254</Address>",
            "<InterfaceType>Cni</InterfaceType>",
            "<InterfaceAddress>127.0.0.1:10001</InterfaceAddress>",
            "<Unit><Address>4</Address>",
            "<UnitType>KEYE1</UnitType>",
            "<FirmwareVersion>2.5.00</FirmwareVersion>",
            "<SerialNumber>101136.1558</SerialNumber>",
            "<OID>00000000-0000-0000-0000-",
        ] {
            assert!(doc.contains(fragment), "{fragment}");
        }
    }

    #[test]
    fn snippet_quoting_and_oid_retirement() {
        let mut s = Server::new(AccessLevel::Program);
        assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(
            s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        assert_eq!(s.handle("[3] DBADDSAFE //TEST/254 Unit 4 Key").status, 200);
        assert_eq!(
            s.handle("[4] DBSETSAFE //TEST/254/p/4/UnitName A\"B&C<D>")
                .status,
            200
        );
        // Attribute values escape; the snippet stays well-formed.
        let xml = s.handle("[5] DBGETXML //TEST/254/p/4");
        let snippet = xml
            .lines
            .iter()
            .find(|l| l.starts_with("347-"))
            .expect("347 snippet");
        assert!(snippet.contains("name=\"A&quot;B&amp;C&lt;D&gt;\""));
        // CHECKUNIT whole-network selection reports known units.
        let check = s.handle("[6] NET CHECKUNIT //TEST/254 *");
        assert_eq!(check.status, 200);
        assert!(check
            .lines
            .iter()
            .any(|l| l == "120-Single unit detected at address: 4"));
        // Deleting the unit retires its OID: `!oid/OID` stops resolving.
        let net_xml = s.handle("[7] DBGETXML //TEST/254");
        let doc = net_xml
            .lines
            .iter()
            .find(|l| l.starts_with("347-"))
            .expect("347 network");
        let oid = doc
            .split_once("<OID>")
            .and_then(|(_, rest)| rest.split_once("</OID>"))
            .map(|(id, _)| id.to_string())
            .expect("unit OID");
        assert_eq!(s.handle("[8] DBDELETE //TEST/254/p/4").status, 200);
        assert_eq!(s.handle(&format!("[9] DBGET !{oid}/OID")).status, 401);
    }

    #[test]
    fn coded_lines_pass_through_untouched() {
        let resp = Response {
            tag: "9".to_string(),
            lines: vec![
                "343-Begin XML snippet".to_string(),
                "347-<Unit/>".to_string(),
                "plain payload".to_string(),
            ],
            final_text: "200 Done".to_string(),
            status: 200,
        };
        let wire = format_response(&resp);
        assert!(wire.contains("[9] 343-Begin XML snippet\n"));
        assert!(wire.contains("[9] 347-<Unit/>\n"));
        assert!(wire.contains("[9] 200-plain payload\n"));
        assert!(wire.contains("[9] 200 Done\n"));
    }

    #[test]
    fn dequote_value_round_trip() {
        assert_eq!(dequote_value("\"20\""), "20");
        assert_eq!(dequote_value("\"a\\ b\\\"c\\\\d\""), "a b\"c\\d");
        assert_eq!(dequote_value("bare"), "bare");
        // Only the three emitted escapes de-escape.
        assert_eq!(dequote_value("\"a\\qb\""), "a\\qb");
        assert_eq!(dequote_value("\"trailing\\\""), "trailing\\");
    }

    #[test]
    fn envelope_passthrough_is_allowlisted() {
        // Only native envelopes pass through; user text gains the status.
        assert!(has_status_prefix("300-//T/254: state=open"));
        assert!(has_status_prefix("347-<Unit/>"));
        assert!(has_status_prefix("134-result: OK"));
        assert!(has_status_prefix("315-UnitName=X"));
        assert!(has_status_prefix("342-//T/254/p/20/UnitType=KEY1"));
        assert!(!has_status_prefix("200-foo"));
        assert!(!has_status_prefix("301 OID=x"));
        let mut s = Server::new(AccessLevel::Program);
        // Non-envelope codes cannot spoof (they gain the reply status and
        // parse back exactly); envelope codes are rejected outright.
        assert_eq!(s.handle("[1] PROJECT NEW 200-foo").status, 200);
        assert_eq!(s.handle("[1] PROJECT NEW 315-x").status, 400);
        assert_eq!(s.handle("[1] PROJECT NEW 342-x").status, 400);
        // Coded parameter/database rows survive wire formatting with
        // their own envelope instead of gaining a 200- prefix.
        let wire = format_response(&Response {
            tag: "1".to_string(),
            lines: vec!["315-UnitName=X".to_string(), "342-P/Q=F".to_string()],
            final_text: "200 OK".to_string(),
            status: 200,
        });
        assert!(wire.contains("[1] 315-UnitName=X\n"));
        assert!(wire.contains("[1] 342-P/Q=F\n"));
        assert_eq!(s.handle("[2] PROJECT NEW TEST").status, 200);
        assert_eq!(
            s.handle("[3] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        assert_eq!(
            s.handle("[4] DBADDSAFE //TEST/254 Unit 20 Lounge").status,
            200
        );
        // A whole-unit path has no field segment: no bogus `20` field.
        assert_eq!(s.handle("[5] DBSETSAFE //TEST/254/p/20 77").status, 200);
        let star = s.handle("[6] GET //TEST/254/p/20 *");
        assert_eq!(star.status, 300);
        let rows: Vec<&str> = star
            .lines
            .iter()
            .map(String::as_str)
            .chain(std::iter::once(star.final_text.as_str()))
            .collect();
        assert!(!rows.iter().any(|l| l.contains(": 20=")));
        assert!(rows.iter().any(|l| l.contains("UnitName=Lounge")));
    }

    #[test]
    fn rename_migrates_field_paths() {
        let mut s = Server::new(AccessLevel::Program);
        assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(
            s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        assert_eq!(
            s.handle("[3] DBADDSAFE //TEST/254 Unit 20 Lounge").status,
            200
        );
        assert_eq!(
            s.handle("[4] DBSETSAFE //TEST/254/p/20/UnitName X").status,
            200
        );
        assert_eq!(s.handle("[5] DBRENAMENETSAFE 254 253").status, 200);
        // The stored field followed the network to its new address.
        let g = s.handle("[6] GET //TEST/253/p/20 UnitName");
        assert_eq!(g.status, 300);
        assert!(g.final_text.contains("UnitName=X"));
        let stale = s.handle("[7] DBGET //TEST/254/56");
        assert_eq!(stale.status, 401);
    }

    #[test]
    fn privileged_roles_keep_pp_denied() {
        for access in [AccessLevel::Admin, AccessLevel::Monitor] {
            let mut s = Server::new(access).with_programming(true);
            assert_eq!(s.handle("[1] PP LOCK //TEST/254").status, 420);
            assert_eq!(s.handle("[2] NET LOAD DB").status, 420);
        }
    }

    #[test]
    fn application_commands_validate_arguments() {
        let mut s = Server::new(AccessLevel::Program);
        assert_eq!(s.handle("[1] PROJECT NEW TEST").status, 200);
        assert_eq!(
            s.handle("[2] DBCREATENET 254 Local Cni 127.0.0.1:10001")
                .status,
            200
        );
        // Native scene-executor forms.
        assert_eq!(s.handle("[3] LIGHTING ON //TEST/254/56/1").status, 200);
        assert_eq!(s.handle("[4] LIGHTING OFF //TEST/254/56/1").status, 200);
        assert_eq!(
            s.handle("[5] LIGHTING RAMP //TEST/254/56/1 128 20").status,
            200
        );
        assert_eq!(
            s.handle("[6] LIGHTING RAMP //TEST/254/56/1 128 2147483647")
                .status,
            200
        );
        assert_eq!(s.handle("[7] LIGHTING BOGUS //TEST/254/56/1").status, 400);
        assert_eq!(
            s.handle("[8] LIGHTING RAMP //TEST/254/56/1 999 20").status,
            400
        );
        assert_eq!(
            s.handle("[9] LIGHTING RAMP //TEST/254/56/1 128 -1").status,
            400
        );
        // Native trigger/enable forms, including FORCE.
        assert_eq!(s.handle("[10] TRIGGER EVENT //TEST/254/56 42").status, 200);
        assert_eq!(
            s.handle("[11] TRIGGER EVENT //TEST/254/56 42 FORCE").status,
            200
        );
        assert_eq!(s.handle("[12] TRIGGER EVENT //TEST/254/56").status, 400);
        assert_eq!(
            s.handle("[13] TRIGGER INDICATORKILL //TEST/254/56").status,
            200
        );
        assert_eq!(s.handle("[14] ENABLE SET //TEST/254/56 42").status, 200);
        assert_eq!(
            s.handle("[15] ENABLE SET //TEST/254/56 42 FORCE").status,
            200
        );
        assert_eq!(s.handle("[16] ENABLE SET //TEST/254/56 999").status, 400);
        assert_eq!(s.handle("[17] ENABLE REMOVE //TEST/254/56").status, 200);
        // Label families and database paths.
        assert_eq!(
            s.handle("[18] LIGHTING LABEL //TEST/254/56 0 1 - F0 0")
                .status,
            200
        );
        assert_eq!(
            s.handle("[19] ENABLE UNICODELABEL //TEST/254/56 0 1 - F0 RAW")
                .status,
            400
        );
        assert_eq!(s.handle("[20] DBGET //TEST/254/56").status, 200);
        // Foreign-project paths are selection errors (404); objects
        // missing inside the selected project are absent (401).
        assert_eq!(s.handle("[21] DBGET //NOPE/254/56").status, 404);
        assert_eq!(s.handle("[21b] DBGET //TEST/253/56").status, 401);
        assert_eq!(s.handle("[21c] GET //TEST/253 state").status, 401);
        assert_eq!(s.handle("[22] DBGET !abc123/OID").status, 401);
        assert_eq!(s.handle("[23] DBGETXML //TEST/254/56").status, 200);
        assert_eq!(s.handle("[24] ON //TEST/254/56 42").status, 400);
    }
}
