# Corpus eleitoral do MIND

Esta pasta é a área local da coleta das eleições brasileiras. O repositório
público contém este guia, a especificação e o código necessário para obter os
dados. O que for baixado ou produzido aqui fica fora do Git.

Em um clone novo, portanto, esta pasta começa apenas com `README.md` e
`SPEC.md`. Cada máquina baixa fontes públicas e constrói seu próprio corpus.

## Regra do repositório

O `.gitignore` mantém fora do histórico:

- `mind.db` e seus arquivos WAL/SHM;
- documentos `*.jsonl.gz`;
- vídeos, áudios, imagens, frames, OCR e transcrições;
- downloads do TSE e datasets intermediários;
- sessões, cookies, credenciais, logs, locks e arquivos parciais;
- snapshots locais criados em `dist/`.

Não use `git add -f` nesses arquivos. O repositório deve continuar leve e
público; ele ensina como obter os dados, mas não redistribui o corpus coletado.

## Estado da máquina original

Na auditoria de 16 de setembro de 2026, a máquina coletora tinha:

- 160.918 documentos;
- 31.503 registros de mídia;
- 2.626 transcrições;
- 1.910 snapshots de perfis públicos;
- 73.797 arquivos e aproximadamente 8,7 GiB;
- `PRAGMA quick_check` do SQLite: `ok`;
- última coleta registrada: 4 de setembro de 2026;
- três execuções antigas sem horário de término.

Esses números descrevem aquela máquina, não o conteúdo do Git. Consulte o seu
estado local com:

```bash
uv run mind-data status
uv run mind-data status --json
```

## O que é criado aqui

| Caminho | Conteúdo |
|---|---|
| `mind.db` | índice, filas, cursores, transcrições, OCR, rótulos e histórico operacional |
| `<fonte>/*.jsonl.gz` | documentos canônicos separados por fonte e dia |
| `perfis_sociais.jsonl` | exportação legível dos perfis públicos descobertos |
| `_midia/` | áudio, vídeo, imagens, frames, miniaturas e caches de processamento |
| `_tse/` e `_tse_abertos/` | downloads e proveniência dos dados oficiais |
| `_datasets/` | bases externas e material intermediário reconstruível |
| `_quarentena/` | itens que ainda não foram aceitos no corpus |
| `_logs/` | registros locais de execução |

Sessões autenticadas ficam em `.local-state/mind/`, fora desta pasta e do Git.

## Instalação

Pré-requisitos:

1. Git;
2. [uv](https://docs.astral.sh/uv/getting-started/installation/);
3. FFmpeg para áudio, vídeo e keyframes;
4. Poppler (`pdftotext`) para propostas de governo em PDF.

Clone e instale a coleta portátil:

```bash
git clone https://github.com/BeeyWasser/MIND.git
cd MIND
uv sync --locked --extra collect
uv run python -m mind_collect.run --credenciais
```

No Ubuntu/Debian:

```bash
sudo apt install ffmpeg poppler-utils
```

No macOS:

```bash
brew install ffmpeg poppler
```

No Windows, instale os pacotes indicados nas páginas do
[FFmpeg](https://ffmpeg.org/download.html) e do
[Poppler](https://poppler.freedesktop.org/), adicione os executáveis ao `PATH`
e abra um novo PowerShell.

Transcrição com MLX e OCR com Vision exigem macOS 14 ou mais novo com Apple
Silicon. Nessa máquina, instale:

```bash
uv sync --locked --extra media
```

Windows e Linux podem coletar URLs, textos e metadados. O backend multimodal
atual não é portátil para esses sistemas.

## Escolher outro disco

Por padrão, o corpus fica em `data/eleicoes2026/`. Para usar outro disco,
defina `MIND_DATA_DIR` antes de iniciar o programa.

macOS e Linux:

```bash
export MIND_DATA_DIR="$HOME/mind-data/eleicoes2026"
```

PowerShell:

```powershell
$env:MIND_DATA_DIR = "$HOME\mind-data\eleicoes2026"
```

Não mantenha o SQLite ativo em Drive, Dropbox ou OneDrive. Use uma pasta local
com um único processo escritor.

## Baixar e coletar os dados

Copie o exemplo de configuração e preencha somente os acessos gratuitos que
tiver:

```bash
cp .env.exemplo .env
uv run python -m mind_collect.run --credenciais
```

No PowerShell, o primeiro comando equivalente é:

```powershell
Copy-Item .env.exemplo .env
```

O ciclo sem transcrição funciona mesmo sem tokens e usa RSS, Bing News, GDELT,
Common Crawl, Wayback, TSE, Câmara, Senado, Reddit via Arctic Shift, Bluesky e
YouTube público:

```bash
uv run python -m mind_collect.run --ciclo --sem-transcricao
uv run python -m mind_collect.run --exportar-perfis
uv run mind-data status
```

As fontes, seus custos e o passo a passo de cada credencial estão em
[`CREDENCIAIS.md`](../../CREDENCIAIS.md). A política atual não usa Brave Search
nem outro serviço pago.

Para executar fontes isoladas:

```bash
uv run python -m mind_collect.run --feeds
uv run python -m mind_collect.run --bluesky --limite 100
uv run python -m mind_collect.run --telegram --limite 300
uv run python -m mind_collect.run --youtube-comments --limite 5 --paginas-comentarios 5
uv run python -m mind_collect.run --commoncrawl --de 201801 --limite 200
uv run python -m mind_collect.run --wayback --de 201801 --limite 200
uv run python -m mind_collect.run --tse
uv run python -m mind_collect.run --tse-abertos --limite 500
uv run python -m mind_collect.run --dou-espelho --limite 500
```

No macOS compatível, processe mídia em lotes pequenos:

```bash
uv run python -m mind_collect.run --worker-midia --limite 3 --espera 60
```

Cada computador configura seu próprio `.env`, seu próprio `MIND_SALT` e sua
própria sessão do Telegram. Nunca compartilhe arquivos `.session` ou cookies.

## Coleta contínua

Não há serviço em segundo plano instalado pelo repositório. Primeiro valide um
ciclo manual. Depois, a máquina coletora pode agendar o mesmo comando com Task
Scheduler, `launchd` ou systemd:

```bash
uv run python -m mind_collect.run --ciclo --sem-transcricao
```

Use somente uma máquina como escritora do corpus autoritativo. Ainda não existe
merge seguro de dois bancos ou duas filas de coleta.

## Backup local opcional

`mind-data` também cria um snapshot verificável para backup local ou
transferência manual autorizada. O resultado fica em `dist/`, que também está
ignorado pelo Git.

```bash
uv run mind-data pack --profile team
uv run mind-data verify dist/data/ARQUIVO.bundle.json
```

O perfil `team` inclui o backup consistente do SQLite, os JSONL canônicos, a
exportação de perfis e miniaturas. Ele exclui mídia original, sessões,
credenciais, cookies, logs, quarentena e arquivos parciais.

Para restaurar um snapshot recebido por disco externo ou outro canal aprovado:

```bash
uv run mind-data restore CAMINHO/ARQUIVO.bundle.json
```

Se já houver dados, o comando interrompe sem apagar nada. Use `--replace`
somente depois de conferir o backup que será preservado.

## Licença e uso

Conteúdo público não é automaticamente conteúdo livre para redistribuição. Na
auditoria original, 160.878 documentos estavam marcados como `referencia` e
apenas 40 como `livre`. O material de referência serve à análise interna e não
entra em treino ou publicação aberta.

O conteúdo do Reddit exige retenção mínima e retirada quando solicitada. Antes
de publicar qualquer dataset, revise a licença de cada fonte e prefira IDs,
URLs, hashes e scripts de reconstrução.

## O que não está no Git

- o corpus de 8,7 GiB da máquina original;
- snapshots ou Releases com os dados coletados;
- sessões, cookies ou credenciais;
- mídia e textos de terceiros;
- agendadores específicos de uma máquina;
- merge de coletores concorrentes.

Os contratos de formato, segurança e restauração local estão em
[`SPEC.md`](SPEC.md).
