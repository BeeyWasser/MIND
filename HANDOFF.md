# Handoff da coleta de dados do MIND

Estado operacional revisado em 15 de setembro de 2026. A metodologia está em
`COLETA.md`, os acessos em `CREDENCIAIS.md`, a especificação científica em
`SPEC.md`, os datasets reconstruíveis em `DADOS.md` e a distribuição do corpus
em `data/eleicoes2026/README.md`.

## 1. Resumo verificável

O corpus local auditado contém **160.918 documentos**, **720 arquivos
`jsonl.gz`** e **8,7 GiB** em `data/eleicoes2026/`:

| Fonte | Documentos |
|---|---:|
| Notícias | 61.112 |
| Reddit | 49.225 |
| Registros de candidaturas do TSE | 20.530 |
| Telegram | 13.683 |
| YouTube | 6.687 |
| Bluesky | 3.009 |
| Checagens | 2.847 |
| Partidos | 2.664 |
| Instagram | 511 |
| TikTok | 306 |
| HGPE em blocos | 170 |
| HGPE em inserções | 108 |
| DOU | 40 |
| Sites de candidatos | 8 |
| Facebook | 2 |
| X | 16 |

O SQLite passou em `PRAGMA quick_check`. A auditoria estrita encontrou igualdade
exata entre os 160.918 registros e os JSONL, sem gzip corrompido, JSON inválido,
`doc_id` duplicado ou mídia registrada ausente. Há três execuções antigas sem
`fim`, preservadas como interrupções operacionais. A coleta mais recente no
banco é de 4 de setembro de 2026; portanto o corpus está íntegro, mas a série
precisa ser retomada antes do congelamento científico.

O arquivo `data/eleicoes2026/perfis_sociais.jsonl` é uma exportação de
conveniência. Cada snapshot local o regenera a partir do banco para não guardar
uma versão defasada.

O corpus produzido existe somente na máquina coletora e está ignorado pelo Git.
O repositório público contém os coletores, a documentação e os comandos para
cada orientado construir seu próprio corpus local. Snapshots em `dist/` também
são locais e servem apenas para backup ou transferência manual autorizada.

## 2. Decisão de escopo

O TSE é uma semente de alta precisão, não a fronteira da coleta. O universo
inclui candidatos, partidos, imprensa, criadores, coletivos, influenciadores,
agências de checagem e qualquer conta pública que produza ou circule conteúdo
político brasileiro.

O grafo de descoberta cresce por:

1. redes declaradas ao TSE;
2. busca temática ampla no YouTube e descoberta gratuita pelo Bing News;
3. TikTok Research API quando houver aprovação;
4. URLs presentes em notícias, checagens, Reddit e Telegram;
5. autor de cada publicação coletada;
6. marcações `@perfil` em posts raiz;
7. busca global do Telegram e busca pública do Bluesky.

Comentários não expandem o grafo por marcações, evitando seguir usuários comuns
apenas por participarem da conversa. O conteúdo textual deles ainda pode ser
coletado e pseudonimizado quando a fonte autorizada o fornecer.

## 3. Filas persistentes

O SQLite `data/eleicoes2026/mind.db` contém duas estruturas centrais:

- `alvos_sociais`: plataforma, URL, tipo, origem, relevância, tentativas,
  erro e última coleta;
- `snapshots_perfis_sociais`: versões distintas dos campos públicos de uma
  conta, identificadas por hash do payload.

O inventário atual contém, entre outros:

| Plataforma/tipo | Alvos |
|---|---:|
| Instagram/perfil | 14.955 |
| Facebook/perfil | 6.431 |
| TikTok/perfil | 4.266 |
| YouTube/perfil | 2.450 |
| X/perfil | 2.056 |
| Instagram/publicação | 892 |
| YouTube/publicação | 816 |
| Bluesky/perfil | 496 |
| X/publicação | 332 |
| Telegram/perfil | 112 |
| TikTok/publicação | 55 |

Esses números incluem sementes e descobertas externas; não significam que cada
perfil já teve todas as publicações baixadas. A fila revisita perfis em ordem de
relevância e tempo desde a última coleta.

## 4. Conteúdo das contas

Cada publicação tenta preservar legenda/descrição, data, duração, métricas,
hashtags, links, conta de origem e modalidade. Quando a plataforma disponibiliza,
o snapshot da conta inclui nome público, handle, bio, URL externa, seguidores,
seguindo, total de posts, verificação e foto pública.

Rotas implementadas:

- Instagram: embed para URL conhecida; `gallery-dl` com cookies da própria
  sessão para enumerar perfis e capturar metadados públicos;
- TikTok: `yt-dlp` para URLs e perfis públicos descobertos; Research API para
  busca temática, `voice_to_text`, métricas, comentários e respostas;
- YouTube: busca temática, canais, vídeos, Shorts, streams, metadados e todos os
  replies que não vierem embutidos em `commentThreads.list`;
- Facebook e X: publicação com URL exata quando suportada; descoberta web e
  inventário de perfis permanecem mesmo quando a plataforma bloqueia extração;
- Bluesky: busca e perfis pela API pública do AT Protocol;
- Telegram: canais conhecidos, URLs citadas e busca global temática.

Meta Content Library continua sendo a rota necessária para escala e comentários
orgânicos de Facebook, Instagram e Threads. A fila local não substitui esse
acesso institucional.

## 5. Transcrição, imagem e vídeo

Há um worker exclusivo disponível. Ele processa três etapas independentes:

1. áudio/vídeo: áudio mínimo via `yt-dlp` ou Telethon e transcrição segmentada
   com `mlx-whisper`;
2. vídeo: download temporário, keyframes por mudança de cena e OCR;
3. imagem: OCR, pHash, dHash e miniatura.

O backlog muda a cada ciclo e deve ser consultado com `--list`. O worker não
relê todos os documentos a cada lote. Ele seleciona IDs no
SQLite, abre somente os gzip necessários e registra cada etapa em
`processamentos_midia`. Três falhas recentes colocam apenas aquela etapa em
quarentena temporária. OCR de vídeo continua mesmo quando não há áudio ou o
Whisper falha. Resultado vazio válido, como vídeo sem texto na tela, é marcado
como concluído para não baixar a peça infinitamente.

## 6. Coleta contínua

Não há agente `launchd` ativo no estado revisado. Os scripts locais continuam
no repositório, mas não devem ser descritos como serviço em execução. A última
coleta registrada é de 4 de setembro de 2026.

Windows, macOS e Linux podem chamar o mesmo ciclo de rede:

```bash
uv run python -m mind_collect.run --ciclo --sem-transcricao
```

A máquina autoritativa pode agendar esse comando com Task Scheduler, `launchd`
ou systemd. As credenciais ficam na máquina, não no agendador versionado. O
worker de mídia usa uma trava portátil, mas os backends atuais de transcrição e
OCR exigem macOS 14 ou mais novo com Apple Silicon.

## 7. Comandos da aplicação

```bash
# estado e inventários
uv run python -m mind_collect.run --list
uv run python -m mind_collect.run --credenciais
uv run python -m mind_collect.run --feeds
uv run python -m mind_collect.run --exportar-perfis

# execução normal
uv run python -m mind_collect.run --ciclo --sem-transcricao
uv run python -m mind_collect.run --worker-midia --limite 3 --espera 60

# descoberta fora do TSE
uv run python -m mind_collect.run --descoberta-social --limite 20 --posts-por-perfil 5
uv run python -m mind_collect.run --social --limite 100 --sem-transcricao
uv run python -m mind_collect.run --bluesky --limite 100
uv run python -m mind_collect.run --telegram --limite 300

# mídia e comentários
uv run python -m mind_collect.run --enriquecer-midia --limite 10
uv run python -m mind_collect.run --telegram-midia --limite 10
uv run python -m mind_collect.run --youtube-comments --limite 5 --paginas-comentarios 5

# histórico e fontes institucionais
uv run python -m mind_collect.run --commoncrawl --de 201801 --limite 200
uv run python -m mind_collect.run --wayback --de 201801 --limite 200
uv run python -m mind_collect.run --tse
uv run python -m mind_collect.run --tse-abertos --limite 500
uv run python -m mind_collect.run --dou-espelho --limite 500
```

## 8. Credenciais e acessos humanos

Sem novas chaves, RSS, Common Crawl, Wayback, Bing News, GDELT, Reddit via
Arctic Shift, Bluesky, YouTube público e TSE seguem funcionando. A sessão antiga
do Telegram foi revogada por `AuthKeyDuplicatedError` e preservada fora do
corpus com sufixo `invalid-20260916`; execute `--telegram-login` para criar uma
sessão nova. Cada outra máquina também precisa de sua própria sessão.

O material do Reddit permanece somente como referência interna: não entra em
treino nem pode ser redistribuído. Ampliação, retenção e retirada precisam
seguir os termos vigentes citados em `CREDENCIAIS.md`.

Pendências locais:

- `META_ADS_TOKEN`: anúncios políticos, criativo, gasto e alcance;
- `YOUTUBE_API_KEY`: comentários e respostas;
- `INSTAGRAM_COOKIES_FILE`: enumeração de perfis com sessão própria;
- `MEDIACLOUD_API_KEY`: arquivo jornalístico complementar;
- `INLABS_EMAIL` e `INLABS_PASSWORD`: DOU oficial diário.

A Brave Search API foi retirada do ciclo: exige plano e dados de pagamento. A
política atual aceita somente fontes sem cobrança; a matriz completa está em
`CREDENCIAIS.md`.

Pendências institucionais:

- Meta Content Library/API para conteúdo orgânico em escala;
- TikTok Research API, somente se o projeto atender formalmente aos critérios
  de elegibilidade;
- Reddit for Researchers para a rota oficial de pesquisa.

Não há mais necessidade de `REDDIT_CLIENT_ID` ou `REDDIT_CLIENT_SECRET` no
pipeline atual. Detalhes e links estão em `CREDENCIAIS.md`.

## 9. Segurança, licença e limites

`.env`, sessão do Telethon, cookies, banco, corpus e exportações estão fora do
Git. Nunca imprimir ou documentar tokens. O `api_id` e o `api_hash` iniciais do
Telegram foram expostos em conversa, mas o portal não oferece rotação garantida
do hash. Revise as sessões ativas da conta, encerre acessos desconhecidos,
descarte sessões locais antigas e refaça o login; use outro aplicativo somente
se o Telegram permitir criá-lo.

Conteúdo público permanece `licenca_uso=referencia` por padrão. Não usar proxy
residencial, CAPTCHA solver, API privada, conta descartável, cookie de terceiros,
bypass de paywall ou conteúdo privado. Cookies próprios do Instagram são uma
opção local explícita; Meta Content Library é preferível para escala e
reprodutibilidade.

Identificadores de autores comuns ficam pseudonimizados com `MIND_SALT`.
Snapshots em claro se restringem às contas públicas que entraram no grafo de
pesquisa; comentários não criam novos alvos por marcação.

Limitações a relatar: acesso desigual entre plataformas, viés de descoberta,
remoção de posts, quotas, transcrição ruim em jingles, OCR ruim em texto pequeno,
faixas aproximadas de alcance/gasto e cobertura temporal ainda em formação.

## 10. Validação e retomada

Antes de congelar uma versão:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest -q
uv run python scripts/get_data.py --selftest
uv run mind-data status
git diff --check
```

Ao retomar:

1. verificar `git status` e `uv run mind-data status`;
2. executar `--credenciais` sem copiar valores para a saída;
3. confirmar qual máquina é o único coletor autoritativo;
4. executar um ciclo manual e acompanhar o backlog com `--list`;
5. criar e verificar um snapshot `team` antes de um backup importante;
6. medir cobertura por plataforma, ator, partido, estado, tempo e modalidade,
   não apenas pelo total bruto.
