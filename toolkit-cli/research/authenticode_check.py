#!/usr/bin/env python3
"""Check embedded Authenticode signatures of pinned installers without executing them.

For each PE file this recomputes the Authenticode image digest, compares it to
the signed SpcIndirectDataContent, checks the PKCS#9 messageDigest, verifies
the signer's signature over the authenticated attributes, and verifies each
certificate link up to a certificate issued by a root in the macOS system root
keychain. It prints only publisher subjects, digests and outcomes.

This is a cryptographic consistency check, not Windows policy: it does not
evaluate revocation, code-signing EKU/policy, certificate validity at the
countersigned timestamp, or nested secondary signatures. Windows ``signtool
verify /pa /all`` remains the policy-grade verifier.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import warnings

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa


FORMAT = "cbus-authenticode-consistency-v1"
ROOT_KEYCHAIN = "/System/Library/Keychains/SystemRootCertificates.keychain"
OID_SIGNED_DATA = "1.2.840.113549.1.7.2"
OID_SPC_INDIRECT = "1.3.6.1.4.1.311.2.1.4"
OID_MESSAGE_DIGEST = "1.2.840.113549.1.9.4"
DIGESTS = {
    "1.3.14.3.2.26": (hashlib.sha1, hashes.SHA1),
    "2.16.840.1.101.3.4.2.1": (hashlib.sha256, hashes.SHA256),
    "2.16.840.1.101.3.4.2.2": (hashlib.sha384, hashes.SHA384),
    "2.16.840.1.101.3.4.2.3": (hashlib.sha512, hashes.SHA512),
}


class SignatureError(ValueError):
    pass


def _tlv(data: bytes, offset: int = 0) -> tuple[int, int, int, int]:
    """Return (tag, content start, content end, element end) for one DER element."""
    if offset + 2 > len(data):
        raise SignatureError("Truncated DER element")
    tag = data[offset]
    length = data[offset + 1]
    start = offset + 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 4 or start + count > len(data):
            raise SignatureError("Unsupported DER length")
        length = int.from_bytes(data[start:start + count], "big")
        start += count
    end = start + length
    if end > len(data):
        raise SignatureError("Truncated DER element")
    return tag, start, end, end


def _children(data: bytes, start: int, end: int) -> list[tuple[int, int, int, int]]:
    items = []
    while start < end:
        item = _tlv(data, start)
        items.append((item[0], start, item[1], item[2]))
        start = item[3]
    return items


def _oid(data: bytes, start: int, end: int) -> str:
    raw = data[start:end]
    if not raw:
        raise SignatureError("Empty OID")
    parts = [raw[0] // 40, raw[0] % 40]
    value = 0
    for byte in raw[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(value)
            value = 0
    return ".".join(map(str, parts))


def _signature_blob(pe: bytes) -> tuple[bytes, list[tuple[int, int]]]:
    """Return the PKCS#7 blob and the byte ranges covered by the image digest."""
    if pe[:2] != b"MZ":
        raise SignatureError("Not a PE image")
    header = struct.unpack_from("<I", pe, 0x3C)[0]
    if pe[header:header + 4] != b"PE\0\0":
        raise SignatureError("Not a PE image")
    optional = header + 24
    magic = struct.unpack_from("<H", pe, optional)[0]
    directories = optional + (96 if magic == 0x10B else 112 if magic == 0x20B else -1)
    if directories < optional:
        raise SignatureError("Unsupported PE optional header")
    checksum = optional + 64
    security = directories + 4 * 8
    table, size = struct.unpack_from("<II", pe, security)
    if not table or not size or table + size > len(pe):
        raise SignatureError("PE has no embedded Authenticode signature")
    length, revision, kind = struct.unpack_from("<IHH", pe, table)
    if kind != 2 or length < 8 or length > size:
        raise SignatureError("Unsupported WIN_CERTIFICATE entry")
    ranges = [(0, checksum), (checksum + 4, security), (security + 8, table), (table + size, len(pe))]
    return pe[table + 8:table + length], ranges


def _macos_roots() -> list[x509.Certificate]:
    result = subprocess.run(["security", "find-certificate", "-a", "-p", ROOT_KEYCHAIN],
                            capture_output=True, check=False)
    if result.returncode or not result.stdout:
        raise SignatureError("Cannot read the macOS system root keychain")
    with warnings.catch_warnings():
        # Some legacy system roots carry non-positive serial numbers.
        warnings.simplefilter("ignore")
        return x509.load_pem_x509_certificates(result.stdout)


def _verify_signature(certificate: x509.Certificate, signature: bytes, data: bytes, digest) -> None:
    key = certificate.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        key.verify(signature, data, padding.PKCS1v15(), digest())
    elif isinstance(key, ec.EllipticCurvePublicKey):
        key.verify(signature, data, ec.ECDSA(digest()))
    else:
        raise SignatureError("Unsupported signer key type")


def check(path: Path, roots: list[x509.Certificate]) -> dict[str, object]:
    pe = path.read_bytes()
    blob, ranges = _signature_blob(pe)
    _tag, start, end, _ = _tlv(blob)
    content_type, content = _children(blob, start, end)[:2]
    if _oid(blob, content_type[2], content_type[3]) != OID_SIGNED_DATA:
        raise SignatureError("Signature is not PKCS#7 SignedData")
    signed = _tlv(blob, content[2])
    fields = _children(blob, signed[1], signed[2])
    encapsulated = fields[2]
    encap_fields = _children(blob, encapsulated[2], encapsulated[3])
    if _oid(blob, encap_fields[0][2], encap_fields[0][3]) != OID_SPC_INDIRECT:
        raise SignatureError("Signed content is not SpcIndirectDataContent")
    indirect = _tlv(blob, encap_fields[1][2])
    indirect_start, indirect_end = indirect[1], indirect[2]
    spc = _children(blob, indirect_start, indirect_end)
    digest_info = _children(blob, spc[1][2], spc[1][3])
    algorithm = _children(blob, digest_info[0][2], digest_info[0][3])
    image_algorithm = _oid(blob, algorithm[0][2], algorithm[0][3])
    signed_image_digest = blob[digest_info[1][2]:digest_info[1][3]]
    if image_algorithm not in DIGESTS:
        raise SignatureError("Unsupported image digest algorithm")
    image = DIGESTS[image_algorithm][0]()
    for low, high in ranges:
        image.update(pe[low:high])
    image_matches = image.digest() == signed_image_digest

    certificates_field = next(item for item in fields if item[0] == 0xA0)
    bag = [x509.load_der_x509_certificate(blob[item[1]:item[3]])
           for item in _children(blob, certificates_field[2], certificates_field[3])]
    signer_infos = fields[-1]
    signers = _children(blob, signer_infos[2], signer_infos[3])
    if len(signers) != 1:
        raise SignatureError("Expected exactly one primary signer")
    signer = _children(blob, signers[0][2], signers[0][3])
    serial_der = _children(blob, signer[1][2], signer[1][3])[1]
    serial = int.from_bytes(blob[serial_der[2]:serial_der[3]], "big", signed=True)
    certificate = next((item for item in bag if item.serial_number == serial), None)
    if certificate is None:
        raise SignatureError("Signer certificate is not embedded")
    signer_digest = _oid(blob, *_children(blob, signer[2][2], signer[2][3])[0][2:4])
    attributes = signer[3]
    if attributes[0] != 0xA0:
        raise SignatureError("Signer has no authenticated attributes")
    message_digest = None
    for attribute in _children(blob, attributes[2], attributes[3]):
        parts = _children(blob, attribute[2], attribute[3])
        if _oid(blob, parts[0][2], parts[0][3]) == OID_MESSAGE_DIGEST:
            value = _children(blob, parts[1][2], parts[1][3])[0]
            message_digest = blob[value[2]:value[3]]
    hasher, digest = DIGESTS[signer_digest]
    content_matches = message_digest == hasher(blob[indirect_start:indirect_end]).digest()
    authenticated = b"\x31" + blob[attributes[1] + 1:attributes[3]]
    signature_field = signer[5]
    try:
        _verify_signature(certificate, blob[signature_field[2]:signature_field[3]], authenticated, digest)
        signature_valid = True
    except InvalidSignature:
        signature_valid = False

    chain = [certificate]
    anchored = False
    while len(chain) < 8:
        current = chain[-1]
        root = next((item for item in roots if item.subject == current.issuer), None)
        if root is not None:
            current.verify_directly_issued_by(root)
            anchored = True
            break
        issuer = next((item for item in bag if item.subject == current.issuer and item != current), None)
        if issuer is None:
            break
        current.verify_directly_issued_by(issuer)
        chain.append(issuer)
    return {
        "sha256": hashlib.sha256(pe).hexdigest(),
        "image_digest_matches": image_matches,
        "content_digest_matches": content_matches,
        "signature_valid": signature_valid,
        "chain_anchored_in_macos_roots": anchored,
        "signer": certificate.subject.rfc4514_string(),
        "signer_not_after": certificate.not_valid_after_utc.isoformat(),
        "chain_sha256": [item.fingerprint(hashes.SHA256()).hex() for item in chain],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pe", nargs="+", type=Path)
    args = parser.parse_args(argv)
    roots = _macos_roots()
    results, failed = [], False
    for path in args.pe:
        try:
            result = {"name": path.name, **check(path, roots)}
        except (SignatureError, ValueError, InvalidSignature, StopIteration, IndexError, KeyError) as error:
            result = {"name": path.name, "error": str(error) or type(error).__name__}
        ok = all(result.get(key) is True for key in (
            "image_digest_matches", "content_digest_matches", "signature_valid",
            "chain_anchored_in_macos_roots"))
        failed |= not ok
        results.append({**result, "consistent": ok})
    print(json.dumps({"format": FORMAT, "results": results}, indent=2))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
