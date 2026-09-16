"""Distribuição verificável e privada do corpus eleitoral.

O módulo cria snapshots portáveis sem copiar sessões, credenciais, downloads
parciais ou arquivos de execução. Os snapshots podem ser verificados e
restaurados em Windows, macOS e Linux usando apenas Python.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import zipfile
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .paths import CORPUS_ROOT, REPO_ROOT, resolve_corpus_reference

FORMAT_VERSION = 1
DEFAULT_PART_SIZE = 1_900 * 1024 * 1024
PRIVATE_CLASSIFICATION = "private-team-only"
TRACKED_DOCS = {"README.md", "SPEC.md", ".gitkeep"}
BLOCKED_TOP_LEVEL = {"_logs", "_quarentena"}
BLOCKED_NAMES = {
    ".DS_Store",
    ".env",
    "mind.db-shm",
    "mind.db-wal",
}
SENSITIVE_NAME_MARKERS = (
    "api-key",
    "api_key",
    "apikey",
    "auth",
    "config",
    "cookie",
    "credential",
    "password",
    "secret",
    "session",
    "senha",
    "token",
)
SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
FULL_PRIVATE_MEDIA_SUFFIXES = {
    ".aac",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".png",
    ".wav",
    ".webm",
}
SENSITIVE_JSON_KEYS = {
    "access_token",
    "api_hash",
    "api_key",
    "authorization",
    "client_secret",
    "cookie",
    "credentials",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "senha",
    "session",
    "token",
}
SENSITIVE_CONTENT_MARKERS = (
    b"-----begin private key",
    b'"access_token"',
    b'"api_hash"',
    b'"api_key"',
    b'"client_secret"',
    b'"password"',
    b'"private_key"',
    b'"refresh_token"',
    b'"secret"',
    b'"senha"',
    b'"session"',
    b'"token"',
    b"access_token=",
    b"api_hash=",
    b"api_key=",
    b"authorization: bearer",
    b"client_secret=",
    b"password=",
    b"refresh_token=",
    b"senha=",
    b"token=",
)
TEXTUAL_ARCHIVE_SUFFIXES = {"", ".csv", ".env", ".json", ".txt", ".xml"}
BUFFER_SIZE = 1024 * 1024


class BundleError(RuntimeError):
    """Snapshot inválido, inseguro ou impossível de processar."""


CommandRunner = Callable[[Sequence[str]], str]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(BUFFER_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _unsafe_reason(relative: Path) -> str | None:
    if relative.is_absolute() or ".." in relative.parts:
        return "caminho fora do corpus"
    if relative.parts and relative.parts[0] in BLOCKED_TOP_LEVEL:
        return "diretório operacional ou sem revisão"
    name = relative.name
    lower = name.lower()
    if relative == Path("perfis_sociais.jsonl"):
        return "export regenerado a partir do SQLite congelado"
    if name in TRACKED_DOCS:
        return "documentação versionada separadamente"
    if name in BLOCKED_NAMES or lower.startswith(".env."):
        return "arquivo local ou credencial"
    if any(marker in lower for marker in SENSITIVE_NAME_MARKERS):
        return "nome indica credencial, cookie ou segredo"
    if relative.suffix.lower() in SENSITIVE_SUFFIXES:
        return "formato de chave ou certificado privado"
    if lower == "mind.db":
        return "banco ativo; entra somente por backup consistente"
    if lower.endswith((".session", ".session-journal")):
        return "sessão autenticada"
    if lower.endswith((".part", ".pid", ".lock")):
        return "arquivo parcial ou trava operacional"
    if lower.endswith(".unknown_video"):
        return "download de mídia incompleto"
    return None


def _included_in_profile(relative: Path, profile: str) -> bool:
    if _unsafe_reason(relative):
        return False
    if profile == "full-private":
        if _is_document_shard(relative):
            return True
        top_level = relative.parts[0]
        suffix = relative.suffix.lower()
        if top_level == "_midia":
            return suffix in FULL_PRIVATE_MEDIA_SUFFIXES or suffix == ".json"
        if top_level == "_tse":
            return suffix == ".csv" or relative == Path("_tse/_origem.json")
        if top_level == "_tse_abertos":
            return suffix in {".csv", ".pdf", ".zip"} or relative == Path(
                "_tse_abertos/_origem.json"
            )
        return False
    if profile != "team":
        raise BundleError(f"perfil desconhecido: {profile}")
    if relative.parts[:2] == ("_midia", "thumbs"):
        return True
    return (
        len(relative.parts) >= 2
        and not relative.parts[0].startswith("_")
        and relative.suffixes[-2:] == [".jsonl", ".gz"]
    )


def _iter_corpus_files(root: Path, profile: str) -> Iterable[tuple[Path, Path]]:
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise BundleError(f"links simbólicos não são aceitos no corpus: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _included_in_profile(relative, profile) and not (
            profile == "full-private" and _file_contains_sensitive_content(path)
        ):
            yield path, relative


def _json_contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in SENSITIVE_JSON_KEYS or normalized.endswith(
                ("_password", "_secret", "_token", "_private_key")
            ):
                return True
            if _json_contains_sensitive_key(nested):
                return True
    elif isinstance(value, list):
        return any(_json_contains_sensitive_key(item) for item in value)
    return False


def _file_contains_sensitive_content(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return _zip_contains_sensitive_content(path)
    if suffix == ".json":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return True
        if path.parent.name == "_midia":
            expected_keys = {"inicio_seg", "fim_seg", "texto", "confianca"}
            if not isinstance(value, list) or any(
                not isinstance(item, dict) or not set(item).issubset(expected_keys)
                for item in value
            ):
                return True
        return _json_contains_sensitive_key(value)
    if suffix not in {".csv", ".txt", ".xml"}:
        return False
    try:
        sample = path.read_bytes()[: 2 * BUFFER_SIZE].decode("utf-8", "ignore").lower()
    except OSError:
        return True
    return any(
        marker in sample
        for marker in (
            "-----begin private key",
            "access_token",
            "api_hash",
            "api_key",
            "authorization: bearer",
            "client_secret",
            "refresh_token",
        )
    )


def _stream_contains_sensitive_content(stream: Any) -> bool:
    overlap = max(len(marker) for marker in SENSITIVE_CONTENT_MARKERS) - 1
    tail = b""
    while chunk := stream.read(BUFFER_SIZE):
        lowered = (tail + chunk).lower()
        if any(marker in lowered for marker in SENSITIVE_CONTENT_MARKERS):
            return True
        tail = lowered[-overlap:]
    return False


def _zip_contains_sensitive_content(source: Any) -> bool:
    try:
        with zipfile.ZipFile(source) as nested:
            for info in nested.infolist():
                relative_posix = _safe_archive_name(info.filename)
                relative = Path(*relative_posix.parts)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or info.flag_bits & 1:
                    return True
                if info.is_dir():
                    continue
                if _unsafe_reason(relative) or relative.suffix.lower() == ".zip":
                    return True
                if relative.suffix.lower() in TEXTUAL_ARCHIVE_SUFFIXES:
                    with nested.open(info) as stream:
                        if _stream_contains_sensitive_content(stream):
                            return True
    except (OSError, RuntimeError, zipfile.BadZipFile, BundleError):
        return True
    return False


def _zipped_entry_contains_sensitive_content(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    relative: Path,
) -> bool:
    suffix = relative.suffix.lower()
    if suffix == ".zip":
        with tempfile.SpooledTemporaryFile(max_size=8 * BUFFER_SIZE) as temporary:
            with archive.open(info) as source:
                shutil.copyfileobj(source, temporary, BUFFER_SIZE)
            temporary.seek(0)
            return _zip_contains_sensitive_content(temporary)
    if suffix == ".json":
        try:
            with archive.open(info) as raw, io.TextIOWrapper(raw, encoding="utf-8") as stream:
                value = json.load(stream)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return True
        if relative.parts[0] == "_midia":
            expected_keys = {"inicio_seg", "fim_seg", "texto", "confianca"}
            if not isinstance(value, list) or any(
                not isinstance(item, dict) or not set(item).issubset(expected_keys)
                for item in value
            ):
                return True
        return _json_contains_sensitive_key(value)
    if suffix not in {".csv", ".txt", ".xml"}:
        return False
    with archive.open(info) as stream:
        sample = stream.read(2 * BUFFER_SIZE).decode("utf-8", "ignore").lower()
    return any(
        marker in sample
        for marker in (
            "-----begin private key",
            "access_token",
            "api_hash",
            "api_key",
            "authorization: bearer",
            "client_secret",
            "refresh_token",
        )
    )


def _sqlite_backup(source_path: Path, destination_path: Path) -> None:
    if not source_path.is_file():
        raise BundleError(f"banco não encontrado: {source_path}")
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30)
    destination = sqlite3.connect(destination_path)
    try:
        source.backup(destination)
        result = destination.execute("PRAGMA quick_check").fetchone()
        if result != ("ok",):
            raise BundleError(f"backup SQLite inconsistente: {result}")
    finally:
        destination.close()
        source.close()


def _sqlite_summary(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        summary: dict[str, Any] = {"quick_check": quick_check[0] if quick_check else None}
        summary["schema_user_version"] = connection.execute("PRAGMA user_version").fetchone()[0]
        for table in ("documentos", "midias", "transcricoes", "snapshots_perfis_sociais"):
            summary[table] = (
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if table in tables
                else 0
            )
        if "documentos" in tables:
            summary["latest_collected_at"] = connection.execute(
                "SELECT MAX(coletado_em) FROM documentos"
            ).fetchone()[0]
            summary["by_source"] = dict(
                connection.execute(
                    "SELECT fonte, COUNT(*) FROM documentos GROUP BY fonte ORDER BY fonte"
                ).fetchall()
            )
            summary["by_license"] = dict(
                connection.execute(
                    "SELECT licenca_uso, COUNT(*) FROM documentos "
                    "GROUP BY licenca_uso ORDER BY licenca_uso"
                ).fetchall()
            )
        if "execucoes" in tables:
            summary["open_runs"] = connection.execute(
                "SELECT COUNT(*) FROM execucoes WHERE fim IS NULL"
            ).fetchone()[0]
        return summary
    finally:
        connection.close()


def corpus_status(root: Path = CORPUS_ROOT) -> dict[str, Any]:
    """Resume o estado local e aponta material que nunca deve ser publicado."""
    root = root.resolve()
    files = 0
    total_bytes = 0
    blocked: list[dict[str, str]] = []
    by_extension: dict[str, dict[str, int]] = {}
    if root.exists():
        for path in root.rglob("*"):
            if path.is_symlink():
                blocked.append(
                    {"path": path.relative_to(root).as_posix(), "reason": "link simbólico"}
                )
                continue
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            size = path.stat().st_size
            files += 1
            total_bytes += size
            extension = "".join(path.suffixes[-2:]) or "[sem extensão]"
            values = by_extension.setdefault(extension, {"files": 0, "bytes": 0})
            values["files"] += 1
            values["bytes"] += size
            reason = _unsafe_reason(relative)
            if reason and relative.name not in TRACKED_DOCS and relative.name != "mind.db":
                blocked.append({"path": relative.as_posix(), "reason": reason})
    database = root / "mind.db"
    return {
        "root": str(root),
        "exists": root.is_dir(),
        "files": files,
        "bytes": total_bytes,
        "database": _sqlite_summary(database) if database.is_file() else None,
        "blocked_files": blocked,
        "by_extension": dict(sorted(by_extension.items())),
    }


def _git_state() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def _is_document_shard(relative: Path) -> bool:
    return (
        len(relative.parts) >= 2
        and not relative.parts[0].startswith("_")
        and relative.suffixes[-2:] == [".jsonl", ".gz"]
    )


def _validate_document_shards(database_path: Path, files: list[tuple[Path, Path]]) -> None:
    database_ids = _database_document_ids(database_path)
    shard_ids: set[str] = set()
    for source, relative in files:
        if not _is_document_shard(relative):
            continue
        try:
            with gzip.open(source, "rt", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    doc_id = item.get("doc_id")
                    if not isinstance(doc_id, str) or not doc_id:
                        raise BundleError(f"doc_id ausente em {relative.as_posix()}:{line_number}")
                    if doc_id in shard_ids:
                        raise BundleError(f"doc_id duplicado nos JSONL: {doc_id}")
                    shard_ids.add(doc_id)
        except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BundleError(f"shard inválido: {relative.as_posix()}: {error}") from error
    if shard_ids != database_ids:
        missing_in_database = len(shard_ids - database_ids)
        missing_in_shards = len(database_ids - shard_ids)
        raise BundleError(
            "SQLite e JSONL divergem: "
            f"{missing_in_database} somente nos shards; {missing_in_shards} somente no banco"
        )


def _database_document_ids(database_path: Path) -> set[str]:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        return {row[0] for row in connection.execute("SELECT doc_id FROM documentos")}
    finally:
        connection.close()


def _read_zipped_shard(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    relative_text: str,
    seen: set[str],
) -> None:
    try:
        with (
            archive.open(info) as compressed,
            gzip.GzipFile(fileobj=compressed, mode="rb") as uncompressed,
            io.TextIOWrapper(uncompressed, encoding="utf-8") as stream,
        ):
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                item = json.loads(line)
                doc_id = item.get("doc_id")
                if not isinstance(doc_id, str) or not doc_id:
                    raise BundleError(f"doc_id ausente em {relative_text}:{line_number}")
                if doc_id in seen:
                    raise BundleError(f"doc_id duplicado no ZIP: {doc_id}")
                seen.add(doc_id)
    except (OSError, EOFError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleError(f"shard inválido no ZIP: {relative_text}: {error}") from error


def _validate_media_references(database_path: Path, source_root: Path) -> None:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        references = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT thumb_path FROM midias WHERE thumb_path IS NOT NULL"
            )
        ]
    finally:
        connection.close()
    missing = []
    for value in references:
        try:
            resolved = resolve_corpus_reference(value, source_root)
        except ValueError as error:
            raise BundleError(f"miniatura aponta para fora do corpus: {value}") from error
        if not resolved.is_file():
            missing.append(value)
    if missing:
        raise BundleError(
            f"{len(missing)} miniaturas referenciadas no SQLite não existem; exemplo: {missing[0]}"
        )


def _export_profiles(database_path: Path, destination: Path) -> None:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if not {"alvos_sociais", "snapshots_perfis_sociais"}.issubset(tables):
            destination.write_text("", encoding="utf-8")
            return
        rows = connection.execute(
            """
            SELECT a.plataforma, a.url, a.origem, a.relevancia, a.primeira_vista,
                   a.ultima_vista, a.ultima_coleta, a.tentativas, a.ultimo_erro,
                   s.dados_json, s.coletado_em
            FROM alvos_sociais a
            LEFT JOIN snapshots_perfis_sociais s ON s.rowid = (
                SELECT ss.rowid FROM snapshots_perfis_sociais ss
                WHERE ss.plataforma=a.plataforma AND ss.url=a.url
                ORDER BY ss.coletado_em DESC, ss.rowid DESC LIMIT 1
            )
            WHERE a.tipo='perfil' AND a.ativo=1
            ORDER BY a.plataforma, a.url
            """
        )
        with destination.open("w", encoding="utf-8") as stream:
            for row in rows:
                profile = json.loads(row[9]) if row[9] else {}
                stream.write(
                    json.dumps(
                        {
                            "plataforma": row[0],
                            "url": row[1],
                            "origem": row[2],
                            "relevancia": row[3],
                            "primeira_vista": row[4],
                            "ultima_vista": row[5],
                            "ultima_coleta": row[6],
                            "tentativas": row[7],
                            "ultimo_erro": row[8],
                            "snapshot": profile,
                            "snapshot_em": row[10],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    finally:
        connection.close()


def _zip_info(name: str, created_at: datetime, compress_type: int) -> zipfile.ZipInfo:
    year = max(created_at.year, 1980)
    info = zipfile.ZipInfo(
        name,
        date_time=(year, created_at.month, created_at.day, created_at.hour, created_at.minute, 0),
    )
    info.compress_type = compress_type
    info.external_attr = 0o100644 << 16
    return info


def _copy_file_into_zip(
    archive: zipfile.ZipFile,
    source: Path,
    archive_name: str,
    created_at: datetime,
) -> dict[str, Any]:
    before = source.stat()
    compress_type = (
        zipfile.ZIP_STORED
        if source.suffix.lower() in {".gz", ".zip", ".jpg", ".jpeg", ".png", ".m4a", ".mp4"}
        else zipfile.ZIP_DEFLATED
    )
    digest = hashlib.sha256()
    copied = 0
    info = _zip_info(archive_name, created_at, compress_type)
    with source.open("rb") as input_stream, archive.open(info, "w", force_zip64=True) as output:
        while chunk := input_stream.read(BUFFER_SIZE):
            output.write(chunk)
            digest.update(chunk)
            copied += len(chunk)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise BundleError(f"arquivo mudou durante o snapshot: {source}")
    if copied != before.st_size:
        raise BundleError(f"cópia incompleta durante o snapshot: {source}")
    return {
        "path": archive_name.removeprefix("corpus/"),
        "bytes": copied,
        "sha256": digest.hexdigest(),
    }


def _split_archive(archive_path: Path, part_size: int) -> list[Path]:
    if part_size <= 0:
        raise BundleError("o tamanho das partes deve ser positivo")
    if archive_path.stat().st_size <= part_size:
        return [archive_path]
    parts: list[Path] = []
    try:
        with archive_path.open("rb") as source:
            number = 1
            while source.peek(1):
                part = archive_path.with_name(f"{archive_path.name}.part{number:03d}")
                parts.append(part)
                remaining = part_size
                with part.open("wb") as output:
                    while remaining:
                        chunk = source.read(min(BUFFER_SIZE, remaining))
                        if not chunk:
                            break
                        output.write(chunk)
                        remaining -= len(chunk)
                number += 1
        archive_path.unlink()
    except Exception:
        for part in parts:
            part.unlink(missing_ok=True)
        raise
    return parts


def pack_bundle(
    source_root: Path = CORPUS_ROOT,
    output_dir: Path | None = None,
    profile: str = "team",
    part_size: int = DEFAULT_PART_SIZE,
    now: datetime | None = None,
) -> Path:
    """Cria um snapshot e devolve o caminho do índice ``*.bundle.json``."""
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise BundleError(f"corpus não encontrado: {source_root}")
    if profile not in {"team", "full-private"}:
        raise BundleError(f"perfil desconhecido: {profile}")
    output_dir = (output_dir or REPO_ROOT / "dist" / "data").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    created_at = (now or _utc_now()).astimezone(UTC).replace(microsecond=0)
    snapshot_id = f"{created_at:%Y%m%dT%H%M%SZ}-{profile}"
    base_name = f"mind-eleicoes2026-{snapshot_id}"
    archive_path = output_dir / f"{base_name}.zip"
    index_path = output_dir / f"{base_name}.bundle.json"
    if archive_path.exists() or index_path.exists():
        raise BundleError(f"snapshot já existe: {snapshot_id}")

    created_paths: list[Path] = []
    try:
        with tempfile.TemporaryDirectory(prefix="mind-bundle-") as temporary:
            database_backup = Path(temporary) / "mind.db"
            _sqlite_backup(source_root / "mind.db", database_backup)
            database_summary = _sqlite_summary(database_backup)
            selected = list(_iter_corpus_files(source_root, profile))
            _validate_document_shards(database_backup, selected)
            _validate_media_references(database_backup, source_root)
            profiles_export = Path(temporary) / "perfis_sociais.jsonl"
            _export_profiles(database_backup, profiles_export)
            manifest_files: list[dict[str, Any]] = []
            with zipfile.ZipFile(archive_path, "w", allowZip64=True) as archive:
                manifest_files.append(
                    _copy_file_into_zip(archive, database_backup, "corpus/mind.db", created_at)
                )
                manifest_files.append(
                    _copy_file_into_zip(
                        archive,
                        profiles_export,
                        "corpus/perfis_sociais.jsonl",
                        created_at,
                    )
                )
                for source, relative in selected:
                    manifest_files.append(
                        _copy_file_into_zip(
                            archive,
                            source,
                            f"corpus/{relative.as_posix()}",
                            created_at,
                        )
                    )
                manifest = {
                    "format_version": FORMAT_VERSION,
                    "snapshot_id": snapshot_id,
                    "created_at": created_at.isoformat().replace("+00:00", "Z"),
                    "profile": profile,
                    "privacy": PRIVATE_CLASSIFICATION,
                    "git": _git_state(),
                    "database": database_summary,
                    "file_count": len(manifest_files),
                    "uncompressed_bytes": sum(item["bytes"] for item in manifest_files),
                    "excluded": {
                        "always": [
                            "credenciais, cookies e sessões autenticadas",
                            "downloads parciais, locks, PIDs, logs e WAL/SHM",
                            "quarentena e documentação versionada no Git",
                        ],
                        "profile": (
                            "mídia original, frames e caches regeneráveis"
                            if profile == "team"
                            else "formatos desconhecidos fora da allowlist privada"
                        ),
                    },
                    "files": manifest_files,
                }
                manifest_bytes = _json_bytes(manifest)
                archive.writestr(
                    _zip_info("MANIFEST.json", created_at, zipfile.ZIP_DEFLATED),
                    manifest_bytes,
                )
            created_paths.append(archive_path)

            _verify_archive(
                archive_path,
                {
                    "format_version": FORMAT_VERSION,
                    "snapshot_id": snapshot_id,
                    "profile": profile,
                    "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                },
                Path(temporary),
            )

            archive_size = archive_path.stat().st_size
            archive_sha256 = _sha256_path(archive_path)
            parts = _split_archive(archive_path, part_size)
            created_paths = parts.copy()
            index = {
                "format_version": FORMAT_VERSION,
                "snapshot_id": snapshot_id,
                "created_at": manifest["created_at"],
                "profile": profile,
                "privacy": PRIVATE_CLASSIFICATION,
                "archive": {
                    "name": archive_path.name,
                    "bytes": archive_size,
                    "sha256": archive_sha256,
                },
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "parts": [
                    {
                        "name": part.name,
                        "bytes": part.stat().st_size,
                        "sha256": _sha256_path(part),
                    }
                    for part in parts
                ],
            }
            index_path.write_bytes(_json_bytes(index))
            created_paths.append(index_path)
            return index_path
    except Exception:
        for path in created_paths:
            path.unlink(missing_ok=True)
        archive_path.unlink(missing_ok=True)
        index_path.unlink(missing_ok=True)
        raise


def _read_index(index_path: Path) -> dict[str, Any]:
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BundleError(f"índice inválido: {index_path}") from error
    if index.get("format_version") != FORMAT_VERSION:
        raise BundleError("versão de bundle incompatível")
    if index.get("privacy") != PRIVATE_CLASSIFICATION:
        raise BundleError("classificação de privacidade ausente ou inválida")
    if index.get("profile") not in {"team", "full-private"}:
        raise BundleError("perfil ausente ou inválido no índice")
    parts = index.get("parts")
    if not isinstance(parts, list) or not parts:
        raise BundleError("índice sem partes")
    return index


def _safe_archive_name(name: str) -> PurePosixPath:
    if "\\" in name or "\x00" in name:
        raise BundleError(f"caminho inseguro no ZIP: {name}")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or any(":" in part for part in path.parts)
    ):
        raise BundleError(f"caminho inseguro no ZIP: {name}")
    return path


def _assemble_archive(index_path: Path, index: dict[str, Any], destination: Path) -> Path:
    archive = index.get("archive", {})
    expected_name = archive.get("name")
    if not isinstance(expected_name, str) or Path(expected_name).name != expected_name:
        raise BundleError("nome de arquivo inválido no índice")
    archive_path = destination / expected_name
    digest = hashlib.sha256()
    copied = 0
    with archive_path.open("wb") as output:
        for part in index["parts"]:
            name = part.get("name")
            if not isinstance(name, str) or Path(name).name != name:
                raise BundleError("nome de parte inválido no índice")
            source = index_path.parent / name
            if not source.is_file():
                raise BundleError(f"parte ausente: {source}")
            if source.stat().st_size != part.get("bytes"):
                raise BundleError(f"tamanho divergente: {source.name}")
            part_digest = hashlib.sha256()
            with source.open("rb") as input_stream:
                while chunk := input_stream.read(BUFFER_SIZE):
                    output.write(chunk)
                    part_digest.update(chunk)
                    digest.update(chunk)
                    copied += len(chunk)
            if part_digest.hexdigest() != part.get("sha256"):
                raise BundleError(f"checksum divergente: {source.name}")
    if copied != archive.get("bytes") or digest.hexdigest() != archive.get("sha256"):
        raise BundleError("arquivo ZIP reconstruído não corresponde ao índice")
    return archive_path


def _verify_archive(archive_path: Path, index: dict[str, Any], temporary: Path) -> dict[str, Any]:
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as error:
        raise BundleError("arquivo ZIP inválido") from error
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise BundleError("ZIP contém caminhos duplicados")
        for info in infos:
            path = _safe_archive_name(info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise BundleError(f"link simbólico proibido no ZIP: {info.filename}")
            if path.name != "MANIFEST.json" and path.parts[0] != "corpus":
                raise BundleError(f"arquivo fora da raiz corpus/: {info.filename}")
        if "MANIFEST.json" not in names:
            raise BundleError("MANIFEST.json ausente")
        manifest_bytes = archive.read("MANIFEST.json")
        if hashlib.sha256(manifest_bytes).hexdigest() != index.get("manifest_sha256"):
            raise BundleError("checksum do manifesto divergente")
        try:
            manifest = json.loads(manifest_bytes)
        except json.JSONDecodeError as error:
            raise BundleError("manifesto JSON inválido") from error
        if manifest.get("format_version") != FORMAT_VERSION:
            raise BundleError("versão do manifesto incompatível")
        if manifest.get("snapshot_id") != index.get("snapshot_id"):
            raise BundleError("snapshot do manifesto diverge do índice")
        if manifest.get("profile") != index.get("profile"):
            raise BundleError("perfil do manifesto diverge do índice")
        entries = manifest.get("files")
        if not isinstance(entries, list):
            raise BundleError("lista de arquivos ausente no manifesto")
        expected_names = {"MANIFEST.json"}
        seen_paths: set[str] = set()
        shard_ids: set[str] = set()
        database_path: Path | None = None
        for entry in entries:
            relative_text = entry.get("path")
            if not isinstance(relative_text, str):
                raise BundleError("caminho inválido no manifesto")
            relative_posix = _safe_archive_name(relative_text)
            relative = Path(*relative_posix.parts)
            if relative_text in seen_paths:
                raise BundleError(f"caminho duplicado no manifesto: {relative_text}")
            seen_paths.add(relative_text)
            if relative_text not in {"mind.db", "perfis_sociais.jsonl"}:
                if _unsafe_reason(relative):
                    raise BundleError(f"arquivo proibido no bundle: {relative_text}")
                if not _included_in_profile(relative, manifest["profile"]):
                    raise BundleError(
                        f"arquivo não permitido no perfil {manifest['profile']}: {relative_text}"
                    )
            archive_name = f"corpus/{relative_posix.as_posix()}"
            expected_names.add(archive_name)
            try:
                info = archive.getinfo(archive_name)
            except KeyError as error:
                raise BundleError(f"arquivo ausente no ZIP: {relative_text}") from error
            if info.file_size != entry.get("bytes"):
                raise BundleError(f"tamanho divergente no ZIP: {relative_text}")
            digest = hashlib.sha256()
            with archive.open(info) as stream:
                while chunk := stream.read(BUFFER_SIZE):
                    digest.update(chunk)
            if digest.hexdigest() != entry.get("sha256"):
                raise BundleError(f"checksum interno divergente: {relative_text}")
            if manifest["profile"] == "full-private" and _zipped_entry_contains_sensitive_content(
                archive, info, relative
            ):
                raise BundleError(f"conteúdo sensível ou formato inesperado: {relative_text}")
            if _is_document_shard(relative):
                _read_zipped_shard(archive, info, relative_text, shard_ids)
            if relative_text == "mind.db":
                database_path = temporary / "mind.db"
                with archive.open(info) as source, database_path.open("wb") as output:
                    shutil.copyfileobj(source, output, BUFFER_SIZE)
        if set(names) != expected_names:
            extras = sorted(set(names) - expected_names)
            raise BundleError(f"ZIP contém arquivos não declarados: {extras[:3]}")
        if manifest.get("file_count") != len(entries):
            raise BundleError("contagem de arquivos divergente no manifesto")
        if database_path is None:
            raise BundleError("mind.db ausente no snapshot")
        database_summary = _sqlite_summary(database_path)
        if database_summary.get("quick_check") != "ok":
            raise BundleError("SQLite restaurado não passou no quick_check")
        if manifest.get("database") != database_summary:
            raise BundleError("resumo do SQLite diverge do manifesto")
        database_ids = _database_document_ids(database_path)
        if shard_ids != database_ids:
            raise BundleError(
                "SQLite e JSONL divergem dentro do ZIP: "
                f"{len(shard_ids - database_ids)} somente nos shards; "
                f"{len(database_ids - shard_ids)} somente no banco"
            )
        return manifest


def verify_bundle(index_path: Path) -> dict[str, Any]:
    """Verifica partes, ZIP, manifesto, arquivos internos e SQLite."""
    index_path = index_path.resolve()
    index = _read_index(index_path)
    with tempfile.TemporaryDirectory(prefix="mind-verify-") as temporary:
        temporary_path = Path(temporary)
        archive_path = _assemble_archive(index_path, index, temporary_path)
        return _verify_archive(archive_path, index, temporary_path)


def _managed_entries(destination: Path) -> list[Path]:
    if not destination.exists():
        return []
    return [entry for entry in destination.iterdir() if entry.name not in TRACKED_DOCS]


def _extract_corpus(archive_path: Path, staging: Path) -> None:
    corpus = (staging / "corpus").resolve()
    corpus.mkdir(parents=True)
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            if info.filename == "MANIFEST.json":
                continue
            path = _safe_archive_name(info.filename)
            relative = Path(*path.parts[1:])
            destination = (corpus / relative).resolve()
            if destination != corpus and corpus not in destination.parents:
                raise BundleError(f"caminho fora do staging: {info.filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output, BUFFER_SIZE)


def restore_bundle(
    index_path: Path,
    destination: Path = CORPUS_ROOT,
    replace: bool = False,
) -> Path | None:
    """Restaura atomicamente; com ``replace``, mantém uma cópia da pasta anterior."""
    index_path = index_path.resolve()
    if destination.is_symlink():
        raise BundleError(f"destino não pode ser link simbólico: {destination}")
    destination = destination.resolve()
    if destination == Path(destination.anchor) or destination in {
        Path.home().resolve(),
        REPO_ROOT.resolve(),
        REPO_ROOT.parent.resolve(),
    }:
        raise BundleError(f"destino perigoso recusado: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    managed = _managed_entries(destination)
    if managed and not replace:
        raise BundleError(
            f"destino já contém dados ({managed[0].name}); use --replace para preservar um backup"
        )
    index = _read_index(index_path)
    backup_path: Path | None = None
    with tempfile.TemporaryDirectory(prefix=".mind-restore-", dir=destination.parent) as temporary:
        temporary_path = Path(temporary)
        archive_path = _assemble_archive(index_path, index, temporary_path)
        _verify_archive(archive_path, index, temporary_path)
        staging = temporary_path / "staging"
        _extract_corpus(archive_path, staging)
        staged_corpus = staging / "corpus"
        docs = {
            name: (destination / name).read_bytes()
            for name in TRACKED_DOCS
            if (destination / name).is_file()
        }
        for name, content in docs.items():
            (staged_corpus / name).write_bytes(content)
        previous: Path | None = None
        if managed:
            stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
            backup_path = destination.with_name(f"{destination.name}.backup-{stamp}")
            if backup_path.exists():
                raise BundleError(f"backup já existe: {backup_path}")
            destination.rename(backup_path)
            previous = backup_path
        elif destination.exists():
            previous = temporary_path / "previous-docs"
            destination.rename(previous)
            current_docs = {
                name: (previous / name).read_bytes()
                for name in TRACKED_DOCS
                if (previous / name).is_file()
            }
            if _managed_entries(previous) or current_docs != docs:
                previous.rename(destination)
                previous = None
                raise BundleError("destino foi alterado durante a restauração")
        try:
            staged_corpus.rename(destination)
        except Exception:
            if previous and previous.exists():
                if destination.exists():
                    if previous != backup_path:
                        recovery = Path(
                            tempfile.mkdtemp(
                                prefix=f"{destination.name}.recovery-",
                                dir=destination.parent,
                            )
                        )
                        recovery.rmdir()
                        previous.rename(recovery)
                else:
                    previous.rename(destination)
            backup_path = None
            raise
    return backup_path


def _run_gh(arguments: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ["gh", *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise BundleError("GitHub CLI (gh) não está instalado") from error
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise BundleError(f"gh falhou: {detail}") from error
    return result.stdout


def _require_private_repository(repository: str, runner: CommandRunner) -> None:
    try:
        payload = json.loads(runner(["repo", "view", repository, "--json", "visibility"]))
    except json.JSONDecodeError as error:
        raise BundleError("resposta inválida do GitHub CLI") from error
    if payload.get("visibility") != "PRIVATE":
        raise BundleError(
            f"publicação recusada: {repository} não é privado. "
            "O corpus não pode ir para o repositório público do código."
        )


def publish_bundle(
    index_path: Path,
    repository: str,
    tag: str | None = None,
    allow_full_private: bool = False,
    runner: CommandRunner = _run_gh,
) -> str:
    """Publica um bundle imutável em Release de um repositório privado."""
    index_path = index_path.resolve()
    manifest = verify_bundle(index_path)
    index = _read_index(index_path)
    if manifest["profile"] == "full-private" and not allow_full_private:
        raise BundleError("publicação full-private exige revisão de licença e --allow-full-private")
    _require_private_repository(repository, runner)
    release_tag = tag or f"eleicoes2026-{manifest['snapshot_id']}"
    assets = [index_path]
    for part in index["parts"]:
        asset = index_path.parent / part["name"]
        if not asset.is_file():
            raise BundleError(f"parte ausente: {asset}")
        assets.append(asset)
    notes = (
        "Snapshot privado e verificável do corpus eleitoral MIND.\n\n"
        f"Perfil: {manifest['profile']}\n"
        f"Arquivos: {manifest['file_count']}\n"
        f"Documentos: {manifest['database'].get('documentos', 0)}\n\n"
        "Baixe o índice *.bundle.json e todas as partes; depois execute "
        "`uv run mind-data restore caminho/do/indice.bundle.json`."
    )
    runner(
        [
            "release",
            "create",
            release_tag,
            "--repo",
            repository,
            "--title",
            f"Corpus eleitoral {manifest['snapshot_id']}",
            "--notes",
            notes,
            *[str(asset) for asset in assets],
        ]
    )
    return release_tag


def fetch_bundle(
    repository: str,
    destination: Path = CORPUS_ROOT,
    release: str | None = None,
    replace: bool = False,
    runner: CommandRunner = _run_gh,
) -> Path | None:
    """Baixa a Release privada, verifica e restaura o corpus."""
    _require_private_repository(repository, runner)
    with tempfile.TemporaryDirectory(prefix="mind-download-") as temporary:
        arguments = ["release", "download"]
        if release:
            arguments.append(release)
        arguments.extend(["--repo", repository, "--dir", temporary])
        runner(arguments)
        indexes = list(Path(temporary).glob("*.bundle.json"))
        if len(indexes) != 1:
            raise BundleError(
                f"a Release deve conter exatamente um índice; encontrados: {len(indexes)}"
            )
        return restore_bundle(indexes[0], destination=destination, replace=replace)


def _human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def _print_status(status: dict[str, Any]) -> None:
    print(f"Corpus: {status['root']}")
    print(f"Arquivos: {status['files']:,} ({_human_bytes(status['bytes'])})")
    database = status.get("database")
    if database:
        print(f"SQLite: {database['quick_check']}")
        print(f"Documentos: {database.get('documentos', 0):,}")
        print(f"Última coleta: {database.get('latest_collected_at') or '-'}")
    blocked = status.get("blocked_files", [])
    print(f"Arquivos locais excluídos de snapshots: {len(blocked)}")
    for item in blocked[:10]:
        print(f"  - {item['path']}: {item['reason']}")
    if len(blocked) > 10:
        print(f"  ... e mais {len(blocked) - 10}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mind-data", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="audita o corpus local")
    status.add_argument("--source", type=Path, default=CORPUS_ROOT)
    status.add_argument("--json", action="store_true")

    pack = subparsers.add_parser("pack", help="cria snapshot privado verificável")
    pack.add_argument("--source", type=Path, default=CORPUS_ROOT)
    pack.add_argument("--output", type=Path, default=REPO_ROOT / "dist" / "data")
    pack.add_argument("--profile", choices=("team", "full-private"), default="team")
    pack.add_argument("--part-size-mib", type=int, default=1900)

    verify = subparsers.add_parser("verify", help="verifica um snapshot")
    verify.add_argument("bundle", type=Path)

    restore = subparsers.add_parser("restore", help="restaura um snapshot local")
    restore.add_argument("bundle", type=Path)
    restore.add_argument("--destination", type=Path, default=CORPUS_ROOT)
    restore.add_argument("--replace", action="store_true")

    publish = subparsers.add_parser("publish", help="publica em Release privada")
    publish.add_argument("bundle", type=Path)
    publish.add_argument("--repository", required=True)
    publish.add_argument("--tag")
    publish.add_argument("--allow-full-private", action="store_true")

    fetch = subparsers.add_parser("fetch", help="baixa e restaura uma Release privada")
    fetch.add_argument("--repository", required=True)
    fetch.add_argument("--release")
    fetch.add_argument("--destination", type=Path, default=CORPUS_ROOT)
    fetch.add_argument("--replace", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        if arguments.command == "status":
            status = corpus_status(arguments.source)
            if arguments.json:
                print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                _print_status(status)
        elif arguments.command == "pack":
            print("Validando e empacotando o corpus...", flush=True)
            index = pack_bundle(
                source_root=arguments.source,
                output_dir=arguments.output,
                profile=arguments.profile,
                part_size=arguments.part_size_mib * 1024 * 1024,
            )
            print(index)
        elif arguments.command == "verify":
            manifest = verify_bundle(arguments.bundle)
            print(
                f"OK: {manifest['snapshot_id']} — "
                f"{manifest['file_count']} arquivos, "
                f"{manifest['database'].get('documentos', 0):,} documentos"
            )
        elif arguments.command == "restore":
            backup = restore_bundle(
                arguments.bundle,
                destination=arguments.destination,
                replace=arguments.replace,
            )
            print(f"Corpus restaurado em {arguments.destination.resolve()}")
            if backup:
                print(f"Cópia anterior preservada em {backup}")
        elif arguments.command == "publish":
            print("Verificando e enviando o snapshot privado...", flush=True)
            tag = publish_bundle(
                arguments.bundle,
                repository=arguments.repository,
                tag=arguments.tag,
                allow_full_private=arguments.allow_full_private,
            )
            print(f"Release criada: {arguments.repository}@{tag}")
        elif arguments.command == "fetch":
            print("Baixando, verificando e restaurando o snapshot...", flush=True)
            backup = fetch_bundle(
                repository=arguments.repository,
                destination=arguments.destination,
                release=arguments.release,
                replace=arguments.replace,
            )
            print(f"Corpus restaurado em {arguments.destination.resolve()}")
            if backup:
                print(f"Cópia anterior preservada em {backup}")
    except BundleError as error:
        print(f"erro: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
