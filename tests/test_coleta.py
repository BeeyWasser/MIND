"""Testes da espinha da coleta. Sem rede."""

import gzip
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

    @pytest.mark.parametrize("campo,valor", [
        ("fonte", "inexistente"), ("licenca_uso", "publico"), ("modalidade", "gif"),
    ])
    def test_rejeita_valor_invalido(self, campo, valor):
        with pytest.raises(ValueError):
            doc(**{campo: valor})

    def test_treinavel_so_com_licenca_livre(self):
        assert doc(licenca_uso="livre").treinavel
        assert not doc(licenca_uso="referencia").treinavel
        assert not doc(licenca_uso="restrito").treinavel

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


class TestStore:
    def test_guarda_e_deduplica(self, tmp_path: Path):
        with Store(tmp_path) as st:
            assert st.guardar(doc()) is True
            assert st.guardar(doc()) is False

    def test_dedup_por_conteudo_nao_por_url(self, tmp_path: Path):
        with Store(tmp_path) as st:
            st.guardar(doc(url="https://g1.globo.com/a", texto="mesmo"))
            # mesma matéria republicada em outra URL: doc_id difere porque a URL
            # entra no hash — o dedup por similaridade é do dedup.py, não daqui
            assert st.guardar(doc(url="https://g1.globo.com/b", texto="mesmo")) is True

    def test_filtro_de_licenca_isola_o_treino(self, tmp_path: Path):
        with Store(tmp_path) as st:
            st.guardar(doc(texto="livre"))
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
            m = Midia(doc_id=d.doc_id, tipo="frame", url_origem="https://x/1.jpg",
                      t_seg=3.0, phash="ff00", ocr_texto="URGENTE")
            st.guardar_midia(m)
            campos = [c[1] for c in st.con.execute("PRAGMA table_info(midias)")]
            assert "conteudo" not in campos and "blob" not in campos
            assert st.con.execute("SELECT ocr_texto FROM midias").fetchone()[0] == "URGENTE"


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
            Segmento(60, 90, "o que é a verdade?"),   # só muda a caixa
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
            Segmento(0, 6, "Fede como Atocampak", confianca=-1.39),   # jingle
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
        info = {"id": "abc", "url": "https://cdn/x.m3u8",
                "webpage_url": "https://www.youtube.com/watch?v=abc"}
        assert _url(info) == "https://www.youtube.com/watch?v=abc"

    def test_reconstroi_a_partir_do_id(self):
        from mind_collect.media.download import _url
        assert _url({"id": "abc"}) == "https://www.youtube.com/watch?v=abc"

    def test_sem_id_devolve_vazio(self):
        from mind_collect.media.download import _url
        assert _url({}) == ""


class TestCommonCrawl:
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
        a = {"ad_creative_link_titles": ["Vote 13"],
             "ad_creative_bodies": ["Mude o Brasil", "Mude o Brasil", "Agora"]}
        assert _texto(a) == "Vote 13\nMude o Brasil\nAgora"

    def test_faixa_vira_ponto_medio(self):
        from mind_collect.sources.meta_ads import _numero
        assert _numero({"lower_bound": "100", "upper_bound": "200"}) == 150.0
        assert _numero({"lower_bound": "100"}) == 100.0
        assert _numero("42") == 42.0
        assert _numero(None) is None

    def test_documento_preserva_gasto_e_alcance(self):
        from mind_collect.sources.meta_ads import para_documento
        d = para_documento({
            "id": "1", "ad_snapshot_url": "https://fb.com/ads/1",
            "ad_creative_bodies": ["texto do anuncio"],
            "ad_delivery_start_time": "2026-08-20", "bylines": "Coligação X",
            "spend": {"lower_bound": "500", "upper_bound": "999"},
            "impressions": {"lower_bound": "10000", "upper_bound": "20000"},
        })
        assert d.fonte == "meta_ads"
        assert d.patrocinador == "Coligação X"
        assert d.gasto == 749.5
        assert d.alcance == 15000
        assert d.eleicao == "2026"

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
        assert _plataforma("https://site.com.br") is None

    def test_registro_ausente_nao_quebra(self, tmp_path: Path):
        from mind_collect.sources.tse import carregar, resumo
        assert carregar(tmp_path) == {}
        assert "vazio" in resumo({})

    def test_contas_filtra_por_cargo_e_aptidao(self):
        from mind_collect.sources.tse import Candidato, contas
        reg = {
            "1": Candidato("1", "A", "A", "PT", "PRESIDENTE", "BR", "APTO",
                           {"youtube": ["https://youtube.com/@a"]}),
            "2": Candidato("2", "B", "B", "PL", "DEPUTADO FEDERAL", "SP", "APTO",
                           {"youtube": ["https://youtube.com/@b"]}),
            "3": Candidato("3", "C", "C", "PP", "GOVERNADOR", "RJ", "INAPTO",
                           {"youtube": ["https://youtube.com/@c"]}),
        }
        assert contas(reg, "youtube") == ["https://youtube.com/@a"]

    def test_inapto_nao_conta_como_apto(self):
        from mind_collect.sources.tse import Candidato
        assert Candidato("1", "A", "A", "PT", "PRESIDENTE", "BR", "APTO").apto
        assert not Candidato("2", "B", "B", "PL", "PRESIDENTE", "BR", "INAPTO").apto
        assert not Candidato("3", "C", "C", "PP", "PRESIDENTE", "BR", "CASSADO").apto


class TestAcharMidia:
    def test_ignora_json_de_transcricao(self, tmp_path: Path):
        from mind_collect.media.download import EXT_AUDIO, EXT_VIDEO, _achar
        (tmp_path / "abc.json").write_text("[]")     # cache da transcrição
        (tmp_path / "abc.m4a").write_bytes(b"audio")
        (tmp_path / "abc.mp4").write_bytes(b"video")
        assert _achar(tmp_path, "abc", EXT_AUDIO).suffix == ".m4a"
        assert _achar(tmp_path, "abc", EXT_VIDEO).suffix == ".mp4"

    def test_sem_midia_devolve_none(self, tmp_path: Path):
        from mind_collect.media.download import EXT_VIDEO, _achar
        (tmp_path / "abc.json").write_text("[]")
        assert _achar(tmp_path, "abc", EXT_VIDEO) is None


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
        achados = [self.ach("ressalva em letra miuda", y=0.1),
                   self.ach("MANCHETE GRANDE", y=0.9)]
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
            assert len(list(st.ler())) >= 1        # não levanta

    def test_reparo_alinha_indice_e_conteudo(self, tmp_path: Path):
        from mind_collect.store import Store
        with Store(tmp_path) as st:
            st.guardar(doc(texto="a"))
            st.guardar(doc(texto="b"))
            for f in tmp_path.glob("*/*.jsonl.gz"):
                f.write_bytes(b"\x1f\x8b\x08\x00lixo")   # destrói o conteúdo
            salvos, _ = st.reparar()
            n = st.con.execute("SELECT COUNT(*) FROM documentos").fetchone()[0]
            # índice não pode afirmar ter documento cujo conteúdo sumiu: senão a
            # deduplicação pula a recoleta e o documento some de vez
            assert n == salvos


class TestMencoes:
    def test_extrai_das_tres_plataformas(self):
        from mind_collect.sources.mencoes import extrair
        t = ("veja https://www.tiktok.com/@x/video/7412345678901234567 e "
             "https://www.instagram.com/reel/Cx1y2Z3aBcD/ e https://youtu.be/dQw4w9WgXcQ")
        a = extrair(t)
        assert set(a) == {"tiktok", "instagram", "youtube"}

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

    def test_varre_janela_ampla_por_padrao(self):
        from mind_collect.sources.commoncrawl import DESDE_PADRAO
        # sem from_ts o cdx_toolkit usa um padrão estreito e a coleta raspa uma
        # fração dos 127 índices mensais do Common Crawl
        assert DESDE_PADRAO <= "201801"


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
            assert len(list(st.ler())) == 200   # relê sem zlib.error


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
