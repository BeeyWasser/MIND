"""O contrato entre todos os coletores.

Todo coletor devolve `Documento`. Nada mais. Se uma fonte tem campo que não cabe
aqui, ele vai em `metadados` — não se cria campo novo sem passar pelo COLETA.md.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

# De onde veio. Serve para particionar o armazenamento e para filtrar no treino.
FONTES = {
    "meta_ads",  # Biblioteca de Anúncios da Meta
    "hgpe_bloco",  # bloco em rede do horário eleitoral
    "hgpe_insercao",  # inserção de 30s/60s
    "youtube",  # vídeo ou comentário
    "tiktok",
    "instagram",
    "facebook",
    "x",
    "kwai",
    "bluesky",
    "site_candidato",
    "partido",  # comunicação oficial produzida por partidos
    "dou",  # Diário Oficial da União via INLABS
    "reddit",
    "telegram",
    "noticia",
    "checagem",  # agência de fact-checking
    "tse_decisao",  # decisão de remoção de propaganda
    "tse_denuncia",  # denúncia no Pardal — não implica irregularidade confirmada
    "tse_pesquisa",  # pesquisas eleitorais registradas
    "tse_financas",  # prestação de contas de campanha
    "tse_proposta",  # planos de governo entregues pelas candidaturas
    "tse_registro",  # candidatura — não é corpus, é vocabulário
}

# Se pode ir para treino. A Lupa publica Content-Signal ai-train=no e o Aos Fatos
# bloqueia bots de IA; o pipeline de treino filtra por "livre" e ninguém esquece.
LICENCAS = {"livre", "referencia", "restrito"}

MODALIDADES = {"texto", "audio", "video", "imagem"}


def _agora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Segmento:
    """Trecho transcrito, com posição no áudio.

    `confianca` é o avg_logprob do Whisper. Guardado porque discrimina fala de
    canto: jingle de HGPE sai perto de -1.4, fala real perto de -0.1. Fica no
    dado para o limiar poder ser calibrado depois, com material anotado.
    """

    inicio_seg: float
    fim_seg: float
    texto: str
    confianca: float | None = None


@dataclass
class Midia:
    """Frame de vídeo ou imagem. Nunca guarda o original — ver COLETA.md.

    Só hash perceptual, o texto do OCR, uma miniatura de 256px e a URL de origem.
    Um milhão de imagens a 200 KB não cabe em disco; a 20 KB, cabe.
    """

    doc_id: str
    tipo: str  # frame | imagem | thumbnail
    url_origem: str
    t_seg: float | None = None
    phash: str | None = None
    dhash: str | None = None
    ocr_texto: str | None = None
    thumb_path: str | None = None

    @property
    def midia_id(self) -> str:
        base = f"{self.doc_id}|{self.tipo}|{self.t_seg}|{self.url_origem}"
        return hashlib.sha256(base.encode()).hexdigest()[:32]


@dataclass
class Documento:
    fonte: str
    url: str
    texto: str = ""

    canal: str = "web"  # tv | radio | facebook | instagram | youtube | ...
    modalidade: str = "texto"
    eleicao: str | None = None  # 2018 | 2020 | 2022 | 2024 | 2026
    titulo: str = ""

    coletado_em: str = field(default_factory=_agora)
    veiculado_em: str | None = None
    veiculado_ate: str | None = None

    transcricao: list[Segmento] = field(default_factory=list)
    duracao_seg: float | None = None

    # Quem pagou e para quem. É o que separa este corpus de um monte de texto:
    # permite perguntar se técnica de manipulação correlaciona com gasto e alcance.
    patrocinador: str | None = None
    candidato_id: str | None = None
    partido: str | None = None
    cargo: str | None = None
    gasto: float | None = None
    alcance: int | None = None
    segmentacao: dict = field(default_factory=dict)

    # Transforma coleta em dado supervisionado: veredito de checagem ou decisão
    # judicial, sempre com a procedência junto.
    rotulo_externo: str | None = None
    fonte_rotulo: str | None = None

    # Conteúdo público não é sinônimo de licença aberta. O padrão conservador
    # evita que texto de jornal, post ou vídeo entre em treino por acidente.
    licenca_uso: str = "referencia"
    robots_ok: bool = True
    url_arquivada: str | None = None

    # Hash do identificador do autor + sal. Nunca o handle em claro: opinião
    # política é dado sensível pela LGPD (art. 5º, II).
    autor_hash: str | None = None

    metadados: dict = field(default_factory=dict)
    _doc_id: str | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.fonte not in FONTES:
            raise ValueError(f"fonte desconhecida: {self.fonte!r}")
        if self.licenca_uso not in LICENCAS:
            raise ValueError(f"licenca_uso inválida: {self.licenca_uso!r}")
        if self.modalidade not in MODALIDADES:
            raise ValueError(f"modalidade inválida: {self.modalidade!r}")

    @property
    def conteudo(self) -> str:
        """O que conta como texto do documento, transcrição incluída."""
        partes = [self.titulo, self.texto]
        partes += [s.texto for s in self.transcricao]
        return "\n".join(p for p in partes if p).strip()

    @property
    def doc_id(self) -> str:
        if self._doc_id:
            return self._doc_id
        base = f"{self.fonte}|{self.url}|{self.conteudo}"
        return hashlib.sha256(base.encode()).hexdigest()

    @property
    def treinavel(self) -> bool:
        return self.licenca_uso == "livre" and bool(self.conteudo.strip())

    def to_json(self) -> str:
        d = asdict(self)
        d.pop("_doc_id", None)
        d["doc_id"] = self.doc_id
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_json(cls, linha: str) -> Documento:
        d = json.loads(linha)
        doc_id = d.pop("doc_id", None)
        d["transcricao"] = [Segmento(**s) for s in d.get("transcricao", [])]
        doc = cls(**d)
        doc._doc_id = doc_id
        return doc


ANOS_ELEITORAIS = {"2014", "2016", "2018", "2020", "2022", "2024", "2026"}


def eleicao_de(data: str | None) -> str | None:
    """Ciclo eleitoral a que o documento pertence, a partir da data de publicação.

    Carimbar o ano corrente em tudo é errado e passa despercebido: sitemap vem do
    mais antigo para o mais novo, e o Common Crawl devolve página de qualquer ano.
    """
    if not data or len(data) < 4:
        return None
    ano = data[:4]
    return ano if ano in ANOS_ELEITORAIS else None


def anonimizar(identificador: str, sal: str) -> str:
    """Hash de autor. O sal fica fora do repositório."""
    return hashlib.sha256(f"{sal}|{identificador}".encode()).hexdigest()[:32]
