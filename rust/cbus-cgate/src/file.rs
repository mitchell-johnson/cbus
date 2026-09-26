//! Native-shaped C-Gate `FILE` family over the durable cmqttd repository.
//!
//! Native C-Gate maps these commands to `file.base`. cmqttd deliberately
//! presents an isolated virtual root instead: paths and binary contents are
//! durable in the atomic C-Gate state file, so a command connection cannot
//! traverse the host filesystem. The command grammar, base64 transfer,
//! directory, backup, digest and response envelopes follow retained 3.4.0
//! behavior.

use std::collections::BTreeMap;

use base64::{engine::general_purpose::STANDARD, Engine as _};
use chrono::{Local, TimeZone, Utc};

use crate::{Response, Server};

pub(crate) const HELP: &[&str] = &[
    "Help: FILE commands:",
    "Help:  FILE ? Help for these commands",
    "Help:  FILE DELETE - Remove a file or directory from the server",
    "Help:  FILE DIR - Return a list of directory contents for the given directory",
    "Help:  FILE DOWNLOAD - Download a copy of a file as a base-64 encoded chunk of data",
    "Help:  FILE LS - Return a list of directory contents for the given directory",
    "Help:  FILE MKDIR - Return a list of directory contents for the given directory",
    "Help:  FILE SHA256 - Calculate an SHA256 hash of a project file on the server",
    "Help:  FILE UPLOAD - Upload  a file to the server as a base-64 encoded chunk of data ",
];

#[derive(Debug, Clone)]
struct ControlledPath {
    key: String,
    requested: String,
    root: String,
}

#[derive(Debug, Clone)]
struct DirectoryEntry {
    directory: bool,
    size: usize,
    modified: i64,
}

pub(crate) fn command(
    model: &mut Server,
    tag: &str,
    body: &str,
    document: Option<&str>,
) -> Response {
    let words = tokens(body);
    if words.len() == 1 || (words.len() == 2 && words[1] == "?") {
        return help(tag);
    }
    let Some(sub) = words.get(1).map(|word| word.to_ascii_uppercase()) else {
        return syntax(tag);
    };
    match sub.as_str() {
        "UPLOAD" => upload(model, tag, body, document),
        "DOWNLOAD" => download(model, tag, body),
        "SHA256" => sha256(model, tag, body),
        "DIR" | "LS" => directory(model, tag, body),
        "DELETE" => delete(model, tag, body),
        "MKDIR" => mkdir(model, tag, body),
        _ => syntax(tag),
    }
}

fn help(tag: &str) -> Response {
    let mut rows = HELP
        .iter()
        .map(|row| (*row).to_string())
        .collect::<Vec<_>>();
    let final_text = format!("101 {}", rows.pop().expect("FILE help is nonempty"));
    Response {
        tag: tag.to_string(),
        lines: rows,
        final_text,
        status: 101,
    }
}

fn syntax(tag: &str) -> Response {
    failure(tag, 400, "Syntax Error.")
}

fn failure(tag: &str, status: u16, text: &str) -> Response {
    Response {
        tag: tag.to_string(),
        lines: Vec::new(),
        final_text: format!("{status} {text}"),
        status,
    }
}

fn operation_failed(tag: &str, text: impl AsRef<str>) -> Response {
    failure(tag, 408, &format!("Operation failed: {}", text.as_ref()))
}

fn ok(tag: &str) -> Response {
    Response {
        tag: tag.to_string(),
        lines: Vec::new(),
        final_text: "200 OK.".to_string(),
        status: 200,
    }
}

fn status_rows(tag: &str, mut rows: Vec<(u16, String)>) -> Response {
    let (status, final_row) = rows.pop().expect("FILE response has at least one row");
    Response {
        tag: tag.to_string(),
        lines: rows
            .into_iter()
            .map(|(code, row)| {
                if code == status {
                    row
                } else {
                    format!("{code}-{row}")
                }
            })
            .collect(),
        final_text: format!("{status} {final_row}"),
        status,
    }
}

fn upload(model: &mut Server, tag: &str, body: &str, document: Option<&str>) -> Response {
    let args = tokens(&remaining(body, 2));
    let Some(name) = args.first() else {
        return syntax(tag);
    };
    let Some(document) = document else {
        return operation_failed(tag, "no data to upload");
    };
    let path = match controlled_path(model, name) {
        Ok(path) => path,
        Err(error) => return operation_failed(tag, error),
    };
    if path.key.is_empty() || path.key == path.root || directory_exists(model, &dir_key(&path.key))
    {
        return operation_failed(tag, "Is a directory");
    }
    let parent = parent_dir(&path.key, &path.root);
    if !directory_exists(model, &parent) {
        return operation_failed(tag, "No such file or directory");
    }
    let compact = document
        .bytes()
        .filter(|byte| !byte.is_ascii_whitespace())
        .collect::<Vec<_>>();
    let bytes = match STANDARD.decode(compact) {
        Ok(bytes) => bytes,
        Err(base64::DecodeError::InvalidPadding | base64::DecodeError::InvalidLength(_)) => {
            return operation_failed(tag, "Base64 input not properly padded.")
        }
        Err(_) => return operation_failed(tag, "Invalid character in Base64 data."),
    };
    let now = Utc::now().timestamp();
    if let Some(previous) = model.file_store.remove(&path.key) {
        let backup = format!("{}.0", path.key);
        model.file_store.remove(&backup);
        model.file_modified.remove(&backup);
        model.file_store.insert(backup.clone(), previous);
        let previous_modified = model.file_modified.remove(&path.key).unwrap_or(now);
        model.file_modified.insert(backup, previous_modified);
    }
    model.file_store.insert(path.key.clone(), bytes);
    model.file_modified.insert(path.key, now);
    ok(tag)
}

fn download(model: &Server, tag: &str, body: &str) -> Response {
    let args = tokens(&remaining(body, 2));
    if args.len() != 1 {
        return syntax(tag);
    }
    let name = &args[0];
    let path = match controlled_path(model, name) {
        Ok(path) => path,
        Err(error) => return operation_failed(tag, error),
    };
    let Some(bytes) = model
        .file_store
        .get(&path.key)
        .filter(|_| !path.key.ends_with('/'))
    else {
        return operation_failed(
            tag,
            format!("{} (No such file or directory)", virtual_name(&path)),
        );
    };
    let encoded = STANDARD.encode(bytes);
    let mut rows = vec![(
        345,
        format!("Start file download for file: {}", path.requested),
    )];
    rows.extend(
        encoded
            .as_bytes()
            .chunks(76)
            .map(|chunk| (347, String::from_utf8_lossy(chunk).into_owned())),
    );
    rows.push((346, "End file download".to_string()));
    status_rows(tag, rows)
}

fn sha256(model: &Server, tag: &str, body: &str) -> Response {
    let args = tokens(&remaining(body, 2));
    if args.is_empty() {
        return syntax(tag);
    }
    let mut rows = Vec::with_capacity(args.len());
    for name in args {
        match controlled_path(model, &name) {
            Ok(path) => match model
                .file_store
                .get(&path.key)
                .filter(|_| !path.key.ends_with('/'))
            {
                Some(bytes) => rows.push((
                    302,
                    format!(
                        "File={name} SHA256Hash={}",
                        crate::manual::sha256_hex(bytes)
                    ),
                )),
                None => rows.push((408, format!("Operation failed: Can not find file {name}"))),
            },
            Err(error) => rows.push((408, format!("Operation failed: {error}"))),
        }
    }
    status_rows(tag, rows)
}

fn directory(model: &Server, tag: &str, body: &str) -> Response {
    let raw = remaining_dequoted(body, 2);
    let requested = if raw.is_empty() { "." } else { raw.as_str() };
    let path = match controlled_path(model, requested) {
        Ok(path) => path,
        Err(error) => return operation_failed(tag, format!("Unable to read directory: {error}")),
    };
    let directory_key = dir_key(&path.key);
    if !directory_exists(model, &directory_key) {
        return operation_failed(tag, "Not a directory");
    }
    let entries = immediate_entries(model, &directory_key);
    let mut rows = vec![(
        304,
        format!(
            "directory=\"{}\" files={}",
            virtual_directory(&path),
            entries.len()
        ),
    )];
    for (name, entry) in entries {
        let name = if entry.directory {
            format!("{name}/")
        } else {
            name
        };
        rows.push((
            305,
            format!(
                "name=\"{name}\" size={} modified={}",
                entry.size,
                modified_text(entry.modified)
            ),
        ));
    }
    status_rows(tag, rows)
}

fn delete(model: &mut Server, tag: &str, body: &str) -> Response {
    let raw = remaining_dequoted(body, 2);
    let path = match controlled_path(model, &raw) {
        Ok(path) => path,
        Err(error) => {
            return operation_failed(tag, format!("Unable to delete file or directory: {error}"))
        }
    };
    if path.key.is_empty() || path.key == path.root {
        return operation_failed(tag, "Delete failed");
    }
    if model.file_store.remove(&path.key).is_some() {
        model.file_modified.remove(&path.key);
        return ok(tag);
    }
    let directory_key = dir_key(&path.key);
    if !model.file_store.contains_key(&directory_key) {
        return operation_failed(tag, "Does not exist");
    }
    if model
        .file_store
        .keys()
        .any(|key| key != &directory_key && key.starts_with(&directory_key))
    {
        return operation_failed(tag, "Delete failed");
    }
    model.file_store.remove(&directory_key);
    model.file_modified.remove(&directory_key);
    ok(tag)
}

fn mkdir(model: &mut Server, tag: &str, body: &str) -> Response {
    let raw = remaining_dequoted(body, 2);
    let path = match controlled_path(model, &raw) {
        Ok(path) => path,
        Err(error) => return operation_failed(tag, format!("Unable to make directory: {error}")),
    };
    let target = dir_key(&path.key);
    if path.key.is_empty()
        || path.key == path.root
        || model.file_store.contains_key(&path.key)
        || directory_exists(model, &target)
    {
        return operation_failed(tag, "Already exists");
    }
    let now = Utc::now().timestamp();
    for directory in directory_chain(&path.key, &path.root) {
        if model
            .file_store
            .contains_key(directory.trim_end_matches('/'))
        {
            return operation_failed(tag, "Directory create failed");
        }
        model.file_store.entry(directory.clone()).or_default();
        model.file_modified.entry(directory).or_insert(now);
    }
    ok(tag)
}

fn controlled_path(model: &Server, requested: &str) -> Result<ControlledPath, String> {
    if let Some((prefix, remainder)) = requested.split_once('%') {
        if !prefix.is_empty() {
            return Err(format!("Illegal path element in filename {requested}"));
        }
        let Some((project, suffix)) = remainder.split_once('%') else {
            return normalize_base(requested);
        };
        validate_component_source(project, requested)?;
        if !model.projects.contains_key(project) {
            return Err(format!("Illegal path element in filename {requested}"));
        }
        // Native `%PROJECT%/path` resolves the suffix relative to the
        // project's repository parent. Preserve that spelling while keeping
        // cmqttd inside its virtual namespace.
        let suffix = suffix.trim_start_matches(['/', '\\']);
        validate_component_source(suffix, requested)?;
        let relative = normalize_relative(suffix);
        let root = format!("%{project}%/");
        let key = if relative.is_empty() {
            root.clone()
        } else {
            format!("{root}{relative}")
        };
        return Ok(ControlledPath {
            key,
            requested: requested.to_string(),
            root,
        });
    }
    normalize_base(requested)
}

fn normalize_base(requested: &str) -> Result<ControlledPath, String> {
    validate_component_source(requested, requested)?;
    let key = normalize_relative(requested);
    Ok(ControlledPath {
        key,
        requested: requested.to_string(),
        root: String::new(),
    })
}

fn validate_component_source(value: &str, original: &str) -> Result<(), String> {
    if value.starts_with(['/', '\\', '~']) || value.contains("..") || value.contains(':') {
        Err(format!("Illegal path element in filename {original}"))
    } else {
        Ok(())
    }
}

fn normalize_relative(value: &str) -> String {
    value
        .replace('\\', "/")
        .split('/')
        .filter(|component| !component.is_empty() && *component != ".")
        .collect::<Vec<_>>()
        .join("/")
}

fn dir_key(key: &str) -> String {
    if key.is_empty() || key.ends_with('/') {
        key.to_string()
    } else {
        format!("{key}/")
    }
}

fn directory_exists(model: &Server, key: &str) -> bool {
    key.is_empty()
        || (key.starts_with('%')
            && key.ends_with("%/")
            && model.projects.contains_key(key.trim_matches(['%', '/'])))
        || model.file_store.contains_key(key)
}

fn parent_dir(key: &str, root: &str) -> String {
    let relative = key.strip_prefix(root).unwrap_or(key);
    let parent = relative.rsplit_once('/').map_or("", |(parent, _)| parent);
    if parent.is_empty() {
        root.to_string()
    } else {
        format!("{root}{parent}/")
    }
}

fn directory_chain(key: &str, root: &str) -> Vec<String> {
    let relative = key.strip_prefix(root).unwrap_or(key);
    let mut path = root.to_string();
    let mut directories = Vec::new();
    for component in relative
        .split('/')
        .filter(|component| !component.is_empty())
    {
        path.push_str(component);
        path.push('/');
        directories.push(path.clone());
    }
    directories
}

fn immediate_entries(model: &Server, directory: &str) -> BTreeMap<String, DirectoryEntry> {
    let mut rows = BTreeMap::new();
    for (key, bytes) in &model.file_store {
        if directory.is_empty() && key.starts_with('%') {
            continue;
        }
        let Some(relative) = key.strip_prefix(directory) else {
            continue;
        };
        if relative.is_empty() {
            continue;
        }
        let (name, nested) = relative
            .split_once('/')
            .map_or((relative.trim_end_matches('/'), false), |(name, tail)| {
                (name, !tail.is_empty() || key.ends_with('/'))
            });
        if name.is_empty() {
            continue;
        }
        let child_key = format!("{directory}{name}{}", if nested { "/" } else { "" });
        let modified = model.file_modified.get(&child_key).copied().unwrap_or(0);
        rows.entry(name.to_string())
            .and_modify(|entry: &mut DirectoryEntry| entry.directory |= nested)
            .or_insert(DirectoryEntry {
                directory: nested,
                size: if nested { 0 } else { bytes.len() },
                modified,
            });
    }
    rows
}

fn virtual_name(path: &ControlledPath) -> String {
    if path.root.is_empty() {
        format!("cmqttd:/{}", path.key)
    } else {
        let project = path.root.trim_matches(['%', '/']);
        let relative = path.key.strip_prefix(&path.root).unwrap_or(&path.key);
        format!("cmqttd-project://{project}/{relative}")
    }
}

fn virtual_directory(path: &ControlledPath) -> String {
    let name = virtual_name(path);
    if path.key.is_empty() || path.key == path.root {
        name
    } else {
        name.trim_end_matches('/').to_string()
    }
}

fn modified_text(seconds: i64) -> String {
    Local
        .timestamp_opt(seconds, 0)
        .single()
        .unwrap_or_else(Local::now)
        .format("%a %b %d %H:%M:%S %Z %Y")
        .to_string()
}

fn remaining(body: &str, count: usize) -> String {
    let bytes = body.as_bytes();
    let mut offset = 0;
    for _ in 0..count {
        while offset < bytes.len() && bytes[offset].is_ascii_whitespace() {
            offset += 1;
        }
        while offset < bytes.len() && !bytes[offset].is_ascii_whitespace() {
            offset += 1;
        }
    }
    body[offset..].trim().to_string()
}

fn remaining_dequoted(body: &str, count: usize) -> String {
    let raw = remaining(body, count);
    let mut value = String::with_capacity(raw.len());
    let mut chars = raw.chars();
    while let Some(character) = chars.next() {
        match character {
            '"' => {}
            '\\' => match chars.clone().next() {
                Some(next @ ('\\' | '"' | ' ')) => {
                    chars.next();
                    value.push(next);
                }
                _ => value.push('\\'),
            },
            _ => value.push(character),
        }
    }
    value
}

fn tokens(raw: &str) -> Vec<String> {
    let mut values = Vec::new();
    let mut current = String::new();
    let mut quoted = false;
    let mut chars = raw.chars().peekable();
    while let Some(character) = chars.next() {
        match character {
            '"' => quoted = !quoted,
            '\\' if matches!(chars.peek(), Some('\\' | '"' | ' ')) => {
                current.push(chars.next().expect("peeked escape"));
            }
            value if value.is_whitespace() && !quoted => {
                if !current.is_empty() {
                    values.push(std::mem::take(&mut current));
                }
            }
            value => current.push(value),
        }
    }
    if !current.is_empty() {
        values.push(current);
    }
    values
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::AccessLevel;

    #[test]
    fn virtual_family_round_trips_binary_and_keeps_native_backup() {
        let mut server = Server::new(AccessLevel::Program);
        assert_eq!(
            command(&mut server, "1", "FILE MKDIR a/b", None).status,
            200
        );
        assert_eq!(
            command(&mut server, "2", "FILE UPLOAD a/b/x", Some("YWJj\n")).status,
            200
        );
        assert_eq!(
            command(&mut server, "3", "FILE SHA256 a/b/x", None).final_text,
            "302 File=a/b/x SHA256Hash=ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        let downloaded = command(&mut server, "4", "FILE DOWNLOAD a/b/x", None);
        assert_eq!(
            downloaded.lines,
            ["345-Start file download for file: a/b/x", "347-YWJj"]
        );
        assert_eq!(downloaded.final_text, "346 End file download");
        assert_eq!(
            command(&mut server, "5", "FILE UPLOAD a/b/x", Some("ZA==\n")).status,
            200
        );
        assert_eq!(server.file_store["a/b/x.0"], b"abc");
        assert_eq!(server.file_store["a/b/x"], b"d");
    }

    #[test]
    fn path_and_directory_boundaries_are_fail_closed() {
        let mut server = Server::new(AccessLevel::Program);
        for path in ["/x", "../x", "~", "C:x", "x..y"] {
            assert_eq!(
                command(&mut server, "x", &format!("FILE MKDIR {path}"), None).status,
                408,
                "{path}"
            );
        }
        assert_eq!(command(&mut server, "1", "FILE MKDIR d", None).status, 200);
        assert_eq!(
            command(&mut server, "2", "FILE UPLOAD d/f", Some("YQ==")).status,
            200
        );
        assert_eq!(command(&mut server, "3", "FILE DELETE d", None).status, 408);
        assert_eq!(
            command(&mut server, "4", "FILE DELETE d/f", None).status,
            200
        );
        assert_eq!(command(&mut server, "5", "FILE DELETE d", None).status, 200);
    }

    #[test]
    fn project_paths_stay_in_their_virtual_namespace() {
        let mut server = Server::new(AccessLevel::Program);
        server.projects.insert(
            "TEST".to_string(),
            crate::Project {
                name: "TEST".to_string(),
                networks: std::collections::HashMap::new(),
            },
        );
        assert_eq!(
            command(&mut server, "1", "FILE MKDIR %TEST%/exports", None).status,
            200
        );
        assert_eq!(
            command(
                &mut server,
                "2",
                "FILE UPLOAD %TEST%/exports/data.bin",
                Some("AA==")
            )
            .status,
            200
        );
        assert!(server.file_store.contains_key("%TEST%/exports/data.bin"));
        assert_eq!(
            command(&mut server, "3", "FILE MKDIR %MISSING%/exports", None).status,
            408
        );
        assert_eq!(
            command(&mut server, "4", "FILE MKDIR %TEST%/../escape", None).status,
            408
        );
    }
}
