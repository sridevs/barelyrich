import hashlib
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from src import backup
from src.backup import create_backup, key_for, restore_backup
from src.repo.db import initialise


@pytest.fixture
def encrypted(tmp_path, db_path):
    encrypted = tmp_path / "backup.enc"
    create_backup(db_path, encrypted, "test passphrase")
    return encrypted


@pytest.fixture
def destination(tmp_path):
    destination = tmp_path / "existing.db"
    destination.write_bytes(b"original")
    return destination


def assert_preserved(destination):
    assert destination.read_bytes() == b"original"
    assert not destination.with_suffix(".db.tmp").exists()


def test_round_trip(tmp_path):
    src, enc, dest = tmp_path/"src.db", tmp_path/"backup.enc", tmp_path/"restored.db"
    initialise(src)
    with sqlite3.connect(src) as connection:
        connection.execute("INSERT INTO accounts(name,institution,country_code,account_type,currency) VALUES(?,?,?,?,?)",
                           ("Test","Test Bank","IN","bank","INR"))
    create_backup(src,enc,"a strong test passphrase")
    assert b"Test Bank" not in enc.read_bytes()
    restore_backup(enc,dest,"a strong test passphrase")
    with sqlite3.connect(dest) as connection:
        assert connection.execute("SELECT institution FROM accounts").fetchone()[0] == "Test Bank"

def test_wrong_passphrase(tmp_path):
    src, enc = tmp_path/"src.db", tmp_path/"backup.enc"
    initialise(src); create_backup(src,enc,"correct passphrase")
    with pytest.raises(ValueError):
        restore_backup(enc,tmp_path/"restored.db","wrong passphrase")


def test_empty_passphrase_is_rejected():
    with pytest.raises(ValueError, match="must not be empty"):
        key_for("", b"0" * 16)


def test_missing_source_does_not_create_backup(tmp_path):
    output = tmp_path / "backup.enc"
    with pytest.raises(FileNotFoundError):
        create_backup(tmp_path / "missing.db", output, "test passphrase")
    assert not output.exists()


@pytest.mark.parametrize("blob", [b"", b"invalid format", b"WTRACKER1" + b"0" * 16])
def test_invalid_backup_format_preserves_destination(tmp_path, blob: bytes):
    encrypted = tmp_path / "invalid.enc"
    destination = tmp_path / "existing.db"
    encrypted.write_bytes(blob)
    destination.write_bytes(b"existing contents")
    with pytest.raises(ValueError, match="Unrecognised backup format"):
        restore_backup(encrypted, destination, "test passphrase")
    assert destination.read_bytes() == b"existing contents"


def test_decrypted_non_database_is_rejected_and_temporary_file_is_cleaned(tmp_path, destination):
    source = tmp_path / "not-a-database.db"
    source.write_bytes(b"not a sqlite database")
    encrypted = tmp_path / "backup.enc"
    create_backup(source, encrypted, "test passphrase")
    with pytest.raises(sqlite3.DatabaseError):
        restore_backup(encrypted, destination, "test passphrase")
    assert_preserved(destination)


def test_failed_integrity_check_preserves_destination(monkeypatch, encrypted, destination):
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    connection.execute.return_value.fetchone.return_value = ("integrity failure",)
    monkeypatch.setattr("src.backup.sqlite3.connect", Mock(return_value=connection))
    with pytest.raises(ValueError, match="integrity check failed"):
        restore_backup(encrypted, destination, "test passphrase")
    assert_preserved(destination)
    connection.close.assert_called_once_with()


def test_backup_checksums_describe_persisted_bytes(tmp_path, db_path):
    encrypted = tmp_path / "nested" / "backup.enc"
    destination = tmp_path / "restored" / "destination.db"
    checksum = create_backup(db_path, encrypted, "test passphrase")
    assert checksum == hashlib.sha256(encrypted.read_bytes()).hexdigest()
    restored_checksum = restore_backup(encrypted, destination, "test passphrase")
    assert restored_checksum == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert destination.read_bytes() == db_path.read_bytes()


def test_failed_restore_replacement_cleans_staging_and_preserves_destination(
    monkeypatch, encrypted, destination,
):

    def failed_replace(_path, _target):
        raise OSError("Destination cannot be replaced")

    monkeypatch.setattr(Path, "replace", failed_replace)
    with pytest.raises(OSError, match="cannot be replaced"):
        restore_backup(encrypted, destination, "test passphrase")
    assert_preserved(destination)


def test_failed_restore_write_cleans_partial_staging(monkeypatch, encrypted, destination):
    write_bytes = Path.write_bytes

    def partial_write(path, content):
        write_bytes(path, content[:10])
        raise OSError("Disk write failed")

    monkeypatch.setattr(Path, "write_bytes", partial_write)
    with pytest.raises(OSError, match="Disk write failed"):
        restore_backup(encrypted, destination, "test passphrase")
    assert_preserved(destination)


@pytest.mark.parametrize("command", ["create", "restore"])
def test_backup_cli_dispatches_and_prompts_for_passphrase(monkeypatch, capsys, command):
    monkeypatch.setattr("sys.argv", ["backup", command, "input", "output"])
    prompt = Mock(return_value="test passphrase")
    create = Mock(return_value="created-checksum")
    restore = Mock(return_value="restored-checksum")
    monkeypatch.setattr(backup.getpass, "getpass", prompt)
    monkeypatch.setattr(backup, "create_backup", create)
    monkeypatch.setattr(backup, "restore_backup", restore)
    backup.main()
    prompt.assert_called_once_with("Backup passphrase: ")
    selected, unused = (create, restore) if command == "create" else (restore, create)
    selected.assert_called_once_with("input", "output", "test passphrase")
    unused.assert_not_called()
    assert selected.return_value in capsys.readouterr().out
