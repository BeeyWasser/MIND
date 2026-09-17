# MIND

MIND (Manipulation Identification and Narrative Detector) é uma ferramenta para
identificar técnicas de manipulação cognitiva em conteúdo digital.

Aplicação atual: técnicas de manipulação em texto político brasileiro, com a
propaganda das eleições de 2026 como corpus. Projeto em preparação para
submissão à FEBRACE 2027.

## Documentos

| Arquivo | Conteúdo |
|---|---|
| `HANDOFF.md` | **Estado da coleta, bugs conhecidos, o que está bloqueado e próximos passos. Comece por aqui para retomar.** |
| `SPEC.md` | Especificação científica do projeto — hipóteses, cronograma e riscos. **Fonte de autoridade da pesquisa.** |
| `COLETA.md` | Plano de coleta: fontes, arquitetura do pipeline, schema |
| `CREDENCIAIS.md` | Matriz de fontes gratuitas, decisões de uso e como obter cada acesso |
| `DADOS.md` | Corpora preexistentes em `data/`, reconstruídos por `scripts/get_data.py` |
| `data/eleicoes2026/README.md` | Como baixar, verificar, restaurar e continuar o corpus eleitoral em qualquer sistema |
| `data/eleicoes2026/SPEC.md` | Contrato técnico e de segurança dos backups locais |
| `febrace/` | Material oficial da FEBRACE (local, fora do git) |

Para decisões científicas, vale a `SPEC.md` da raiz. Para empacotamento e
distribuição do corpus, vale `data/eleicoes2026/SPEC.md`.

## Coleta

```bash
uv sync --locked --extra collect
uv run python -m mind_collect.run --ciclo --sem-transcricao
uv run python -m mind_collect.run --descoberta-social --limite 20
uv run python -m mind_collect.run --exportar-perfis
uv run python -m mind_collect.run --list
```

No macOS 14 ou mais novo com Apple Silicon, instale o extra `media` antes do
worker de transcrição e OCR:

```bash
uv sync --locked --extra media
uv run python -m mind_collect.run --worker-midia --limite 3
```

O ciclo rápido descobre textos, posts e contas. Um worker exclusivo processa em
segundo plano transcrição, imagens e keyframes/OCR. O TSE é apenas uma semente: o
grafo também cresce por busca temática, notícias, checagens, links e perfis
mencionados nas próprias publicações.

## Dados eleitorais locais

O repositório público contém o código e as instruções para obter os dados, mas
não contém o corpus produzido. `data/eleicoes2026/` fica ignorada pelo Git, com
exceção do README e da especificação.

```bash
uv run python -m mind_collect.run --ciclo --sem-transcricao
uv run mind-data status
```

Cada máquina constrói seu corpus local a partir das fontes públicas e das
credenciais gratuitas configuradas. O procedimento completo está em
[`data/eleicoes2026/README.md`](data/eleicoes2026/README.md).
