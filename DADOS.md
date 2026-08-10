# Dados

Os dados não ficam no repositório, são pesados demais. Para baixar:

```bash
python3 scripts/get_data.py
```

Não precisa instalar nada além do Python. Leva uns 10 minutos e ocupa 470 MB.
Se cair a internet no meio, roda de novo, ele pula o que já baixou.

```bash
python3 scripts/get_data.py --list             # ver o que já tem
python3 scripts/get_data.py --only wnc hatebr  # baixar só algumas
```

## O que vem

Em inglês, com a técnica de manipulação marcada em cada exemplo. É esse tipo de
rótulo que a gente quer:

- `semeval2021-t6`: 688 memes, 20 técnicas (apelo ao medo, autoridade, slogan e por aí vai)
- `mentalmanip`: 4.000 diálogos de filme, com a técnica usada e a fragilidade que ela explora
- `wnc`: 180 mil pares de frases da Wikipédia, a versão enviesada e a versão neutra da mesma frase. Dá pra ver a palavra exata que carrega o viés
- `dark-patterns` e `ec-darkpattern`: truques de loja online, tipo contagem regressiva e "12 pessoas vendo agora"
- `anthropic-persuasion`: 3.939 argumentos com a opinião do leitor medida antes e depois de ler

Em português, sem rótulo de manipulação. Servem de matéria-prima pra gente
anotar à mão:

- `hatebr`: 7.000 comentários do Instagram
- `told-br`: 21.000 tweets
- `fakebr`: 7.200 notícias, metade falsa
- `fakerecogna`: 11.903 notícias de agências de checagem

Fora do padrão tem o `clickbait17`, posts com nota de clickbait de 0 a 1. São
148 MB por causa das imagens, então só baixa se pedir:
`python3 scripts/get_data.py --only clickbait17`

## Por que tem notícia falsa aqui se o projeto não é sobre isso

Mentira e manipulação não são a mesma coisa.

"O IBGE divulgou inflação de 0,4%" é verdade e é direto. "URGENTE, só hoje: os
médicos não querem que você saiba disto" pode ser verdade também, e mesmo assim
é manipulação pura. Do outro lado, "morreu o ator fulano" é mentira, mas
mentira crua, sem técnica nenhuma.

O MIND tem que pegar a manipulação nos dois casos, inclusive quando o conteúdo
é verdadeiro. Detector de fake news só pega a mentira.

Por isso `fakebr` e `fakerecogna` nunca entram como resposta certa no treino.
Entram como texto pra anotar e como teste. Se o modelo apontar manipulação numa
promoção de Black Friday, ele acertou.

## A que falta

SemEval-2023 Task 3: 50 mil artigos de notícia com 23 técnicas marcadas, em 9
idiomas. Notícia é bem mais parecido com o que a gente vai analisar do que meme
ou roteiro de filme.

Precisa de cadastro, o script não baixa sozinho:

1. Cadastro em https://propaganda.math.unipd.it/semeval2023task3/
2. A aprovação é manual e leva alguns dias, então pede logo. Explicar que é pra
   iniciação científica ajuda.
3. Baixa com a senha que chega por e-mail e descompacta em `data/semeval2023-t3/`

Só pode usar em pesquisa, sem repassar os arquivos pra ninguém.

O SemEval-2020 Task 11 está na mesma situação
(https://propaganda.math.unipd.it/semeval2020task11/). São 14 técnicas de
propaganda marcadas trecho por trecho em notícia de verdade.

## Coisas que aparecem quando abre os arquivos

O WNC vem tokenizado. O `data/wnc/WNC/biased.word.train` é um TSV de 7 colunas e
as colunas 2 e 3 estão picadas em pedaço (`ch ##lor ##of`). Usa as colunas 4 e
5, que são as frases inteiras.

O download do WNC demora, uns 8 minutos pra 110 MB. O servidor de Stanford é
lento mesmo, não travou.

O SemEval-2021 é bem desequilibrado. No treino, Loaded Language aparece 358
vezes, Name calling 218, Smears 200, e as outras 17 técnicas ficam todas abaixo
de 55. Treinar nas 20 de uma vez não vai dar certo, melhor começar com as 6 ou 8
mais comuns.

Traduzir resolve metade do problema. As bases marcadas são em inglês, mas
também são sobre meme americano, filme e loja online. A tradução arruma o
idioma e não arruma o assunto. É por isso que o conjunto que a gente vai anotar
com conteúdo brasileiro pesa tanto.

LGPD: usar conteúdo público das agências de checagem e apagar @ e nome de
pessoa comum antes de publicar qualquer exemplo.
