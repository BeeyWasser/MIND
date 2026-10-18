# Especificação de backup do corpus eleitoral

## Objetivo

Definir como o corpus é construído e mantido localmente, além do formato de
backup verificável, sem versionar dados pesados ou segredos no repositório
público do código.

## Decisão de armazenamento

O repositório público contém código, documentação, inventários de fontes e
instruções de coleta. O corpus produzido fica em `data/eleicoes2026/` e é
ignorado pelo Git, assim como os snapshots em `dist/`.

Não existe repositório separado de dados nem download automático de um corpus
pronto. Cada máquina executa os coletores e mantém seu próprio estado local. Um
snapshot pode ser criado para backup ou transferência manual autorizada, mas
não é publicado pelo programa.

## Fonte de verdade

O corpus canônico combina:

1. shards `<fonte>/*.jsonl.gz`, com uma linha JSON por documento;
2. `mind.db`, com índice, transcrições, textos enriquecidos, OCR, rótulos,
   cursores e filas;
3. arquivos derivados explicitamente incluídos pelo perfil do snapshot.

O SQLite não é reconstruível integralmente apenas pelos JSONL, porque alguns
enriquecimentos posteriores vivem somente no banco. Por isso todo snapshot
contém um backup consistente do banco.

## Perfis

### `team`

Perfil padrão para análise e continuidade:

- backup consistente de `mind.db`;
- todos os shards canônicos `*.jsonl.gz`;
- `perfis_sociais.jsonl` regenerado do backup;
- miniaturas de `_midia/thumbs/`.

Exclui mídia original, keyframes, caches, datasets intermediários e proveniência
bruta. OCR e transcrições continuam disponíveis pelo SQLite.

### `full-private`

Inclui tudo do perfil `team` e arquivos completos considerados seguros somente
quando o formato pertence à lista permitida de dados e mídia. Serve para
recuperação interna, não para publicação aberta.

Arquivos extras só podem vir de `_midia`, `_tse` ou `_tse_abertos`; datasets
externos reconstruíveis continuam fora. Shards canônicos são aceitos em seus
diretórios de fonte. JSON de mídia precisa ter o contrato de cache de
transcrição, e arquivos textuais com chaves ou assinaturas de credencial são
excluídos. Esse perfil serve somente para recuperação local e exige revisão de
licença antes de qualquer transferência manual.

## Exclusões obrigatórias

Nenhum perfil pode conter:

- `.env` ou variações;
- cookies;
- `*.session` e `*.session-journal`;
- `mind.db-wal` e `mind.db-shm`;
- `*.part`, `*.unknown_video`, `*.pid` e `*.lock`;
- `.DS_Store`;
- `_logs/`;
- `_quarentena/`;
- links simbólicos;
- documentação já versionada no Git.

O arquivo `perfis_sociais.jsonl` vivo também não é copiado. Ele é regenerado a
partir do SQLite congelado para não ficar defasado em relação ao snapshot.

## Consistência na criação

`mind-data pack` deve:

1. abrir o SQLite em modo somente leitura e criar a cópia com
   `sqlite3.Connection.backup()`;
2. executar `PRAGMA quick_check` na cópia;
3. ler estritamente todos os shards canônicos;
4. rejeitar JSON inválido, gzip truncado e `doc_id` ausente ou duplicado;
5. exigir igualdade exata entre `doc_id` dos shards e do banco;
6. exigir que todas as miniaturas referenciadas existam;
7. verificar tamanho e `mtime` antes e depois de copiar cada arquivo;
8. reconciliar novamente os `doc_id` dos shards já gravados no ZIP com o banco
   congelado;
9. comparar o resumo do SQLite arquivado com o resumo declarado no manifesto;
10. inspecionar nomes e conteúdo textual dentro dos ZIPs brutos permitidos,
    rejeitando credenciais, arquivos cifrados e ZIPs aninhados;
11. abortar e remover a saída parcial se qualquer etapa falhar.

Uma execução antiga sem `fim` é preservada como evidência operacional e aparece
no resumo do manifesto. Ela não torna o conteúdo inconsistente.

## Formato

Cada snapshot produz:

```text
mind-eleicoes2026-<UTC>-<perfil>.bundle.json
mind-eleicoes2026-<UTC>-<perfil>.zip
```

Se o ZIP ultrapassar o limite configurado, ele é substituído por:

```text
mind-eleicoes2026-<UTC>-<perfil>.zip.part001
mind-eleicoes2026-<UTC>-<perfil>.zip.part002
...
```

O ZIP usa ZIP64 e contém:

```text
MANIFEST.json
corpus/mind.db
corpus/perfis_sociais.jsonl
corpus/<arquivos do perfil>
```

O índice externo registra versão, identificador, data UTC, perfil,
classificação `private-team-only`, tamanho e SHA-256 do ZIP lógico, hash do
manifesto e tamanho e SHA-256 de cada parte.

O manifesto registra commit e estado limpo/sujo do Git, resumo do SQLite,
contagens, exclusões e, para cada arquivo, caminho relativo POSIX, tamanho e
SHA-256.

## Verificação

`mind-data verify` deve falhar quando:

- uma parte está ausente, tem outro tamanho ou outro hash;
- o ZIP lógico não corresponde ao índice;
- o manifesto foi alterado;
- há caminho absoluto, `..`, barra invertida, link simbólico, caminho duplicado
  ou arquivo não declarado;
- há arquivo declarado fora da lista permitida pelo perfil `team` ou
  `full-private`;
- qualquer arquivo interno diverge de seu tamanho ou hash;
- o resumo calculado do SQLite diverge do resumo declarado no manifesto;
- o SQLite não passa no `quick_check`.

Verificação bem-sucedida não transforma conteúdo de referência em conteúdo
livre. Integridade e licença são controles diferentes.

## Restauração

A restauração deve ocorrer em diretório temporário no mesmo volume do destino.
Todos os controles de integridade são executados antes da troca.

Sem `--replace`, qualquer dado existente interrompe a operação. `README.md`,
`SPEC.md` e `.gitkeep` não contam como dados e são preservados.

Com `--replace`, a pasta anterior é renomeada para
`eleicoes2026.backup-<UTC>`. A pasta validada assume o destino e a documentação
versionada já entra na pasta temporária antes da troca. Assim, não há escrita
falível no novo destino depois da instalação. Falhas durante a troca restauram
a pasta anterior sem apagar arquivos criados por outro processo.

## Caminhos portáveis

Novas linhas do SQLite guardam apenas caminhos relativos POSIX dentro do
corpus. A leitura também aceita os dois formatos legados:

- `data/eleicoes2026/<caminho>`;
- caminho absoluto de outro checkout que contenha o segmento `eleicoes2026`.

`MIND_DATA_DIR` permite escolher outra raiz antes de iniciar o processo. URLs
HTTP não são convertidas em caminhos locais.

## Limite público e transferência manual

Nenhum bundle é publicado automaticamente. O Git recebe apenas `README.md` e
`SPEC.md` dentro desta pasta; todos os demais caminhos continuam ignorados.

Quando houver necessidade de backup ou transferência autorizada, o responsável
cria o bundle com `mind-data pack`, verifica com `mind-data verify` e move o
índice e todas as partes por um canal escolhido fora do repositório. A máquina
destinatária usa `mind-data restore`.

## Coleta depois da restauração

Existe um único escritor autoritativo. O snapshot preserva cursores e filas,
portanto essa máquina pode retomar o ciclo. Não existe merge de bancos criados
por vários alunos; essa capacidade fica fora desta versão.

A coleta de rede foi projetada para ser portátil e a matriz de CI passou em
Windows, macOS e Linux. Transcrição MLX e OCR Vision são opcionais e restritos
ao macOS 14 ou mais novo com Apple Silicon. A ausência deles não impede
executar o ciclo com `--sem-transcricao`.

## Critérios de aceite

- a CLI base instala e abre sem extras de mídia;
- `uv run mind-data status` audita o corpus a partir de qualquer diretório;
- testes cobrem exclusões, backup com SQLite aberto, adulteração, path
  traversal, restauração e preservação do backup anterior;
- caminhos novos são relativos e caminhos antigos continuam legíveis;
- o lock do worker funciona sem `fcntl` e não bloqueia Windows;
- PDF temporário do TSE é fechado antes de `pdftotext`;
- lint e suíte completa passam;
- a CI executa instalação, CLIs, lint e testes em Windows, macOS e Linux;
- um snapshot real `team` foi criado e verificado localmente antes da entrega;
- nenhuma sessão, credencial, cookie ou dado bruto entra no Git.
