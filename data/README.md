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

O guia completo para baixar, verificar, restaurar, atualizar e compartilhar o
corpus está em [`data/eleicoes2026/README.md`](eleicoes2026/README.md). O
contrato técnico dos snapshots está em
[`data/eleicoes2026/SPEC.md`](eleicoes2026/SPEC.md).

Nunca copie a pasta inteira com `zip`, `tar`, Drive ou Dropbox. Ela contém
estado vivo do SQLite e pode conter sessão autenticada, arquivos parciais e
travas. Use sempre `uv run mind-data pack`.
