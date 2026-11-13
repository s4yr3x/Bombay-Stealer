#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decrypt_exfil.py - BOMBAY Stealer (stub 1.2.2) exfil-blob decryptor / unpacker.

Reverse-engineered static format (see BOMBAY_STAGE5_MASTER_REPORT.MD, Ph.4):
  upload body : data=<base64(base64( IV(16) || AES-256-CBC(PKCS#7, ASAR) ))>
                POST <backend>?action=upload&type=<t>&unique_id=<id>
                Content-Type: application/x-www-form-urlencoded
                X-License-Key: <license>                      <-- the key source
  AES key     : SHA-256(<X-License-Key value>)               (no salt, no KDF iters)
  IV          : first 16 bytes of the de-base64'd blob       (BCryptGenRandom)
  plaintext   : Electron-style ASAR archive written by pack_pkg_to_buffer
                (rename.exe @ 0x1400AAD40):
                [u32 json_size_field==4][u32 total][u32 payload_sz]
                [u32 json_len][PkgMeta JSON][pad-to-4][raw file blobs]

Default license key is the one burned into this build's .data at RVA 0x311048
("C307-ABE1-D50C-B96A" + 'X' padding, trimmed by get_license_key 0x140042670).

Usage:
  py -3.11 decrypt_exfil.py capture.txt                 # file w/ 'data=...' body
  py -3.11 decrypt_exfil.py -b <base64 blob>            # raw blob
  py -3.11 decrypt_exfil.py blob.b64 -k DEADBEEF...     # AES key as hex
  py -3.11 decrypt_exfil.py blob.b64 --license OTHER-KEY
  py -3.11 decrypt_exfil.py --selftest                  # synthetic round-trip

Analysis tooling only - operates on captured exfil data, never contacts hosts.
"""
import argparse
import base64
import hashlib
import json
import os
import struct
import sys
import urllib.parse

DEFAULT_LICENSE = "C307-ABE1-D50C-B96A"   # 0x140311048, this build
HEADER_LEN = 16                            # 4 x u32 preamble


# ---------------------------------------------------------------- AES backend
def _aes_cbc_decrypt(key: bytes, iv: bytes, ct: bytes) -> bytes:
    """AES-256-CBC via PyCryptodome or cryptography, whichever is installed."""
    try:
        from Crypto.Cipher import AES                      # pycryptodome
        return AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
    except ImportError:
        pass
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        return dec.update(ct) + dec.finalize()
    except ImportError:
        sys.exit("[-] no AES backend: install 'pycryptodome' or 'cryptography'")


def pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("empty plaintext")
    n = data[-1]
    if not 1 <= n <= 16 or data[-n:] != bytes([n]) * n:
        raise ValueError("bad PKCS#7 padding (wrong key/IV?)")
    return data[:-n]


# ------------------------------------------------------------ blob pre-unwrap
def strip_data_param(text: str) -> str:
    """Accept a full POST body / URL; keep only the data= value (URL-decoded)."""
    if "data=" in text:
        qs = urllib.parse.parse_qs(text.strip(), keep_blank_values=True)
        if "data" in qs:
            return qs["data"][0]
    return text.strip()


def unwrap_base64(blob: str, max_passes: int = 4) -> bytes:
    """The packer base64-encodes twice (cryptapi_base64_encode, 2 passes).
    Decode repeatedly until the result stops looking like base64."""
    raw = blob.encode("ascii", "ignore")
    passes = 0
    while passes < max_passes:
        # tolerate missing padding
        pad = (-len(raw)) % 4
        try:
            nxt = base64.b64decode(raw + b"=" * pad, validate=False)
        except Exception:
            break
        # stop if decoding did nothing productive / result is binary (non-b64)
        if nxt == raw or len(nxt) < 16:
            raw, passes = nxt, passes + 1
            break
        printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in nxt) / len(nxt)
        raw, passes = nxt, passes + 1
        if printable < 0.98:            # hit binary (IV||CT) - done
            break
    return raw


# ----------------------------------------------------------------- decryptor
def decrypt_exfil(b64_blob: str, license_key: str = DEFAULT_LICENSE,
                  aes_key: bytes = None) -> bytes:
    """base64(...) -> IV||AES-CBC -> ASAR bytes. Raises on structural errors.
    Accepts a bare base64 blob or a full 'data=...' parameter body."""
    raw = unwrap_base64(strip_data_param(b64_blob))
    if len(raw) < HEADER_LEN + 16:
        raise ValueError(f"blob too small after unwrap ({len(raw)} bytes)")
    iv, ct = raw[:16], raw[16:]
    key = aes_key if aes_key else hashlib.sha256(license_key.encode()).digest()
    return pkcs7_unpad(_aes_cbc_decrypt(key, iv, ct))


# ------------------------------------------------------------- ASAR unpacker
def parse_asar(archive: bytes):
    """Validate the pack_pkg_to_buffer preamble; return (meta_json, blobs)."""
    if len(archive) < HEADER_LEN:
        raise ValueError("ASAR: truncated")
    json_size_field, total, payload_sz, json_len = struct.unpack("<IIII", archive[:HEADER_LEN])
    if json_size_field != 4:
        raise ValueError(f"ASAR: bad preamble dword0={json_size_field} (want 4) - "
                         "wrong key or not a BOMBAY package")
    if json_len == 0 or HEADER_LEN + json_len > len(archive):
        raise ValueError(f"ASAR: bad json_len={json_len}")
    pad = (-json_len) & 3
    js = archive[HEADER_LEN:HEADER_LEN + json_len].decode("utf-8", "replace")
    blobs = archive[HEADER_LEN + json_len + pad:]
    meta = json.loads(js)
    return meta, blobs, (total, payload_sz, pad)


def carve_files(node, blobs: bytes, base_dir: str, prefix: str = ""):
    """Electron-ASAR style file table: nodes carrying offset/size get carved.
    BOMBAY's PkgMeta stores names->data via FNV-1a-64; the JSON table (when
    present) still names/offsets files - we carve anything with offset+size."""
    count = 0
    if isinstance(node, dict):
        if "offset" in node and "size" in node and "files" not in node:
            try:
                off = int(node["offset"]); size = int(node["size"])
                data = blobs[off:off + size]
                out = os.path.join(base_dir, prefix.replace("/", os.sep))
                os.makedirs(os.path.dirname(out) or base_dir, exist_ok=True)
                with open(out, "wb") as f:
                    f.write(data)
                print(f"    + {prefix}  ({size} bytes)")
                return 1
            except (ValueError, OSError) as e:
                print(f"    ! carve failed for {prefix}: {e}")
                return 0
        for name, child in node.items():
            count += carve_files(child, blobs, base_dir,
                                 f"{prefix}/{name}" if prefix else name)
    elif isinstance(node, list):
        for i, child in enumerate(node):
            count += carve_files(child, blobs, base_dir, f"{prefix}[{i}]")
    return count


# -------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="BOMBAY stealer exfil decryptor (static RE)")
    ap.add_argument("input", nargs="?", help="file containing the data= param, "
                                             "base64 blob, or raw encrypted blob")
    ap.add_argument("-b", "--blob", help="base64 blob directly from argv")
    ap.add_argument("--license", default=DEFAULT_LICENSE,
                    help=f"license key (default: this build's {DEFAULT_LICENSE})")
    ap.add_argument("-k", "--key-hex", help="raw AES-256 key as hex (overrides license)")
    ap.add_argument("-o", "--outdir", help="directory for extracted loot")
    ap.add_argument("--raw", action="store_true", help="stop after AES, just write .asar")
    ap.add_argument("--selftest", action="store_true", help="synthetic round-trip test")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    text = args.blob
    if not text:
        if not args.input or not os.path.isfile(args.input):
            ap.error("provide an input file or -b blob")
        text = open(args.input, "r", encoding="utf-8", errors="replace").read()
    text = strip_data_param(text)
    key = bytes.fromhex(args.key_hex) if args.key_hex else None

    print(f"[*] license : {args.license}" if not key else "[*] key     : (raw hex)")
    asar = decrypt_exfil(text, args.license, key)
    print(f"[+] decrypted ASAR: {len(asar)} bytes")

    meta, blobs, (total, payload_sz, pad) = parse_asar(asar)
    print(f"[+] preamble : total={total} payload={payload_sz} "
          f"json_len={len(json.dumps(meta))} pad={pad} blobs={len(blobs)} bytes")
    print("[+] PkgMeta  :")
    print(json.dumps(meta, indent=2)[:4000])

    outdir = args.outdir or (args.input + ".extracted" if args.input else "exfil_extracted")
    os.makedirs(outdir, exist_ok=True)
    asar_path = os.path.join(outdir, "package.asar")
    with open(asar_path, "wb") as f:
        f.write(asar)
    print(f"[+] archive  : {asar_path}")
    if args.raw:
        return 0
    n = carve_files(meta, blobs, outdir)
    print(f"[+] carved {n} file(s) into {outdir}" + os.sep)
    if n == 0 and blobs:
        blob_path = os.path.join(outdir, "blobs.bin")
        with open(blob_path, "wb") as f:
            f.write(blobs)
        print(f"[-] no offset/size table found - raw blob tail written to {blob_path}")
    return 0


def selftest() -> int:
    """Encrypt a synthetic package the way encrypt_payload does, then decrypt."""
    meta = {"stub_version": "1.2.2", "files": {"a.txt": {"offset": 0, "size": 5}}}
    js = json.dumps(meta)
    pad = (-len(js)) & 3
    payload = len(js) + pad + 4
    asar = struct.pack("<IIII", 4, payload + 4, payload, len(js))
    asar += js.encode() + b"\x00" * pad + b"HELLO"
    try:
        from Crypto.Cipher import AES                      # pycryptodome
        key = hashlib.sha256(DEFAULT_LICENSE.encode()).digest()
        iv = bytes(range(16))
        pt_pad = (-len(asar)) % 16 or 16          # PKCS#7: value == count
        pt = asar + bytes([pt_pad]) * pt_pad
        ct = AES.new(key, AES.MODE_CBC, iv).encrypt(pt)
    except ImportError:
        print("[!] selftest needs pycryptodome; skipping crypto leg")
        return 0
    blob = base64.b64encode(base64.b64encode(iv + ct)).decode()
    out = decrypt_exfil("data=" + urllib.parse.quote(blob))
    ok = out == asar and parse_asar(out)[0] == meta
    print(f"[selftest] {'PASS' if ok else 'FAIL'} "
          f"(double-b64 unwrap, SHA-256 license key, IV-prefix, PKCS#7, ASAR parse)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
