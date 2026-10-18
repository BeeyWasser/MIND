# Metodologia de coleta do corpus eleitoral

Este documento descreve como o MIND constrói um corpus multimodal para estudar
técnicas de manipulação em comunicação política brasileira, com foco nas
eleições de 2026. Números operacionais e comandos ficam em `HANDOFF.md`.

## 1. Objeto e princípio

O objeto não é apenas “opinião política” nem apenas “fake news”. A coleta busca
peças produzidas por campanhas e partidos, anúncios pagos, propaganda eleitoral,
publicações orgânicas de candidatos, material jornalístico que repercute essas
peças, checagens, decisões e denúncias eleitorais, além de comentários e
reencaminhamentos que mostram circulação.

O princípio é **coletar largo e anotar estreito**. A máquina pode preservar um
universo amplo e rastreável; a validade científica depende de um subconjunto
amostrado, anotado por pessoas e separado por tempo, fonte e ator para evitar
vazamento entre treino e teste.

Volume bruto não é critério de qualidade. A cobertura deve ser medida por:

- candidato, partido, cargo e estado;
- plataforma e tipo de mídia;
- origem paga, orgânica, jornalística ou institucional;
- período da campanha;
- alcance e gasto, quando disponíveis;
- peça única, não número de republicações.

## 2. Camadas de evidência

As fontes são organizadas por função metodológica.

### Peça política primária

- Meta Ad Library;
- HGPE, inserções, spots de rádio e vídeos de campanha;
- contas e sites declarados ao TSE;
- posts públicos de candidatos e partidos;
- comunicação oficial de partidos;
- propostas de governo.

Esses itens são o material em que as técnicas serão identificadas.

### Circulação e contexto

- notícias nacionais, regionais, populares e partidárias;
- Reddit, Telegram, Bluesky e comentários;
- links sociais citados em outras fontes;
- GDELT, Bing News, Common Crawl e Wayback.

Essa camada ajuda a descobrir URLs, medir repercussão e recuperar peças apagadas.
Ela não deve ser confundida com amostra representativa da população.

### Rótulo e desfecho

- agências de checagem;
- decisões e dados processuais eleitorais;
- Pardal;
- DOU;
- resultados e prestações de contas quando publicados.

Checagem ou denúncia não é automaticamente verdade de referência. O schema
guarda a procedência do rótulo, e denúncia permanece distinta de decisão.

### Vocabulário de entidades

- candidatura, cargo, partido, estado e situação;
- URLs de redes declaradas;
- identificadores do TSE.

`tse_registro` serve para enumeração e ligação de entidades. Não é texto de
treino.

## 3. Estratégia por plataforma

### Notícias

Há 78 feeds ativos, com veículos nacionais, regionais, populares, partidários e
especializados. Feeds gerais passam por um filtro eleitoral no título e resumo
antes que o artigo seja baixado. Isso reduz tráfego e impede que volume regional
vire esporte e entretenimento.

O histórico vem do Common Crawl desde 2018. Alvos de domínio amplo repetem o
filtro no texto extraído. O índice histórico também cobre notícias do TSE e dos
27 TRES. Wayback é reservado para páginas retiradas do ar.

Bing News roda consultas fixas e uma rotação dos nomes de candidatos
majoritários aptos. GDELT fornece descoberta adicional. Resultado sem corpo é
guardado e posteriormente hidratado sem alterar o `doc_id`.

### Meta: Facebook e Instagram

A Meta Ad Library é a fonte oficial para anúncios políticos e sociais. O
adaptador pagina `ads_archive`, preserva criativo, anunciante, datas, faixas de
gasto e alcance e segmentação publicada. A retenção oficial é de sete anos, logo
o histórico é perecível e deve ser capturado assim que o token existir.

Conteúdo orgânico público em escala deve vir da Meta Content Library/API. Ela
cobre páginas, posts, grupos e eventos do Facebook e contas de criador/empresa
do Instagram, além de comentários; a interface inclui Threads. O acesso exige
aprovação institucional.

URLs individuais citadas em notícias, checagens, Reddit, Telegram, YouTube e
outras peças entram numa fila persistente de publicações e perfis. Posts
conhecidos são lidos pelo embed público. A enumeração de perfil usa
opcionalmente cookies de uma sessão própria com `gallery-dl`; nenhum cookie
entra no corpus. Em escala, a rota preferencial continua sendo a Meta Content
Library, somente se houver acesso institucional sem cobrança.

### TikTok

O registro do TSE é uma semente, não a fronteira. O `yt-dlp` enumera publicações
públicas de qualquer perfil descoberto em notícia, checagem, Telegram, busca
web, descrição de vídeo ou outro post. A fila local registra origem, prioridade,
tentativas e última coleta para revisitar contas continuamente.

O adaptador da Research API também está implementado. Após aprovação, pesquisa
vídeos brasileiros por tema em janelas de 30 dias e ingere descrição,
`voice_to_text`, métricas, comentários e respostas. A elegibilidade brasileira
publicada limita o acesso a estudos de segurança de jovens; essa condição não
deve ser mascarada por scraping evasivo.

### YouTube e HGPE

O pipeline cobre:

- buscas de HGPE de 2018, 2022 e 2026;
- busca temática ampla, independente do TSE;
- vídeos, Shorts e streams de canais declarados ao TSE;
- metadados via `yt-dlp`;
- comentários e todas as respostas via YouTube Data API;
- áudio para transcrição;
- keyframes para OCR quando o vídeo completo é necessário.

Vídeo curto é classificado como inserção apenas nas sementes de HGPE. Conteúdo
de perfil de candidato permanece como `youtube`, com partido, cargo e
`candidato_id`.

### Telegram

A API oficial do Telegram permite histórico de canais públicos. A lista une
sementes editoriais, contas declaradas ao TSE, canais citados no corpus e busca
global rotativa por temas políticos. Mensagens sem texto ainda são preservadas
quando contêm imagem, áudio ou vídeo.

O ciclo guarda metadados primeiro. Um worker contínuo e exclusivo baixa uma
mídia por vez, executa Whisper, extrai keyframes por mudança de cena, faz OCR e
registra cada etapa no SQLite. Ele continua até zerar a fila e retoma após
reinício sem repetir vídeo que não tinha texto visual. Handles de usuários
comuns não entram em claro.

### Reddit e Bluesky

Reddit é coletado pelo Arctic Shift; o acesso oficial de pesquisa exige o
programa Reddit for Researchers. Bluesky usa a API pública oficial do AT
Protocol, por termos e por qualquer perfil descoberto.
Imagens do Bluesky geram OCR, hashes perceptuais e miniaturas.

### X, Kwai e Threads

X é limitado a posts com URL exata descoberta no corpus ou na busca web e mídia
aceita pelo `yt-dlp`. A API oficial em escala é paga.

A instalação atual não possui extrator de Kwai. As contas declaradas ao TSE são
mantidas no inventário até existir rota pública reproduzível.

Threads fica no inventário do TSE e na solicitação da Meta Content Library.

## 4. Fontes oficiais brasileiras

O pipeline integra:

- candidaturas e redes do TSE;
- catálogo de processos, Pardal, pesquisas, contas, propostas e fotos;
- spots oficiais de rádio;
- notícias do TSE e TRES;
- Câmara e Senado;
- Diário Oficial da União.

O CDN de dados abertos do TSE responde 403 nesta rede. Candidaturas usam um
espelho versionado dos CSVs oficiais, com procedência gravada. Os outros recursos
só são marcados como ingeridos depois de um download real.

O DOU tem duas rotas: INLABS oficial diário e snapshot CC0. O filtro exige
vocabulário eleitoral em título, órgão ou corpo; “publicado no DOU” por si só
não torna o texto pertinente.

## 5. Contrato do documento

Todo adaptador devolve `Documento` com:

- fonte, URL, título, texto e modalidade;
- data de coleta e, quando conhecida, de veiculação;
- ciclo eleitoral derivado da data;
- candidato, partido, cargo e patrocinador quando identificáveis;
- gasto, alcance e segmentação quando publicados;
- transcrição segmentada e duração para áudio/vídeo;
- rótulo externo e sua procedência;
- licença de uso e resultado de robots;
- autor pseudonimizado quando necessário;
- metadados específicos da origem.

O `doc_id` é calculado na primeira captura e persistido. Enriquecimentos não o
recalculam.

## 6. Armazenamento e retomada

O conteúdo é armazenado em `jsonl.gz`, particionado por fonte, dia e PID. O
SQLite mantém:

- índice de documentos e URLs;
- cursores por fonte e lista de falhas;
- execuções com início, fim e contagens;
- transcrições;
- textos hidratados;
- rótulos;
- mídias derivadas;
- fila persistente de perfis e publicações sociais descobertos;
- estado independente de transcrição, imagem e frames/OCR;
- snapshots versionados de bio, verificação e métricas públicas de contas.

O modo WAL e a trava do `Store` permitem tarefas de rede concorrentes. Arquivo
por PID impede dois processos de anexarem no mesmo gzip. Cada coletor consulta
URLs já existentes antes de baixar o corpo, reduzindo ciclos horários de horas
para trabalho apenas incremental.

Execuções interrompidas podem recomeçar: o documento gravado é pulado e o cursor
avança em lotes circulares para listas grandes de candidatos.

## 7. Mídia e extração

### Áudio

Descoberta não baixa áudio. A fila posterior usa `yt-dlp` para extrair a menor
faixa adequada e `mlx-whisper` no Metal. Segmentos guardam início, fim e
confiança. Repetição de janela, créditos de legenda e segmentos de baixa
confiança são filtrados conservadoramente.

O worker seleciona os IDs pendentes no SQLite e abre somente os arquivos gzip
que os contêm. Assim ele consegue drenar milhares de peças sem reler o corpus
inteiro a cada lote. Transcrições antigas embutidas no JSONL são migradas uma
vez para a tabela de sobreposição.

### Imagem

O original não é preservado por padrão. São guardados:

- URL de origem;
- pHash e dHash;
- OCR;
- miniatura de 256 px;
- timestamp, no caso de frame.

Isso permite deduplicação e revisão humana sem multiplicar o armazenamento.

### Vídeo

O vídeo completo só é baixado para OCR. Keyframes são selecionados por mudança
de cena. Texto de tela que apenas repete a fala é separado por sobreposição de
palavras; o restante é candidato a grafismo persuasivo.

Transcrição e frames são etapas independentes. Vídeo sem trilha, fala
ininteligível ou falha do Whisper ainda passa pelo OCR. Cada etapa tem até três
tentativas antes de uma quarentena temporária, e um vídeo sem texto visual pode
ser marcado como concluído sem gerar uma linha falsa de OCR.

## 8. Descoberta e snapshots de contas

As contas do TSE inicializam o grafo, mas não o limitam. Novos nós entram por
busca temática, URLs em notícias e checagens, autores de peças coletadas,
encaminhamentos e marcações `@perfil` em posts raiz. Marcações dentro de
comentários não expandem o grafo, para evitar transformar usuários comuns em
alvos de coleta.

`alvos_sociais` registra plataforma, URL, origem, relevância, tentativas e
última coleta. `snapshots_perfis_sociais` preserva somente versões distintas dos
campos públicos disponíveis, como bio, nome, seguidores e verificação. O
inventário mais recente é exportado para
`data/eleicoes2026/perfis_sociais.jsonl`; tudo permanece local e fora do Git.

## 9. Licença, privacidade e ética

`licenca_uso` aceita `livre`, `referencia` e `restrito`. O padrão é
`referencia`. Disponibilidade pública nunca implica autorização automática
para treinar modelo.

O corpus completo é local e ignorado pelo Git. Uma publicação deve conter apenas
o que a licença autorizar, ou IDs/URLs e scripts de reconstrução.

Opinião política é dado pessoal sensível. Identificadores de pessoas comuns são
hashes com `MIND_SALT`. O desenho não usa mensagens privadas, grupos fechados,
cookies de terceiros nem dados obtidos por login alheio.

As seguintes técnicas estão fora do método:

- proxy residencial rotativo;
- resolução de CAPTCHA;
- assinatura forjada de API privada;
- conta descartável;
- bypass de paywall;
- coleta de conteúdo privado;
- fingir um tema científico elegível para obter uma API.

## 10. Deduplicação e qualidade

Há quatro controles diferentes:

1. igualdade exata por `doc_id`;
2. prevenção por URL para não rebaixar páginas já conhecidas;
3. MinHash/LSH para medir quase duplicação textual;
4. pHash/dHash para imagens recodificadas.

MinHash e pHash ainda não bloqueiam a inserção. Antes de treinar, grupos de quase
duplicatas devem ser formados e mantidos inteiros em uma única partição. Caso
contrário, a mesma peça aparece em treino e teste e infla a métrica.

Qualidade é auditada por leitura estrita dos gzip, reconciliação com SQLite,
órfãos de overlays, execuções sem fim, distribuição de licença, cobertura
temporal e inspeção de amostras.

## 11. Amostragem para a pesquisa

O corpus bruto não deve ser entregue diretamente ao modelo. A amostra anotada
precisa:

- estratificar por plataforma, partido/candidato, cargo, estado, tempo e
  modalidade;
- limitar republicações e versões quase idênticas;
- incluir casos sem manipulação;
- separar conteúdo primário de notícia ou comentário sobre ele;
- registrar mais de um rótulo quando técnicas coexistirem;
- usar ao menos dois anotadores e adjudicação;
- medir concordância;
- reservar teste temporal posterior ao treino;
- reservar candidatos ou grupos de peças para avaliar generalização.

Rótulos automáticos de checagem são sementes de avaliação e nunca substituem
anotação da técnica de manipulação. “Falso” descreve veracidade; a taxonomia do
MIND descreve estratégia retórica ou visual.

## 12. Limitações que devem aparecer no relatório

- acesso desigual entre plataformas;
- viés de descoberta por menções;
- cobertura maior de candidatos com presença digital;
- atraso e remoção de conteúdo;
- OCR ruim em letra pequena e baixo contraste;
- transcrição mais fraca em música, jingle e sobreposição de vozes;
- faixas de gasto/alcance, não números exatos, em bibliotecas de anúncios;
- comentários desativados, removidos ou limitados por quota da API;
- conteúdo público preservado apenas como referência por licença;
- TSE aberto parcialmente dependente de mirror;
- mudança contínua de APIs e regras de acesso.

Essas limitações não impedem a pesquisa. Elas definem quais inferências podem ser
feitas e impedem que “muitos documentos” seja confundido com representação
completa do debate eleitoral.
