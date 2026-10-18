"""CLI da coleta.

    uv run python -m mind_collect.run --list
    uv run python -m mind_collect.run --only g1-politica ebc-politica
    uv run python -m mind_collect.run --rapido      # sem baixar texto completo

Roda de novo e pula o que já baixou — mesmo idioma do scripts/get_data.py.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .http import Cliente
from .media.download import EXT_AUDIO, _achar, baixar_audio, baixar_video
from .media.images import processar as processar_imagens
from .media.images import processar_arquivo
from .media.transcribe import texto as texto_transcricao
from .media.transcribe import transcrever
from .sources import (
    bing_news,
    bluesky,
    camara,
    commoncrawl,
    dou,
    dou_espelho,
    gdelt,
    hidratacao,
    instagram,
    instagram_profiles,
    mediacloud,
    mencoes,
    meta_ads,
    reddit,
    rotulos,
    rss,
    senado,
    sitemap,
    sites_candidatos,
    social_search,
    telegram,
    tiktok,
    tiktok_research,
    tse,
    tse_abertos,
    tse_radio,
    youtube,
    youtube_comments,
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
            for doc in rss.coletar(
                cliente,
                feed,
                completo=completo,
                descartados=descartados,
                ja_tem=store.tem_url,
            ):
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
        print(
            f"{marca} {feed.chave:20} novos={novos:<5} repetidos={repetidos:<5} {curtos} {detalhe}"
        )


def coletar_video(
    store: Store, chaves: list[str], transcrever: bool, com_frames: bool = False
) -> None:
    sementes = [youtube.POR_CHAVE[k] for k in chaves] if chaves else youtube.SEMENTES
    vistos = {
        r[0] for r in store.con.execute("SELECT url FROM documentos WHERE fonte LIKE 'hgpe%'")
    }

    def ja_tem(video_id: str) -> bool:
        return any(video_id in u for u in vistos)

    for semente in sementes:
        exec_id = store.iniciar_execucao(semente.chave)
        novos = repetidos = erros = 0
        detalhe = ""
        try:
            for doc, frames in youtube.coletar(
                semente, ja_tem, transcrever_audio=transcrever, com_frames=com_frames
            ):
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


def coletar_comentarios_youtube(store: Store, lote_videos: int, paginas_por_video: int) -> None:
    exec_id = store.iniciar_execucao("youtube_comentarios")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        ids = sorted(
            {
                str(doc.metadados.get("video_id"))
                for doc in store.ler()
                if doc.canal == "youtube" and doc.metadados.get("video_id")
            }
        )
        cursor = store.cursor("youtube-comentarios")
        lote, proximo = _lote_circular(ids, cursor, lote_videos)
        for video_id in lote:
            for doc in youtube_comments.coletar(video_id, paginas=paginas_por_video):
                if store.guardar(doc):
                    novos += 1
                else:
                    repetidos += 1
        store.salvar_cursor("youtube-comentarios", proximo)
        detalhe = f"videos={len(lote)}/{len(ids)} paginas={paginas_por_video}"
    except youtube_comments.SemChave as erro:
        erros, detalhe = 1, str(erro)
    except Exception as erro:
        erros, detalhe = 1, f"{type(erro).__name__}: {erro}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'youtube_comentarios':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_cc(
    store: Store, chaves: list[str], de: str | None, limite: int, origem: str = "cc"
) -> None:
    catalogo = commoncrawl.POR_CHAVE_WAYBACK if origem == "ia" else commoncrawl.POR_CHAVE
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
            for doc in sitemap.coletar(cliente, mapa, limite=limite, ja_tem=store.tem_url):
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


def _termos_ads() -> list[str]:
    termos = ["eleições", "propaganda eleitoral", "campanha eleitoral"]
    registro = tse.carregar()
    nomes = {
        candidato.nome_urna.strip()
        for candidato, _ in (
            tse.candidatos_com_conta(registro, "facebook")
            + tse.candidatos_com_conta(registro, "instagram")
        )
        if candidato.nome_urna.strip()
    }
    return termos + sorted(nomes)


def coletar_ads(
    store: Store,
    de: str | None,
    ate: str | None,
    quantidade_termos: int = 1,
    limite_paginas: int = 100,
) -> None:
    exec_id = store.iniciar_execucao("meta_ads")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        termos = _termos_ads()
        cursor = store.cursor("meta-ads-termo")
        lote, proximo = _lote_circular(termos, cursor, quantidade_termos)
        for termo in lote:
            for anuncio in meta_ads.buscar(
                termos=termo, de=de, ate=ate, limite_paginas=limite_paginas
            ):
                doc = meta_ads.para_documento(anuncio)
                if store.guardar(doc):
                    novos += 1
                else:
                    repetidos += 1
        store.salvar_cursor("meta-ads-termo", proximo)
        detalhe = f"termos={','.join(lote)} cursor={proximo}/{len(termos)}"
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


def hidratar_noticias(store: Store, limite: int) -> None:
    exec_id = store.iniciar_execucao("hidratacao_noticias")
    novos = repetidos = erros = 0
    detalhe = ""
    bloqueadas = store.bloqueadas("hidratacao_noticias")
    try:
        with Cliente() as cliente:
            for doc_id, titulo, texto in hidratacao.coletar(
                cliente,
                store.ler(fonte="noticia"),
                bloqueadas=bloqueadas,
                limite=limite,
                ao_falhar=lambda url, erro: store.registrar_falha(
                    "hidratacao_noticias", url, f"{type(erro).__name__}: {erro}"
                ),
            ):
                store.guardar_conteudo(doc_id, titulo, texto)
                novos += 1
        detalhe = f"limite={limite} bloqueadas={len(bloqueadas)}"
    except Exception as erro:
        erros, detalhe = 1, f"{type(erro).__name__}: {erro}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'hidratacao_noticias':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_tse(store: Store, forcar: bool = False) -> None:
    exec_id = store.iniciar_execucao("tse_registro")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        mudou, origens = tse.atualizar(forcar=forcar)
        registro = tse.carregar()
        existentes = store.con.execute(
            "SELECT COUNT(*) FROM documentos WHERE fonte = 'tse_registro'"
        ).fetchone()[0]
        if mudou or not existentes:
            for doc in tse.documentos(registro):
                if store.guardar(doc):
                    novos += 1
                else:
                    repetidos += 1
        origem = "espelho" if any("github" in url for url in origens.values()) else "oficial"
        detalhe = f"candidaturas={len(registro)} origem={origem} mudou={mudou}"
    except Exception as e:
        erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'tse_registro':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_tse_abertos(store: Store, limite_por_recurso: int, forcar: bool = False) -> None:
    exec_id = store.iniciar_execucao("tse_abertos")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        manifesto = tse_abertos.atualizar(forcar=forcar)
        processados = 0
        for recurso, caminho in tse_abertos.arquivos():
            versao = f"{caminho.stat().st_size}-{caminho.stat().st_mtime_ns}"
            cursor_chave = f"tse-abertos:{recurso.chave}:{versao}"
            inicio = store.cursor(cursor_chave)
            lote, proximo = tse_abertos.lote(
                recurso, caminho, inicio=inicio, limite=limite_por_recurso
            )
            for doc in lote:
                if store.guardar(doc):
                    novos += 1
                else:
                    repetidos += 1
            store.salvar_cursor(cursor_chave, proximo)
            processados += len(lote)
        for recurso, caminho in tse_abertos.arquivos_propostas():
            versao = f"{caminho.stat().st_size}-{caminho.stat().st_mtime_ns}"
            cursor_chave = f"tse-propostas:{recurso.chave}:{versao}"
            inicio = store.cursor(cursor_chave)
            lote, proximo = tse_abertos.lote_propostas(
                recurso, caminho, inicio=inicio, limite=limite_por_recurso
            )
            for doc in lote:
                if store.guardar(doc):
                    novos += 1
                else:
                    repetidos += 1
            store.salvar_cursor(cursor_chave, proximo)
            processados += len(lote)
        disponiveis = sum(
            item["estado"] != "indisponivel" for item in manifesto.get("recursos", [])
        )
        detalhe = (
            f"recursos={disponiveis}/{len(tse_abertos.RECURSOS)} "
            f"linhas={processados} cdn_bloqueado={manifesto.get('cdn_bloqueado')}"
        )
    except Exception as erro:
        erros, detalhe = 1, f"{type(erro).__name__}: {erro}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'tse_abertos':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_dou(store: Store, de: str | None, ate: str | None) -> None:
    exec_id = store.iniciar_execucao("dou")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        for doc in dou.coletar(de=de, ate=ate):
            if store.guardar(doc):
                novos += 1
            else:
                repetidos += 1
        detalhe = f"secoes={len(dou.SECOES)}"
    except dou.SemCredencial as erro:
        erros, detalhe = 1, str(erro)
    except Exception as erro:
        erros, detalhe = 1, f"{type(erro).__name__}: {erro}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'dou':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_dou_espelho(store: Store, limite: int) -> None:
    exec_id = store.iniciar_execucao("dou_espelho")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        inicio = store.cursor("dou-espelho")
        documentos, proximo, total = dou_espelho.lote(inicio, limite)
        for doc in documentos:
            if store.guardar(doc):
                novos += 1
            else:
                repetidos += 1
        store.salvar_cursor("dou-espelho", proximo)
        detalhe = f"linhas={proximo}/{total} filtradas={len(documentos)}"
    except Exception as erro:
        erros, detalhe = 1, f"{type(erro).__name__}: {erro}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'dou_espelho':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_bluesky(store: Store, de: str | None, limite: int) -> None:
    exec_id = store.iniciar_execucao("bluesky")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        registro = tse.carregar()
        perfis = tse.contas(registro, "bluesky", cargos=())
        for doc in bluesky.coletar(
            perfis=perfis,
            de=de,
            limite_por_termo=limite,
            limite_por_perfil=min(limite, 100),
        ):
            if store.guardar(doc):
                novos += 1
                _registrar_perfil_do_documento(store, doc, "bluesky_busca")
                for midia in processar_imagens(doc.doc_id, doc.metadados.get("midias") or []):
                    store.guardar_midia(midia)
            else:
                repetidos += 1
        detalhe = f"termos={len(bluesky.TERMOS)} perfis={len(perfis)}"
    except Exception as e:
        erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'bluesky':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def _termos_noticias() -> tuple[str, ...]:
    registro = tse.carregar()
    nomes = {
        candidato.nome_urna.strip()
        for candidato in registro.values()
        if candidato.apto
        and candidato.nome_urna.strip()
        and any(
            cargo in candidato.cargo.upper() for cargo in ("PRESIDENTE", "GOVERNADOR", "SENADOR")
        )
    }
    return (*bing_news.TERMOS, *(f'"{nome}" eleições 2026' for nome in sorted(nomes)))


def coletar_bing_news(
    store: Store,
    termos: tuple[str, ...] | None = bing_news.TERMOS,
    quantidade_termos: int | None = None,
) -> None:
    exec_id = store.iniciar_execucao("bing_news")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        consultas = termos or _termos_noticias()
        cursor = store.cursor("bing-news-termo")
        lote, proximo = (
            _lote_circular(list(consultas), cursor, quantidade_termos)
            if quantidade_termos
            else (list(consultas), cursor)
        )
        with Cliente() as cliente:
            for doc in bing_news.coletar(cliente, tuple(lote), ja_tem=store.tem_url):
                if store.guardar(doc):
                    novos += 1
                else:
                    repetidos += 1
        if quantidade_termos:
            store.salvar_cursor("bing-news-termo", proximo)
        detalhe = f"consultas={len(lote)}/{len(consultas)} cursor={proximo}"
    except Exception as e:
        erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'bing_news':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_tse_radio(store: Store) -> None:
    exec_id = store.iniciar_execucao("tse_radio")
    novos = repetidos = erros = transcricoes = 0
    detalhe = ""
    try:
        for doc, segmentos in tse_radio.coletar():
            inserido = store.guardar(doc)
            novos += int(inserido)
            repetidos += int(not inserido)
            if segmentos:
                store.guardar_transcricao(doc.doc_id, segmentos)
                transcricoes += 1
        detalhe = f"transcricoes={transcricoes}"
    except Exception as e:
        erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'tse_radio':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def _lote_circular(itens: list, inicio: int, tamanho: int) -> tuple[list, int]:
    if not itens:
        return [], 0
    quantidade = min(tamanho, len(itens))
    lote = [itens[(inicio + deslocamento) % len(itens)] for deslocamento in range(quantidade)]
    return lote, (inicio + quantidade) % len(itens)


def _registrar_perfil_do_documento(store: Store, doc, origem: str) -> None:
    perfil = None
    if url_perfil := str(doc.metadados.get("perfil_url") or "").strip():
        perfil = mencoes.perfil_de_url(url_perfil)
    if not perfil:
        perfil = mencoes.perfil_de_url(doc.url)
    if perfil:
        plataforma, url = perfil
        store.registrar_alvo_social(plataforma, url, "perfil", origem, relevancia=3)
    conta = str(doc.metadados.get("conta") or doc.metadados.get("canal_id") or "").strip()
    if conta and doc.fonte == "tiktok":
        url = f"https://www.tiktok.com/@{conta.lstrip('@')}"
        store.registrar_alvo_social("tiktok", url, "perfil", origem, relevancia=3)
        perfil = ("tiktok", url)
    elif conta and doc.canal == "youtube":
        url = f"https://www.youtube.com/channel/{conta}"
        store.registrar_alvo_social("youtube", url, "perfil", origem, relevancia=3)
        perfil = ("youtube", url)
    dados_perfil = doc.metadados.get("perfil_publico")
    if perfil and isinstance(dados_perfil, dict):
        store.registrar_snapshot_perfil(perfil[0], perfil[1], dados_perfil, origem)
    for plataforma, url in mencoes.perfis_mencionados(doc):
        store.registrar_alvo_social(plataforma, url, "perfil", "mencao_em_publicacao", relevancia=2)


def atualizar_descobertas_sociais(store: Store, incluir_tse: bool = True) -> tuple[int, int]:
    """Material já coletado vira fila de novas publicações e contas."""
    exec_id = store.iniciar_execucao("descoberta_social")
    publicacoes = perfis = erros = 0
    detalhe = ""
    antes = int(store.con.execute("SELECT COUNT(*) FROM alvos_sociais").fetchone()[0])
    try:
        alvos: list[tuple[str, str, str, str, int]] = []
        for plataforma, urls in mencoes.varrer(store.ler()).items():
            for url, citacoes in urls.items():
                alvos.append((plataforma, url, "publicacao", "mencao_corpus", citacoes))
                publicacoes += 1
        for plataforma, urls in mencoes.varrer_perfis(store.ler()).items():
            for url, citacoes in urls.items():
                alvos.append((plataforma, url, "perfil", "mencao_corpus", citacoes))
                perfis += 1
        if incluir_tse:
            for candidato in tse.carregar().values():
                for _plataforma, urls in candidato.redes.items():
                    for url in urls:
                        perfil = mencoes.perfil_de_url(url)
                        if not perfil:
                            continue
                        plataforma_normalizada, url_normalizada = perfil
                        alvos.append(
                            (
                                plataforma_normalizada,
                                url_normalizada,
                                "perfil",
                                "tse",
                                5,
                            )
                        )
                        perfis += 1
        store.registrar_alvos_sociais(alvos)
        depois = int(store.con.execute("SELECT COUNT(*) FROM alvos_sociais").fetchone()[0])
        novos = depois - antes
        repetidos = max(0, len(alvos) - novos)
        detalhe = (
            f"novos={novos} repetidos={repetidos} "
            f"observacoes_publicacao={publicacoes} observacoes_perfil={perfis}"
        )
    except Exception as erro:
        novos = repetidos = 0
        erros, detalhe = 1, f"{type(erro).__name__}: {erro}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'descoberta_social':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")
    return novos, erros


def coletar_publicacoes_descobertas(store: Store, limite: int) -> tuple[int, int]:
    exec_id = store.iniciar_execucao("publicacoes_descobertas")
    novos = repetidos = erros = 0
    alvos = store.listar_alvos_sociais(
        "publicacao", ("instagram", "tiktok", "facebook", "x", "youtube"), limite
    )
    for alvo in alvos:
        if store.tem_url(alvo.url):
            store.marcar_alvo_social(alvo.plataforma, alvo.url)
            repetidos += 1
            continue
        falha: list[str] = []
        inseridos_alvo = 0
        try:
            if alvo.plataforma == "instagram":
                documentos = list(instagram.coletar([alvo.url], store.tem_url, limite=1))
                for doc, midias in documentos:
                    if store.guardar(doc):
                        novos += 1
                        inseridos_alvo += 1
                        _registrar_perfil_do_documento(store, doc, "autor_publicacao")
                        for midia in midias:
                            store.guardar_midia(midia)
            else:
                documentos_sociais = list(
                    tiktok.coletar(
                        [alvo.url],
                        store.tem_url,
                        transcrever_audio=False,
                        limite=1,
                        max_tentativas=1,
                        ao_falhar=lambda _url, erro, _falha=falha: _falha.append(
                            f"{type(erro).__name__}: {erro}"
                        ),
                    )
                )
                for doc in documentos_sociais:
                    if store.guardar(doc):
                        novos += 1
                        inseridos_alvo += 1
                        _registrar_perfil_do_documento(store, doc, "autor_publicacao")
            if store.tem_url(alvo.url) or inseridos_alvo:
                store.marcar_alvo_social(alvo.plataforma, alvo.url)
            else:
                raise RuntimeError(falha[-1] if falha else "publicação sem conteúdo acessível")
        except Exception as erro:
            erros += 1
            store.marcar_alvo_social(alvo.plataforma, alvo.url, f"{type(erro).__name__}: {erro}")
    detalhe = f"alvos={len(alvos)}"
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'publicacoes_sociais':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")
    return novos, erros


def coletar_perfis_descobertos(store: Store, limite: int, posts_por_perfil: int) -> tuple[int, int]:
    exec_id = store.iniciar_execucao("perfis_descobertos")
    novos = repetidos = erros = 0
    plataformas = ["tiktok", "youtube", "bluesky"]
    if instagram_profiles.configurado():
        plataformas.append("instagram")
    alvos = store.listar_alvos_sociais("perfil", tuple(plataformas), limite)
    for alvo in alvos:
        try:
            if alvo.plataforma == "bluesky":
                for doc in bluesky.coletar(
                    termos=(), perfis=[alvo.url], limite_por_perfil=posts_por_perfil
                ):
                    if store.guardar(doc):
                        novos += 1
                        _registrar_perfil_do_documento(store, doc, "perfil_descoberto")
                    else:
                        repetidos += 1
                store.marcar_alvo_social(alvo.plataforma, alvo.url)
                continue
            if alvo.plataforma == "instagram":
                descoberta = instagram_profiles.descobrir_detalhado(alvo.url, posts_por_perfil)
                store.registrar_alvos_sociais(
                    (
                        "instagram",
                        url,
                        "publicacao",
                        "instagram_perfil",
                        max(2, alvo.relevancia),
                    )
                    for url in descoberta.urls
                )
                store.registrar_snapshot_perfil(
                    "instagram", alvo.url, descoberta.perfil, "instagram_perfil"
                )
                store.marcar_alvo_social(alvo.plataforma, alvo.url)
                continue
            perfil = tiktok.Alvo(url=alvo.url, perfil=alvo.url)
            descobertas = list(tiktok.descobrir_perfis([perfil], posts_por_perfil))
            for doc in tiktok.coletar(
                descobertas,
                store.tem_url,
                transcrever_audio=False,
                limite=max(1, len(descobertas)),
                max_tentativas=max(1, len(descobertas)),
            ):
                if store.guardar(doc):
                    novos += 1
                    _registrar_perfil_do_documento(store, doc, "perfil_descoberto")
                else:
                    repetidos += 1
            store.marcar_alvo_social(alvo.plataforma, alvo.url)
        except Exception as erro:
            erros += 1
            store.marcar_alvo_social(alvo.plataforma, alvo.url, f"{type(erro).__name__}: {erro}")
    detalhe = f"perfis={len(alvos)} posts_por_perfil={posts_por_perfil}"
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'perfis_descobertos':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")
    return novos, erros


def coletar_busca_social(store: Store, quantidade_termos: int = 1, resultados: int = 20) -> None:
    exec_id = store.iniciar_execucao("busca_social")
    novos = repetidos = erros = 0
    detalhes: list[str] = []
    termos = list(social_search.TERMOS)
    cursor = store.cursor("busca-social-termo")
    lote, proximo = _lote_circular(termos, cursor, quantidade_termos)
    for termo in lote:
        try:
            pecas = tiktok.listar(f"ytsearch{resultados}:{termo}", limite=resultados)
            alvos = [tiktok.Alvo(peca.url) for peca in pecas if peca.url]
            for doc in tiktok.coletar(
                alvos,
                store.tem_url,
                transcrever_audio=False,
                limite=resultados,
                max_tentativas=resultados,
            ):
                if store.guardar(doc):
                    novos += 1
                    _registrar_perfil_do_documento(store, doc, "busca_youtube")
                else:
                    repetidos += 1
            detalhes.append(f"youtube:{termo}")
        except Exception as erro:
            erros += 1
            detalhes.append(f"youtube:{type(erro).__name__}")

        if tiktok_research.configurado():
            try:
                for doc in tiktok_research.coletar(termo, paginas_videos=2, paginas_comentarios=1):
                    if store.guardar(doc):
                        novos += 1
                        _registrar_perfil_do_documento(store, doc, "tiktok_research")
                    else:
                        repetidos += 1
                detalhes.append(f"tiktok:{termo}")
            except Exception as erro:
                erros += 1
                detalhes.append(f"tiktok:{type(erro).__name__}")

    store.salvar_cursor("busca-social-termo", proximo)
    detalhe = " ".join(detalhes)[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'busca_social':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_perfis_sociais(
    store: Store, lote_perfis: int, posts_por_perfil: int, transcrever_audio: bool
) -> None:
    registro = tse.carregar()
    if not registro:
        coletar_tse(store)
        registro = tse.carregar()

    for plataforma in ("tiktok", "youtube"):
        exec_id = store.iniciar_execucao(f"perfis_{plataforma}")
        novos = repetidos = erros = 0
        detalhe = ""
        try:
            contas = tse.candidatos_com_conta(registro, plataforma, cargos=())
            cursor = store.cursor(f"perfil-{plataforma}")
            lote, proximo = _lote_circular(contas, cursor, lote_perfis)
            perfis = [
                tiktok.Alvo(
                    url=url,
                    candidato_id=candidato.sq,
                    candidato=candidato.nome_urna,
                    partido=candidato.partido,
                    cargo=candidato.cargo,
                )
                for candidato, url in lote
            ]
            descobertas = list(tiktok.descobrir_perfis(perfis, posts_por_perfil))
            vistas = {
                linha[0]
                for linha in store.con.execute(
                    "SELECT url FROM documentos WHERE fonte = ?", (plataforma,)
                )
            }
            for doc in tiktok.coletar(
                descobertas,
                lambda url, _vistas=vistas: url in _vistas,
                transcrever_audio=transcrever_audio,
                limite=max(1, len(descobertas)),
                max_tentativas=max(1, len(descobertas)),
                ao_falhar=lambda url, erro, _plataforma=plataforma: store.registrar_falha(
                    f"perfil_{_plataforma}", url, f"{type(erro).__name__}: {erro}"
                ),
            ):
                if store.guardar(doc):
                    novos += 1
                    vistas.add(doc.url)
                    store.limpar_falha(f"perfil_{plataforma}", doc.url)
                    _registrar_perfil_do_documento(store, doc, "tse_perfil")
                else:
                    repetidos += 1
            store.salvar_cursor(f"perfil-{plataforma}", proximo)
            detalhe = f"perfis={len(lote)}/{len(contas)} pecas={len(descobertas)} cursor={proximo}"
        except Exception as e:
            erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
        store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
        marca = "!" if erros else " "
        print(
            f"{marca} {f'perfis_{plataforma}':20} "
            f"novos={novos:<5} repetidos={repetidos:<5} {detalhe}"
        )


def sincronizar_transcricoes_embutidas(store: Store) -> int:
    """Migra uma vez transcrições antigas do JSONL para a fila persistente."""
    if store.cursor("midia-transcricoes-embutidas-v1"):
        return 0
    transcritos = store.transcritos()
    migradas = 0
    for doc in store.ler():
        if doc.transcricao and doc.doc_id not in transcritos:
            store.guardar_transcricao(doc.doc_id, doc.transcricao)
            store.marcar_processamento_midia(doc.doc_id, "transcricao", True, "migrada do JSONL")
            transcritos.add(doc.doc_id)
            migradas += 1
    store.salvar_cursor("midia-transcricoes-embutidas-v1", 1)
    return migradas


def _ids_midias_genericas(
    store: Store,
    limite: int,
    transcritos: set[str],
    transcricao_bloqueada: set[str],
    frames_processados: set[str],
    frames_bloqueados: set[str],
    imagens_processadas: set[str],
    imagens_bloqueadas: set[str],
) -> list[str]:
    selecionados: list[str] = []
    for doc_id, modalidade in store.con.execute(
        """
        SELECT doc_id, modalidade FROM documentos
        WHERE fonte != 'telegram' AND modalidade IN ('audio','video','imagem')
        ORDER BY coletado_em, doc_id
        """
    ):
        precisa_transcricao = (
            modalidade in {"audio", "video"}
            and doc_id not in transcritos
            and doc_id not in transcricao_bloqueada
        )
        precisa_frames = (
            modalidade == "video"
            and doc_id not in frames_processados
            and doc_id not in frames_bloqueados
        )
        precisa_imagem = (
            modalidade == "imagem"
            and doc_id not in imagens_processadas
            and doc_id not in imagens_bloqueadas
        )
        if precisa_transcricao or precisa_frames or precisa_imagem:
            selecionados.append(doc_id)
            if len(selecionados) >= limite:
                break
    return selecionados


def enriquecer_midias(store: Store, limite: int) -> tuple[int, int]:
    exec_id = store.iniciar_execucao("transcricao_pendente")
    novos = repetidos = erros = 0
    detalhe = ""
    transcritos = store.transcritos()
    transcricao_bloqueada = store.bloqueados_midia("transcricao")
    frames_processados = store.processados_midia("frames") | {
        linha[0]
        for linha in store.con.execute("SELECT DISTINCT doc_id FROM midias WHERE tipo='frame'")
    }
    frames_bloqueados = store.bloqueados_midia("frames")
    imagens_processadas = store.processados_midia("imagem") | {
        linha[0]
        for linha in store.con.execute("SELECT DISTINCT doc_id FROM midias WHERE tipo='imagem'")
    }
    imagens_bloqueadas = store.bloqueados_midia("imagem")
    baixados = 0
    ids = _ids_midias_genericas(
        store,
        limite,
        transcritos,
        transcricao_bloqueada,
        frames_processados,
        frames_bloqueados,
        imagens_processadas,
        imagens_bloqueadas,
    )
    try:
        for doc in store.ler_ids(ids):
            midias_remotas = doc.metadados.get("midias") or []
            precisa_transcricao = (
                doc.modalidade in {"audio", "video"}
                and not doc.transcricao
                and doc.doc_id not in transcritos
                and doc.doc_id not in transcricao_bloqueada
            )
            precisa_frames = (
                doc.modalidade == "video"
                and doc.doc_id not in frames_processados
                and doc.doc_id not in frames_bloqueados
            )
            precisa_imagem = (
                doc.modalidade == "imagem"
                and doc.doc_id not in imagens_processadas
                and doc.doc_id not in imagens_bloqueadas
            )
            segmentos = doc.transcricao
            if precisa_transcricao:
                audio = None
                try:
                    video_id = doc.metadados.get("video_id")
                    audio = _achar(tiktok.MIDIA, str(video_id), EXT_AUDIO) if video_id else None
                    if not audio:
                        peca = baixar_audio(doc.url, tiktok.MIDIA)
                        audio = peca.audio
                        baixados += int(audio is not None)
                    if not audio:
                        raise ValueError("áudio não foi encontrado após o download")
                    segmentos = transcrever(audio)
                    store.guardar_transcricao(doc.doc_id, segmentos)
                    store.marcar_processamento_midia(doc.doc_id, "transcricao", True)
                    transcritos.add(doc.doc_id)
                    novos += 1
                    audio.unlink(missing_ok=True)
                except Exception as erro:
                    erros += 1
                    store.marcar_processamento_midia(
                        doc.doc_id, "transcricao", False, f"{type(erro).__name__}: {erro}"
                    )

            if precisa_frames:
                video = None
                try:
                    video = baixar_video(doc.url, tiktok.MIDIA)
                    baixados += int(video is not None)
                    if not video:
                        raise ValueError("vídeo não foi encontrado após o download")
                    frames = youtube.frames_de(
                        video,
                        doc.doc_id,
                        texto_transcricao(segmentos),
                        tiktok.MIDIA,
                        maximo=40,
                    )
                    for frame in frames:
                        store.guardar_midia(frame)
                    store.marcar_processamento_midia(
                        doc.doc_id, "frames", True, f"frames_com_texto={len(frames)}"
                    )
                    frames_processados.add(doc.doc_id)
                    novos += 1
                except Exception as erro:
                    erros += 1
                    store.marcar_processamento_midia(
                        doc.doc_id, "frames", False, f"{type(erro).__name__}: {erro}"
                    )
                finally:
                    if video:
                        video.unlink(missing_ok=True)

            if precisa_imagem:
                try:
                    imagens = processar_imagens(doc.doc_id, midias_remotas)
                    if not imagens:
                        raise ValueError("nenhuma imagem pôde ser processada")
                    for imagem in imagens:
                        store.guardar_midia(imagem)
                    store.marcar_processamento_midia(
                        doc.doc_id, "imagem", True, f"imagens={len(imagens)}"
                    )
                    imagens_processadas.add(doc.doc_id)
                    novos += 1
                except Exception as erro:
                    erros += 1
                    store.marcar_processamento_midia(
                        doc.doc_id, "imagem", False, f"{type(erro).__name__}: {erro}"
                    )
        detalhe = (
            f"processados={len(ids)} downloads={baixados} "
            f"bloqueadas={len(transcricao_bloqueada | frames_bloqueados | imagens_bloqueadas)}"
        )
    except Exception as e:
        erros += 1
        detalhe = f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(
        f"{marca} {'transcricao_pendente':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}"
    )
    return novos, erros


def pendencias_midia(store: Store) -> dict[str, int]:
    consultas = {
        "transcricao": """
            SELECT COUNT(*) FROM documentos d
            WHERE d.modalidade IN ('audio','video')
              AND NOT EXISTS (SELECT 1 FROM transcricoes t WHERE t.doc_id=d.doc_id)
        """,
        "frames": """
            SELECT COUNT(*) FROM documentos d
            WHERE d.modalidade='video'
              AND NOT EXISTS (
                    SELECT 1 FROM processamentos_midia p
                    WHERE p.doc_id=d.doc_id AND p.etapa='frames' AND p.status='concluido'
              )
              AND NOT EXISTS (SELECT 1 FROM midias m WHERE m.doc_id=d.doc_id AND m.tipo='frame')
        """,
        "imagens": """
            SELECT COUNT(*) FROM documentos d
            WHERE d.modalidade='imagem'
              AND NOT EXISTS (
                    SELECT 1 FROM processamentos_midia p
                    WHERE p.doc_id=d.doc_id AND p.etapa='imagem' AND p.status='concluido'
              )
              AND NOT EXISTS (SELECT 1 FROM midias m WHERE m.doc_id=d.doc_id AND m.tipo='imagem')
        """,
    }
    return {nome: int(store.con.execute(sql).fetchone()[0]) for nome, sql in consultas.items()}


def worker_midias(
    store: Store,
    lote: int = 5,
    espera: int = 60,
    rodadas: int | None = None,
) -> int:
    """Drena fala, keyframes/OCR e imagens continuamente, com exclusão mútua."""
    from filelock import FileLock, Timeout

    trava = store.raiz / "_worker-midia.lock"
    trava.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(trava)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        print("worker de mídia já está em execução")
        return 0
    try:
        migradas = sincronizar_transcricoes_embutidas(store)
        if migradas:
            print(f"  worker_midia transcrições antigas migradas={migradas}", flush=True)
        rodada = 0
        while rodadas is None or rodada < rodadas:
            rodada += 1
            antes = pendencias_midia(store)
            novos, erros = enriquecer_midias(store, limite=lote)
            if telegram.estado() == "pronto":
                novos_telegram, erros_telegram = enriquecer_telegram(store, limite=lote)
                novos += novos_telegram
                erros += erros_telegram
            depois = pendencias_midia(store)
            print(
                "  worker_midia "
                f"rodada={rodada} novos={novos} erros={erros} "
                f"antes={antes} depois={depois}",
                flush=True,
            )
            if rodadas is not None and rodada >= rodadas:
                break
            time.sleep(1 if novos else max(10, espera))
    finally:
        lock.release()
    return 0


def coletar_rotulos(store: Store) -> None:
    exec_id = store.iniciar_execucao("rotulos_checagem")
    novos = repetidos = erros = 0
    detalhe = ""
    existentes = {
        doc_id: (rotulo, fonte)
        for doc_id, rotulo, fonte in store.con.execute(
            "SELECT doc_id, rotulo, fonte_rotulo FROM rotulos_externos"
        )
    }
    fontes_automaticas = {feed.chave for feed in rss.FEEDS if feed.fonte == "checagem"}
    fontes_automaticas.add("checagem")
    removidos = 0
    try:
        for doc in store.ler(fonte="checagem"):
            inferido = rotulos.inferir(doc)
            atual = existentes.get(doc.doc_id)
            if not inferido:
                if atual and atual[1] in fontes_automaticas:
                    store.remover_rotulo(doc.doc_id)
                    removidos += 1
                continue
            if atual == inferido:
                repetidos += 1
                continue
            rotulo, fonte_rotulo = inferido
            store.guardar_rotulo(doc.doc_id, rotulo, fonte_rotulo)
            novos += 1
        detalhe = f"removidos={removidos} somente_titulos_com_veredito_explicito"
    except Exception as e:
        erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'rotulos_checagem':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def coletar_sites_candidatos(store: Store, lote_sites: int, paginas_por_site: int) -> None:
    exec_id = store.iniciar_execucao("sites_candidatos")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        registro = tse.carregar()
        contas = tse.candidatos_com_conta(registro, "site", cargos=())
        cursor = store.cursor("site-candidato")
        lote, proximo = _lote_circular(contas, cursor, lote_sites)
        alvos = [
            sites_candidatos.Alvo(
                url=url,
                candidato_id=candidato.sq,
                candidato=candidato.nome_urna,
                partido=candidato.partido,
                cargo=candidato.cargo,
            )
            for candidato, url in lote
        ]
        vistas = {
            linha[0]
            for linha in store.con.execute(
                "SELECT url FROM documentos WHERE fonte = 'site_candidato'"
            )
        }
        with Cliente() as cliente:
            for doc in sites_candidatos.coletar(
                cliente, alvos, lambda url: url in vistas, paginas_por_site
            ):
                if store.guardar(doc):
                    novos += 1
                    vistas.add(doc.url)
                else:
                    repetidos += 1
        store.salvar_cursor("site-candidato", proximo)
        detalhe = f"sites={len(lote)}/{len(contas)} cursor={proximo}"
    except Exception as e:
        erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'sites_candidatos':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


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
    coletar_tse(store)
    coletar_tse_abertos(store, limite_por_recurso=500)
    coletar_dou_espelho(store, limite=500)
    tarefas: list[tuple[str, Callable[[], None]]] = [
        ("rss", lambda: _com_cliente(coletar_rss, store, [], completo=True)),
        ("sitemap", lambda: _com_cliente(coletar_sitemap, store, [], limite=200)),
        ("gdelt", lambda: coletar_gdelt(store, None)),
        ("camara", lambda: coletar_camara(store, None, None)),
        ("senado", lambda: coletar_senado(store, None, None)),
        ("reddit", lambda: coletar_reddit(store, [], de=None, por_sub=200)),
        ("bluesky", lambda: coletar_bluesky(store, de=None, limite=50)),
        (
            "bing_news",
            lambda: coletar_bing_news(store, termos=None, quantidade_termos=12),
        ),
        ("tse_radio", lambda: coletar_tse_radio(store)),
        (
            "sites_candidatos",
            lambda: coletar_sites_candidatos(store, lote_sites=20, paginas_por_site=3),
        ),
    ]
    est = telegram.estado()
    if est == "pronto":
        tarefas.append(("telegram", lambda: coletar_telegram(store, [], por_canal=200)))
    else:
        print(f"  {'telegram':20} pulado ({est})")
    if os.environ.get("META_ADS_TOKEN"):
        tarefas.append(
            (
                "meta_ads",
                lambda: coletar_ads(store, None, None, quantidade_termos=1, limite_paginas=20),
            )
        )
    if os.environ.get("MEDIACLOUD_API_KEY"):
        tarefas.append(("mediacloud", lambda: coletar_mediacloud(store, None, None)))
    if os.environ.get("INLABS_EMAIL") and os.environ.get("INLABS_PASSWORD"):
        tarefas.append(("dou", lambda: coletar_dou(store, None, None)))
    if os.environ.get("YOUTUBE_API_KEY"):
        tarefas.append(
            (
                "youtube_comentarios",
                lambda: coletar_comentarios_youtube(store, lote_videos=5, paginas_por_video=5),
            )
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futuros = {pool.submit(f): nome for nome, f in tarefas}
        for fut in as_completed(futuros):
            nome = futuros[fut]
            try:
                fut.result()
            except Exception as e:
                print(f"! {nome:20} {type(e).__name__}: {e}"[:200])

    # Descoberta ativa e por grafo: nomes do TSE são sementes, não fronteira.
    coletar_busca_social(store, quantidade_termos=1, resultados=20)
    atualizar_descobertas_sociais(store)
    coletar_publicacoes_descobertas(store, limite=50)
    coletar_perfis_descobertos(store, limite=20, posts_por_perfil=5)
    exportar_perfis(store)

    # Pista de computação, em série: disputa o Metal.
    coletar_video(store, [], transcrever=False)
    coletar_perfis_sociais(store, lote_perfis=20, posts_por_perfil=5, transcrever_audio=False)
    if transcrever:
        enriquecer_midias(store, limite=5)
        if telegram.estado() == "pronto":
            enriquecer_telegram(store, limite=3)
    hidratar_noticias(store, limite=20)
    coletar_rotulos(store)


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
    """TikTok, Instagram, Facebook e X citados no corpus."""
    plataformas = ("tiktok", "instagram", "facebook", "x")
    achados = mencoes.varrer(store.ler(), plataformas=plataformas)
    vistas = {
        r[0]
        for r in store.con.execute(
            "SELECT url FROM documentos WHERE fonte IN ('tiktok','instagram','facebook','x')"
        )
    }
    fila_video = [
        url
        for plataforma in ("tiktok", "facebook", "x")
        for url, _ in achados.get(plataforma, Counter()).most_common()
    ]
    bloqueadas = store.bloqueadas("social")
    fila_video = [url for url in fila_video if url not in bloqueadas]
    fila_instagram = [url for url, _ in achados.get("instagram", Counter()).most_common()]
    exec_id = store.iniciar_execucao("social")
    novos = repetidos = erros = 0
    detalhe = f"descobertas={len(fila_video) + len(fila_instagram)} bloqueadas={len(bloqueadas)}"
    try:
        for doc, midias in instagram.coletar(
            fila_instagram, lambda url: url in vistas, limite=limite
        ):
            if store.guardar(doc):
                novos += 1
                vistas.add(doc.url)
                for midia in midias:
                    store.guardar_midia(midia)
            else:
                repetidos += 1
        for doc in tiktok.coletar(
            fila_video,
            lambda u: u in vistas,
            transcrever_audio=transcrever,
            limite=limite,
            max_tentativas=limite,
            ao_falhar=lambda url, erro: store.registrar_falha(
                "social", url, f"{type(erro).__name__}: {erro}"
            ),
        ):
            if store.guardar(doc):
                novos += 1
                vistas.add(doc.url)
                store.limpar_falha("social", doc.url)
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
    declarados = tse.contas(tse.carregar(), "telegram", cargos=())
    alvos = canais or list(dict.fromkeys(telegram.SEMENTES + declarados + extras))

    exec_id = store.iniciar_execucao("telegram")
    novos = repetidos = erros = 0
    detalhe = ""
    try:
        for doc in telegram.coletar(alvos, por_canal=por_canal):
            if store.guardar(doc):
                novos += 1
                _registrar_perfil_do_documento(store, doc, "telegram_canal")
            else:
                repetidos += 1
        cursor = store.cursor("telegram-busca-global")
        termos, proximo = _lote_circular(list(telegram.TERMOS), cursor, 1)
        for doc in telegram.buscar_global(termos, por_termo=min(100, por_canal)):
            if store.guardar(doc):
                novos += 1
                _registrar_perfil_do_documento(store, doc, "telegram_busca_global")
            else:
                repetidos += 1
        store.salvar_cursor("telegram-busca-global", proximo)
        detalhe = (
            f"sementes={len(telegram.SEMENTES)} tse={len(declarados)} "
            f"mencoes={len(extras)} busca={termos[0] if termos else '-'}"
        )
    except telegram.SemCredencial as e:
        erros, detalhe = 1, str(e)[:200]
    except Exception as e:
        erros, detalhe = 1, f"{type(e).__name__}: {e}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'telegram':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")


def enriquecer_telegram(store: Store, limite: int) -> tuple[int, int]:
    exec_id = store.iniciar_execucao("telegram_midia")
    novos = repetidos = erros = 0
    detalhe = ""
    imagens_processadas = store.processados_midia("imagem") | {
        linha[0]
        for linha in store.con.execute("SELECT DISTINCT doc_id FROM midias WHERE tipo='imagem'")
    }
    frames_processados = store.processados_midia("frames") | {
        linha[0]
        for linha in store.con.execute("SELECT DISTINCT doc_id FROM midias WHERE tipo='frame'")
    }
    transcritos = store.transcritos()
    bloqueadas_url = store.bloqueadas("telegram_midia")
    imagens_bloqueadas = store.bloqueados_midia("imagem")
    frames_bloqueados = store.bloqueados_midia("frames")
    transcricoes_bloqueadas = store.bloqueados_midia("transcricao")
    ids: list[str] = []
    for doc_id, modalidade, url in store.con.execute(
        """
        SELECT doc_id, modalidade, url FROM documentos
        WHERE fonte='telegram' AND modalidade IN ('imagem','video','audio')
        ORDER BY coletado_em, doc_id
        """
    ):
        if url in bloqueadas_url:
            continue
        precisa_imagem = (
            modalidade == "imagem"
            and doc_id not in imagens_processadas
            and doc_id not in imagens_bloqueadas
        )
        precisa_transcricao = (
            modalidade in {"audio", "video"}
            and doc_id not in transcritos
            and doc_id not in transcricoes_bloqueadas
        )
        precisa_frames = (
            modalidade == "video"
            and doc_id not in frames_processados
            and doc_id not in frames_bloqueados
        )
        if precisa_imagem or precisa_transcricao or precisa_frames:
            ids.append(doc_id)
            if len(ids) >= limite:
                break

    try:
        for doc, caminho in telegram.baixar_midias(
            store.ler_ids(ids),
            limite,
            ao_falhar=lambda url, erro: store.registrar_falha(
                "telegram_midia", url, f"{type(erro).__name__}: {erro}"
            ),
        ):
            sufixo = caminho.suffix.lower()
            if sufixo in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                try:
                    midia = processar_arquivo(doc.doc_id, caminho, doc.url)
                    store.guardar_midia(midia)
                    store.marcar_processamento_midia(doc.doc_id, "imagem", True)
                    imagens_processadas.add(doc.doc_id)
                    if not doc.conteudo and midia.ocr_texto:
                        store.guardar_conteudo(doc.doc_id, doc.titulo, midia.ocr_texto)
                    novos += 1
                    store.limpar_falha("telegram_midia", doc.url)
                except Exception as erro:
                    erros += 1
                    store.marcar_processamento_midia(
                        doc.doc_id, "imagem", False, f"{type(erro).__name__}: {erro}"
                    )
                continue

            if sufixo not in {
                ".m4a",
                ".mp3",
                ".opus",
                ".ogg",
                ".wav",
                ".aac",
                ".mp4",
                ".mov",
                ".mkv",
                ".webm",
            }:
                erros += 1
                etapa = "frames" if doc.modalidade == "video" else "transcricao"
                store.marcar_processamento_midia(
                    doc.doc_id, etapa, False, f"tipo de mídia não suportado: {sufixo}"
                )
                continue

            segmentos = doc.transcricao
            if doc.doc_id not in transcritos and doc.doc_id not in transcricoes_bloqueadas:
                try:
                    segmentos = transcrever(caminho)
                    store.guardar_transcricao(doc.doc_id, segmentos)
                    store.marcar_processamento_midia(doc.doc_id, "transcricao", True)
                    transcritos.add(doc.doc_id)
                    novos += 1
                except Exception as erro:
                    erros += 1
                    store.marcar_processamento_midia(
                        doc.doc_id, "transcricao", False, f"{type(erro).__name__}: {erro}"
                    )

            if (
                sufixo in {".mp4", ".mov", ".mkv", ".webm"}
                and doc.doc_id not in frames_processados
                and doc.doc_id not in frames_bloqueados
            ):
                try:
                    frames = youtube.frames_de(
                        caminho,
                        doc.doc_id,
                        " ".join(segmento.texto for segmento in segmentos),
                        tiktok.MIDIA,
                        maximo=20,
                    )
                    for midia in frames:
                        store.guardar_midia(midia)
                    store.marcar_processamento_midia(
                        doc.doc_id, "frames", True, f"frames_com_texto={len(frames)}"
                    )
                    frames_processados.add(doc.doc_id)
                    novos += 1
                except Exception as erro:
                    erros += 1
                    store.marcar_processamento_midia(
                        doc.doc_id, "frames", False, f"{type(erro).__name__}: {erro}"
                    )
            if doc.doc_id in transcritos or doc.doc_id in frames_processados:
                store.limpar_falha("telegram_midia", doc.url)
        bloqueadas = (
            bloqueadas_url | imagens_bloqueadas | frames_bloqueados | transcricoes_bloqueadas
        )
        detalhe = f"selecionadas={len(ids)} bloqueadas={len(bloqueadas)}"
    except Exception as erro:
        erros, detalhe = 1, f"{type(erro).__name__}: {erro}"[:300]
    store.encerrar_execucao(exec_id, novos, repetidos, erros, detalhe)
    marca = "!" if erros else " "
    print(f"{marca} {'telegram_midia':20} novos={novos:<5} repetidos={repetidos:<5} {detalhe}")
    return novos, erros


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

    pendencias = pendencias_midia(store)
    print(
        "mídia pendente: "
        f"transcrição={pendencias['transcricao']} "
        f"frames/OCR={pendencias['frames']} imagens/OCR={pendencias['imagens']}"
    )

    alvos = store.alvos_sociais_por_plataforma()
    if alvos:
        resumo_alvos = ", ".join(f"{plataforma}/{tipo}={n}" for plataforma, tipo, n in alvos)
        print(f"alvos sociais: {resumo_alvos}")
    snapshots, perfis = store.con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT plataforma || '|' || url) FROM snapshots_perfis_sociais"
    ).fetchone()
    print(f"snapshots de perfis: {snapshots} versões de {perfis} contas")

    for fonte in {r[0] for r in linhas}:
        if b := store.buracos(fonte):
            print(f"  buraco em {fonte}: {len(b)} dia(s) sem coleta — {b[0]}…{b[-1]}")


def exportar_perfis(store: Store, destino: Path | None = None) -> Path:
    """Exporta o inventário e o snapshot mais recente de cada conta em JSONL."""
    destino = destino or (store.raiz / "perfis_sociais.jsonl")
    temporario = destino.with_suffix(".jsonl.tmp")
    linhas = store.con.execute(
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
    with temporario.open("w", encoding="utf-8") as arquivo:
        for linha in linhas:
            dados = json.loads(linha[9]) if linha[9] else {}
            arquivo.write(
                json.dumps(
                    {
                        "plataforma": linha[0],
                        "url": linha[1],
                        "origem": linha[2],
                        "relevancia": linha[3],
                        "primeira_vista": linha[4],
                        "ultima_vista": linha[5],
                        "ultima_coleta": linha[6],
                        "tentativas": linha[7],
                        "ultimo_erro": linha[8],
                        "snapshot": dados,
                        "snapshot_em": linha[10],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    temporario.replace(destino)
    return destino


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
        (
            "META_ADS_TOKEN",
            "Biblioteca de Anúncios da Meta",
            "histórico político com criativo, gasto e alcance",
        ),
        ("TELEGRAM_API_ID", "Telegram", "histórico integral de canal público"),
        ("MEDIACLOUD_API_KEY", "Media Cloud", "arquivo jornalístico complementar"),
        ("YOUTUBE_API_KEY", "YouTube API", "comentários de vídeos em volume"),
        (
            "TIKTOK_RESEARCH_CLIENT_KEY",
            "TikTok Research API",
            "vídeos e comentários por tema em escala",
        ),
        (
            "INSTAGRAM_COOKIES_FILE",
            "Instagram com sessão própria",
            "enumeração de posts, bio e métricas de perfis",
        ),
        ("INLABS_EMAIL", "DOU oficial / INLABS", "edições XML oficiais diárias"),
    ]
    variable_width = max(len(key) for key, _, _ in itens) + 2
    source_width = max(len(source) for _, source, _ in itens) + 2
    print(f"{'':3}{'variável':<{variable_width}}{'fonte':<{source_width}}efeito da ausência")
    for chave, fonte, efeito in itens:
        configurada = (
            instagram_profiles.configurado()
            if chave == "INSTAGRAM_COOKIES_FILE"
            else bool(os.environ.get(chave))
        )
        marca = "ok" if configurada else "--"
        print(
            f"{marca:2} {chave:<{variable_width}}{fonte:<{source_width}}"
            f"{'' if configurada else efeito}"
        )
    est = telegram.estado()
    if est != "pronto":
        print(
            f"\ntelegram: {est}"
            + (
                "  → uv run python -m mind_collect.run --telegram-login"
                if est == "sem_login"
                else ""
            )
        )
    if not Path(".env").exists():
        print("\nsem .env — copie de .env.exemplo e preencha o que tiver")
    if bool(os.environ.get("INLABS_EMAIL")) != bool(os.environ.get("INLABS_PASSWORD")):
        print("\nINLABS incompleto: configure e-mail e senha juntos")
    if bool(os.environ.get("TIKTOK_RESEARCH_CLIENT_KEY")) != bool(
        os.environ.get("TIKTOK_RESEARCH_CLIENT_SECRET")
    ):
        print("\nTikTok Research incompleto: configure client key e client secret juntos")
    if os.environ.get("MIND_TSE_MIRROR_BASE"):
        print("\nespelho dos ZIPs do TSE: configurado")
    print("\ndependências locais:")
    for executable, purpose in (
        ("ffmpeg", "áudio, vídeo e keyframes"),
        ("pdftotext", "propostas de governo em PDF do TSE"),
    ):
        mark = "ok" if shutil.which(executable) else "--"
        print(f"{mark:2} {executable:22}{purpose}")


def main(argv: list[str] | None = None) -> int:
    carregar_env()
    p = argparse.ArgumentParser(prog="mind_collect", description=__doc__)
    p.add_argument("--only", nargs="+", metavar="CHAVE", help="coletar só estes feeds")
    p.add_argument("--list", action="store_true", help="mostrar cobertura do corpus")
    p.add_argument("--feeds", action="store_true", help="listar feeds disponíveis")
    p.add_argument("--rapido", action="store_true", help="não baixar o texto completo")
    p.add_argument("--video", action="store_true", help="coletar vídeo (HGPE, YouTube)")
    p.add_argument(
        "--youtube-comments",
        action="store_true",
        help="comentários e respostas via YouTube Data API",
    )
    p.add_argument(
        "--paginas-comentarios", type=int, default=5, help="páginas de comentários por vídeo"
    )
    p.add_argument("--commoncrawl", action="store_true", help="varrer o índice do Common Crawl")
    p.add_argument("--sitemap", action="store_true", help="varrer sitemaps dos portais")
    p.add_argument("--gdelt", action="store_true", help="descobrir URLs pelo GDELT")
    p.add_argument("--camara", action="store_true", help="discursos da Câmara dos Deputados")
    p.add_argument("--senado", action="store_true", help="discursos do plenário do Senado")
    p.add_argument("--reddit", action="store_true", help="arquivo do Reddit via arctic_shift")
    p.add_argument("--mediacloud", action="store_true", help="arquivo do Media Cloud")
    p.add_argument(
        "--wayback", action="store_true", help="recuperar conteúdo removido pelo Internet Archive"
    )
    p.add_argument(
        "--frames",
        action="store_true",
        help="extrair keyframes e OCR do vídeo (baixa o vídeo inteiro)",
    )
    p.add_argument(
        "--social", action="store_true", help="TikTok, Instagram e Facebook citados no corpus"
    )
    p.add_argument(
        "--descoberta-social",
        action="store_true",
        help="buscar temas políticos e drenar a fila de contas/publicações descobertas",
    )
    p.add_argument(
        "--bluesky", action="store_true", help="buscar posts públicos do Bluesky sem token"
    )
    p.add_argument(
        "--bing-news",
        action="store_true",
        help="descobrir notícias eleitorais no RSS público do Bing",
    )
    p.add_argument(
        "--tse-radio", action="store_true", help="spots oficiais de rádio publicados pelo TSE"
    )
    p.add_argument(
        "--perfis-sociais", action="store_true", help="posts de TikTok e YouTube declarados ao TSE"
    )
    p.add_argument(
        "--sites-candidatos", action="store_true", help="sites de campanha declarados ao TSE"
    )
    p.add_argument(
        "--paginas-por-site", type=int, default=5, help="páginas relevantes por site de candidatura"
    )
    p.add_argument(
        "--posts-por-perfil", type=int, default=5, help="publicações recentes enumeradas por perfil"
    )
    p.add_argument(
        "--enriquecer-midia",
        action="store_true",
        help="transcrever áudios já baixados que ficaram pendentes",
    )
    p.add_argument(
        "--worker-midia",
        action="store_true",
        help="drenar continuamente transcrição, keyframes e OCR",
    )
    p.add_argument(
        "--espera",
        type=int,
        default=60,
        help="segundos de espera do worker quando não houver progresso",
    )
    p.add_argument(
        "--rotulos", action="store_true", help="extrair vereditos explícitos das checagens"
    )
    p.add_argument(
        "--hidratar-noticias",
        action="store_true",
        help="buscar corpo de URLs vazias do GDELT e Media Cloud",
    )
    p.add_argument("--telegram", action="store_true", help="canais públicos do Telegram")
    p.add_argument(
        "--telegram-midia",
        action="store_true",
        help="OCR e transcrição das mídias já descobertas no Telegram",
    )
    p.add_argument(
        "--telegram-login",
        action="store_true",
        help="login interativo do Telegram, uma vez só (exige terminal)",
    )
    p.add_argument("--telefone", help="telefone com +55, para poupar uma pergunta no login")
    p.add_argument(
        "--tse", action="store_true", help="atualizar e armazenar candidaturas e redes do TSE"
    )
    p.add_argument(
        "--tse-abertos",
        action="store_true",
        help="processos, Pardal, pesquisas e contas eleitorais do TSE",
    )
    p.add_argument(
        "--dou", action="store_true", help="atos eleitorais do Diário Oficial via INLABS"
    )
    p.add_argument(
        "--dou-espelho",
        action="store_true",
        help="snapshot CC0 do DOU 2025-2026 derivado do INLABS",
    )
    p.add_argument("--credenciais", action="store_true", help="o que está configurado")
    p.add_argument(
        "--exportar-perfis",
        action="store_true",
        help="exportar contas descobertas e snapshots para JSONL",
    )
    p.add_argument("--workers", type=int, default=5, help="tarefas de rede em paralelo")
    p.add_argument(
        "--ciclo",
        action="store_true",
        help="uma passada por tudo que é incremental (usado pelo launchd)",
    )
    p.add_argument("--ads", action="store_true", help="varrer a Biblioteca de Anúncios da Meta")
    p.add_argument(
        "--termos-ads",
        type=int,
        default=1,
        help="termos/candidatos da Meta processados nesta execução",
    )
    p.add_argument(
        "--paginas-ads", type=int, default=100, help="páginas máximas da API da Meta por termo"
    )
    p.add_argument("--de", metavar="AAAAMM", help="início da janela")
    p.add_argument("--ate", metavar="AAAAMM", help="fim da janela")
    p.add_argument("--limite", type=int, default=500, help="capturas por alvo (Common Crawl)")
    p.add_argument(
        "--sem-transcricao", action="store_true", help="baixar vídeo sem transcrever — só metadados"
    )
    a = p.parse_args(argv)

    if a.telegram_login:
        return login_telegram(a.telefone)
    if a.credenciais:
        credenciais()
        return 0
    if a.feeds:
        for f in rss.FEEDS:
            print(f"  {f.chave:20} {f.fonte:9} {f.licenca:11} {f.url}")
        for s_ in youtube.SEMENTES:
            print(f"  {s_.chave:20} {'video':9} {'referencia':11} {s_.alvo}")
        for a_ in commoncrawl.ALVOS:
            print(f"  {a_.chave:20} {'cc':9} {a_.licenca:11} {a_.padrao}")
        for m_ in sitemap.MAPAS:
            print(f"  {m_.chave:20} {'sitemap':9} {m_.licenca:11} {m_.url}")
        return 0

    with Store() as store:
        if a.list:
            relatorio(store)
            return 0
        if a.exportar_perfis:
            print(exportar_perfis(store))
            return 0
        if a.video:
            coletar_video(
                store, a.only or [], transcrever=not a.sem_transcricao, com_frames=a.frames
            )
            print()
            relatorio(store)
            return 0
        if a.youtube_comments:
            coletar_comentarios_youtube(
                store, lote_videos=a.limite, paginas_por_video=a.paginas_comentarios
            )
            print()
            relatorio(store)
            return 0
        if a.tse:
            coletar_tse(store, forcar=True)
            print(tse.resumo(tse.carregar()))
            print()
            relatorio(store)
            return 0
        if a.tse_abertos:
            coletar_tse_abertos(store, limite_por_recurso=a.limite, forcar=True)
            print()
            relatorio(store)
            return 0
        if a.dou:
            coletar_dou(store, de=a.de, ate=a.ate)
            print()
            relatorio(store)
            return 0
        if a.dou_espelho:
            coletar_dou_espelho(store, limite=a.limite)
            print()
            relatorio(store)
            return 0
        if a.bluesky:
            coletar_bluesky(store, de=a.de, limite=a.limite)
            print()
            relatorio(store)
            return 0
        if a.bing_news:
            coletar_bing_news(store)
            print()
            relatorio(store)
            return 0
        if a.tse_radio:
            coletar_tse_radio(store)
            print()
            relatorio(store)
            return 0
        if a.perfis_sociais:
            coletar_perfis_sociais(
                store,
                lote_perfis=a.limite,
                posts_por_perfil=a.posts_por_perfil,
                transcrever_audio=not a.sem_transcricao,
            )
            print()
            relatorio(store)
            return 0
        if a.sites_candidatos:
            coletar_sites_candidatos(
                store, lote_sites=a.limite, paginas_por_site=a.paginas_por_site
            )
            print()
            relatorio(store)
            return 0
        if a.enriquecer_midia:
            enriquecer_midias(store, limite=a.limite)
            print()
            relatorio(store)
            return 0
        if a.worker_midia:
            return worker_midias(store, lote=a.limite, espera=a.espera)
        if a.descoberta_social:
            coletar_busca_social(store, quantidade_termos=1, resultados=a.limite)
            atualizar_descobertas_sociais(store)
            coletar_publicacoes_descobertas(store, limite=a.limite)
            coletar_perfis_descobertos(store, limite=a.limite, posts_por_perfil=a.posts_por_perfil)
            exportar_perfis(store)
            print()
            relatorio(store)
            return 0
        if a.rotulos:
            coletar_rotulos(store)
            print()
            relatorio(store)
            return 0
        if a.hidratar_noticias:
            hidratar_noticias(store, limite=a.limite)
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
        if a.telegram_midia:
            enriquecer_telegram(store, limite=a.limite)
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
            coletar_ads(
                store,
                de=a.de,
                ate=a.ate,
                quantidade_termos=a.termos_ads,
                limite_paginas=a.paginas_ads,
            )
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
