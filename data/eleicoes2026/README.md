# Corpus eleitoral do MIND

Este diretório é a área de trabalho da coleta das eleições brasileiras. Os
dados reais ficam ignorados pelo Git; este guia e a especificação são os únicos
arquivos daqui que devem ser enviados ao repositório de código.

O corpus é interno. Em 15 de setembro de 2026, somente 40 dos 160.918
documentos estavam marcados como `livre`; os outros 160.878 estavam marcados
como `referencia`. Conteúdo público não é automaticamente conteúdo com licença
para redistribuição. Não publique o corpus em uma Release deste repositório,
que é público.

## Estado verificado

Na última auditoria local:

- 160.918 documentos;
- 31.503 registros de mídia;
- 2.626 transcrições;
- 1.910 snapshots de perfis públicos;
- cerca de 73,8 mil arquivos e 8,7 GiB;
- `PRAGMA quick_check` do SQLite: `ok`;
- última coleta registrada: 4 de setembro de 2026;
- três execuções antigas ainda estavam sem horário de término.

Esses números envelhecem. O estado atual deve ser consultado com:

```bash
uv run mind-data status
uv run mind-data status --json
```

## O que existe aqui

| Caminho | Conteúdo | Entra no snapshot `team`? |
|---|---|:---:|
| `mind.db` | índice, filas, cursores, transcrições, OCR, rótulos e histórico operacional | sim, por backup consistente |
| `<fonte>/*.jsonl.gz` | documentos canônicos por fonte e dia | sim |
| `perfis_sociais.jsonl` | visão legível dos perfis públicos | sim, regenerada do SQLite |
| `_midia/thumbs/` | miniaturas para revisão humana | sim |
| `_midia/frames/` | keyframes de vídeo | não |
| `_midia/*.{m4a,mp3,mp4,json}` | mídia e caches de processamento | não |
| `_tse/` e `_datasets/` | downloads e proveniência intermediária | não |
| `_quarentena/` | material ainda não aceito no corpus | nunca |
| `_telegram.session` | sessão antiga; novas sessões ficam fora desta árvore | nunca |
| `_logs/`, `*.part`, `*.lock`, WAL/SHM | estado temporário | nunca |

O perfil `full-private` inclui mídia, frames, caches de transcrição e
proveniência do TSE somente em formatos e caminhos permitidos. Datasets externos
reconstruíveis continuam fora. O perfil também exclui sessões, credenciais,
cookies, chaves privadas, formatos desconhecidos, quarentena, logs, locks,
downloads parciais e arquivos `unknown_video`.

## Instalação em qualquer sistema

Pré-requisitos:

1. Git;
2. [uv](https://docs.astral.sh/uv/getting-started/installation/);
3. [GitHub CLI](https://cli.github.com/) para baixar ou publicar snapshots;
4. acesso de leitura ao repositório privado dos dados.

Os comandos abaixo foram desenhados para Windows, macOS e Linux:

```bash
git clone https://github.com/BeeyWasser/MIND.git
cd MIND
uv sync --locked --extra collect
gh auth login
uv run mind-data status
```

O extra `collect` instala aquisição de mídia e processamento de imagens
portáveis. Transcrição com MLX e OCR com Vision são acelerações exclusivas do
macOS 14 ou mais novo com Apple Silicon; nesse computador use
`uv sync --locked --extra media`.
Baixar, verificar, restaurar e executar a coleta de rede não depende delas.
O workflow `.github/workflows/data-portability.yml` executa instalação, CLIs,
lint e testes nos três sistemas quando estas mudanças forem enviadas ao GitHub.
Até essa execução remota ocorrer, a validação completa feita nesta entrega é do
macOS; Windows e Linux tiveram resolução de dependências e contratos testados,
mas ainda precisam da primeira execução real da matriz.

FFmpeg é necessário para áudio, vídeo e keyframes; `pdftotext`, fornecido pelo
Poppler, é necessário para propostas de governo em PDF. No Ubuntu/Debian use
`sudo apt install ffmpeg poppler-utils`; no macOS use
`brew install ffmpeg poppler`. No Windows, instale os pacotes indicados nas
páginas de download do [FFmpeg](https://ffmpeg.org/download.html) e do
[Poppler](https://poppler.freedesktop.org/), adicione os executáveis ao `PATH` e
abra um novo PowerShell. `uv run python -m mind_collect.run --credenciais`
mostra se ambos estão disponíveis.

Por padrão os dados ficam no checkout, em `data/eleicoes2026`. Para guardar o
corpus em outro disco, defina `MIND_DATA_DIR` antes de iniciar o programa.

macOS e Linux:

```bash
export MIND_DATA_DIR="$HOME/mind-data/eleicoes2026"
```

PowerShell:

```powershell
$env:MIND_DATA_DIR = "$HOME\mind-data\eleicoes2026"
```

Não coloque o banco ativo em pasta sincronizada por Drive, Dropbox ou OneDrive.
O SQLite deve ter um único computador escritor. Compartilhe snapshots fechados.
Sessões autenticadas ficam em `.local-state/mind/` ou no diretório definido por
`MIND_STATE_DIR`, sempre fora do corpus e do Git.

## Baixar o mesmo corpus da equipe

O armazenamento recomendado para a equipe é um repositório GitHub **privado e
separado**, [`daviiabreu/MIND-data`](https://github.com/daviiabreu/MIND-data).
Ele usa as mesmas permissões de repositório que os alunos já conhecem. Os dados
ficam em Releases, não em commits nem em Git LFS.

Depois que o aluno tiver acesso:

```bash
uv run mind-data fetch --repository daviiabreu/MIND-data
```

O comando baixa a Release mais recente, verifica SHA-256 das partes, abre o ZIP
sem aceitar caminhos inseguros, confere cada arquivo, executa `quick_check` no
SQLite e só então restaura o corpus. Para escolher uma versão:

```bash
uv run mind-data fetch \
  --repository daviiabreu/MIND-data \
  --release eleicoes2026-20260916T003307Z-team
```

No PowerShell, use o comando em uma linha ou troque `\` pelo acento grave de
continuação. O formato do snapshot é o mesmo em todos os sistemas.

Se já houver dados no destino, o comando para e não apaga nada. Para substituir
o corpus após uma nova Release:

```bash
uv run mind-data fetch --repository daviiabreu/MIND-data --replace
```

A versão anterior é movida para uma pasta `eleicoes2026.backup-<data>`. Apague
esse backup somente depois de validar o novo corpus.

## Criar e enviar um snapshot

Antes de compartilhar, prefira interromper novas coletas para evitar trabalho
desnecessário. O empacotador usa a API de backup do SQLite, compara os JSONL
antes da cópia e repete a reconciliação sobre os bytes já gravados no ZIP. Se
um processo de coleta alterar o corpus no intervalo, a criação aborta em vez de
publicar um estado misto.

Snapshot padrão da equipe:

```bash
uv run mind-data pack --profile team
uv run mind-data verify dist/data/ARQUIVO.bundle.json
uv run mind-data publish \
  dist/data/ARQUIVO.bundle.json \
  --repository daviiabreu/MIND-data
```

Snapshot completo, somente quando houver necessidade e autorização para a
mídia:

```bash
uv run mind-data pack --profile full-private
```

O comando de publicação recusa esse perfil por padrão. Depois de uma revisão
documentada de licença e necessidade, o responsável precisa acrescentar
`--allow-full-private`; o perfil `team` não exige esse override.

Arquivos maiores que 1.900 MiB são divididos automaticamente. O índice
`*.bundle.json` registra tamanho e SHA-256 do ZIP, das partes, do manifesto e
de cada arquivo interno. A publicação é recusada se o repositório de destino
não for privado.

## Acesso ao armazenamento

O repositório foi criado como `PRIVATE` e a Release
`eleicoes2026-20260916T003307Z-team` foi publicada e testada de ponta a ponta.
Ela contém um índice de 636 bytes e um ZIP de 429 MiB. O download remoto,
verificação e restauração devolveram 32.190 arquivos e 160.918 documentos.
Reserve pelo menos 2 GiB livres para uma primeira restauração do perfil `team`,
porque download, ZIP verificado e arquivos extraídos coexistem temporariamente.
Com `--replace`, reserve também espaço para manter a cópia anterior; consulte o
tamanho dela com `uv run mind-data status` antes de começar.

O responsável deve adicionar cada orientado como colaborador com acesso de
leitura. Pela interface, use **Settings > Collaborators**. Pela CLI:

```bash
gh api --method PUT \
  repos/daviiabreu/MIND-data/collaborators/USUARIO_GITHUB \
  -f permission=pull
gh repo view daviiabreu/MIND-data --json visibility
```

O último comando precisa responder `PRIVATE`. Dê escrita apenas a quem for
produzir snapshots oficiais. Adicione também um segundo responsável
administrativo para o projeto não depender de uma única conta pessoal. A única
pendência para liberar o download é receber os nomes de usuário dos orientados
e aceitar os convites.

## Uso interno e retirada

O repositório privado é um controle de acesso, não uma licença. O snapshot é
compartilhado somente com a equipe de pesquisa para análise interna, sem
republicação, espelhamento ou redistribuição dos textos e miniaturas. Cada
orientado deve manter o repositório privado e apagar a cópia ao deixar o grupo.

Se uma fonte, autor ou titular solicitar retirada, o responsável registra a
URL e a fonte, remove o documento e seus derivados do corpus autoritativo,
publica um novo snapshot e avisa a equipe para apagar o anterior. Antes de
qualquer dataset aberto, a equipe precisa revisar licença por fonte e publicar
apenas conteúdo `livre` ou IDs, URLs, hashes e scripts permitidos.

## Continuar a coleta

A coleta de rede foi projetada para Windows, macOS e Linux:

```bash
uv run python -m mind_collect.run --credenciais
uv run python -m mind_collect.run --ciclo --sem-transcricao
uv run python -m mind_collect.run --exportar-perfis
uv run mind-data status
```

As fontes sem custo e as credenciais opcionais estão em
[`CREDENCIAIS.md`](../../CREDENCIAIS.md). O pipeline não usa Brave Search nem
outra API paga. Sem credenciais, RSS, Bing News, GDELT, Common Crawl, Wayback,
TSE, Câmara, Senado, Reddit via Arctic Shift, Bluesky e YouTube público ainda
podem rodar. O conteúdo do Reddit fica somente como referência interna, sem uso
para treino ou redistribuição; veja as restrições em `CREDENCIAIS.md`.

Para mídia no macOS 14 ou mais novo com Apple Silicon:

```bash
uv run python -m mind_collect.run --worker-midia --limite 3 --espera 60
```

Em Windows e Linux a coleta de URLs, textos e metadados foi projetada para
funcionar, mas ainda depende da primeira execução da matriz remota. O backend
atual de transcrição/OCR não é portátil. Não anuncie enriquecimento multimodal
nesses sistemas até existir e passar em testes um backend alternativo. Cada
máquina também precisa configurar seu próprio `.env` e autenticar uma sessão
própria do Telegram.

## Uma máquina escritora

Ainda não existe merge de dois bancos e duas filas de coleta. Portanto:

- uma máquina é o coletor autoritativo;
- os alunos baixam snapshots para análise;
- somente o responsável publica uma nova versão oficial;
- quem precisar coletar em outra máquina usa outro diretório e não mistura o
  resultado manualmente no banco oficial;
- uma coleta distribuída futura deve trocar pacotes delta por `doc_id`, com
  merge testado e auditável.

Agendadores de cada sistema podem chamar o mesmo comando de ciclo. O agendamento
não é parte do snapshot: `launchd`, systemd e Task Scheduler ficam na máquina
autoritativa e nunca guardam credenciais no repositório.

## O que não foi feito

- o corpus não foi publicado no GitHub público;
- fontes pagas continuam fora do projeto;
- não há backend portátil de Whisper/OCR em Windows e Linux;
- não há merge de coletores concorrentes;
- não há publicação aberta da mídia ou dos textos de terceiros;
- as três execuções antigas sem término continuam registradas para auditoria;
- o snapshot `full-private` não deve ser enviado antes de revisão de licença e
  necessidade.

Detalhes de formato, segurança, versionamento e critérios de aceite estão em
[`SPEC.md`](SPEC.md).
