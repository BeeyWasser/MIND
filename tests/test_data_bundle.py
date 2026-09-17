from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

import mind_collect.data_bundle as data_bundle
from mind_collect.data_bundle import (
    BundleError,
    pack_bundle,
    restore_bundle,
    verify_bundle,
)
from mind_collect.schema import Documento, Midia
from mind_collect.store import Store


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    with Store(root) as store:
        document = Documento(
            fonte="noticia",
            url="https://example.org/politica",
            titulo="Notícia eleitoral",
            texto="Conteúdo político suficiente para o corpus de teste.",
            eleicao="2026",
        )
        assert store.guardar(document)
        thumbnail = root / "_midia" / "thumbs" / "imagem.jpg"
        thumbnail.parent.mkdir(parents=True)
        thumbnail.write_bytes(b"thumbnail")
        store.guardar_midia(
            Midia(
                doc_id=document.doc_id,
                tipo="imagem",
                url_origem="https://example.org/imagem.jpg",
                thumb_path=str(thumbnail),
            )
        )
        store.registrar_alvo_social(
            "instagram",
            "https://instagram.com/conta",
            "perfil",
            "teste",
        )

    (root / "perfis_sociais.jsonl").write_text('{"desatualizado": true}\n')
    (root / "_midia" / "frames").mkdir(parents=True)
    (root / "_midia" / "frames" / "frame.jpg").write_bytes(b"frame")
    (root / "_midia" / "audio.m4a").write_bytes(b"audio")
    (root / "_midia" / "incompleto.part").write_bytes(b"partial")
    (root / "_midia" / "falha.unknown_video").write_bytes(b"unknown")
    (root / "_telegram.session").write_bytes(b"secret")
    (root / "instagram-cookies.txt").write_text("secret")
    (root / "credentials.json").write_text("secret")
    (root / "token.json").write_text("secret")
    (root / "client-secret.json").write_text("secret")
    (root / "neutral.json").write_text("secret")
    service_account = root / "_datasets" / "service-account.json"
    service_account.parent.mkdir(exist_ok=True)
    service_account.write_text('{"private_key": "secret", "client_email": "x@example.org"}')
    login_cache = root / "_midia" / "login.json"
    login_cache.write_text('{"username": "x", "password": "secret"}')
    transcript_cache = root / "_midia" / "video-id.json"
    transcript_cache.write_text(
        '[{"inicio_seg": 0, "fim_seg": 1, "texto": "fala", "confianca": -0.1}]'
    )
    tse_archive = root / "_tse_abertos" / "dados.zip"
    tse_archive.parent.mkdir()
    with zipfile.ZipFile(tse_archive, "w") as archive:
        archive.writestr("consulta_cand_2026_BRASIL.csv", "nome;partido\nMaria;ABC\n")
    (root / "private.pem").write_text("secret")
    (root / "telegram.session.invalid-backup").write_text("secret")
    (root / "_worker-midia.lock").write_text("lock")
    (root / "_logs").mkdir()
    (root / "_logs" / "coleta.log").write_text("log")
    (root / "_quarentena").mkdir()
    (root / "_quarentena" / "duvida.jsonl").write_text("{}\n")
    return root


def create_bundle(corpus: Path, output: Path, profile: str = "team") -> Path:
    return pack_bundle(
        source_root=corpus,
        output_dir=output,
        profile=profile,
        part_size=10 * 1024 * 1024,
        now=datetime(2026, 9, 15, 20, 0, tzinfo=UTC),
    )


def rewrite_bundle(
    index_path: Path,
    mutate: Callable[[dict, dict[str, bytes]], None],
) -> None:
    index = json.loads(index_path.read_text())
    archive_path = index_path.parent / index["parts"][0]["name"]
    with zipfile.ZipFile(archive_path) as archive:
        files = {
            info.filename: archive.read(info)
            for info in archive.infolist()
            if info.filename != "MANIFEST.json"
        }
        manifest = json.loads(archive.read("MANIFEST.json"))
    mutate(manifest, files)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    with zipfile.ZipFile(archive_path, "w", allowZip64=True) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
        archive.writestr("MANIFEST.json", manifest_bytes)
    archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_size = archive_path.stat().st_size
    index["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    index["archive"]["bytes"] = archive_size
    index["archive"]["sha256"] = archive_hash
    index["parts"][0]["bytes"] = archive_size
    index["parts"][0]["sha256"] = archive_hash
    index_path.write_text(json.dumps(index))


def add_declared_file(index_path: Path, relative: str, content: bytes) -> None:
    def add(manifest: dict, files: dict[str, bytes]) -> None:
        files[f"corpus/{relative}"] = content
        manifest["files"].append(
            {
                "path": relative,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
        manifest["file_count"] += 1
        manifest["uncompressed_bytes"] += len(content)

    rewrite_bundle(index_path, add)


def test_team_snapshot_is_consistent_and_excludes_sensitive_data(
    corpus: Path, tmp_path: Path
) -> None:
    index_path = create_bundle(corpus, tmp_path / "out")

    manifest = verify_bundle(index_path)
    paths = {entry["path"] for entry in manifest["files"]}

    assert "mind.db" in paths
    assert "perfis_sociais.jsonl" in paths
    assert any(path.startswith("noticia/") for path in paths)
    assert "_midia/thumbs/imagem.jpg" in paths
    assert "_midia/audio.m4a" not in paths
    assert "_midia/frames/frame.jpg" not in paths
    assert not any("session" in path for path in paths)
    assert manifest["database"]["quick_check"] == "ok"
    assert manifest["database"]["schema_user_version"] == 1
    assert manifest["database"]["documentos"] == 1

    index = json.loads(index_path.read_text())
    archive = index_path.parent / index["parts"][0]["name"]
    with zipfile.ZipFile(archive) as zipped:
        exported = zipped.read("corpus/perfis_sociais.jsonl").decode()
    assert "instagram.com/conta" in exported
    assert "desatualizado" not in exported


def test_full_private_includes_complete_media_but_not_runtime_files(
    corpus: Path, tmp_path: Path
) -> None:
    index_path = create_bundle(corpus, tmp_path / "out", profile="full-private")

    paths = {entry["path"] for entry in verify_bundle(index_path)["files"]}

    assert "_midia/audio.m4a" in paths
    assert "_midia/frames/frame.jpg" in paths
    assert "_midia/incompleto.part" not in paths
    assert "_midia/falha.unknown_video" not in paths
    assert "_telegram.session" not in paths
    assert "instagram-cookies.txt" not in paths
    assert "credentials.json" not in paths
    assert "token.json" not in paths
    assert "client-secret.json" not in paths
    assert "neutral.json" not in paths
    assert "_datasets/service-account.json" not in paths
    assert "_midia/login.json" not in paths
    assert "_midia/video-id.json" in paths
    assert "_tse_abertos/dados.zip" in paths
    assert "private.pem" not in paths
    assert "telegram.session.invalid-backup" not in paths
    assert "_logs/coleta.log" not in paths
    assert "_quarentena/duvida.jsonl" not in paths


def test_pack_uses_sqlite_backup_while_database_is_open(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    output = tmp_path / "out"
    with Store(root) as store:
        assert store.guardar(
            Documento(
                fonte="noticia",
                url="https://example.org/aberta",
                texto="Documento gravado com conexão SQLite ainda aberta.",
            )
        )
        index_path = pack_bundle(
            source_root=root,
            output_dir=output,
            now=datetime(2026, 9, 15, 20, 1, tzinfo=UTC),
        )

    assert verify_bundle(index_path)["database"]["documentos"] == 1


def test_tampered_part_is_rejected(corpus: Path, tmp_path: Path) -> None:
    index_path = create_bundle(corpus, tmp_path / "out")
    index = json.loads(index_path.read_text())
    part = index_path.parent / index["parts"][0]["name"]
    with part.open("ab") as stream:
        stream.write(b"tampered")

    with pytest.raises(BundleError, match="tamanho divergente"):
        verify_bundle(index_path)


def test_split_bundle_can_be_reassembled_and_verified(corpus: Path, tmp_path: Path) -> None:
    index_path = pack_bundle(
        source_root=corpus,
        output_dir=tmp_path / "out",
        profile="team",
        part_size=1_000,
        now=datetime(2026, 9, 15, 20, 2, tzinfo=UTC),
    )
    index = json.loads(index_path.read_text())

    assert len(index["parts"]) > 1
    assert all(part["bytes"] <= 1_000 for part in index["parts"])
    assert verify_bundle(index_path)["database"]["documentos"] == 1


def test_split_failure_removes_partial_parts(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "snapshot.zip"
    archive.write_bytes(b"x" * 3_000)
    original_open = Path.open

    def fail_second_part(path: Path, *args, **kwargs):
        if path.name.endswith("part002") and args and args[0] == "wb":
            raise OSError("falha simulada")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_second_part)

    with pytest.raises(OSError, match="falha simulada"):
        data_bundle._split_archive(archive, 1_000)

    assert archive.exists()
    assert not list(tmp_path.glob("*.part*"))


def test_unlink_failure_removes_all_created_parts(tmp_path: Path, monkeypatch) -> None:
    archive = tmp_path / "snapshot.zip"
    archive.write_bytes(b"x" * 3_000)
    original_unlink = Path.unlink

    def fail_archive_unlink(path: Path, *args, **kwargs):
        if path == archive:
            raise OSError("falha simulada")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_archive_unlink)

    with pytest.raises(OSError, match="falha simulada"):
        data_bundle._split_archive(archive, 1_000)

    assert archive.exists()
    assert not list(tmp_path.glob("*.part*"))


def test_path_traversal_inside_zip_is_rejected(corpus: Path, tmp_path: Path) -> None:
    index_path = create_bundle(corpus, tmp_path / "out")
    index = json.loads(index_path.read_text())
    archive = index_path.parent / index["parts"][0]["name"]
    with zipfile.ZipFile(archive, "a") as zipped:
        zipped.writestr("../escape.txt", "escape")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    size = archive.stat().st_size
    index["archive"]["bytes"] = size
    index["archive"]["sha256"] = checksum
    index["parts"][0]["bytes"] = size
    index["parts"][0]["sha256"] = checksum
    index_path.write_text(json.dumps(index))

    with pytest.raises(BundleError, match="caminho inseguro"):
        verify_bundle(index_path)


def test_windows_drive_path_inside_zip_is_rejected(corpus: Path, tmp_path: Path) -> None:
    index_path = create_bundle(corpus, tmp_path / "out")
    index = json.loads(index_path.read_text())
    archive = index_path.parent / index["parts"][0]["name"]
    with zipfile.ZipFile(archive, "a") as zipped:
        zipped.writestr("corpus/D:/escape.txt", "escape")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    size = archive.stat().st_size
    index["archive"]["bytes"] = size
    index["archive"]["sha256"] = checksum
    index["parts"][0]["bytes"] = size
    index["parts"][0]["sha256"] = checksum
    index_path.write_text(json.dumps(index))

    with pytest.raises(BundleError, match="caminho inseguro"):
        verify_bundle(index_path)


@pytest.mark.parametrize(
    ("profile", "relative"),
    [
        ("team", "_midia/video.mp4"),
        ("full-private", "arquivo-arbitrario.exe"),
    ],
)
def test_declared_file_outside_profile_allowlist_is_rejected(
    corpus: Path, tmp_path: Path, profile: str, relative: str
) -> None:
    index_path = create_bundle(corpus, tmp_path / "out", profile=profile)
    add_declared_file(index_path, relative, b"unexpected")

    with pytest.raises(BundleError, match="não permitido no perfil"):
        verify_bundle(index_path)


def test_database_summary_must_match_archived_sqlite(corpus: Path, tmp_path: Path) -> None:
    index_path = create_bundle(corpus, tmp_path / "out")

    def alter_summary(manifest: dict, _files: dict[str, bytes]) -> None:
        manifest["database"]["documentos"] = 999_999

    rewrite_bundle(index_path, alter_summary)

    with pytest.raises(BundleError, match="resumo do SQLite diverge"):
        verify_bundle(index_path)


def test_restore_preserves_docs_and_keeps_backup_on_replace(corpus: Path, tmp_path: Path) -> None:
    index_path = create_bundle(corpus, tmp_path / "out")
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "README.md").write_text("documentação versionada")

    assert restore_bundle(index_path, destination) is None
    assert (destination / "mind.db").is_file()
    assert (destination / "README.md").read_text() == "documentação versionada"
    connection = sqlite3.connect(destination / "mind.db")
    try:
        stored_path = connection.execute("SELECT arquivo FROM documentos").fetchone()[0]
    finally:
        connection.close()
    assert not Path(stored_path).is_absolute()
    assert Path(stored_path).parts[0] == "noticia"

    marker = destination / "anotacoes-locais.txt"
    marker.write_text("não perder")
    with pytest.raises(BundleError, match="destino já contém dados"):
        restore_bundle(index_path, destination)

    backup = restore_bundle(index_path, destination, replace=True)
    assert backup is not None
    assert (backup / "anotacoes-locais.txt").read_text() == "não perder"
    assert (destination / "README.md").read_text() == "documentação versionada"


def test_pack_rechecks_the_content_written_to_zip(
    corpus: Path, tmp_path: Path, monkeypatch
) -> None:
    original = data_bundle._copy_file_into_zip
    changed = False

    def mutate_before_copy(archive, source, archive_name, created_at):
        nonlocal changed
        if not changed and source.suffix == ".gz":
            changed = True
            extra = Documento(
                fonte="noticia",
                url="https://example.org/race",
                texto="Documento inserido depois da primeira validação.",
            )
            import gzip

            with gzip.open(source, "at", encoding="utf-8") as stream:
                stream.write(extra.to_json() + "\n")
        return original(archive, source, archive_name, created_at)

    monkeypatch.setattr(data_bundle, "_copy_file_into_zip", mutate_before_copy)

    with pytest.raises(BundleError, match="divergem dentro do ZIP"):
        create_bundle(corpus, tmp_path / "out")


def test_pack_rechecks_sensitive_content_written_to_zip(
    corpus: Path, tmp_path: Path, monkeypatch
) -> None:
    original = data_bundle._copy_file_into_zip

    def mutate_before_copy(archive, source, archive_name, created_at):
        if source.name == "video-id.json":
            source.write_text('{"private_key": "secret"}')
        return original(archive, source, archive_name, created_at)

    monkeypatch.setattr(data_bundle, "_copy_file_into_zip", mutate_before_copy)

    with pytest.raises(BundleError, match="conteúdo sensível"):
        create_bundle(corpus, tmp_path / "out", profile="full-private")


def test_pack_rechecks_credentials_hidden_inside_nested_zip(
    corpus: Path, tmp_path: Path, monkeypatch
) -> None:
    original = data_bundle._copy_file_into_zip

    def mutate_before_copy(archive, source, archive_name, created_at):
        if source.name == "dados.zip":
            with zipfile.ZipFile(source, "w") as nested:
                nested.writestr(
                    "service-account.json",
                    '{"private_key": "secret", "client_email": "x@example.org"}',
                )
        return original(archive, source, archive_name, created_at)

    monkeypatch.setattr(data_bundle, "_copy_file_into_zip", mutate_before_copy)

    with pytest.raises(BundleError, match="conteúdo sensível"):
        create_bundle(corpus, tmp_path / "out", profile="full-private")


def test_restore_rolls_back_if_documentation_copy_fails(
    corpus: Path, tmp_path: Path, monkeypatch
) -> None:
    index_path = create_bundle(corpus, tmp_path / "out")
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "README.md").write_text("anterior")
    (destination / "local.txt").write_text("preservar")
    original_write_bytes = Path.write_bytes

    def fail_for_readme(path: Path, content: bytes) -> int:
        if path.name == "README.md" and path != destination / "README.md":
            raise OSError("falha simulada")
        return original_write_bytes(path, content)

    monkeypatch.setattr(Path, "write_bytes", fail_for_readme)

    with pytest.raises(OSError, match="falha simulada"):
        restore_bundle(index_path, destination, replace=True)

    assert (destination / "README.md").read_text() == "anterior"
    assert (destination / "local.txt").read_text() == "preservar"


def test_restore_never_removes_concurrent_file_after_install(
    corpus: Path, tmp_path: Path, monkeypatch
) -> None:
    index_path = create_bundle(corpus, tmp_path / "out")
    destination = tmp_path / "restored"
    destination.mkdir()
    (destination / "README.md").write_text("documentação")
    original_rename = Path.rename

    def create_file_after_install(path: Path, target: Path) -> Path:
        result = original_rename(path, target)
        if target == destination and path.name == "corpus":
            (destination / "concorrente.txt").write_text("preservar")
        return result

    monkeypatch.setattr(Path, "rename", create_file_after_install)

    restore_bundle(index_path, destination)

    assert (destination / "concorrente.txt").read_text() == "preservar"
    assert (destination / "README.md").read_text() == "documentação"


def test_restore_does_not_delete_destination_created_concurrently(
    corpus: Path, tmp_path: Path, monkeypatch
) -> None:
    index_path = create_bundle(corpus, tmp_path / "out")
    destination = tmp_path / "restored"
    original_extract = data_bundle._extract_corpus

    def create_competing_destination(archive_path: Path, staging: Path) -> None:
        original_extract(archive_path, staging)
        destination.mkdir()
        (destination / "concorrente.txt").write_text("preservar")

    monkeypatch.setattr(data_bundle, "_extract_corpus", create_competing_destination)

    with pytest.raises(BundleError, match="destino foi alterado"):
        restore_bundle(index_path, destination)

    assert (destination / "concorrente.txt").read_text() == "preservar"


def test_pack_rejects_divergence_between_sqlite_and_jsonl(corpus: Path, tmp_path: Path) -> None:
    shard = next((corpus / "noticia").glob("*.jsonl.gz"))
    shard.unlink()

    with pytest.raises(BundleError, match="SQLite e JSONL divergem"):
        create_bundle(corpus, tmp_path / "out")


def test_store_rejects_database_from_newer_schema(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    connection = sqlite3.connect(root / "mind.db")
    connection.execute("PRAGMA user_version=99")
    connection.close()

    with pytest.raises(RuntimeError, match="schema do corpus é mais novo"):
        Store(root)
