# Credenciais e acessos da coleta

Consulte o estado real com:

```bash
uv run python -m mind_collect.run --credenciais
```

Copie `.env.exemplo` para `.env`. O arquivo não entra no Git. Coletores sem
credencial são pulados sem interromper as fontes abertas.

Credenciais, cookies e sessões nunca entram nos snapshots compartilhados. O
procedimento de distribuição está em
[`data/eleicoes2026/README.md`](data/eleicoes2026/README.md).

## Política de custo

O projeto usa somente fontes que não exigem pagamento, assinatura, crédito
pré-pago ou cadastro de cartão. Uma franquia promocional que exige ativar plano
pago não é considerada gratuita. Também não contratamos aumento de quota: ao
atingir o limite gratuito, o coletor espera a renovação.

`SIM` significa que a rota faz parte do plano. `CONDICIONAL` significa que só
será usada depois de aprovação e confirmação escrita de custo zero. `NÃO`
significa que ela fica fora do ambiente, do ciclo automático e da lista de
credenciais.

## Matriz completa de fontes

### Fontes gratuitas já utilizáveis

| Fonte ou rota | O que fornece | Custo | Como obter | Vamos usar? |
|---|---|---:|---|:---:|
| RSS de imprensa, partidos e checagens | notícias, comunicação partidária e verificações | gratuito | lista versionada em `mind_collect/sources/rss.py`; roda em `--ciclo` | **SIM** |
| Sitemaps e sites de candidatos | páginas recentes e páginas declaradas ao TSE | gratuito | descoberta automática dos domínios públicos | **SIM** |
| Bing News RSS | descoberta de notícias por tema e candidato | gratuito, sem chave | consultas públicas feitas pelo coletor | **SIM** |
| [GDELT](https://www.gdeltproject.org/data.html) | descoberta e metadados de notícias | gratuito e aberto | API pública, sem cadastro | **SIM** |
| [Common Crawl](https://commoncrawl.org/get-started) | histórico web desde 2018 | gratuito por HTTPS, sem conta AWS | índice CDX e trechos WARC públicos | **SIM** |
| [Wayback Machine](https://web.archive.org/) | recuperação de páginas removidas | gratuito, sem chave | índice do Internet Archive, com limites educados | **SIM** |
| [TSE Dados Abertos](https://dadosabertos.tse.jus.br/) | candidaturas, redes, propostas, contas, pesquisas e processos | gratuito | ZIPs e catálogos oficiais; usar espelho gratuito quando o CDN bloquear | **SIM** |
| TSE rádio e HGPE | spots, inserções e blocos de propaganda | gratuito | páginas e canais públicos oficiais do TSE | **SIM** |
| [Câmara Dados Abertos](https://dadosabertos.camara.leg.br/swagger/api.html) | discursos e eventos parlamentares | gratuito, sem chave | API REST oficial | **SIM** |
| [Senado Dados Abertos](https://legis.senado.leg.br/dadosabertos/docs/) | discursos do plenário | gratuito, sem chave | API oficial | **SIM** |
| DOU espelho CC0 | atos eleitorais históricos | gratuito, sem login | snapshot configurado no coletor | **SIM** |
| YouTube público com `yt-dlp` | vídeos, Shorts, lives, canais e metadados | gratuito, sem chave | busca e páginas públicas | **SIM** |
| [Reddit via Arctic Shift](https://arctic-shift.photon-reddit.com/) | posts e comentários públicos arquivados | gratuito, sem chave; rota não oficial e sem licença de treino | somente referência interna, com retenção mínima e retirada | **SIM, COM RESTRIÇÕES** |
| [Bluesky AppView](https://docs.bsky.app/docs/api/app-bsky-feed-get-feed) | posts, perfis, imagens e métricas públicas | gratuito, sem autenticação | `https://public.api.bsky.app` | **SIM** |
| Instagram embed público | posts já conhecidos | gratuito, sem chave | URL pública encontrada no corpus | **SIM** |
| TikTok, Facebook e X por URL conhecida | mídia e metadados públicos aceitos pelo `yt-dlp` | gratuito, sem API | URLs encontradas em notícias, Telegram, Reddit e outras peças | **SIM** |
| Zenodo e corpora de pesquisa | conjuntos publicados com licença e metodologia | gratuito | downloads descritos em `DADOS.md`; respeitar licença e restrições | **SIM** |
| Transcrição e OCR locais | fala, texto de tela, miniaturas e hashes | sem API ou serviço pago | `mlx-whisper`, FFmpeg e OCR executados no Mac | **SIM** |

### Acessos gratuitos que ainda precisam ser obtidos

| Acesso | O que libera | Custo | Como obter | Vamos usar? |
|---|---|---:|---|:---:|
| Meta Ad Library API | anúncios políticos, criativo, gasto, alcance e segmentação | sem tarifa de API publicada | confirmar identidade, criar conta Meta for Developers, app e token `ads_archive` | **SIM** |
| Telegram API | histórico e mídia de canais públicos | gratuito | criar app em `my.telegram.org` e fazer login interativo uma vez | **SIM** |
| YouTube Data API v3 | comentários e todas as respostas | quota gratuita padrão | projeto Google Cloud, ativar API e gerar chave restrita | **SIM** |
| Media Cloud | busca no arquivo jornalístico | quota gratuita de 4.000 requisições/semana | cadastrar conta, confirmar e-mail e copiar API key | **SIM** |
| INLABS | XML oficial diário do DOU | cadastro gratuito | registrar e-mail e senha no portal da Imprensa Nacional | **SIM** |
| Cookies próprios do Instagram | enumeração de posts, bio e métricas públicas | sem tarifa; usa conta própria | exportar sessão local para arquivo Netscape fora do Git | **SIM** |
| TikTok Research API | busca temática, contas, vídeos e comentários em escala | sem tarifa publicada, mas exige aprovação | candidatura institucional, proposta e revisão ética | **NÃO AGORA** — o escopo brasileiro publicado exige pesquisa sobre segurança online de jovens |
| Meta Content Library no Meta Secure Research Environment | conteúdo orgânico público de Facebook e Instagram | sem tarifa publicada; confirmar na aprovação | candidatura institucional no portal da Meta | **CONDICIONAL** — somente com custo zero |
| Reddit Data API / programa de pesquisa | rota oficial para posts e comentários | gratuito apenas dentro dos limites aprovados | solicitar acesso não comercial ao Reddit | **NÃO AGORA** — Arctic Shift já cobre a coleta atual |

### Fontes rejeitadas ou indisponíveis

| Fonte ou rota | Motivo | Custo ou impedimento | Vamos usar? |
|---|---|---:|:---:|
| [Brave Search API](https://api-dashboard.search.brave.com/app/plans) | exige ativar plano e informar pagamento; créditos mensais não a tornam uma API gratuita | US$ 5 por 1.000 buscas no plano publicado | **NÃO** |
| [X API v2](https://docs.x.com/x-api/fundamentals/post-cap) | leitura e busca são cobradas por uso | créditos pré-pagos por requisição | **NÃO** |
| [SOMAR Virtual Data Enclave](https://www.icpsr.umich.edu/sites/somar/somar-vde-overview-and-resources) | ambiente pago da Meta Content Library | US$ 1.000 de instalação e US$ 371/mês | **NÃO** |
| TikTok Commercial Content API | não cobre o Brasil | países suportados são europeus | **NÃO** |
| Kwai | não há rota pública gratuita e reproduzível implementada | acesso indisponível | **NÃO AGORA** |
| SaaS de scraping, proxies e APIs de transcrição | cria custo recorrente e reduz a reprodutibilidade | pago por uso | **NÃO** |

## Estado local em 15 de setembro de 2026

| Acesso gratuito | Estado | Próxima ação |
|---|---|---|
| Telegram | `api_id` e `api_hash` presentes; sessão sem login | executar `--telegram-login` em Terminal interativo |
| Meta Ads | falta token/aprovação | iniciar confirmação de identidade |
| YouTube Data API | falta chave | criar projeto e chave restrita |
| Instagram | falta sessão/cookies | exportar cookies próprios localmente |
| Media Cloud | falta chave | cadastrar conta gratuita |
| INLABS | falta login | cadastrar conta gratuita |
| TikTok Research API | sem acesso e fora da elegibilidade atual | não solicitar com escopo incompatível |
| Meta Content Library | não solicitado | solicitar apenas pela opção gratuita da Meta |

## 1. Meta Ad Library

Variável:

```dotenv
META_ADS_TOKEN=
META_GRAPH_API_VERSION=v26.0
```

A Biblioteca de Anúncios mantém anúncios sobre temas sociais, eleições e
política por sete anos. O endpoint entrega criativo textual, anunciante, datas,
faixas de gasto e impressões e dados demográficos/geográficos disponíveis.

1. Entre em [Meta for Developers](https://developers.facebook.com/).
2. Crie um aplicativo e conclua a verificação exigida para a Ad Library API.
3. Confirme identidade/localização quando o fluxo pedir.
4. Gere um token aceito pelo endpoint `ads_archive`.
5. Coloque apenas o token no `.env`.
6. Teste uma consulta pequena:

```bash
uv run python -m mind_collect.run --ads --termos-ads 1 --paginas-ads 2
```

Não assumir que um token comum é permanente. Acompanhe expiração e erros de
permissão. A implementação usa a versão configurável em
`META_GRAPH_API_VERSION`.

Documentação: [Meta Ad Library](https://www.facebook.com/ads/library/api).

## 2. Telegram

Variáveis:

```dotenv
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
```

1. Entre em [my.telegram.org](https://my.telegram.org).
2. Abra **API development tools**.
3. Crie um aplicativo com nome e short name alfanumérico.
4. Copie `api_id` e `api_hash` para o `.env`.
5. Em um Terminal interativo, execute:

```bash
uv run python -m mind_collect.run --telegram-login
```

O Telethon pedirá telefone, código e, se habilitada, senha de duas etapas. A
sessão fica em `.local-state/mind/telegram.session`, fora do corpus e do Git.
Defina `MIND_STATE_DIR` para usar outro diretório local. Depois disso os ciclos
seguintes não pedem interação.

Os valores usados inicialmente foram colados em uma conversa. O Telegram não
oferece um fluxo garantido para rotacionar o `api_hash` de um aplicativo já
criado. Portanto, não descreva esse valor como revogado: revise as sessões
ativas da conta no aplicativo do Telegram, encerre qualquer sessão desconhecida,
apague arquivos `.session` antigos e faça um login novo. Se o portal permitir
criar outro aplicativo, prefira as novas credenciais. O arquivo de sessão é a
credencial que efetivamente autoriza acesso à conta e nunca pode ser
compartilhado. Não copie `api_id`, `api_hash` ou sessão para issue, relatório ou
commit.

## 3. YouTube Data API

Variável:

```dotenv
YOUTUBE_API_KEY=
```

O `yt-dlp` já descobre vídeos, Shorts, lives, descrição e metadados sem essa
chave. A API oficial é usada para comentários e respostas.

1. Crie um projeto no [Google Cloud Console](https://console.cloud.google.com/).
2. Ative **YouTube Data API v3**.
3. Crie uma chave e restrinja-a à API.
4. Teste:

```bash
uv run python -m mind_collect.run --youtube-comments --limite 5 --paginas-comentarios 2
```

`commentThreads.list` custa uma unidade por chamada e retorna até 100 threads
por página. Como o recurso não inclui necessariamente todas as respostas, o
adaptador chama também `comments.list` e pagina todas as respostas restantes.

Documentação: [commentThreads.list](https://developers.google.com/youtube/v3/docs/commentThreads/list).

## 4. Descoberta social sem API paga

A Brave Search API não é usada. O plano publicado cobra por requisição, exige
ativação e pede dados de pagamento mesmo quando oferece créditos promocionais.
`BRAVE_SEARCH_API_KEY` foi removida do exemplo, do diagnóstico e do ciclo.

A descoberta gratuita combina:

1. busca temática pública do YouTube;
2. Bing News RSS e GDELT;
3. URLs em notícias, checagens, Reddit e Telegram;
4. autores e marcações em publicações já coletadas;
5. busca pública do Bluesky;
6. contas e sites declarados ao TSE.

```bash
uv run python -m mind_collect.run --descoberta-social --limite 20
```

Não cadastrar cartão, não ativar plano e não colocar uma chave Brave antiga no
`.env`: o código não a consulta mais.

## 5. Perfis públicos do Instagram

Variáveis alternativas:

```dotenv
INSTAGRAM_COOKIES_FILE=/caminho/cookies.txt
# ou
INSTAGRAM_COOKIES_FROM_BROWSER=chrome
```

Posts já conhecidos continuam sendo lidos pelo embed público, sem login. Para
enumerar as publicações recentes de qualquer perfil descoberto, `gallery-dl`
precisa de cookies de uma sessão própria. A enumeração também captura os campos
de perfil disponíveis, como bio, nome, seguidores e verificação. Prefira um
arquivo Netscape exportado: a leitura direta do navegador pode pedir acesso às
Chaves do macOS e não é ideal para execução agendada. Cookies ficam fora do
corpus e do Git.

## 6. TikTok Research API

Variáveis:

```dotenv
TIKTOK_RESEARCH_CLIENT_KEY=
TIKTOK_RESEARCH_CLIENT_SECRET=
```

O adaptador está implementado: renova o token de duas horas, consulta vídeos
brasileiros por tema e janela de até 30 dias, ingere `voice_to_text`, métricas,
comentários e respostas. O acesso não tem tarifa publicada, mas a elegibilidade
brasileira atual exige pesquisa sobre segurança online de jovens. Como esse não
é o objeto do MIND, a decisão atual é **não solicitar nem usar**. O código fica
inativo enquanto as variáveis estiverem vazias e só poderá ser habilitado se a
regra oficial mudar ou o projeto atender formalmente aos critérios.

Documentação: [TikTok Research Tools](https://developers.tiktok.com/products/research-api/)
e [FAQ oficial](https://developers.tiktok.com/docs/en/research-api-faq).

## 7. Media Cloud

Variável:

```dotenv
MEDIACLOUD_API_KEY=
```

Crie conta em [Media Cloud](https://www.mediacloud.org/), solicite acesso à API
para pesquisa e coloque a chave no `.env`.

```bash
uv run python -m mind_collect.run --mediacloud --de 2026-01-01
```

Media Cloud é complementar ao Common Crawl: melhora descoberta e metadados, mas
nem todo resultado contém o corpo integral. URLs sem corpo entram na hidratação.

## 8. INLABS / Diário Oficial da União

Variáveis:

```dotenv
INLABS_EMAIL=
INLABS_PASSWORD=
```

Crie um login no [INLABS](https://inlabs.in.gov.br/) e configure e-mail e senha
juntos. O ciclo baixa XMLs oficiais das edições disponíveis e mantém apenas atos
que passam pelo filtro eleitoral.

```bash
uv run python -m mind_collect.run --dou
```

Sem login, o espelho CC0 continua funcionando por
`--dou-espelho`. O INLABS é necessário para atualização diária oficial, não
para reconstruir a amostra já coletada.

Cliente de referência: [repositório INLABS da Imprensa Nacional](https://github.com/Imprensa-Nacional/inlabs).

## 9. Reddit para pesquisa

O código não pede mais `REDDIT_CLIENT_ID` ou `REDDIT_CLIENT_SECRET`, porque a
rota oficial atual para pesquisa é o programa Reddit for Researchers, com
aprovação, parecer ético e acesso pelo BigQuery Analytics Hub. Arctic Shift
continua separado como arquivo de referência; não deve ser apresentado como
API oficial do Reddit. O arquivo não concede licença para treinar modelos,
redistribuir textos ou manter conteúdo além da finalidade aprovada. O material
fica com `licenca_uso=referencia`, restrito à análise interna, sujeito a
minimização e retirada. Para ampliar ou publicar qualquer uso, revise os
[Data API Terms](https://redditinc.com/policies/data-api-terms) e os
[Developer Terms](https://redditinc.com/policies/developer-terms) vigentes e
prefira o programa oficial de pesquisa.

## 10. Espelho dos dados abertos do TSE

Variável opcional:

```dotenv
MIND_TSE_MIRROR_BASE=
```

O CDN oficial é tentado primeiro. O registro de candidaturas e redes já tem um
espelho configurado no código e funciona. Os outros 72 recursos catalogados
continuam recebendo 403 nesta rede. Para ingeri-los, publique os arquivos
oficiais sem alteração em um diretório HTTP e aponte a variável para sua base.

```bash
uv run python -m mind_collect.run --tse-abertos --limite 500
```

Não colocar credencial de nuvem na URL do mirror. A procedência de cada download
é gravada em `data/eleicoes2026/_tse_abertos/_origem.json`.

## 11. Sal de anonimização

Variável:

```dotenv
MIND_SALT=
```

Gere uma vez, com o mesmo comando em Windows, macOS e Linux:

```bash
uv run python -c "import secrets; print(secrets.token_hex(32))"
```

O sal entra no hash de identificadores de autores. Opinião política é dado
pessoal sensível; o corpus não deve expor handles de pessoas comuns. Trocar o
sal depois rompe a ligação entre mensagens do mesmo autor.

## 12. Acessos institucionais, não tokens

### Meta Content Library e API

É a rota oficial de maior cobertura para posts, comentários e métricas públicas
de Facebook e Instagram; a interface também inclui Threads. Pesquisadores de
instituições acadêmicas ou organizações qualificadas solicitam acesso no portal
da Meta e trabalham em ambiente controlado.

Página oficial: [Meta Content Library](https://www.icpsr.umich.edu/sites/somar/meta-content-library).

A API pode ser oferecida no Meta Secure Research Environment ou no SOMAR VDE.
O SOMAR VDE custa US$ 1.000 de instalação e US$ 371 por mês e, portanto, está
descartado. A solicitação deve selecionar o ambiente da Meta e só prosseguir se
a aprovação confirmar custo zero. A interface web também só será usada sob a
mesma condição.

Prepare antes de solicitar:

- resumo e pergunta científica;
- instituição e orientador responsável;
- lista de pesquisadores;
- justificativa de proporcionalidade dos campos;
- plano de proteção de dados e retenção;
- aprovação ou parecer ético, quando exigido;
- lista de produtores baseada nas contas declaradas ao TSE.

Esse acesso é distinto do `META_ADS_TOKEN`: Ad Library cobre anúncios; Content
Library cobre conteúdo orgânico público.

Como descrito na seção 6, o projeto não solicita a TikTok Research API enquanto
não atender formalmente aos critérios. A Commercial Content API também não
resolve anúncios brasileiros: a
[lista oficial de países](https://developers.tiktok.com/docs/en/commercial-content-api-supported-countries)
é europeia.

## 13. Verificação final

Depois de editar `.env`:

```bash
uv run python -m mind_collect.run --credenciais
uv run python -m mind_collect.run --bluesky --limite 1
uv run python -m mind_collect.run --list
```

Um status `ok` confirma presença e, no Telegram, sessão válida. Para os demais,
a confirmação definitiva é uma consulta pequena bem-sucedida. Não há agentes
`launchd` instalados no estado revisado; configure Task Scheduler, `launchd` ou
systemd somente depois de o ciclo manual funcionar na máquina autoritativa.
