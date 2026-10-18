"""Caminhos absolutos do corpus, independentes do diretório de execução."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath, PureWindowsPath

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = REPO_ROOT / "data"
LOCAL_STATE_ROOT = (
    Path(os.environ.get("MIND_STATE_DIR", REPO_ROOT / ".local-state" / "mind"))
    .expanduser()
    .resolve()
)


def configured_corpus_root() -> Path:
    """Raiz configurável, com padrão no checkout para manter o uso atual."""
    configured = os.environ.get("MIND_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (DATA_ROOT / "eleicoes2026").resolve()


CORPUS_ROOT = configured_corpus_root()


def corpus_path(*parts: str | Path) -> Path:
    """Resolve um caminho interno ao corpus e rejeita escapes da raiz."""
    path = CORPUS_ROOT.joinpath(*parts).resolve()
    if path != CORPUS_ROOT and CORPUS_ROOT not in path.parents:
        raise ValueError("caminho fora da raiz do corpus")
    return path


def relative_to_corpus(path: Path, root: Path = CORPUS_ROOT) -> str:
    """Converte um caminho local em referência POSIX portável para o SQLite."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"caminho fora da raiz do corpus: {path}") from error


def resolve_corpus_reference(value: str | Path, root: Path = CORPUS_ROOT) -> Path:
    """Resolve referências novas, legadas e absolutas de outro checkout."""
    root = root.resolve()
    raw = str(value)
    native = Path(value)
    if native.is_absolute():
        resolved_native = native.resolve()
        if resolved_native == root or root in resolved_native.parents:
            return resolved_native
        parts = native.parts
        try:
            marker = parts.index("eleicoes2026")
        except ValueError as error:
            raise ValueError(f"referência fora da raiz do corpus: {value}") from error
        reference = Path(*parts[marker + 1 :])
    elif "\\" in raw or PureWindowsPath(raw).drive:
        windows = PureWindowsPath(raw)
        try:
            marker = windows.parts.index("eleicoes2026")
        except ValueError:
            if windows.drive or windows.is_absolute() or ".." in windows.parts:
                raise ValueError(f"referência fora da raiz do corpus: {value}") from None
            reference = Path(*windows.parts)
        else:
            reference = Path(*windows.parts[marker + 1 :])
    elif PurePosixPath(raw).is_absolute():
        posix = PurePosixPath(raw)
        try:
            marker = posix.parts.index("eleicoes2026")
        except ValueError as error:
            raise ValueError(f"referência fora da raiz do corpus: {value}") from error
        reference = Path(*posix.parts[marker + 1 :])
    else:
        reference = Path(value)
    if not reference.is_absolute():
        parts = reference.parts
        if len(parts) >= 2 and parts[:2] == ("data", "eleicoes2026"):
            reference = Path(*parts[2:])
        candidate = (root / reference).resolve()
    else:
        candidate = reference.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"referência fora da raiz do corpus: {value}")
    return candidate
