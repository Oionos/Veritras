"""Stream encrypted recovery archives. Never upload plaintext production backups."""

import argparse
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"VRREC01\n"


def key_bytes(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("A private 32-byte hex archive key is required")
    return bytes.fromhex(value)


def encrypt_files(files, destination, key, metadata):
    secret = key_bytes(key)
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > 4096 or not files:
        raise ValueError("Invalid archive metadata or file set")
    header = MAGIC + len(encoded).to_bytes(4, "big") + encoded + os.urandom(12)
    encryptor = Cipher(algorithms.AES(secret), modes.GCM(header[-12:])).encryptor()
    encryptor.authenticate_additional_data(header)
    destination = Path(destination)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(header)

            class Writer:
                def write(self, value):
                    output.write(encryptor.update(value))
                    return len(value)

            names = set()
            with tarfile.open(mode="w|", fileobj=Writer()) as archive:
                for name, path in files:
                    path = Path(path)
                    if (
                        not re.fullmatch(r"[a-zA-Z0-9_./-]+", name)
                        or name.startswith("/")
                        or ".." in name.split("/")
                        or name in names
                        or path.is_symlink()
                        or not path.is_file()
                    ):
                        raise ValueError("Invalid evidence file")
                    names.add(name)
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = path.stat().st_size, 0o600
                    with path.open("rb") as source:
                        archive.addfile(info, source)
            output.write(encryptor.finalize())
            output.write(encryptor.tag)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def decrypt_archive(source, destination, key):
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Output already exists")
    fd, temporary = tempfile.mkstemp(
        prefix=".recovery-decrypt-", dir=destination.parent
    )
    try:
        with os.fdopen(fd, "wb") as output, open(source, "rb") as encrypted:
            magic = encrypted.read(len(MAGIC))
            size_bytes = encrypted.read(4)
            size = int.from_bytes(size_bytes, "big")
            if magic != MAGIC or len(size_bytes) != 4 or not 1 <= size <= 4096:
                raise ValueError("Invalid archive header")
            encoded, nonce = encrypted.read(size), encrypted.read(12)
            header = magic + size_bytes + encoded + nonce
            remaining = os.fstat(encrypted.fileno()).st_size - len(header) - 16
            if len(encoded) != size or len(nonce) != 12 or remaining < 0:
                raise ValueError("Invalid archive length")
            encrypted.seek(-16, os.SEEK_END)
            tag = encrypted.read(16)
            encrypted.seek(len(header))
            decryptor = Cipher(
                algorithms.AES(key_bytes(key)), modes.GCM(nonce, tag)
            ).decryptor()
            decryptor.authenticate_additional_data(header)
            while remaining:
                chunk = encrypted.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("Truncated archive")
                output.write(decryptor.update(chunk))
                remaining -= len(chunk)
            output.write(
                decryptor.finalize()
            )  # Authenticate BEFORE publishing plaintext.
        metadata = json.loads(encoded)
        os.link(
            temporary, destination
        )  # Atomic refusal to overwrite an existing output.
        return metadata
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decrypt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        decrypt_archive(
            args.decrypt, args.output, os.environ.get("REHEARSAL_BACKUP_KEY")
        )
    except Exception:
        print(
            json.dumps(
                {"decrypted": False, "state": "archive_invalid_or_output_unavailable"}
            )
        )
        return 1
    print(json.dumps({"decrypted": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
