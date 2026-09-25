//! Optional cmqttd-local shared-secret gate for the embedded C-Gate
//! service (auth first-slice; loopback tests only).
//!
//! This is explicitly **not** native `access.txt` parity: no native LOGIN
//! captures exist, so native LOGIN/LOGOUT status codes and semantics are
//! unknown and nothing here claims them.
//!
//! File framing: the auth file is a **high-entropy token file, not a
//! password file**. Only SHA-256-family primitives are guaranteed present
//! in the offline build (no `argon2`/`scrypt`/`bcrypt` crate is vendored,
//! and this slice adds no network dependencies), so a memory-hard password
//! hash is unavailable. The operator provisions a long random token (first
//! line of the file, e.g. 32+ random bytes rendered as hex), the loader
//! hashes it once at startup with SHA-256, and the service compares only
//! digests in constant time. A fast hash is acceptable for a
//! high-entropy token and is **not** acceptable for a human password:
//! upgrading to `argon2` (with a versioned file format) is recorded
//! follow-up work for any password-oriented use.
//!
//! Single-token rule: the token must be a single whitespace-free token.
//! LOGIN splits the command line on ASCII whitespace, so a token containing
//! whitespace could never be presented; the loader rejects such files
//! fail-closed instead of arming a gate the operator can never open.
//!
//! Rate limiting: the service compares in constant time, never logs or
//! echoes the secret, and counts consecutive per-connection failures
//! (`ClientState::login_attempts`, saturating). No attempt cap or
//! connection drop is enforced in this slice: `Service::handle` has no
//! connection-close channel and adding one exceeds the slice. The
//! deployment constraint (loopback bind, high-entropy token) makes online
//! guessing infeasible; a cap is follow-up work.

use std::io;
use std::path::Path;

/// SHA-256 digest of `data` (FIPS 180-4). Pure-std implementation so this
/// slice adds no dependencies; verified against NIST vectors in-test.
pub fn sha256(data: &[u8]) -> [u8; 32] {
    // Initial hash values (first 32 bits of the fractional parts of the
    // square roots of the first eight primes).
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    // Round constants (first 32 bits of the fractional parts of the cube
    // roots of the first sixty-four primes).
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];

    // Padding: 0x80, zero bytes, then the 64-bit big-endian bit length.
    // The padded length is always a multiple of 64 bytes.
    let bit_len = (data.len() as u64).wrapping_mul(8);
    let mut padded = Vec::with_capacity(data.len().wrapping_add(1).wrapping_add(64));
    padded.extend_from_slice(data);
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&bit_len.to_be_bytes());

    let mut w = [0u32; 64];
    for block in padded.as_slice().as_chunks::<64>().0 {
        for (i, word) in w.iter_mut().enumerate().take(16) {
            let o = i * 4;
            *word = u32::from_be_bytes([block[o], block[o + 1], block[o + 2], block[o + 3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let (mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh) =
            (h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]);
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }

    let mut out = [0u8; 32];
    for (i, word) in h.iter().enumerate() {
        out[i * 4..i * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    out
}

/// Constant-time equality for token digests: no early exit, no secret-
/// dependent branches. Hand-rolled so this slice adds no dependencies.
#[must_use]
pub fn constant_time_eq(a: &[u8; 32], b: &[u8; 32]) -> bool {
    let mut diff: u8 = 0;
    for i in 0..32 {
        diff |= a[i] ^ b[i];
    }
    // `u8 == 0` compiles to a single comparison, not a branch on secret data.
    diff == 0
}

/// Minimum accepted token length in characters (32; `str::len()` counts
/// bytes, and any whitespace-free characters are accepted — 32 characters
/// hold 128 bits when rendered as hex). Framed as a placeholder floor
/// rather than a reviewed strength target; do not lower it. The file holds
/// a high-entropy token, not a password; short values are rejected
/// fail-closed so a placeholder can never arm the gate.
/// Generate with e.g. `python3 -c "import secrets;
/// print(secrets.token_hex(32))"` (64 hex chars) and store with mode 0400.
pub const MIN_TOKEN_LEN: usize = 32;

/// Load the C-Gate LOGIN token file and return the SHA-256 digest of the
/// token. Only the first line is significant (trailing newline ignored);
/// the raw token is never retained, logged, or echoed.
///
/// Fail-closed: a missing/unreadable/empty file, a token shorter than
/// [`MIN_TOKEN_LEN`], or (on unix) any group/other access bit on the file
/// is an error. Expected permissions are `0400` (or `0600`); the mode
/// itself is not rewritten.
pub fn load_token_hash(path: &Path) -> io::Result<[u8; 32]> {
    // Permissions first: fail closed on group/other access before the
    // secret bytes are ever read.
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let mode = std::fs::metadata(path)?.mode();
        if mode & 0o077 != 0 {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                format!(
                    "C-Gate auth file {} must not be accessible by group/other (use 0400 or 0600)",
                    path.display()
                ),
            ));
        }
    }
    let data = std::fs::read(path)?;
    let text = String::from_utf8(data)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "C-Gate auth file is not UTF-8"))?;
    let token = text.lines().next().unwrap_or("").trim();
    if token.is_empty() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "C-Gate auth file holds no token on its first line",
        ));
    }
    // LOGIN splits the command line on ASCII whitespace, so a token
    // containing whitespace could never be presented (arity would never be
    // 2). Reject it at load: otherwise the operator provisions a token that
    // permanently cannot open the gate.
    if token.as_bytes().iter().any(u8::is_ascii_whitespace) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "C-Gate auth token must be a single whitespace-free token (LOGIN takes one token)",
        ));
    }
    if token.len() < MIN_TOKEN_LEN {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            format!(
                "C-Gate auth token is shorter than {MIN_TOKEN_LEN} characters; \
                 provision a high-entropy token (use 32+ random bytes, hex-encoded), not a password"
            ),
        ));
    }
    Ok(sha256(token.as_bytes()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(digest: &[u8; 32]) -> String {
        digest.iter().map(|b| format!("{b:02x}")).collect()
    }

    #[test]
    fn sha256_matches_nist_vectors() {
        // FIPS 180-4 / NIST test vectors.
        assert_eq!(
            hex(&sha256(b"")),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            hex(&sha256(b"abc")),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(
            hex(&sha256(
                b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
            )),
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
        );
        // Multi-block input (112 bytes) exercises the second compression.
        assert_eq!(
            hex(&sha256(b"abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu")),
            "cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1"
        );
        // SHA-256 padding-boundary lengths: 55 bytes (last length that pads
        // into one block) and 64 bytes (first length needing a second
        // padding block). Expected digests computed with `python3 -c
        // "import hashlib; print(hashlib.sha256(<bytes>).hexdigest())"`,
        // never hand-computed.
        assert_eq!(
            b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnop".len(),
            55,
            "55-byte fixture must sit exactly on the one-block padding boundary"
        );
        assert_eq!(
            b"abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijkl".len(),
            64,
            "64-byte fixture must sit exactly on the two-block padding boundary"
        );
        assert_eq!(
            hex(&sha256(
                b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnop"
            )),
            "aa353e009edbaebfc6e494c8d847696896cb8b398e0173a4b5c1b636292d87c7"
        );
        assert_eq!(
            hex(&sha256(
                b"abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijkl"
            )),
            "2fcd5a0d60e4c941381fcc4e00a4bf8be422c3ddfafb93c809e8d1e2bfffae8e"
        );
    }

    #[test]
    fn constant_time_eq_compares_full_digests() {
        let a = sha256(b"token-a");
        let b = sha256(b"token-a");
        let c = sha256(b"token-b");
        assert!(constant_time_eq(&a, &b));
        assert!(!constant_time_eq(&a, &c));
        // Differing only in the last byte still compares unequal.
        let mut d = a;
        d[31] ^= 0x01;
        assert!(!constant_time_eq(&a, &d));
    }

    #[cfg(unix)]
    fn token_file(contents: &str, mode: u32) -> std::path::PathBuf {
        use std::os::unix::fs::PermissionsExt;
        static ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "cgate-auth-test-{}-{}.token",
            std::process::id(),
            ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        std::fs::write(&path, contents).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode)).unwrap();
        path
    }

    #[cfg(unix)]
    #[test]
    fn loader_accepts_locked_down_token_file() {
        let path = token_file("throwaway-test-token-0123456789abcdef\n", 0o400);
        let hash = load_token_hash(&path).expect("0400 token file loads");
        assert_eq!(hash, sha256(b"throwaway-test-token-0123456789abcdef"));
        // Only the first line is significant; the trailing newline is not
        // part of the token.
        std::fs::remove_file(path).ok();
    }

    #[cfg(unix)]
    #[test]
    fn loader_rejects_group_readable_token_file() {
        let path = token_file("throwaway-test-token-0123456789abcdef\n", 0o640);
        let err = load_token_hash(&path).expect_err("0640 token file must fail closed");
        assert_eq!(err.kind(), io::ErrorKind::PermissionDenied);
        std::fs::remove_file(path).ok();
    }

    #[cfg(unix)]
    #[test]
    fn loader_rejects_empty_and_short_tokens() {
        let empty = token_file("\n", 0o400);
        assert!(load_token_hash(&empty).is_err());
        std::fs::remove_file(empty).ok();
        let short = token_file("tiny\n", 0o400);
        let err = load_token_hash(&short).expect_err("short token must fail closed");
        assert_eq!(err.kind(), io::ErrorKind::InvalidData);
        std::fs::remove_file(short).ok();
        // 31 chars is still below the 32-char (128-bit hex) minimum.
        let boundary = token_file("throwaway-boundary-token-abcdef\n", 0o400);
        assert_eq!(
            "throwaway-boundary-token-abcdef".len(),
            31,
            "test fixture must sit exactly below the minimum"
        );
        assert!(load_token_hash(&boundary).is_err());
        std::fs::remove_file(boundary).ok();
    }

    #[cfg(unix)]
    #[test]
    fn loader_rejects_whitespace_token_it_could_never_present() {
        // LOGIN splits on ASCII whitespace, so this token could never open
        // the gate: fail closed at load instead of locking out the operator.
        let spaced = token_file("throwaway token with spaces 0123456789\n", 0o400);
        let err = load_token_hash(&spaced).expect_err("whitespace token must fail closed");
        assert_eq!(err.kind(), io::ErrorKind::InvalidData);
        std::fs::remove_file(spaced).ok();
    }

    #[test]
    fn loader_rejects_missing_file() {
        let missing = std::env::temp_dir().join(format!(
            "cgate-auth-missing-{}-{}.token",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        assert!(load_token_hash(&missing).is_err());
    }
}
