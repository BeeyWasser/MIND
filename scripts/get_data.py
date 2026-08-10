#!/usr/bin/env python3
"""Baixa as bases de dados do MIND para a pasta data/.

    python3 scripts/get_data.py            baixa tudo
    python3 scripts/get_data.py --list     mostra o que já está baixado
    python3 scripts/get_data.py --only wnc mentalmanip

Os dados não ficam no git. Este script reconstrói data/ do zero.
O que é cada base está explicado em DADOS.md.

Só usa a biblioteca padrão do Python. Nada para instalar.
"""

import argparse
import os
import shutil
import socket
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile

GITHUB = "https://codeload.github.com/%s/tar.gz/refs/heads/%s"

# key, o que é, tamanho, de onde vem, como extrair.
# `só` = extrai apenas estes caminhos. `tirar` = remove este prefixo dos caminhos.
# `achar` = arquivo que precisa existir no fim; se não existir, algo deu errado.
BASES = [
    {
        "key": "semeval2021-t6",
        "oque": "20 técnicas de persuasão em memes (inglês)",
        "tam": "63 MB",
        "url": GITHUB % ("di-dimitrov/SEMEVAL-2021-task6-corpus", "main"),
        "achar": "data/training_set_task1.txt",
    },
    {
        "key": "mentalmanip",
        "oque": "4.000 diálogos com técnica de manipulação (inglês)",
        "tam": "18 MB",
        "url": GITHUB % ("audreycs/MentalManip", "main"),
        "só": ["mentalmanip_dataset/"],
        "tirar": "mentalmanip_dataset/",
        "achar": "mentalmanip_detailed.csv",
    },
    {
        "key": "wnc",
        "oque": "180 mil pares frase enviesada → frase neutra (inglês)",
        "tam": "110 MB",
        "url": "https://nlp.stanford.edu/projects/bias/bias_data.zip",
        "só": ["bias_data/WNC/biased.", "bias_data/real_world_samples/", "bias_data/README"],
        "tirar": "bias_data/",
        "achar": "WNC/biased.word.train",
    },
    {
        "key": "dark-patterns",
        "oque": "1.818 dark patterns de e-commerce (inglês)",
        "tam": "2 MB",
        "url": GITHUB % ("aruneshmathur/dark-patterns", "master"),
        "só": ["data/final-dark-patterns/"],
        "tirar": "data/final-dark-patterns/",
        "achar": "dark-patterns.csv",
    },
    {
        "key": "ec-darkpattern",
        "oque": "2.361 frases rotuladas dark / não-dark (inglês)",
        "tam": "1 MB",
        "url": GITHUB % ("yamanalab/ec-darkpattern", "master"),
        "só": ["dataset/"],
        "tirar": "dataset/",
        "achar": "dataset.tsv",
    },
    {
        "key": "anthropic-persuasion",
        "oque": "3.939 argumentos com efeito persuasivo medido (inglês)",
        "tam": "3 MB",
        "url": "https://huggingface.co/datasets/Anthropic/persuasion/resolve/main/persuasion_data.csv",
        "achar": "persuasion_data.csv",
    },
    {
        "key": "hatebr",
        "oque": "7.000 comentários ofensivos do Instagram (PT-BR)",
        "tam": "1 MB",
        "url": GITHUB % ("franciellevargas/HateBR", "main"),
        "só": ["dataset/", "annotators/"],
        "achar": "dataset/HateBR.csv",
    },
    {
        "key": "told-br",
        "oque": "21.000 tweets com linguagem tóxica (PT-BR)",
        "tam": "7 MB",
        "url": GITHUB % ("JAugusto97/ToLD-Br", "main"),
        "só": ["ToLD-BR.csv", "ToLD-BR_alpha.csv", "LICENSE"],
        "achar": "ToLD-BR.csv",
    },
    {
        "key": "fakebr",
        "oque": "7.200 notícias, metade falsas (PT-BR)",
        "tam": "21 MB",
        "url": GITHUB % ("roneysco/Fake.br-Corpus", "master"),
        "achar": "full_texts",
    },
    {
        "key": "fakerecogna",
        "oque": "11.903 notícias de agências de checagem (PT-BR)",
        "tam": "30 MB",
        "url": "https://huggingface.co/datasets/recogna-nlp/FakeRecogna/resolve/main/FakeRecogna.csv",
        "achar": "FakeRecogna.csv",
    },
    {
        "key": "clickbait17",
        "oque": "posts com intensidade de clickbait (inglês)",
        "tam": "148 MB",
        "extra": True,  # pesada: só baixa com --only clickbait17
        "url": "https://zenodo.org/records/5530410/files/clickbait17-train-170331.zip/content",
        "achar": "clickbait17-train-170331",
    },
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# Sem isto, um servidor travado deixa o download pendurado para sempre.
# É timeout por leitura, então download lento (o do WNC é) continua funcionando.
socket.setdefaulttimeout(120)


def prefixo_comum(nomes):
    """Tarball do GitHub vem dentro de uma pasta tipo 'MentalManip-main/'.

    Devolve esse nível para a gente jogar fora, ou '' se não houver um só.
    """
    tops = set()
    for n in nomes:
        topo = n.split("/", 1)[0]
        if topo:
            tops.add(topo)
        if len(tops) > 1:
            return ""
    return (tops.pop() + "/") if tops else ""


def seguro(rel):
    """Bloqueia path traversal: arquivo baixado não escreve fora de data/."""
    if not rel or rel.startswith(("/", "\\")) or os.path.isabs(rel):
        return False
    return ".." not in rel.replace("\\", "/").split("/")


def escolhido(rel, so):
    return True if not so else any(rel == s or rel.startswith(s) for s in so)


def extrair(nomes, ler, destino, so, tirar):
    """Escreve os arquivos escolhidos em destino/. `ler(nome)` devolve bytes ou None."""
    corte = prefixo_comum(nomes)
    n = 0
    for nome in nomes:
        rel = nome[len(corte):] if corte and nome.startswith(corte) else nome
        if not rel or not seguro(rel) or not escolhido(rel, so):
            continue
        if tirar and rel.startswith(tirar):
            rel = rel[len(tirar):]
            if not rel:
                continue
        dados = ler(nome)
        if dados is None:
            continue
        saida = os.path.join(destino, rel)
        os.makedirs(os.path.dirname(saida), exist_ok=True)
        with open(saida, "wb") as fh:
            fh.write(dados)
        n += 1
    return n


def descompactar(arquivo, destino, so, tirar):
    if zipfile.is_zipfile(arquivo):
        with zipfile.ZipFile(arquivo) as zf:
            ler = lambda nome: None if nome.endswith("/") else zf.read(nome)  # noqa: E731
            return extrair(zf.namelist(), ler, destino, so, tirar)

    with tarfile.open(arquivo, "r:gz") as tf:
        itens = {m.name: m for m in tf.getmembers()}

        def ler(nome):
            item = itens[nome]
            if not item.isfile():
                return None
            fh = tf.extractfile(item)
            return fh.read() if fh else None

        return extrair(list(itens), ler, destino, so, tirar)


def baixar(url, caminho):
    # Barra de progresso só num terminal. Redirecionada para arquivo,
    # cada \r vira uma linha nova e o log explode.
    if not sys.stdout.isatty():
        urllib.request.urlretrieve(url, caminho)
        return

    def progresso(blocos, tam_bloco, total):
        if total > 0:
            pct = min(100, blocos * tam_bloco * 100 // total)
            sys.stdout.write("\r    baixando... %3d%% de %.0f MB" % (pct, total / 1e6))
            sys.stdout.flush()

    urllib.request.urlretrieve(url, caminho, reporthook=progresso)
    sys.stdout.write("\r" + " " * 40 + "\r")


def pegar(base, refazer=False):
    key = base["key"]
    destino = os.path.join(DATA, key)
    esperado = os.path.join(destino, base["achar"])

    if os.path.exists(esperado) and not refazer:
        print("  ok       %s (já baixado)" % key)
        return True

    print("  baixando %s — %s" % (key, base["tam"]))
    if refazer and os.path.isdir(destino):
        shutil.rmtree(destino)
    os.makedirs(destino, exist_ok=True)

    tmp = tempfile.mkdtemp(prefix="mind-")
    arquivo = os.path.join(tmp, key)
    try:
        baixar(base["url"], arquivo)
        if base["url"].endswith(".csv"):
            shutil.move(arquivo, esperado)
            n = 1
        else:
            n = descompactar(arquivo, destino, base.get("só"), base.get("tirar"))
    except (urllib.error.URLError, OSError) as erro:
        print("  ERRO     %s — não deu para baixar: %s" % (key, erro))
        return False
    except (tarfile.TarError, zipfile.BadZipFile) as erro:
        print("  ERRO     %s — arquivo veio corrompido: %s" % (key, erro))
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not os.path.exists(esperado):
        print("  ERRO     %s — extraiu %d arquivos, mas '%s' não apareceu."
              % (key, n, base["achar"]))
        print("           O repositório de origem deve ter mudado de estrutura.")
        return False

    print("  ok       %s — %d arquivos em data/%s/" % (key, n, key))
    return True


def listar():
    print("\nBases do MIND — o que é cada uma está em DADOS.md\n")
    for b in BASES:
        tem = os.path.exists(os.path.join(DATA, b["key"], b["achar"]))
        extra = "  (pesada, baixe com --only)" if b.get("extra") else ""
        print("  %s %-22s %-9s %s%s"
              % ("✓" if tem else " ", b["key"], b["tam"], b["oque"], extra))
    print("\n  ✓ = já está em data/")
    print("\nO SemEval-2023 (a melhor base para o projeto) exige cadastro e não")
    print("entra aqui. O passo a passo está em DADOS.md.\n")


def autoteste():
    """Testa a lógica de extração, que é a única parte não óbvia daqui."""
    assert prefixo_comum(["repo-main/a", "repo-main/b/c"]) == "repo-main/"
    assert prefixo_comum(["a", "b/c"]) == ""
    assert seguro("data/x.csv") and not seguro("../etc/passwd") and not seguro("/etc/passwd")
    assert escolhido("dataset/x", ["dataset/"]) and not escolhido("outro/x", ["dataset/"])
    assert escolhido("qualquer", None)

    tmp = tempfile.mkdtemp(prefix="mind-teste-")
    try:
        origem = os.path.join(tmp, "repo-main", "dataset")
        os.makedirs(origem)
        open(os.path.join(origem, "d.tsv"), "w").write("ok")
        open(os.path.join(tmp, "repo-main", "pular.txt"), "w").write("nao")
        arq = os.path.join(tmp, "a.tgz")
        with tarfile.open(arq, "w:gz") as tf:
            tf.add(os.path.join(tmp, "repo-main"), arcname="repo-main")
            malicioso = tarfile.TarInfo("repo-main/../invasor.txt")
            malicioso.size = 0
            tf.addfile(malicioso, None)

        saida = os.path.join(tmp, "out")
        assert descompactar(arq, saida, ["dataset/"], None) == 1
        assert open(os.path.join(saida, "dataset", "d.tsv")).read() == "ok"
        assert not os.path.exists(os.path.join(saida, "pular.txt"))
        assert not os.path.exists(os.path.join(tmp, "invasor.txt"))

        saida2 = os.path.join(tmp, "out2")
        assert descompactar(arq, saida2, ["dataset/"], "dataset/") == 1
        assert os.path.exists(os.path.join(saida2, "d.tsv"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("autoteste: ok")


def main():
    ap = argparse.ArgumentParser(description="Baixa as bases de dados do MIND.")
    ap.add_argument("--list", action="store_true", help="mostra o que já está baixado")
    ap.add_argument("--only", nargs="+", metavar="BASE", help="baixa só estas bases")
    ap.add_argument("--force", action="store_true", help="baixa de novo mesmo se já existir")
    ap.add_argument("--selftest", action="store_true", help="testa a lógica de extração")
    args = ap.parse_args()

    if args.selftest:
        return autoteste()
    if args.list:
        return listar()

    if args.only:
        escolhidas = []
        for k in args.only:
            achou = next((b for b in BASES if b["key"] == k), None)
            if achou is None:
                print("não conheço a base '%s'. Use --list para ver as opções." % k)
                return 2
            escolhidas.append(achou)
    else:
        escolhidas = [b for b in BASES if not b.get("extra")]

    os.makedirs(DATA, exist_ok=True)
    print("\nBaixando %d base(s) para data/\n" % len(escolhidas))
    falhou = [b["key"] for b in escolhidas if not pegar(b, args.force)]

    if falhou:
        print("\nNão deu certo: %s" % ", ".join(falhou))
        print("Rode de novo — o script pula o que já baixou.")
        return 1
    print("\nPronto. O que é cada base está em DADOS.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
