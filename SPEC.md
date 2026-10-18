# MIND — especificação do projeto FEBRACE 2027

Fechada em 24/08/2026. Decisões tomadas em entrevista com o orientador.
`COLETA.md` detalha a coleta; `DADOS.md` descreve os corpora preexistentes;
`febrace/` guarda o material oficial da feira.

## Decisões fechadas

| | |
|---|---|
| Feira | FEBRACE 2027, 25ª edição, alvo único |
| Prazo | 20/10/2026, 18h (Brasília) |
| Autores | 3 estudantes |
| Orientador | Davi Abreu da Silveira |
| Projeto | Novo — sem formulário 7 |
| Metodologia | Científica |
| Categoria | Ciências Exatas e da Terra, subárea Ciência da Computação |
| Entregável | Produto funcionando: site; extensão de navegador como extra |
| Publicação | Site vai ao ar (decisão do orientador) |
| Modelo | Multilíngue, rótulos em inglês aproveitados direto, sem tradução |
| Anotação PT | Só conjunto de teste, feita pelos estudantes autores |
| Estudo com pessoas | Percepção antes/depois, executado até 20/10 |
| Escopo de coleta | Cheio, sem cortes |

## A pergunta e as hipóteses

**Questão-problema.** Detectores de desinformação operam sobre veracidade. Isso
deixa passar conteúdo verdadeiro e manipulativo — "só hoje: os médicos não querem
que você saiba disto" pode ser verdade e ainda assim ser manipulação pura. Não
existe ferramenta em português que aponte a *técnica* de persuasão empregada em
um texto político, independentemente de o conteúdo ser verdadeiro ou falso.

**H1 — detecção.** Um classificador treinado em técnicas de manipulação
identifica conteúdo manipulativo verdadeiro que um classificador de veracidade
não identifica.

Variável independente: o tipo de rótulo usado no treino, técnica de manipulação
contra veracidade. Dependente: desempenho na detecção sobre conteúdo manipulativo
verdadeiro. Controle: o mesmo conjunto de teste para os dois classificadores.
A célula que decide é conteúdo verdadeiro **e** manipulativo. Se o baseline de
veracidade acertar tanto quanto o MIND ali, H1 cai.

**H2 — efeito sobre o leitor.** Expor a técnica detectada altera o julgamento de
quem lê o texto.

Variável independente: exposição à saída da ferramenta. Dependente: a percepção
de manipulação registrada em escala. Controle: peças que a ferramenta não
sinaliza, para separar efeito real de conformidade automática com a máquina.
É o que o estudo com pessoas mede.

**O que a metodologia científica cobra**, e o relatório precisa entregar:
questão e hipótese claras e bem definidas, objetivos relacionados a pesquisas
similares, justificativa embasada em dados científicos e pesquisa bibliográfica,
métodos de coleta, registro e análise planejados, variáveis definidas e
cronograma estabelecido. Na execução: coleta e registro com análise matemática e
estatística, dados suficientes e consistentes para sustentar as interpretações e
a reprodutibilidade, e conclusão relacionada à pergunta do início.

A revisão bibliográfica precisa confrontar o que já existe, porque o critério 7
exige que os materiais contenham outras soluções ou teorias: detectores de fake
news em português (Fake.br, FakeRecogna), a checagem humana das agências, e
classificadores de discurso de ódio. Nenhum resolve o problema, e o relatório
precisa dizer por quê, com evidência e não com afirmação.

## O modelo

Transferência multilíngue direta. Fine-tuning de um encoder multilíngue —
XLM-RoBERTa ou mDeBERTa-v3-base — sobre os rótulos em inglês que já estão em
`data/`, sem traduzir, avaliado em português.

Treino: SemEval-2021 Task 6 (688 memes, 20 técnicas) como base principal, com
MentalManip como reforço. Começar pelas 6 a 8 técnicas mais frequentes, como o
`DADOS.md` já concluiu — treinar nas 20 com Loaded Language em 358 exemplos e
dezessete classes abaixo de 55 não vai convergir.

Avaliação: conjunto anotado em português pelos estudantes, sobre propaganda
brasileira real. Sem esse conjunto não há métrica sobre o objeto do projeto, e o
critério de execução cobra dado suficiente para sustentar a conclusão.

Baselines para comparação, porque o critério 7 exige confronto com outras
soluções: um classificador de veracidade treinado em Fake.br, e um baseline
trivial de palavra-chave. A célula que interessa é conteúdo **verdadeiro e
manipulativo** — onde o detector de fake news deve falhar e o MIND não.

mDeBERTa-v3-base tem 278M de parâmetros e faz fine-tuning em horas num M5 de
16 GB. Não há necessidade de GPU alugada — o projeto roda inteiro em hardware
já disponível.

## O produto

O site é o artefato aplicado que demonstra o achado, não o objeto da avaliação —
com metodologia científica, quem carrega os critérios 1a e 2a são as hipóteses e
os dados. Ainda assim ele é entregável e é o que o avaliador vai usar no estande.

Site com o modelo servindo inferência. A pessoa cola um texto e recebe as
técnicas apontadas, com o trecho que disparou cada uma.

Três requisitos que decorrem da palavra "confiar" e viram critério de aceitação:

O sistema mostra confiança e se cala quando não sabe. Apontar manipulação em
fala política legítima tem custo real, então abaixo de um limiar calibrado a
resposta é "não identifiquei técnicas", não um palpite.

O sistema explica. Apontar a técnica sem mostrar o trecho que a evidencia é
inútil para quem quer decidir se concorda.

O sistema funciona sem rede externa na demonstração. No estande da USP o
avaliador vai colar o texto que ele escolher; produto que depende de serviço de
terceiro falha na hora errada.

A extensão de navegador entra depois do site, se sobrar tempo. É a mesma lógica
com uma casca a mais — construir o site não desperdiça nada da extensão.

## O estudo com pessoas

Este é o experimento que testa H2, não um teste de usabilidade.

Desenho de percepção antes e depois. Cada participante lê um conjunto de textos
políticos, registra em escala o quanto percebeu de manipulação, vê a saída da
ferramenta, e registra de novo. Mede-se o deslocamento do julgamento.

É o único desenho que sustenta a palavra "confiar": mostra que a ferramenta
melhora o julgamento de quem a usa, não apenas que acerta um rótulo. Casa com a
base `anthropic-persuasion`, que já está em `data/` e usa exatamente essa
estrutura de opinião medida antes e depois.

Inclui textos de controle — peças que a ferramenta não sinaliza — para separar
efeito real de conformidade automática com a máquina.

Amostra sugerida: 30 participantes por 8 textos, o que dá 240 observações
pareadas, suficiente para teste pareado com efeito moderado. Análise por
Wilcoxon pareado, já que a escala é ordinal.

**Requisito regulatório, em aberto.** Estudo com pessoas — inclusive coleta de
opinião — exige formulário 4 e aprovação de Comissão de Ética Escolar com três
assinaturas: profissional de saúde, educador e gestor escolar, nenhum deles o
orientador ou parente dos alunos. A aprovação precisa ser **datada antes da
primeira coleta** e a data é conferida. A comissão decide, item a item no próprio
formulário, se o TCLE, o assentimento de menores e a autorização de responsáveis
são exigidos no caso concreto. Como envolve testar protótipo desenvolvido pelos
próprios estudantes, o formulário 3 também é marcado como obrigatório na tabela
de normas de segurança. Está registrado em Riscos.

## Divisão de trabalho

O orientador constrói a coleta: `mind_collect/` inteiro, conforme `COLETA.md`.
Isso entra como base preexistente, declarada no formulário 2A e no relatório —
permitido, e omitir é que tira ponto. O `README.md`, o `DADOS.md` e o
`scripts/get_data.py` atuais também são do orientador e entram na mesma
declaração.

Os estudantes são donos de tudo que a banca consegue verificar em conversa:
a formulação do problema, a anotação do conjunto de teste, o desenho da
avaliação, o treino e a medição do modelo, o produto, o estudo com pessoas, a
interpretação dos resultados e o relatório.

Requisito não negociável: mesmo sem terem escrito a coleta, os três precisam
explicar de onde vem cada fonte, por que aquela e não outra, e o que o pipeline
faz com o dado. Cinco avaliadores com doutorado vão perguntar exatamente isso, e
o critério 6 avalia se a contribuição dos alunos ficou clara.

O diário de bordo de cada estudante registra o que ele fez, com data. É a prova
documental dessa divisão e é avaliado na mostra.

## Uso de IA generativa

O guia oficial permite usar IA para escrever o código inicial, com citação
explícita de quais partes foram geradas e registro dos prompts. Proíbe usá-la na
redação inicial do plano, do resumo, do relatório, do artigo e do pôster, e
proíbe gerar bibliografia.

Consequência prática: inventariar o código gerado por IA no repositório,
recuperar o log de prompts que existir, anexar a declaração ao formulário 2A com
ferramenta, versão, finalidade e registro, e incluir a declaração formal na
metodologia. Toda referência bibliográfica precisa ser aberta e conferida uma a
uma.

## Cronograma

**Esta semana (24 a 27/08).** Comissão de ética identificada e reunião agendada,
porque é a única tarefa que depende da agenda de terceiros. Base do coletor:
fila, store, dedup, cliente HTTP. Registro TSE de todos os anos. Caminho
`yt-dlp → mlx-whisper` funcionando ponta a ponta. Verificação de identidade da
Meta pedida hoje, que leva dias.

**28/08.** HGPE começa. Algo precisa estar gravando.

**29/08 a 05/09.** Ad Library quando o token sair. Trilha histórica solta em
paralelo: Common Crawl, dump do Reddit, Media Cloud, datasets já publicados,
Telegram, checagens, decisões do TSE com Wayback, GDELT. Primeiro fine-tuning do
mDeBERTa sobre SemEval, para ter baseline cedo.

**06 a 20/09.** Anotação do conjunto de teste pelos estudantes, em dupla, com
concordância medida. Site em desenvolvimento. Pipeline de imagem e OCR.

**21/09 a 05/10.** Estudo com pessoas, se e quando a aprovação estiver datada.
Calibração de limiar e medição de falso positivo em fala legítima. Site
funcionando.

**06 a 10/10.** Congelamento do corpus. Medições finais.

**10 a 19/10.** Relatório ou artigo, plano de pesquisa, resumo de 2.000
caracteres, formulário 2A com o anexo de IA. Cadastro dos três estudantes na
plataforma, cada um com e-mail próprio, e aceite dos convites — que depende de
terceiros e trava a submissão.

**20/10, 18h.** Submissão.

## Riscos

**Aberto: aprovação ética.** O estudo com pessoas está no escopo e a comissão
ainda não existe. Sem as três assinaturas datadas antes da primeira coleta, o
estudo é irregular e o projeto fica sujeito a desclassificação, inclusive
retroativa. Caminho de saída, se a comissão não se formar até meados de
setembro: descrever o protocolo de validação no relatório sem executá-lo. Um
protocolo bem desenhado é resultado de engenharia legítimo, e a FEBRACE aceita
projeto não concluído com próximos passos descritos.

**Publicação do site durante a campanha.** Sistema que avalia publicamente
propaganda de candidatos identificáveis em período eleitoral, com falso positivo
possível em fala legítima. A exposição recai sobre o orientador e a escola. Não é
exigência da FEBRACE, que pede apenas os documentos até 20/10 e a demonstração no
estande em março. Decisão tomada pelo orientador com essa informação.

**Anotação.** É a única etapa que não acelera com mais infraestrutura e é o
gargalo real do cronograma. Três estudantes, algumas centenas de peças, duas
semanas — apertado e sem folga.

**Concentração de conhecimento no orientador.** A coleta é sofisticada e foi
construída por quem não apresenta. Mitigação: uma sessão semanal em que os
estudantes percorrem o pipeline e explicam em voz alta, registrada no diário de
bordo.

**Disco.** 442 GB livres para um plano que fala em Common Crawl e dump do Reddit.
Mitigação: filtrar na origem, nunca guardar original de imagem, só hash, OCR e
miniatura.

## O que vai na submissão

Cadastro dos três estudantes com e-mail individual e convites aceitos. Dados do
projeto e categoria. Plano de pesquisa. Resumo de no máximo 2.000 caracteres com
3 palavras-chave. Relatório completo ou artigo científico em PDF abaixo de 2 MB —
sem esse documento o projeto não é avaliado. Formulário 2A assinado, com o anexo
de declaração de uso de IA.

Condicionais: formulários 4, TCLE e 3 se o estudo com pessoas for executado.

Não vai na submissão mas é avaliado em março: diário de bordo de cada estudante e
pôster de no máximo 0,9 m × 1,2 m.
