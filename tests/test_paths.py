import os
import subprocess
import sys
from pathlib import Path

import pytest

from mind_collect.media.images import DESTINO
from mind_collect.paths import (
    CORPUS_ROOT,
    DATA_ROOT,
    LOCAL_STATE_ROOT,
    REPO_ROOT,
    corpus_path,
    relative_to_corpus,
    resolve_corpus_reference,
)
from mind_collect.sources.datasets import DIR as DATASETS_DIR
from mind_collect.sources.dou import DIR as DOU_DIR
from mind_collect.sources.dou_espelho import PARQUET
from mind_collect.sources.instagram import MIDIA as INSTAGRAM_MIDIA
from mind_collect.sources.telegram import SESSAO
from mind_collect.sources.tiktok import MIDIA as TIKTOK_MIDIA
from mind_collect.sources.tse import DIR as TSE_DIR
from mind_collect.sources.tse_abertos import DIR as TSE_ABERTOS_DIR
from mind_collect.sources.tse_radio import MIDIA as TSE_RADIO_MIDIA
from mind_collect.sources.youtube import MIDIA as YOUTUBE_MIDIA
from mind_collect.store import RAIZ


def test_roots_use_real_repository_location() -> None:
    expected_repo = Path(__file__).resolve().parents[1]

    assert expected_repo == REPO_ROOT
    assert REPO_ROOT.is_absolute()
    assert expected_repo / "data" == DATA_ROOT
    assert expected_repo / "data" / "eleicoes2026" == CORPUS_ROOT


def test_corpus_path_is_independent_from_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert corpus_path("_midia", "arquivo.mp4") == (CORPUS_ROOT / "_midia" / "arquivo.mp4")


@pytest.mark.parametrize("parts", [("..", "fora"), (REPO_ROOT.parent / "outside",)])
def test_corpus_path_rejects_paths_outside_corpus(parts: tuple[str | Path, ...]) -> None:
    with pytest.raises(ValueError, match="fora da raiz do corpus"):
        corpus_path(*parts)


def test_public_corpus_constants_are_absolute() -> None:
    paths = (
        RAIZ,
        DESTINO,
        DOU_DIR,
        TSE_ABERTOS_DIR,
        DATASETS_DIR,
        TSE_DIR,
        YOUTUBE_MIDIA,
        PARQUET,
        TIKTOK_MIDIA,
        TSE_RADIO_MIDIA,
        INSTAGRAM_MIDIA,
    )

    assert all(path.is_absolute() for path in paths)
    assert all(path == CORPUS_ROOT or CORPUS_ROOT in path.parents for path in paths)
    assert SESSAO == LOCAL_STATE_ROOT / "telegram.session"
    assert CORPUS_ROOT not in SESSAO.parents


def test_persisted_path_is_relative_and_portable(tmp_path: Path) -> None:
    root = tmp_path / "dados"
    path = root / "noticia" / "arquivo.jsonl.gz"

    assert relative_to_corpus(path, root) == "noticia/arquivo.jsonl.gz"
    assert resolve_corpus_reference("noticia/arquivo.jsonl.gz", root) == path


def test_resolves_legacy_and_foreign_absolute_paths(tmp_path: Path) -> None:
    root = tmp_path / "dados"
    expected = root / "noticia" / "arquivo.jsonl.gz"

    assert resolve_corpus_reference("data/eleicoes2026/noticia/arquivo.jsonl.gz", root) == expected
    assert (
        resolve_corpus_reference(
            "/Users/outra/pessoa/MIND/data/eleicoes2026/noticia/arquivo.jsonl.gz",
            root,
        )
        == expected
    )
    assert (
        resolve_corpus_reference(
            r"C:\Users\outra\MIND\data\eleicoes2026\noticia\arquivo.jsonl.gz",
            root,
        )
        == expected
    )


@pytest.mark.parametrize(
    "reference",
    ["../secret", "/tmp/secret", r"C:\Users\outra\secret.txt", r"C:secret.txt"],
)
def test_rejects_reference_outside_corpus(tmp_path: Path, reference: str) -> None:
    with pytest.raises(ValueError, match="fora da raiz do corpus"):
        resolve_corpus_reference(reference, tmp_path / "dados")


def test_data_root_can_be_configured_before_process_start(tmp_path: Path) -> None:
    configured = tmp_path / "dados compartilhados" / "eleições"
    environment = {**os.environ, "MIND_DATA_DIR": str(configured)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from mind_collect.paths import CORPUS_ROOT; print(CORPUS_ROOT)",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert Path(result.stdout.strip()) == configured


def test_store_reads_legacy_reference_from_any_checkout(tmp_path: Path) -> None:
    from mind_collect.schema import Documento
    from mind_collect.store import Store

    with Store(tmp_path) as store:
        document = Documento(
            fonte="noticia",
            url="https://example.org/legado",
            texto="Documento com caminho legado no banco.",
        )
        assert store.guardar(document)
        stored = store.con.execute(
            "SELECT arquivo FROM documentos WHERE doc_id=?", (document.doc_id,)
        ).fetchone()[0]
        foreign = f"/Users/outra/MIND/data/eleicoes2026/{stored}"
        store.con.execute(
            "UPDATE documentos SET arquivo=? WHERE doc_id=?", (foreign, document.doc_id)
        )
        store.con.commit()

        assert [item.doc_id for item in store.ler_ids([document.doc_id])] == [document.doc_id]
