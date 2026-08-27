"""CLI da coleta.

    uv run python -m mind_collect.run --list
    uv run python -m mind_collect.run --only g1-politica ebc-politica
    uv run python -m mind_collect.run --rapido      # sem baixar texto completo

Roda de novo e pula o que já baixou — mesmo idioma do scripts/get_data.py.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .http import Cliente
from .sources import (
    camara,
    commoncrawl,
    gdelt,
    mediacloud,
    mencoes,
    meta_ads,
    reddit,
    rss,
    senado,
    sitemap,
    telegram,
    tiktok,
    tse,
    youtube,
)
from .store import Store


def coletar_rss(store: Store, cliente: Cliente, chaves: list[str], completo: bool) -> None:
    feeds = [rss.POR_CHAVE[k] for k in chaves] if chaves else rss.FEEDS
    for feed in feeds:
        exec_id = store.iniciar_execucao(feed.chave)
        novos = repetidos = erros = 0
        descartados: list = []
        detalhe = ""
        try:
            for doc in rss.coletar(cliente, feed, completo=completo, descartados=descartados):
                if store.guardar(doc):
                    novos += 1
                else:
                    repetidos += 1
        except Exception as e:  # coletor que cai não derruba os outros
            erros += 1
            detalhe = f"{type(e).__name__}: {e}"[:300]
        store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
        marca = "!" if erros else " "
        curtos = f"curtos={len(descartados):<4}" if descartados else ""
        print(f"{marca} {feed.chave:20} novos={novos:<5} "
              f"repetidos={repetidos:<5} {curtos} {detalhe}")


def coletar_video(store: Store, chaves: list[str], transcrever: bool,
                  com_frames: bool = False) -> None:
    sementes = [youtube.POR_CHAVE[k] for k in chaves] if chaves else youtube.SEMENTES
    vistos = {
        r[0] for r in store.con.execute(
            "SELECT url FROM documentos WHERE fonte LIKE 'hgpe%'"
        )
    }

    def ja_tem(video_id: str) -> bool:
        return any(video_id in u for u in vistos)

    for semente in sementes:
        exec_id = store.iniciar_execucao(semente.chave)
        novos = repetidos = erros = 0
        detalhe = ""
        try:
            for doc, frames in youtube.coletar(semente, ja_tem,
                                               transcrever_audio=transcrever,
                                               com_frames=com_frames):
                if store.guardar(doc):
                    novos += 1
                    vistos.add(doc.url)
                    for m in frames:
                        store.guardar_midia(m)
                else:
                    repetidos += 1
        except Exception as e:
            erros += 1
            detalhe = f"{type(e).__name__}: {e}"[:300]
        store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
        marca = "!" if erros else " "
        print(f"{marca} {semente.chave:20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_cc(store: Store, chaves: list[str], de: str | None, limite: int,
               origem: str = "cc") -> None:
    catalogo = (commoncrawl.POR_CHAVE_WAYBACK if origem == "ia"
                else commoncrawl.POR_CHAVE)
    alvos = [catalogo[k] for k in chaves] if chaves else list(catalogo.values())
    for alvo in alvos:
        exec_id = store.iniciar_execucao(alvo.chave)
        novos = repetidos = erros = 0
        detalhe = ""
        try:
            for doc in commoncrawl.coletar(alvo, de=de, limite=limite, origem=origem):
                if store.guardar(doc):
                    novos += 1
                else:
                    repetidos += 1
        except Exception as e:
            erros += 1
            detalhe = f"{type(e).__name__}: {e}"[:300]
        store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
        marca = "!" if erros else " "
        print(f"{marca} {alvo.chave:20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_sitemap(store: Store, cliente: Cliente, chaves: list[str], limite: int) -> None:
    mapas = [sitemap.POR_CHAVE[k] for k in chaves] if chaves else sitemap.MAPAS
    for mapa in mapas:
        exec_id = store.iniciar_execucao(mapa.chave)
        novos = repetidos = erros = 0
        detalhe = ""
        try:
            for doc in sitemap.coletar(cliente, mapa, limite=limite):
                if store.guardar(doc):
                    novos += 1
                else:
                    repetidos += 1
        except Exception as e:
            erros += 1
            detalhe = f"{type(e).__name__}: {e}"[:300]
        store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
        marca = "!" if erros else " "
        print(f"{marca} {mapa.chave:20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_ads(store: Store, de: str | None, ate: str | None) -> None:
    exec_id = store.iniciar_execucao("meta_ads")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        for anuncio in meta_ads.buscar(termos="eleições", de=de, ate=ate):
            doc = meta_ads.para_documento(anuncio)
            if store.guardar(doc):
                novos += 1
            else:
                repetidos += 1
    except meta_ads.SemToken as e:
        detalhe = str(e)[:200]
        erros = 1
    except Exception as e:
        erros = 1
        detalhe = f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'meta_ads':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_gdelt(store: Store, pacotes: list[str] | None) -> None:
    exec_id = store.iniciar_execucao("gdelt")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        for doc in gdelt.coletar(pacotes):
            if store.guardar(doc):
                novos += 1
            else:
                repetidos += 1
    except Exception as e:
        erros = 1
        detalhe = f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'gdelt':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def ciclo(store: Store, transcrever: bool = True, workers: int = 5) -> None:
    """Uma passada por tudo que é incremental.

    As fontes ligadas a rede rodam em paralelo: cada uma espera servidor
    diferente, e serializá-las faz a passada durar a soma em vez do máximo. O
    Store é protegido por trava, e o limite de requisições continua sendo por
    host, não global — paralelizar aqui não deixa a coleta menos educada.

    As ligadas a computação (transcrição, OCR) ficam de fora: elas disputam o
    Metal entre si e paralelizar só faria a fila esperar mais.

    Coletor que cai não derruba os outros, e a deduplicação faz cada passada
    pular o que já existe.
    """
    tarefas: list[tuple[str, Callable[[], None]]] = [
        ("rss", lambda: _com_cliente(coletar_rss, store, [], completo=True)),
        ("sitemap", lambda: _com_cliente(coletar_sitemap, store, [], limite=200)),
        ("gdelt", lambda: coletar_gdelt(store, None)),
        ("camara", lambda: coletar_camara(store, None, None)),
        ("senado", lambda: coletar_senado(store, None, None)),
        ("reddit", lambda: coletar_reddit(store, [], de=None, por_sub=200)),
    ]
    est = telegram.estado()
    if est == "pronto":
        tarefas.append(("telegram", lambda: coletar_telegram(store, [], por_canal=200)))
    else:
        print(f"  {'telegram':20} pulado ({est})")
    if os.environ.get("META_ADS_TOKEN"):
        tarefas.append(("meta_ads", lambda: coletar_ads(store, None, None)))
    if os.environ.get("MEDIACLOUD_API_KEY"):
        tarefas.append(("mediacloud", lambda: coletar_mediacloud(store, None, None)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(f): nome for nome, f in tarefas}
        for fut in as_completed(futuros):
            nome = futuros[fut]
            try:
                fut.result()
            except Exception as e:
                print(f"! {nome:20} {type(e).__name__}: {e}"[:200])

    # Pista de computação, em série: disputa o Metal.
    coletar_video(store, [], transcrever=transcrever)
    coletar_social(store, limite=25, transcrever=transcrever)


def _com_cliente(fn, store, *args, **kw) -> None:
    """Cada tarefa com seu próprio Cliente: o estado de rate limit por host é
    do cliente, e compartilhar um entre threads embaralharia a contagem."""
    with Cliente() as c:
        fn(store, c, *args, **kw)


def coletar_camara(store: Store, de: str | None, ate: str | None) -> None:
    exec_id = store.iniciar_execucao("camara")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        for doc in camara.coletar(de=de, ate=ate):
            if store.guardar(doc):
                novos += 1
            else:
                repetidos += 1
    except Exception as e:
        erros = 1
        detalhe = f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'camara':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_social(store: Store, limite: int, transcrever: bool) -> None:
    """TikTok e Instagram, a partir de URLs citadas no que já foi coletado."""
    achados = mencoes.varrer(store.ler(), plataformas=("tiktok", "instagram"))
    vistas = {r[0] for r in store.con.execute(
        "SELECT url FROM documentos WHERE fonte IN ('tiktok','instagram')")}
    fila = [u for plat in achados for u, _ in achados[plat].most_common()]
    exec_id = store.iniciar_execucao("social")
    novos = repetidos = erros = 0
    detalhe = f"descobertas={len(fila)}"
    try:
        for doc in tiktok.coletar(fila, lambda u: u in vistas,
                                  transcrever_audio=transcrever, limite=limite):
            if store.guardar(doc):
                novos += 1
            else:
                repetidos += 1
    except Exception as e:
        erros = 1
        detalhe += f" {type(e).__name__}: {e}"[:200]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'social':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_mediacloud(store: Store, de: str | None, ate: str | None) -> None:
    exec_id = store.iniciar_execucao("mediacloud")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        for doc in mediacloud.coletar(de=de, ate=ate):
            if store.guardar(doc):
                novos += 1
            else:
                repetidos += 1
    except mediacloud.SemChave as e:
        erros, detalhe = 1, str(e)[:200]
    except Exception as e:
        erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'mediacloud':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_reddit(store: Store, subs: list[str], de: str | None, por_sub: int) -> None:
    exec_id = store.iniciar_execucao("reddit")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        for doc in reddit.coletar(subs or None, de=de, por_sub=por_sub):
            if store.guardar(doc):
                novos += 1
            else:
                repetidos += 1
    except Exception as e:
        erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'reddit':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_senado(store: Store, de: str | None, ate: str | None) -> None:
    exec_id = store.iniciar_execucao("senado")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        for doc in senado.coletar(de=de, ate=ate):
            if store.guardar(doc):
                novos += 1
            else:
                repetidos += 1
    except Exception as e:
        erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'senado':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_telegram(store: Store, canais: list[str], por_canal: int) -> None:
    # Menções t.me no corpus somam à lista-semente: canal citado por outra fonte
    # circulou, e é por onde começar.
    achados = mencoes.varrer(store.ler(), plataformas=("telegram",))
    extras = [u for u, _ in achados.get("telegram", Counter()).most_common(40)]
    alvos = canais or (telegram.SEMENTES + extras)

    exec_id = store.iniciar_execucao("telegram")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        for doc in telegram.coletar(alvos, por_canal=por_canal):
            if store.guardar(doc):
                novos += 1
            else:
                repetidos += 1
    except telegram.SemCredencial as e:
        erros, detalhe = 1, str(e)[:200]
    except Exception as e:
        erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'telegram':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def login_telegram(telefone: str | None = None) -> int:
    """Login interativo, uma vez. A sessão fica em disco e o ciclo roda sozinho."""
    if not sys.stdin.isatty():
        print(
            "o login do Telegram precisa de terminal interativo — ele pergunta o\n"
            "telefone e o código que chega no app, e a entrada aqui não é um TTY.\n\n"
            "abra o Terminal e rode, dentro da pasta do projeto:\n"
            "  uv run python -m mind_collect.run --telegram-login\n\n"
            "é uma vez só: a sessão fica em " + str(telegram.SESSAO) + "\n"
            "e o ciclo horário passa a coletar sozinho.",
            file=sys.stderr,
        )
        return 2
    try:
        with telegram.cliente() as c:
            c.start(phone=telefone) if telefone else c.start()
            eu = c.get_me()
            print(f"autenticado como {eu.first_name} (id {eu.id})")
            print(f"sessão em {telegram.SESSAO}")
        return 0
    except telegram.SemCredencial as e:
        print(e, file=sys.stderr)
        return 2


def relatorio(store: Store) -> None:
    linhas = store.cobertura()
    if not linhas:
        print("corpus vazio")
        return
    print(f"{'fonte':16} {'modalidade':11} {'docs':>7}  período")
    total = 0
    for fonte, modalidade, n, de, ate in linhas:
        periodo = de if de == ate else f"{de} → {ate}"
        print(f"{fonte:16} {modalidade:11} {n:>7}  {periodo}")
        total += n
    print(f"{'':16} {'':11} {total:>7}  total")

    treinaveis = sum(1 for _ in store.ler(treinavel=True))
    print(f"\ntreináveis: {treinaveis}  |  só referência: {total - treinaveis}")

    for fonte in {r[0] for r in linhas}:
        if b := store.buracos(fonte):
            print(f"  buraco em {fonte}: {len(b)} dia(s) sem coleta — {b[0]}…{b[-1]}")


def carregar_env(caminho: Path = Path(".env")) -> None:
    """Lê o .env sem dependência nova. Variável já no ambiente tem precedência."""
    if not caminho.exists():
        return
    for linha in caminho.read_text().splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave, valor = chave.strip(), valor.strip().strip("\"'")
        if valor and chave not in os.environ:
            os.environ[chave] = valor


def credenciais() -> None:
    """O que está configurado e o que cada ausência custa."""
    itens = [
        ("META_ADS_TOKEN", "Biblioteca de Anúncios da Meta", "~3M anúncios com gasto e alcance"),
        ("TELEGRAM_API_ID", "Telegram", "histórico integral de canal público"),
        ("MEDIACLOUD_API_KEY", "Media Cloud", "2 bi de matérias"),
        ("REDDIT_CLIENT_ID", "Reddit ao vivo", "só 2026; o dump cobre até 2025/12"),
        ("YOUTUBE_API_KEY", "YouTube API", "opcional: comentários em volume"),
    ]
    print(f"{'':2}{'variável':22}{'fonte':32}efeito da ausência")
    for chave, fonte, efeito in itens:
        marca = "ok" if os.environ.get(chave) else "--"
        print(f"{marca:2}{chave:22}{fonte:32}{'' if os.environ.get(chave) else efeito}")
    est = telegram.estado()
    if est != "pronto":
        print(f"\ntelegram: {est}"
              + ("  → uv run python -m mind_collect.run --telegram-login"
                 if est == "sem_login" else ""))
    if not Path(".env").exists():
        print("\nsem .env — copie de .env.exemplo e preencha o que tiver")


def main(argv: list[str] | None = None) -> int:
    carregar_env()
    p = argparse.ArgumentParser(prog="mind_collect", description=__doc__)
    p.add_argument("--only", nargs="+", metavar="CHAVE", help="coletar só estes feeds")
    p.add_argument("--list", action="store_true", help="mostrar cobertura do corpus")
    p.add_argument("--feeds", action="store_true", help="listar feeds disponíveis")
    p.add_argument("--rapido", action="store_true", help="não baixar o texto completo")
    p.add_argument("--video", action="store_true", help="coletar vídeo (HGPE, YouTube)")
    p.add_argument("--commoncrawl", action="store_true", help="varrer o índice do Common Crawl")
    p.add_argument("--sitemap", action="store_true", help="varrer sitemaps dos portais")
    p.add_argument("--gdelt", action="store_true", help="descobrir URLs pelo GDELT")
    p.add_argument("--camara", action="store_true", help="discursos da Câmara dos Deputados")
    p.add_argument("--senado", action="store_true", help="discursos do plenário do Senado")
    p.add_argument("--reddit", action="store_true", help="arquivo do Reddit via arctic_shift")
    p.add_argument("--mediacloud", action="store_true", help="arquivo do Media Cloud")
    p.add_argument("--wayback", action="store_true",
                   help="recuperar conteúdo removido pelo Internet Archive")
    p.add_argument("--frames", action="store_true",
                   help="extrair keyframes e OCR do vídeo (baixa o vídeo inteiro)")
    p.add_argument("--social", action="store_true",
                   help="TikTok e Instagram citados no corpus")
    p.add_argument("--telegram", action="store_true", help="canais públicos do Telegram")
    p.add_argument("--telegram-login", action="store_true",
                   help="login interativo do Telegram, uma vez só (exige terminal)")
    p.add_argument("--telefone", help="telefone com +55, para poupar uma pergunta no login")
    p.add_argument("--tse", action="store_true", help="mostrar o registro de candidaturas")
    p.add_argument("--credenciais", action="store_true", help="o que está configurado")
    p.add_argument("--workers", type=int, default=5, help="tarefas de rede em paralelo")
    p.add_argument("--ciclo", action="store_true",
                   help="uma passada por tudo que é incremental (usado pelo launchd)")
    p.add_argument("--ads", action="store_true", help="varrer a Biblioteca de Anúncios da Meta")
    p.add_argument("--de", metavar="AAAAMM", help="início da janela")
    p.add_argument("--ate", metavar="AAAAMM", help="fim da janela")
    p.add_argument("--limite", type=int, default=500, help="capturas por alvo (Common Crawl)")
    p.add_argument("--sem-transcricao", action="store_true",
                   help="baixar vídeo sem transcrever — só metadados")
    a = p.parse_args(argv)

    if a.telegram_login:
        return login_telegram(a.telefone)
    if a.credenciais:
        credenciais()
        return 0
    if a.tse:
        print(tse.resumo(tse.carregar()))
        return 0
    if a.feeds:
        for f in rss.FEEDS:
            print(f"  {f.chave:20} {f.fonte:9} {f.licenca:11} {f.url}")
        for s_ in youtube.SEMENTES:
            print(f"  {s_.chave:20} {'video':9} {'livre':11} {s_.alvo}")
        for a_ in commoncrawl.ALVOS:
            print(f"  {a_.chave:20} {'cc':9} {a_.licenca:11} {a_.padrao}")
        for m_ in sitemap.MAPAS:
            print(f"  {m_.chave:20} {'sitemap':9} {m_.licenca:11} {m_.url}")
        return 0

    with Store() as store:
        if a.list:
            relatorio(store)
            return 0
        if a.video:
            coletar_video(store, a.only or [], transcrever=not a.sem_transcricao,
                          com_frames=a.frames)
            print()
            relatorio(store)
            return 0
        if a.wayback:
            coletar_cc(store, a.only or [], de=a.de, limite=a.limite, origem="ia")
            print()
            relatorio(store)
            return 0
        if a.commoncrawl:
            coletar_cc(store, a.only or [], de=a.de, limite=a.limite)
            print()
            relatorio(store)
            return 0
        if a.sitemap:
            with Cliente() as cliente:
                coletar_sitemap(store, cliente, a.only or [], limite=a.limite)
            print()
            relatorio(store)
            return 0
        if a.ciclo:
            ciclo(store, transcrever=not a.sem_transcricao, workers=a.workers)
            print()
            relatorio(store)
            return 0
        if a.telegram:
            coletar_telegram(store, a.only or [], por_canal=a.limite)
            print()
            relatorio(store)
            return 0
        if a.social:
            coletar_social(store, limite=a.limite, transcrever=not a.sem_transcricao)
            print()
            relatorio(store)
            return 0
        if a.mediacloud:
            coletar_mediacloud(store, de=a.de, ate=a.ate)
            print()
            relatorio(store)
            return 0
        if a.reddit:
            coletar_reddit(store, a.only or [], de=a.de, por_sub=a.limite)
            print()
            relatorio(store)
            return 0
        if a.senado:
            coletar_senado(store, de=a.de, ate=a.ate)
            print()
            relatorio(store)
            return 0
        if a.camara:
            coletar_camara(store, de=a.de, ate=a.ate)
            print()
            relatorio(store)
            return 0
        if a.gdelt:
            coletar_gdelt(store, None)
            print()
            relatorio(store)
            return 0
        if a.ads:
            coletar_ads(store, de=a.de, ate=a.ate)
            print()
            relatorio(store)
            return 0
        if a.only:
            desconhecidos = [k for k in a.only if k not in rss.POR_CHAVE]
            if desconhecidos:
                print(f"feed desconhecido: {', '.join(desconhecidos)}", file=sys.stderr)
                return 2
        with Cliente() as cliente:
            coletar_rss(store, cliente, a.only or [], completo=not a.rapido)
        print()
        relatorio(store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
