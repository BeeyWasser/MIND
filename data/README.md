# Dados do MIND

Esta pasta tem dois conjuntos com regras diferentes. Os arquivos pesados não
entram no Git; somente os guias ficam versionados.

## Bases acadêmicas

São corpora públicos ou de acesso controlado usados como referência para
treino e avaliação. O inventário, as licenças e o comando de download estão em
[`DADOS.md`](../DADOS.md).

```bash
uv run python scripts/get_data.py
```

## Corpus eleitoral brasileiro

Fica em `data/eleicoes2026/` e reúne notícias, propaganda, publicações sociais,
transcrições, OCR e metadados da coleta eleitoral. Como quase todo o conteúdo
está classificado para uso de referência, ele não pode ser publicado junto com
este repositório público.

O guia completo para baixar das fontes, coletar, atualizar e fazer backup local
está em [`data/eleicoes2026/README.md`](eleicoes2026/README.md). O contrato
técnico dos snapshots locais está em
[`data/eleicoes2026/SPEC.md`](eleicoes2026/SPEC.md).

Nunca force a inclusão da pasta no Git. Para backup ou transferência manual,
não copie o SQLite enquanto está ativo: use `uv run mind-data pack`.
