
import argparse
import base64
import getpass
import hashlib
import os
from pathlib import Path
import sqlite3

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from src.log_messages import error as error_messages
from src.repo.queries import load_query


MAGIC = b"WTRACKER1"
SALT_BYTES = 16


def key_for(passphrase: str, salt: bytes) -> bytes:
    if not passphrase:
        raise ValueError(error_messages.PASSPHRASE_MUST_NOT_BE_EMPTY)
    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def create_backup(
    source_db: str | Path, output_file: str | Path, passphrase: str,
) -> str:
    source = Path(source_db)
    if not source.is_file():
        raise FileNotFoundError(source)
    salt = os.urandom(SALT_BYTES)
    encrypted = Fernet(key_for(passphrase, salt)).encrypt(source.read_bytes())
    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    backup_bytes = MAGIC + salt + encrypted
    output.write_bytes(backup_bytes)
    return hashlib.sha256(backup_bytes).hexdigest()


def restore_backup(
    backup_file: str | Path, destination_db: str | Path, passphrase: str,
) -> str:
    blob = Path(backup_file).read_bytes()
    raw = _decrypt_backup(blob, passphrase)
    _restore_database(raw, Path(destination_db))
    return hashlib.sha256(raw).hexdigest()


def _decrypt_backup(blob: bytes, passphrase: str) -> bytes:
    payload_offset = len(MAGIC) + SALT_BYTES
    if not blob.startswith(MAGIC) or len(blob) <= payload_offset:
        raise ValueError(error_messages.UNRECOGNISED_BACKUP_FORMAT)
    salt = blob[len(MAGIC):payload_offset]
    try:
        return Fernet(key_for(passphrase, salt)).decrypt(blob[payload_offset:])
    except (InvalidToken, ValueError) as exc:
        raise ValueError(error_messages.WRONG_PASSPHRASE_OR_DAMAGED_BACKUP) from exc


def _restore_database(raw: bytes, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_suffix(destination.suffix + ".tmp")
    try:
        staging.write_bytes(raw)
        _check_database_integrity(staging)
        staging.replace(destination)
    finally:
        staging.unlink(missing_ok=True)


def _check_database_integrity(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        if connection.execute(load_query("check_database_integrity")).fetchone()[0] != "ok":
            raise ValueError(error_messages.DATABASE_INTEGRITY_CHECK_FAILED)
    finally:
        connection.close()


def main() -> None:
    args = _parse_arguments()
    password = getpass.getpass("Backup passphrase: ")
    if args.cmd == "create":
        print("Encrypted backup SHA-256:", create_backup(args.source_db, args.output_file, password))
    else:
        print(
            "Restored and integrity-checked SHA-256:",
            restore_backup(args.backup_file, args.destination_db, password),
        )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    create_parser = sub.add_parser("create")
    create_parser.add_argument("source_db")
    create_parser.add_argument("output_file")
    restore_parser = sub.add_parser("restore")
    restore_parser.add_argument("backup_file")
    restore_parser.add_argument("destination_db")
    return parser.parse_args()


if __name__ == "__main__":
    main()
