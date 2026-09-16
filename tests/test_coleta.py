"""Testes da espinha da coleta. Sem rede."""

import gzip
import json
from pathlib import Path

import pytest

from mind_collect.schema import Documento, Midia, Segmento, anonimizar
from mind_collect.store import Store


def doc(**kw) -> Documento:
    base = {"fonte": "noticia", "url": "https://g1.globo.com/a", "texto": "corpo"}
    return Documento(**{**base, **kw})


class TestSchema:
    def test_doc_id_depende_do_conteudo(self):
        assert doc(texto="a").doc_id != doc(texto="b").doc_id

    def test_doc_id_estavel(self):
        assert doc().doc_id == doc().doc_id

    def test_conteudo_inclui_transcricao(self):
        d = doc(texto="", transcricao=[Segmento(0, 1, "vote"), Segmento(1, 2, "em mim")])
        assert d.conteudo == "vote\nem mim"

    def test_roundtrip_json(self):
        d = doc(transcricao=[Segmento(0.0, 1.5, "oi")], gasto=12.5, segmentacao={"BR": 1})
        volta = Documento.from_json(d.to_json())
        assert volta.doc_id == d.doc_id
        assert volta.transcricao[0].texto == "oi"
        assert volta.gasto == 12.5

    def test_doc_id_persistido_nao_muda_com_enriquecimento(self):
        original = doc(texto="", titulo="vídeo")
        volta = Documento.from_json(original.to_json())
        doc_id = volta.doc_id
        volta.transcricao = [Segmento(0, 1, "fala enriquecida depois")]
        assert volta.doc_id == doc_id

    @pytest.mark.parametrize(
        "campo,valor",
        [
            ("fonte", "inexistente"),
            ("licenca_uso", "publico"),
            ("modalidade", "gif"),
        ],
    )
    def test_rejeita_valor_invalido(self, campo, valor):
        with pytest.raises(ValueError):
            doc(**{campo: valor})

    def test_treinavel_so_com_licenca_livre(self):
        assert doc(licenca_uso="livre").treinavel
        assert not doc(licenca_uso="referencia").treinavel
        assert not doc(licenca_uso="restrito").treinavel
        assert not doc(texto="", titulo="", licenca_uso="livre").treinavel

    def test_anonimizar_e_deterministico_e_depende_do_sal(self):
        assert anonimizar("@ze", "s1") == anonimizar("@ze", "s1")
        assert anonimizar("@ze", "s1") != anonimizar("@ze", "s2")
        assert "@ze" not in anonimizar("@ze", "s1")


class TestLimpezaDeFeed:
    def test_tira_tags_e_resolve_entidades(self):
        from mind_collect.sources.rss import _sem_html

        html = '<p>Nas <a href="http://x">eleições</a> &mdash; ok.</p>'
        assert _sem_html(html) == "Nas eleições — ok."

    def test_separa_blocos_adjacentes(self):
        from mind_collect.sources.rss import _sem_html

        assert _sem_html("<p>Fim.</p><p>Começo.</p>") == "Fim. Começo."

    def test_filtro_politico_cobre_eleicao_e_instituicoes(self):
        from mind_collect.sources.rss import POLITICA

        assert POLITICA.search("Propaganda eleitoral para presidente")
        assert POLITICA.search("Senado debate regra do TSE")
        assert not POLITICA.search("Time vence campeonato estadual")

    def test_feed_de_partido_fica_separado_e_nao_treinavel(self):
        from mind_collect.sources.rss import POR_CHAVE

        feed = POR_CHAVE["partido-pt"]
        assert feed.fonte == "partido"
        assert feed.licenca == "referencia"

    def test_chaves_de_feed_sao_unicas(self):
        from mind_collect.sources.rss import FEEDS

        chaves = [feed.chave for feed in FEEDS]
        assert len(chaves) == len(set(chaves))


class TestStore:
    def test_guarda_e_deduplica(self, tmp_path: Path):
        with Store(tmp_path) as st:
            assert st.guardar(doc()) is True
            assert st.guardar(doc()) is False
            assert st.tem_url("https://g1.globo.com/a")
            assert not st.tem_url("https://g1.globo.com/inexistente")

    def test_dedup_por_conteudo_nao_por_url(self, tmp_path: Path):
        with Store(tmp_path) as st:
            st.guardar(doc(url="https://g1.globo.com/a", texto="mesmo"))
            # mesma matéria republicada em outra URL: doc_id difere porque a URL
            # entra no hash — o dedup por similaridade é do dedup.py, não daqui
            assert st.guardar(doc(url="https://g1.globo.com/b", texto="mesmo")) is True

    def test_filtro_de_licenca_isola_o_treino(self, tmp_path: Path):
        with Store(tmp_path) as st:
            st.guardar(doc(texto="livre", licenca_uso="livre"))
            st.guardar(doc(texto="checagem", fonte="checagem", licenca_uso="referencia"))
            treino = list(st.ler(treinavel=True))
            assert len(treino) == 1
            assert treino[0].texto == "livre"

    def test_particiona_por_fonte_e_dia(self, tmp_path: Path):
        with Store(tmp_path) as st:
            st.guardar(doc())
            arqs = list(tmp_path.glob("noticia/*.jsonl.gz"))
            assert len(arqs) == 1
            with gzip.open(arqs[0], "rt") as f:
                assert '"fonte": "noticia"' in f.read()

    def test_registra_execucao(self, tmp_path: Path):
        with Store(tmp_path) as st:
            i = st.iniciar_execucao("g1-politica")
            st.encerrar_execucao(i, novos=3, repetidos=1, erros=0)
            n, r = st.con.execute(
                "SELECT novos, repetidos FROM execucoes WHERE id=?", (i,)
            ).fetchone()
            assert (n, r) == (3, 1)

    def test_detecta_buraco_na_serie(self, tmp_path: Path):
        with Store(tmp_path) as st:
            for dia, t in [("2026-08-20", "a"), ("2026-08-23", "b")]:
                st.guardar(doc(texto=t, coletado_em=f"{dia}T10:00:00+00:00"))
            assert st.buracos("noticia") == ["2026-08-21", "2026-08-22"]

    def test_midia_nao_guarda_original(self, tmp_path: Path):
        with Store(tmp_path) as st:
            d = doc(modalidade="video")
            st.guardar(d)
            m = Midia(
                doc_id=d.doc_id,
                tipo="frame",
                url_origem="https://x/1.jpg",
                t_seg=3.0,
                phash="ff00",
                ocr_texto="URGENTE",
            )
            st.guardar_midia(m)
            campos = [c[1] for c in st.con.execute("PRAGMA table_info(midias)")]
            assert "conteudo" not in campos and "blob" not in campos
            assert st.con.execute("SELECT ocr_texto FROM midias").fetchone()[0] == "URGENTE"

    def test_enriquece_rotulo_e_transcricao_sem_duplicar(self, tmp_path: Path):
        with Store(tmp_path) as st:
            d = doc(texto="", titulo="vídeo", modalidade="video")
            st.guardar(d)
            st.guardar_rotulo(d.doc_id, "falso", "lupa")
            st.guardar_transcricao(d.doc_id, [Segmento(0, 2, "fala política")])
            volta = list(st.ler())[0]
            assert volta.rotulo_externo == "falso"
            assert volta.fonte_rotulo == "lupa"
            assert volta.transcricao[0].texto == "fala política"
            assert st.con.execute("SELECT COUNT(*) FROM documentos").fetchone()[0] == 1

    def test_enriquece_texto_sem_mudar_doc_id(self, tmp_path: Path):
        with Store(tmp_path) as st:
            original = doc(
                texto="",
                titulo="",
                metadados={"origem": "gdelt"},
                licenca_uso="livre",
            )
            assert st.guardar(original)
            st.guardar_conteudo(original.doc_id, "Título recuperado", "corpo " * 80)
            volta = next(st.ler())
            assert volta.doc_id == original.doc_id
            assert volta.titulo == "Título recuperado"
            assert volta.treinavel

    def test_cursor_persistente(self, tmp_path: Path):
        with Store(tmp_path) as st:
            assert st.cursor("tiktok") == 0
            st.salvar_cursor("tiktok", 17)
            assert st.cursor("tiktok") == 17

    def test_falha_repetida_entra_em_quarentena(self, tmp_path: Path):
        with Store(tmp_path) as st:
            for _ in range(3):
                st.registrar_falha("social", "https://x/video/1", "indisponível")
            assert "https://x/video/1" in st.bloqueadas("social")
            st.limpar_falha("social", "https://x/video/1")
            assert not st.bloqueadas("social")

    def test_fila_social_persiste_origem_prioridade_e_sucesso(self, tmp_path: Path):
        with Store(tmp_path) as st:
            url = "https://www.instagram.com/contapolitica"
            st.registrar_alvo_social("instagram", url, "publicacao", "corpus", relevancia=1)
            st.registrar_alvo_social("instagram", url, "publicacao", "busca", relevancia=7)
            alvo = st.listar_alvos_sociais("publicacao", ("instagram",), 1)[0]
            assert alvo.relevancia == 7
            assert alvo.origem == "busca"
            st.marcar_alvo_social("instagram", url)
            assert st.listar_alvos_sociais("publicacao", ("instagram",), 1) == []

    def test_etapa_de_midia_vazia_pode_ser_concluida(self, tmp_path: Path):
        with Store(tmp_path) as st:
            st.marcar_processamento_midia("doc-1", "frames", True, "sem texto divergente")
            assert st.processados_midia("frames") == {"doc-1"}

    def test_transcricao_embutida_entra_no_indice(self, tmp_path: Path):
        with Store(tmp_path) as st:
            documento = doc(
                modalidade="video",
                transcricao=[Segmento(0, 1, "fala já transcrita")],
            )
            st.guardar(documento)
            assert documento.doc_id in st.transcritos()

    def test_leitura_seletiva_aplica_enriquecimentos(self, tmp_path: Path):
        with Store(tmp_path) as st:
            primeiro = doc(url="https://g1.globo.com/1", texto="primeiro")
            segundo = doc(url="https://g1.globo.com/2", texto="segundo")
            st.guardar(primeiro)
            st.guardar(segundo)
            st.guardar_conteudo(segundo.doc_id, "recuperado", "texto enriquecido")
            assert [item.doc_id for item in st.ler_ids([segundo.doc_id])] == [segundo.doc_id]
            assert next(st.ler_ids([segundo.doc_id])).texto == "texto enriquecido"

    def test_snapshot_de_perfil_so_repete_quando_muda(self, tmp_path: Path):
        with Store(tmp_path) as st:
            dados = {"bio": "jornalismo político", "seguidores": 100}
            assert st.registrar_snapshot_perfil(
                "instagram", "https://instagram.com/x", dados, "busca"
            )
            assert not st.registrar_snapshot_perfil(
                "instagram", "https://instagram.com/x", dados, "busca"
            )
            assert st.registrar_snapshot_perfil(
                "instagram",
                "https://instagram.com/x",
                {**dados, "seguidores": 101},
                "busca",
            )
            assert (
                st.con.execute("SELECT COUNT(*) FROM snapshots_perfis_sociais").fetchone()[0] == 2
            )

    def test_exporta_inventario_com_snapshot_mais_recente(self, tmp_path: Path):
        from mind_collect.run import exportar_perfis

        with Store(tmp_path) as st:
            url = "https://www.tiktok.com/@politica"
            st.registrar_alvo_social("tiktok", url, "perfil", "busca", relevancia=4)
            st.registrar_snapshot_perfil("tiktok", url, {"seguidores": 10}, "publicacao")
            destino = exportar_perfis(st)
            exportado = json.loads(destino.read_text())
            assert exportado["url"] == url
            assert exportado["snapshot"]["seguidores"] == 10


class TestVideo:
    def peca(self, **kw):
        from mind_collect.media.download import Peca

        base = {"id": "abc123", "url": "https://youtu.be/abc123", "titulo": "Bloco"}
        return Peca(**{**base, **kw})

    def test_insercao_e_bloco_pela_duracao(self):
        from mind_collect.sources.youtube import classificar

        assert classificar(self.peca(duracao_seg=30)) == "hgpe_insercao"
        assert classificar(self.peca(duracao_seg=60)) == "hgpe_insercao"
        assert classificar(self.peca(duracao_seg=758)) == "hgpe_bloco"

    def test_sem_duracao_assume_bloco(self):
        from mind_collect.sources.youtube import classificar

        assert classificar(self.peca(duracao_seg=None)) == "hgpe_bloco"

    def test_documento_leva_transcricao_para_o_conteudo(self):
        from mind_collect.sources.youtube import para_documento

        segs = [Segmento(0.0, 2.0, "vote em mim"), Segmento(2.0, 4.0, "pelo Brasil")]
        d = para_documento(self.peca(duracao_seg=45, canal="Partido X"), "2026", segs)
        assert d.fonte == "hgpe_insercao"
        assert d.modalidade == "video"
        assert d.patrocinador == "Partido X"
        assert "vote em mim pelo Brasil" in d.conteudo.replace("\n", " ")

    def test_documento_sobrevive_sem_transcricao(self):
        from mind_collect.sources.youtube import para_documento

        d = para_documento(self.peca(duracao_seg=600, descricao="corpo"), "2022", [])
        assert d.transcricao == []
        assert d.conteudo  # título e descrição já bastam
        assert d.licenca_uso == "referencia"


class TestDedup:
    def test_normaliza_acento_caixa_e_pontuacao(self):
        from mind_collect.dedup import normalizar

        assert normalizar("Eleições, JÁ!") == normalizar("eleicoes ja")

    def test_pega_quase_identico(self):
        from mind_collect.dedup import IndiceTexto

        ix = IndiceTexto()
        base = "o candidato prometeu reduzir impostos e gerar emprego para o povo brasileiro"
        assert ix.adicionar("a", base) is True
        assert ix.adicionar("b", base + ".") is False
        assert ix.adicionar("c", base.upper()) is False

    def test_nao_colapsa_texto_diferente(self):
        from mind_collect.dedup import IndiceTexto

        ix = IndiceTexto()
        ix.adicionar("a", "o candidato prometeu reduzir impostos e gerar emprego para o povo")
        outro = "a inflacao fechou o mes em zero virgula quatro por cento segundo o ibge"
        assert ix.adicionar("b", outro) is True
        assert len(ix) == 2

    def test_distancia_perceptual(self):
        from mind_collect.dedup import distancia, parecidas

        assert distancia("ffff0000ffff0000", "ffff0000ffff0000") == 0
        assert distancia("ffff0000ffff0000", "ffff0000ffff0001") == 1
        conhecidos = ["ffff0000ffff0001", "0000ffff0000ffff"]
        assert parecidas("ffff0000ffff0000", conhecidos, limite=8) == ["ffff0000ffff0001"]

    def test_texto_curto_nao_quebra(self):
        from mind_collect.dedup import IndiceTexto, shingles

        assert shingles("") == set()
        assert ix_ok(IndiceTexto())


def ix_ok(ix) -> bool:
    ix.adicionar("x", "duas palavras")
    return len(ix) == 1


class TestTranscricao:
    def test_tira_repeticao_consecutiva(self):
        from mind_collect.media.transcribe import _sem_repeticao

        segs = [
            Segmento(0, 28, "O que é a verdade?"),
            Segmento(30, 60, "O que é a verdade?"),
            Segmento(60, 90, "o que é a verdade?"),  # só muda a caixa
            Segmento(90, 93, "Vem comigo."),
        ]
        assert [s.texto for s in _sem_repeticao(segs)] == ["O que é a verdade?", "Vem comigo."]

    def test_preserva_repeticao_nao_consecutiva(self):
        from mind_collect.media.transcribe import _sem_repeticao

        segs = [Segmento(0, 2, "vote"), Segmento(2, 4, "no Brasil"), Segmento(4, 6, "vote")]
        assert len(_sem_repeticao(segs)) == 3

    def test_junta_texto(self):
        from mind_collect.media.transcribe import texto

        assert texto([Segmento(0, 1, "vote"), Segmento(1, 2, "agora")]) == "vote agora"

    def test_corta_segmento_de_baixa_confianca(self):
        from mind_collect.media.transcribe import _sem_repeticao

        segs = [
            Segmento(0, 6, "Fede como Atocampak", confianca=-1.39),  # jingle
            Segmento(93, 98, "Eu não admito chamar fome de fome", confianca=-0.14),
        ]
        assert [s.texto for s in _sem_repeticao(segs)] == ["Eu não admito chamar fome de fome"]

    def test_corta_credito_de_legenda(self):
        from mind_collect.media.transcribe import _sem_repeticao

        segs = [
            Segmento(0, 28, "Legendas pela comunidade Amara.org", confianca=-0.5),
            Segmento(30, 33, "Vem comigo.", confianca=-0.2),
        ]
        assert [s.texto for s in _sem_repeticao(segs)] == ["Vem comigo."]

    def test_corta_janela_cheia_de_30s(self):
        from mind_collect.media.transcribe import _janela_cheia

        assert _janela_cheia(Segmento(30.0, 60.0, "x")) is True
        assert _janela_cheia(Segmento(93.1, 98.9, "x")) is False


class TestUrlDaPeca:
    def test_extracao_plana_usa_campo_url(self):
        from mind_collect.media.download import _url

        # extract_flat não devolve webpage_url — foi o que quebrou a descoberta
        assert _url({"id": "abc", "url": "https://youtu.be/abc"}) == "https://youtu.be/abc"

    def test_extracao_completa_prefere_webpage_url(self):
        from mind_collect.media.download import _url

        info = {
            "id": "abc",
            "url": "https://cdn/x.m3u8",
            "webpage_url": "https://www.youtube.com/watch?v=abc",
        }
        assert _url(info) == "https://www.youtube.com/watch?v=abc"

    def test_reconstroi_a_partir_do_id(self):
        from mind_collect.media.download import _url

        assert _url({"id": "abc"}) == "https://www.youtube.com/watch?v=abc"

    def test_sem_id_devolve_vazio(self):
        from mind_collect.media.download import _url

        assert _url({}) == ""

    def test_perfil_youtube_vai_para_aba_de_videos(self):
        from mind_collect.sources.tiktok import _perfil_listavel

        assert _perfil_listavel("https://youtube.com/@candidato") == (
            "https://youtube.com/@candidato/videos"
        )

    def test_perfil_youtube_enumera_videos_shorts_e_streams(self):
        from mind_collect.sources.tiktok import _perfis_listaveis

        assert _perfis_listaveis("https://youtube.com/@candidato") == (
            "https://youtube.com/@candidato/videos",
            "https://youtube.com/@candidato/shorts",
            "https://youtube.com/@candidato/streams",
        )


class TestCommonCrawl:
    def test_chaves_de_alvo_sao_unicas(self):
        from mind_collect.sources.commoncrawl import ALVOS

        chaves = [alvo.chave for alvo in ALVOS]
        assert len(chaves) == len(set(chaves))

    def test_filtra_galeria_tag_e_binario(self):
        from mind_collect.sources.commoncrawl import util

        assert util("https://g1.globo.com/politica/noticia/2026/08/x.ghtml")
        # foi o que o índice devolveu de verdade no primeiro teste: só foto
        assert not util("https://agenciabrasil.ebc.com.br/politica/foto/2015-10/y")
        assert not util("https://g1.globo.com/politica/tag/eleicoes/")
        assert not util("https://x.com/a/page/3/")
        assert not util("https://x.com/imagem.jpg")


class TestMetaAds:
    def test_junta_variacoes_de_criativo_sem_repetir(self):
        from mind_collect.sources.meta_ads import _texto

        # a API devolve listas: um anúncio pode ter várias variações no mesmo id
        a = {
            "ad_creative_link_titles": ["Vote 13"],
            "ad_creative_bodies": ["Mude o Brasil", "Mude o Brasil", "Agora"],
        }
        assert _texto(a) == "Vote 13\nMude o Brasil\nAgora"

    def test_faixa_vira_ponto_medio(self):
        from mind_collect.sources.meta_ads import _numero

        assert _numero({"lower_bound": "100", "upper_bound": "200"}) == 150.0
        assert _numero({"lower_bound": "100"}) == 100.0
        assert _numero("42") == 42.0
        assert _numero(None) is None

    def test_documento_preserva_gasto_e_alcance(self):
        from mind_collect.sources.meta_ads import para_documento

        d = para_documento(
            {
                "id": "1",
                "ad_snapshot_url": "https://fb.com/ads/1",
                "ad_creative_bodies": ["texto do anuncio"],
                "ad_delivery_start_time": "2026-08-20",
                "bylines": "Coligação X",
                "spend": {"lower_bound": "500", "upper_bound": "999"},
                "impressions": {"lower_bound": "10000", "upper_bound": "20000"},
            }
        )
        assert d.fonte == "meta_ads"
        assert d.patrocinador == "Coligação X"
        assert d.gasto == 749.5
        assert d.alcance == 15000
        assert d.eleicao == "2026"

    def test_alcance_brasileiro_tem_precedencia(self):
        from mind_collect.sources.meta_ads import para_documento

        d = para_documento(
            {
                "id": "1",
                "ad_snapshot_url": "https://fb.com/ads/1",
                "ad_creative_bodies": ["texto"],
                "br_total_reach": 321,
                "impressions": {"lower_bound": "10000", "upper_bound": "20000"},
            }
        )
        assert d.alcance == 321

    def test_versao_da_api_e_configuravel(self, monkeypatch):
        from mind_collect.sources.meta_ads import api

        monkeypatch.setenv("META_GRAPH_API_VERSION", "26.0")
        assert api().endswith("/v26.0/ads_archive")

    def test_termos_incluem_busca_ampla(self):
        from mind_collect.run import _termos_ads

        assert _termos_ads()[:3] == ["eleições", "propaganda eleitoral", "campanha eleitoral"]

    def test_sem_token_da_erro_claro(self, monkeypatch):
        from mind_collect.sources.meta_ads import SemToken, token

        monkeypatch.delenv("META_ADS_TOKEN", raising=False)
        with pytest.raises(SemToken, match="verificação de identidade"):
            token()


class TestCicloEleitoral:
    def test_deriva_da_data_e_nao_do_ano_corrente(self):
        from mind_collect.schema import eleicao_de

        # sitemap devolve do mais antigo para o mais novo: carimbar 2026 em
        # matéria de 2016 passou despercebido até olhar o resultado
        assert eleicao_de("2016-09-02") == "2016"
        assert eleicao_de("2026-08-24") == "2026"

    def test_ano_sem_eleicao_fica_nulo(self):
        from mind_collect.schema import eleicao_de

        assert eleicao_de("2025-12-10") is None
        assert eleicao_de("2021-08-25") is None

    def test_data_ausente_ou_curta(self):
        from mind_collect.schema import eleicao_de

        assert eleicao_de(None) is None
        assert eleicao_de("") is None
        assert eleicao_de("202") is None


class TestGdelt:
    def test_filtro_estreito_exclui_tema_generico(self):
        from mind_collect.sources.gdelt import TEMAS_ELEITORAIS, URL_POLITICA

        # o filtro largo trouxe vagas de emprego e IPO junto com campanha
        assert not TEMAS_ELEITORAIS.search("WB_2670_JOBS;WB_470_EDUCATION")
        assert TEMAS_ELEITORAIS.search("ELECTION;TAX_FNCACT")
        assert URL_POLITICA.search("https://x.com.br/eleicoes/acm-neto")
        assert not URL_POLITICA.search("https://x.com.br/esportes/jogo")

    def test_janelas_de_15_minutos(self):
        from datetime import datetime

        from mind_collect.sources.gdelt import janelas

        js = list(janelas(datetime(2026, 8, 24, 14, 7), datetime(2026, 8, 24, 14, 40)))
        assert len(js) == 3
        assert js[0].endswith("20260824140000.translation.gkg.csv.zip")
        assert js[-1].endswith("20260824143000.translation.gkg.csv.zip")


class TestRegistroTSE:
    def test_reconhece_plataforma_pela_url(self):
        from mind_collect.sources.tse import _plataforma

        assert _plataforma("https://www.instagram.com/fulano") == "instagram"
        assert _plataforma("https://youtu.be/x") == "youtube"
        assert _plataforma("https://t.me/canal") == "telegram"
        assert _plataforma("https://threads.com/@candidato") == "threads"
        assert _plataforma("https://site.com.br") == "site"

    def test_registro_ausente_nao_quebra(self, tmp_path: Path):
        from mind_collect.sources.tse import carregar, resumo

        assert carregar(tmp_path) == {}
        assert "vazio" in resumo({})

    def test_contas_filtra_por_cargo_e_aptidao(self):
        from mind_collect.sources.tse import Candidato, contas

        reg = {
            "1": Candidato(
                "1",
                "A",
                "A",
                "PT",
                "PRESIDENTE",
                "BR",
                "APTO",
                {"youtube": ["https://youtube.com/@a"]},
            ),
            "2": Candidato(
                "2",
                "B",
                "B",
                "PL",
                "DEPUTADO FEDERAL",
                "SP",
                "APTO",
                {"youtube": ["https://youtube.com/@b"]},
            ),
            "3": Candidato(
                "3",
                "C",
                "C",
                "PP",
                "GOVERNADOR",
                "RJ",
                "INAPTO",
                {"youtube": ["https://youtube.com/@c"]},
            ),
        }
        assert contas(reg, "youtube") == ["https://youtube.com/@a"]

    def test_inapto_nao_conta_como_apto(self):
        from mind_collect.sources.tse import Candidato

        assert Candidato("1", "A", "A", "PT", "PRESIDENTE", "BR", "APTO").apto
        assert not Candidato("2", "B", "B", "PL", "PRESIDENTE", "BR", "INAPTO").apto
        assert not Candidato("3", "C", "C", "PP", "PRESIDENTE", "BR", "CASSADO").apto

    def test_situacao_ainda_nao_examinada_continua_coletavel(self):
        from mind_collect.sources.tse import Candidato

        assert Candidato("1", "A", "A", "PT", "PRESIDENTE", "BR", "#NE").apto

    def test_normaliza_url_declarada_sem_protocolo(self):
        from mind_collect.sources.tse import normalizar_url

        assert normalizar_url("WWW.TIKTOK.COM/@NOME/?_r=1") == "https://www.tiktok.com/@NOME"

    def test_recupera_url_colada_de_conversa(self):
        from mind_collect.sources.tse import normalizar_url

        bruto = "[17:38, 04/08/2026] Pessoa: HTTPS://WWW.INSTAGRAM.COM/NOME?IGS"
        assert normalizar_url(bruto) == "https://www.instagram.com/NOME"

    def test_descarta_email_declarado_como_rede(self):
        from mind_collect.sources.tse import normalizar_url

        assert normalizar_url("pessoa@gmail.com") == ""


class TestTseAbertos:
    def test_catalogo_cobre_cinco_conjuntos(self):
        from mind_collect.sources.tse_abertos import RECURSOS

        conjuntos = {recurso.conjunto for recurso in RECURSOS}
        assert conjuntos == {
            "processual-2026",
            "denuncias-eleitorais",
            "pesquisas-eleitorais-2026",
            "prestacao-de-contas-eleitorais-2026",
            "candidatos-2026",
        }
        assert len(RECURSOS) == 72
        assert sum(recurso.chave.startswith("propostas-") for recurso in RECURSOS) == 28
        assert sum(recurso.chave.startswith("fotos-") for recurso in RECURSOS) == 28

    def test_avisa_quando_pdftotext_nao_esta_instalado(self, monkeypatch):
        from mind_collect.sources import tse_abertos

        monkeypatch.setattr(tse_abertos.shutil, "which", lambda _name: None)

        with pytest.raises(RuntimeError, match="instale o Poppler"):
            tse_abertos._texto_pdf(b"%PDF-1.4")

    def test_ingere_csv_incrementalmente(self, tmp_path: Path):
        import zipfile

        from mind_collect.sources.tse_abertos import RECURSOS, lote

        caminho = tmp_path / "pardal.zip"
        with zipfile.ZipFile(caminho, "w") as compactado:
            compactado.writestr(
                "denuncia.csv",
                "SG_PARTIDO_DENUNCIADO;DS_CARGO_DENUNCIADO;DS_TIPO_IRREGULARIDADE\n"
                "ABC;GOVERNADOR;PROPAGANDA NA INTERNET\n"
                "XYZ;SENADOR;OUTDOOR\n",
            )
        recurso = next(item for item in RECURSOS if item.chave == "pardal")
        primeiro, cursor = lote(recurso, caminho, inicio=0, limite=1)
        segundo, fim = lote(recurso, caminho, inicio=cursor, limite=1)
        assert primeiro[0].fonte == "tse_denuncia"
        assert primeiro[0].partido == "ABC"
        assert segundo[0].partido == "XYZ"
        assert (cursor, fim) == (1, 2)


class TestBluesky:
    def test_normaliza_handle_e_descarta_url_truncada(self):
        from mind_collect.sources.bluesky import handle_de_url

        assert (
            handle_de_url("https://bsky.app/PROFILE/CANDIDATO.BSKY.SOCIAL")
            == "candidato.bsky.social"
        )
        assert handle_de_url("https://bsky.app/PROFI") is None

    def test_converte_post_e_preserva_links_e_imagem(self):
        from mind_collect.sources.bluesky import para_documento

        post = {
            "uri": "at://did:plc:x/app.bsky.feed.post/abc",
            "cid": "cid",
            "author": {"did": "did:plc:x", "handle": "candidato.bsky.social"},
            "record": {
                "text": "Vote consciente",
                "createdAt": "2026-09-01T10:00:00Z",
                "langs": ["pt"],
                "facets": [{"features": [{"uri": "https://tiktok.com/@x/video/1"}]}],
            },
            "embed": {"images": [{"fullsize": "https://cdn/x.jpg", "alt": "cartaz"}]},
            "likeCount": 12,
        }
        doc = para_documento(post)
        assert doc.fonte == "bluesky"
        assert "cartaz" in doc.conteudo
        assert doc.metadados["links"] == ["https://tiktok.com/@x/video/1"]
        assert doc.metadados["midias"][0]["url"] == "https://cdn/x.jpg"
        assert doc.modalidade == "imagem"
        assert doc.alcance is None


class TestInstagram:
    def test_extrai_contexto_do_embed_e_converte_imagem(self):
        from mind_collect.sources.instagram import _contexto, para_documento

        media = {
            "__typename": "GraphImage",
            "id": "1",
            "shortcode": "ABC",
            "is_video": False,
            "display_url": "https://cdn/imagem.jpg",
            "accessibility_caption": "cartaz vote 10",
            "edge_media_to_caption": {"edges": [{"node": {"text": "Legenda política"}}]},
            "owner": {"id": "99"},
        }
        contexto = {"gql_data": {"shortcode_media": media}}
        html = f'<script>"contextJSON":{json.dumps(json.dumps(contexto))}</script>'
        extraida = _contexto(html)
        doc = para_documento(extraida, "https://www.instagram.com/p/ABC")
        assert doc.modalidade == "imagem"
        assert "Legenda política" in doc.conteudo
        assert "cartaz vote 10" in doc.conteudo
        assert doc.metadados["midias"][0]["url"] == "https://cdn/imagem.jpg"


class TestSitesCandidatos:
    def test_extrai_titulo_e_links_absolutos(self):
        from mind_collect.sources.sites_candidatos import _pagina

        titulo, links = _pagina(
            '<title>Plano &amp; Governo</title><a href="/propostas">Propostas</a>',
            "https://candidato.com.br/inicio",
        )
        assert titulo == "Plano & Governo"
        assert links == ["https://candidato.com.br/propostas"]


class TestBingNews:
    def test_desembrulha_url_original(self):
        from mind_collect.sources.bing_news import url_original

        url = (
            "https://www.bing.com/news/apiclick.aspx?ref=FexRss&"
            "url=https%3A%2F%2Fportal.com.br%2Fpolitica%2Fmateria"
        )
        assert url_original(url) == "https://portal.com.br/politica/materia"


class TestTseRadio:
    def test_descobre_spots_e_exclui_mapa_e_claquete(self):
        from mind_collect.sources.tse_radio import descobrir

        base = "https://www.tse.jus.br/x/arquivos-partidos/pl-partido-liberal/31-08/"
        markdown = "\n".join(
            [
                f"[FB-04]({base}fb-04)",
                f"[Mapa de mídia]({base}mapa)",
                f"[CLAQUETE-L1]({base}claquete-l1.mp3)",
            ]
        )
        assert descobrir(markdown) == [("FB-04", base + "fb-04", "PL")]


class TestTelegram:
    def test_preserva_tipo_de_midia_sem_caption(self):
        from types import SimpleNamespace

        from mind_collect.sources.telegram import _tipo_midia

        mensagem = SimpleNamespace(
            photo=object(), video=None, audio=None, voice=None, media=object()
        )
        assert _tipo_midia(mensagem) == "imagem"

    def test_processa_imagem_local_sem_guardar_original(self, tmp_path: Path):
        from PIL import Image

        from mind_collect.media.images import processar_arquivo

        origem = tmp_path / "original.png"
        Image.new("RGB", (20, 20), "white").save(origem)
        midia = processar_arquivo("abc", origem, "https://t.me/canal/1", destino=tmp_path)
        assert midia.phash
        assert midia.thumb_path
        assert origem.exists()


class TestYoutubeComments:
    def test_converte_e_anonimiza_comentario(self, monkeypatch):
        from mind_collect.sources.youtube_comments import _documento

        monkeypatch.setenv("MIND_SALT", "teste")
        comentario = {
            "id": "abc",
            "snippet": {
                "textDisplay": "Mensagem política suficientemente longa para coleta",
                "publishedAt": "2026-09-01T10:00:00Z",
                "authorChannelId": {"value": "UC123"},
                "likeCount": 7,
            },
        }
        doc = _documento(comentario, "video")
        assert doc is not None
        assert doc.autor_hash and "UC123" not in doc.to_json()
        assert doc.metadados["likes"] == 7

    def test_pagina_todas_as_respostas_ausentes_do_thread(self, monkeypatch):
        from mind_collect.sources.youtube_comments import _respostas

        monkeypatch.setenv("YOUTUBE_API_KEY", "chave")

        class Resposta:
            def __init__(self, dados):
                self.dados = dados

            def raise_for_status(self):
                return None

            def json(self):
                return self.dados

        class Cliente:
            def __init__(self):
                self.paginas = [
                    {
                        "items": [
                            {
                                "id": "r1",
                                "snippet": {"textOriginal": "resposta política longa o bastante"},
                            },
                            {
                                "id": "r2",
                                "snippet": {"textOriginal": "segunda resposta política completa"},
                            },
                        ],
                        "nextPageToken": "2",
                    },
                    {
                        "items": [
                            {
                                "id": "r3",
                                "snippet": {"textOriginal": "terceira resposta política completa"},
                            }
                        ]
                    },
                ]

            def get(self, *_args, **_kwargs):
                return Resposta(self.paginas.pop(0))

        docs = list(_respostas(Cliente(), "video", "pai", {"r1"}))
        assert [doc.metadados["comentario_id"] for doc in docs] == ["r2", "r3"]


class TestDou:
    def test_converte_xml_eleitoral(self):
        from mind_collect.sources.dou import para_documento

        xml = b"""<xml><article id="42" pubName="DO1" pubDate="01/09/2026"
            artType="Resolucao" artCategory="Tribunal Superior Eleitoral"
            pdfPage="https://in.gov.br/pagina"><body>
            <Identifica><![CDATA[RESOLUCAO N 42]]></Identifica>
            <Ementa><![CDATA[Regras da propaganda eleitoral.]]></Ementa>
            <Texto><![CDATA[<p>Disciplina o impulsionamento de campanha nas
            eleicoes 2026.</p>]]></Texto>
            </body></article></xml>"""
        doc = para_documento(xml, "ato.xml")
        assert doc is not None
        assert doc.fonte == "dou"
        assert doc.eleicao == "2026"
        assert "impulsionamento" in doc.texto
        assert doc.metadados["id"] == "42"

    def test_descarta_xml_sem_relacao_eleitoral(self):
        from mind_collect.sources.dou import para_documento

        xml = b"""<xml><article id="1" pubDate="01/09/2026"><body>
            <Identifica>PORTARIA</Identifica>
            <Texto><![CDATA[<p>Autoriza ferias de servidor publico por trinta dias.</p>]]></Texto>
            </body></article></xml>"""
        assert para_documento(xml) is None

    def test_filtra_linha_publicada_no_espelho(self):
        from mind_collect.sources.dou_espelho import para_documento

        linha = {
            "id_materia": "123",
            "pub_date": "2026-09-01T00:00:00",
            "pub_name": "DO1",
            "identifica": "RESOLUÇÃO TSE",
            "art_category": "Tribunal Superior Eleitoral",
            "text": "Regulamenta a propaganda eleitoral na internet e o impulsionamento " * 3,
        }
        doc = para_documento(linha)
        assert doc is not None
        assert doc.fonte == "dou"
        assert doc.metadados["licenca_dataset"] == "CC0-1.0"


class TestRotulos:
    @pytest.mark.parametrize(
        ("titulo", "esperado"),
        [
            ("É falso que urnas foram fraudadas", "falso"),
            ("Vídeo de candidato foi tirado de contexto", "fora_de_contexto"),
            ("Imagem gerada por IA não mostra comício", "ia_sintetica"),
            ("Não há indícios de fraude", "sem_evidencia"),
        ],
    )
    def test_infere_apenas_vereditos_explicitos(self, titulo, esperado):
        from mind_collect.sources.rotulos import inferir

        d = doc(fonte="checagem", titulo=titulo, metadados={"feed": "lupa"})
        assert inferir(d) == (esperado, "lupa")

    def test_nao_rotula_corpo_ambiguo(self):
        from mind_collect.sources.rotulos import inferir

        d = doc(fonte="checagem", titulo="Entenda a fala", texto="A alegação é falsa")
        assert inferir(d) is None

    def test_nao_confunde_negacao_com_veredito_verdadeiro(self):
        from mind_collect.sources.rotulos import inferir

        d = doc(fonte="checagem", titulo="Não é verdade que candidato foi preso")
        assert inferir(d) is None


class TestAcharMidia:
    def test_ignora_json_de_transcricao(self, tmp_path: Path):
        from mind_collect.media.download import EXT_AUDIO, EXT_VIDEO, _achar

        (tmp_path / "abc.json").write_text("[]")  # cache da transcrição
        (tmp_path / "abc.m4a").write_bytes(b"audio")
        (tmp_path / "abc.mp4").write_bytes(b"video")
        assert _achar(tmp_path, "abc", EXT_AUDIO).suffix == ".m4a"
        assert _achar(tmp_path, "abc", EXT_VIDEO).suffix == ".mp4"

    def test_sem_midia_devolve_none(self, tmp_path: Path):
        from mind_collect.media.download import EXT_VIDEO, _achar

        (tmp_path / "abc.json").write_text("[]")
        assert _achar(tmp_path, "abc", EXT_VIDEO) is None


class TestFilaDeTranscricao:
    def test_youtube_sem_transcricao_nao_baixa_audio(self, monkeypatch):
        from mind_collect.media.download import Peca
        from mind_collect.sources import youtube

        achada = Peca(id="abc", url="https://youtube.com/watch?v=abc", titulo="Peça")
        monkeypatch.setattr(youtube, "listar", lambda *_args, **_kw: [achada])
        monkeypatch.setattr(youtube, "detalhar", lambda url: achada)
        monkeypatch.setattr(
            youtube,
            "baixar_audio",
            lambda *_args, **_kw: pytest.fail("não deveria baixar áudio na descoberta"),
        )
        docs = list(
            youtube.coletar(
                youtube.Semente("teste", "ytsearch1:teste", "2026"),
                lambda _video_id: False,
                transcrever_audio=False,
            )
        )
        assert len(docs) == 1
        assert docs[0][0].metadados["video_id"] == "abc"

    def test_enriquecimento_baixa_audio_ausente(self, tmp_path: Path, monkeypatch):
        from mind_collect import run
        from mind_collect.media.download import Peca

        audio = tmp_path / "abc.m4a"
        audio.write_bytes(b"audio")
        peca = Peca(id="abc", url="https://tiktok.com/@x/video/1", titulo="Peça", audio=audio)
        video = tmp_path / "abc.mp4"
        video.write_bytes(b"video")
        monkeypatch.setattr(run, "baixar_audio", lambda *_args, **_kw: peca)
        monkeypatch.setattr(run, "baixar_video", lambda *_args, **_kw: video)
        monkeypatch.setattr(run.youtube, "frames_de", lambda *_args, **_kw: [])
        monkeypatch.setattr(run, "transcrever", lambda _audio: [Segmento(0, 1, "fala")])
        with Store(tmp_path / "corpus") as st:
            st.guardar(
                doc(
                    fonte="tiktok",
                    url=peca.url,
                    texto="",
                    modalidade="video",
                    metadados={"video_id": "abc"},
                )
            )
            run.enriquecer_midias(st, limite=1)
            assert len(st.transcritos()) == 1
            assert st.processados_midia("frames")

    def test_ocr_do_video_independe_da_transcricao(self, tmp_path: Path, monkeypatch):
        from mind_collect import run

        video = tmp_path / "abc.mp4"
        video.write_bytes(b"video")
        monkeypatch.setattr(
            run,
            "baixar_audio",
            lambda *_args, **_kw: (_ for _ in ()).throw(RuntimeError("sem áudio")),
        )
        monkeypatch.setattr(run, "baixar_video", lambda *_args, **_kw: video)
        monkeypatch.setattr(run.youtube, "frames_de", lambda *_args, **_kw: [])
        with Store(tmp_path / "corpus") as st:
            st.guardar(
                doc(
                    fonte="tiktok",
                    url="https://tiktok.com/@x/video/1",
                    modalidade="video",
                    metadados={"video_id": "abc"},
                )
            )
            _novos, erros = run.enriquecer_midias(st, limite=1)
            assert erros == 1
            assert st.processados_midia("frames")

    def test_enriquecimento_geral_nao_tenta_baixar_telegram(self, tmp_path: Path, monkeypatch):
        from mind_collect import run

        monkeypatch.setattr(
            run,
            "baixar_audio",
            lambda *_args, **_kw: pytest.fail("Telegram usa Telethon, não yt-dlp"),
        )
        with Store(tmp_path / "corpus") as st:
            st.guardar(
                doc(
                    fonte="telegram",
                    canal="telegram",
                    url="https://t.me/canal/1",
                    modalidade="video",
                    metadados={"tem_midia": True, "midia_tipo": "video"},
                )
            )
            novos, erros = run.enriquecer_midias(st, limite=1)
            assert (novos, erros) == (0, 0)

    def test_telegram_faz_ocr_mesmo_se_transcricao_falhar(self, tmp_path: Path, monkeypatch):
        from mind_collect import run

        video = tmp_path / "telegram.mp4"
        video.write_bytes(b"video")

        def baixar(documentos, _limite, ao_falhar=None):
            del ao_falhar
            yield next(iter(documentos)), video

        monkeypatch.setattr(run.telegram, "baixar_midias", baixar)
        monkeypatch.setattr(
            run,
            "transcrever",
            lambda _caminho: (_ for _ in ()).throw(RuntimeError("sem áudio")),
        )
        monkeypatch.setattr(run.youtube, "frames_de", lambda *_args, **_kw: [])
        with Store(tmp_path / "corpus") as st:
            documento = doc(
                fonte="telegram",
                canal="telegram",
                url="https://t.me/canal/1",
                modalidade="video",
                metadados={
                    "tem_midia": True,
                    "midia_tipo": "video",
                    "canal": "canal",
                    "mensagem_id": 1,
                },
            )
            st.guardar(documento)
            _novos, erros = run.enriquecer_telegram(st, limite=1)
            assert erros == 1
            assert documento.doc_id in st.processados_midia("frames")


class TestOcrDivergente:
    def ach(self, texto, y=0.5):
        from mind_collect.media.ocr import Achado

        return Achado(texto, 0.99, (0.1, y, 0.5, 0.05))

    def test_descarta_legenda_que_repete_a_fala(self):
        from mind_collect.media.ocr import divergente

        fala = "eu nasci em dourados interior do mato grosso do sul sou casada"
        achados = [self.ach("Eu nasci em Dourados"), self.ach("SCRAYA PRESIDENTE")]
        assert [a.texto for a in divergente(achados, fala)] == ["SCRAYA PRESIDENTE"]

    def test_mantem_texto_curto_de_grafismo(self):
        from mind_collect.media.ocr import divergente

        # número de partido e cargo são curtos e nunca aparecem na fala assim
        achados = [self.ach("14"), self.ach("PRESIDENTE")]
        assert len(divergente(achados, "qualquer fala longa aqui")) == 2

    def test_ordem_de_leitura_de_cima_para_baixo(self):
        from mind_collect.media.ocr import texto

        # y cresce para cima no Vision: manchete tem y maior que a ressalva
        achados = [self.ach("ressalva em letra miuda", y=0.1), self.ach("MANCHETE GRANDE", y=0.9)]
        assert texto(achados).splitlines() == ["MANCHETE GRANDE", "ressalva em letra miuda"]

    def test_casa_apesar_de_pontuacao_e_acento(self):
        from mind_collect.media.ocr import divergente

        # OCR lê "Dourados," e o Whisper produz "Dourados." — sem normalizar,
        # legenda idêntica escapava do filtro
        fala = "eu nasci em dourados. interior do mato grosso do sul"
        achados = [self.ach("Eu nasci em Dourados,"), self.ach("VOTE 14 PRESIDENTE")]
        assert [a.texto for a in divergente(achados, fala)] == ["VOTE 14 PRESIDENTE"]


class TestConcorrencia:
    def test_arquivo_por_processo(self, tmp_path: Path):
        import os

        from mind_collect.store import Store

        with Store(tmp_path) as st:
            # sem o PID no nome, dois processos anexam ao mesmo .gz e o gzip
            # corrompe do ponto da colisão em diante
            assert str(os.getpid()) in st.caminho("noticia").name

    def test_leitura_sobrevive_a_arquivo_corrompido(self, tmp_path: Path):
        import gzip

        from mind_collect.store import Store

        with Store(tmp_path) as st:
            st.guardar(doc(texto="bom"))
            ruim = tmp_path / "noticia" / "2026-01-01-999.jsonl.gz"
            ruim.write_bytes(gzip.compress(b'{"fonte":"noticia"}\n') + b"\x00lixo\xff")
            assert len(list(st.ler())) >= 1  # não levanta

    def test_reparo_alinha_indice_e_conteudo(self, tmp_path: Path):
        from mind_collect.store import Store

        with Store(tmp_path) as st:
            st.guardar(doc(texto="a"))
            st.guardar(doc(texto="b"))
            for f in tmp_path.glob("*/*.jsonl.gz"):
                f.write_bytes(b"\x1f\x8b\x08\x00lixo")  # destrói o conteúdo
            salvos, _ = st.reparar()
            n = st.con.execute("SELECT COUNT(*) FROM documentos").fetchone()[0]
            # índice não pode afirmar ter documento cujo conteúdo sumiu: senão a
            # deduplicação pula a recoleta e o documento some de vez
            assert n == salvos


class TestMencoes:
    def test_extrai_das_tres_plataformas(self):
        from mind_collect.sources.mencoes import extrair

        t = (
            "veja https://www.tiktok.com/@x/video/7412345678901234567 e "
            "https://www.instagram.com/reel/Cx1y2Z3aBcD/ e https://youtu.be/dQw4w9WgXcQ"
        )
        a = extrair(t)
        assert set(a) == {"tiktok", "instagram", "youtube"}

    def test_extrai_publicacao_do_x(self):
        from mind_collect.sources.mencoes import extrair

        url = "https://x.com/candidato/status/1961234567890123456?s=20"
        assert extrair(url)["x"] == {url}

    def test_tira_parametro_de_rastreamento(self):
        from mind_collect.sources.mencoes import limpar

        # a mesma peça linkada de dois lugares vira duas URLs e escapa do dedup
        u = "https://www.tiktok.com/@x/video/74123?is_from_webapp=1&sender_device=pc"
        assert limpar(u) == "https://www.tiktok.com/@x/video/74123"
        assert limpar("https://youtu.be/abc?utm_source=x#t=10") == "https://youtu.be/abc"

    def test_conta_mencoes_repetidas(self):
        from mind_collect.sources.mencoes import varrer

        u = "https://www.tiktok.com/@x/video/7412345678901234567"
        docs = [doc(texto=f"olha {u}"), doc(texto=f"de novo {u}", url="https://o/2")]
        c = varrer(iter(docs))
        assert c["tiktok"][u] == 2

    def test_varre_link_guardado_em_metadados(self):
        from mind_collect.sources.mencoes import varrer

        u = "https://www.tiktok.com/@candidato/video/123"
        assert u in varrer(iter([doc(metadados={"link": u})]))["tiktok"]

    def test_remove_barra_codificada_de_url_social(self):
        from mind_collect.sources.mencoes import limpar

        assert limpar("https://tiktok.com/@nome%5C") == "https://tiktok.com/@nome"

    def test_perfil_tiktok_nao_vira_publicacao(self):
        from mind_collect.sources.mencoes import extrair

        assert "tiktok" not in extrair("https://www.tiktok.com/@candidato")

    def test_normaliza_tipo_de_publicacao_do_instagram(self):
        from mind_collect.sources.mencoes import limpar

        assert limpar("https://www.instagram.com/REEL/DYSGECYxIH0") == (
            "https://www.instagram.com/reel/DYSGECYxIH0"
        )

    def test_normaliza_tipo_de_publicacao_do_tiktok(self):
        from mind_collect.sources.mencoes import limpar

        assert limpar("https://www.tiktok.com/@NOME/VIDEO/7613140891359776021") == (
            "https://www.tiktok.com/@NOME/video/7613140891359776021"
        )

    def test_varre_janela_ampla_por_padrao(self):
        from mind_collect.sources.commoncrawl import DESDE_PADRAO

        # sem from_ts o cdx_toolkit usa um padrão estreito e a coleta raspa uma
        # fração dos 127 índices mensais do Common Crawl
        assert DESDE_PADRAO <= "201801"

    def test_descobre_perfis_dentro_e_fora_do_tse(self):
        from mind_collect.sources.mencoes import extrair_perfis

        texto = (
            "https://www.tiktok.com/@analise_politica/video/7613140891359776021 "
            "https://x.com/jornalista/status/1961234567890123456 "
            "https://www.instagram.com/coletivopolitico/"
        )
        assert extrair_perfis(texto) == {
            "tiktok": {"https://www.tiktok.com/@analise_politica"},
            "x": {"https://x.com/jornalista"},
            "instagram": {"https://www.instagram.com/coletivopolitico"},
        }


class TestTikTokResearch:
    def test_video_traz_legenda_oficial_e_conta(self):
        from mind_collect.sources.tiktok_research import para_documento

        documento = para_documento(
            {
                "id": 123,
                "username": "canalpolitico",
                "video_description": "Debate sobre a eleição",
                "voice_to_text": "Esta é a fala transcrita",
                "video_duration": 12,
                "create_time": 1788220800,
                "region_code": "BR",
            },
            "eleições 2026",
        )
        assert documento.url == "https://www.tiktok.com/@canalpolitico/video/123"
        assert documento.transcricao[0].texto == "Esta é a fala transcrita"
        assert documento.metadados["descoberta"] == "tiktok_research_api"

    def test_comentario_nao_expoe_autor(self):
        from mind_collect.sources.tiktok_research import para_comentario

        documento = para_comentario(
            {"id": 10, "text": "comentário político", "create_time": 1788220800}, "123"
        )
        assert documento is not None
        assert documento.autor_hash is None
        assert documento.metadados["video_id"] == "123"


class TestMencoesDePerfis:
    def test_post_raiz_expande_rede_de_contas(self):
        from mind_collect.sources.mencoes import perfis_mencionados

        documento = doc(
            fonte="tiktok",
            canal="tiktok",
            texto="Debate com @jornalpolitico e @analista.br",
        )
        assert perfis_mencionados(documento) == {
            ("tiktok", "https://www.tiktok.com/@jornalpolitico"),
            ("tiktok", "https://www.tiktok.com/@analista.br"),
        }

    def test_comentario_nao_expande_rede_de_usuarios(self):
        from mind_collect.sources.mencoes import perfis_mencionados

        documento = doc(
            fonte="youtube",
            canal="youtube",
            texto="concordo com @usuarioqualquer",
            metadados={"tipo": "comentario"},
        )
        assert perfis_mencionados(documento) == set()


class TestInstagramProfiles:
    def test_dump_traz_posts_e_snapshot_da_conta(self):
        from mind_collect.sources.instagram_profiles import dados_do_dump

        bruto = json.dumps(
            [
                [
                    2,
                    "",
                    {
                        "post_url": "https://www.instagram.com/p/ABC/",
                        "user": {
                            "username": "politicaaberta",
                            "full_name": "Política Aberta",
                            "biography": "Notícias e análise política",
                            "follower_count": 1234,
                            "is_verified": True,
                        },
                    },
                ],
                [2, "", {"post_url": "https://www.instagram.com/reel/DEF/"}],
            ]
        )
        descoberta = dados_do_dump(bruto)
        assert descoberta.urls == [
            "https://www.instagram.com/p/ABC/",
            "https://www.instagram.com/reel/DEF/",
        ]
        assert descoberta.perfil["handle"] == "politicaaberta"
        assert descoberta.perfil["seguidores"] == 1234


class TestStoreConcorrente:
    def test_escrita_paralela_nao_corrompe(self, tmp_path: Path):
        from concurrent.futures import ThreadPoolExecutor

        from mind_collect.store import Store

        with Store(tmp_path) as st:

            def grava(i):
                return st.guardar(doc(texto=f"documento numero {i}", url=f"https://x/{i}"))

            with ThreadPoolExecutor(max_workers=8) as pool:
                gravados = sum(pool.map(grava, range(200)))
            assert gravados == 200
            assert len(list(st.ler())) == 200  # relê sem zlib.error


class TestReidratacao:
    def test_dataset_sem_texto_nao_gera_documento(self):
        from mind_collect.sources.datasets import POR_CHAVE, coletar

        # os dois datasets que achei trazem só IDs; gerar Documento vazio a
        # partir deles encheria o corpus de lixo silencioso
        for chave in ("tweets-eleicoes-2022", "telegram-bolsonarista-2022"):
            f = POR_CHAVE[chave]
            assert f.reidratacao is True
            assert list(coletar(f)) == []

    def test_credencial_ausente_da_erro_nomeado(self, monkeypatch):
        from mind_collect.sources.mediacloud import SemChave, _chave

        monkeypatch.delenv("MEDIACLOUD_API_KEY", raising=False)
        with pytest.raises(SemChave, match="CREDENCIAIS.md"):
            _chave()

    def test_plataforma_ausente_devolve_contador_vazio(self):
        from collections import Counter

        from mind_collect.sources.mencoes import varrer

        c = varrer(iter([doc(texto="sem link nenhum aqui")]))
        # dict.get(k, {}) devolveria {} sem .most_common e derrubava a coleta
        assert c.get("telegram", Counter()).most_common(5) == []


def test_diagnostico_de_credenciais_tem_colunas_legiveis(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    from mind_collect import run

    for key in (
        "META_ADS_TOKEN",
        "TELEGRAM_API_ID",
        "MEDIACLOUD_API_KEY",
        "YOUTUBE_API_KEY",
        "TIKTOK_RESEARCH_CLIENT_KEY",
        "INSTAGRAM_COOKIES_FILE",
        "INLABS_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(run.instagram_profiles, "configurado", lambda: False)
    monkeypatch.setattr(run.telegram, "estado", lambda: "pronto")
    monkeypatch.chdir(tmp_path)

    run.credenciais()
    output = capsys.readouterr().out

    assert "   variável" in output and "fonte" in output and "efeito da ausência" in output
    assert "-- META_ADS_TOKEN" in output
    assert "-- TIKTOK_RESEARCH_CLIENT_KEY  TikTok Research API" in output
    assert "-- INSTAGRAM_COOKIES_FILE      Instagram com sessão própria" in output
    assert "dependências locais:" in output
    assert " ffmpeg" in output
