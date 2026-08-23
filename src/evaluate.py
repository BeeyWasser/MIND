import pandas as pd
import torch

from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    classification_report,
)

from transformers import AutoTokenizer, AutoModelForSequenceClassification


# =========================
# 1. CONFIGURAÇÕES
# =========================

MODEL_PATH = "models/saved/bertimbau-teste"
DATASET_PATH = "data/processed/dataset.csv"


# =========================
# 2. CARREGAR DATASET
# =========================

df = pd.read_csv(DATASET_PATH)

textos = df["texto"].tolist()
labels = df["manipulador"].tolist()


# =========================
# 3. SEPARAR TREINO E TESTE
# =========================

X_treino, X_teste, y_treino, y_teste = train_test_split(
    textos,
    labels,
    test_size=0.2,
    random_state=42,
    stratify=labels
)

print(f"Textos utilizados para teste: {len(X_teste)}")


# =========================
# 4. CARREGAR MODELO
# =========================

print("\nCarregando modelo...")

tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)

model = AutoModelForSequenceClassification.from_pretrained(
    MODEL_PATH
)

model.eval()

print("Modelo carregado!")


# =========================
# 5. FAZER PREDIÇÕES
# =========================

predicoes = []

for texto in X_teste:

    inputs = tokenizer(
        texto,
        return_tensors="pt",
        truncation=True,
        max_length=128
    )

    with torch.no_grad():
        outputs = model(**inputs)

    classe = torch.argmax(
        outputs.logits,
        dim=1
    ).item()

    predicoes.append(classe)


# =========================
# 6. CALCULAR MÉTRICAS
# =========================

accuracy = accuracy_score(y_teste, predicoes)

precision = precision_score(
    y_teste,
    predicoes,
    zero_division=0
)

recall = recall_score(
    y_teste,
    predicoes,
    zero_division=0
)

f1 = f1_score(
    y_teste,
    predicoes,
    zero_division=0
)


# =========================
# 7. MOSTRAR RESULTADOS
# =========================

print("\n=============================")
print("RESULTADOS DA AVALIAÇÃO")
print("=============================")

print(f"Accuracy : {accuracy:.2%}")
print(f"Precision: {precision:.2%}")
print(f"Recall   : {recall:.2%}")
print(f"F1-score : {f1:.2%}")


# =========================
# 8. RELATÓRIO DETALHADO
# =========================

print("\nRelatório de classificação:")

print(
    classification_report(
        y_teste,
        predicoes,
        target_names=[
            "Não manipulador",
            "Manipulador"
        ],
        zero_division=0
    )
)


# =========================
# 9. MOSTRAR PREDIÇÕES
# =========================

print("\nPredições individuais:")

for texto, real, previsto in zip(
    X_teste,
    y_teste,
    predicoes
):

    print("\nTexto:")
    print(texto)

    print(f"Classe real:      {real}")
    print(f"Classe prevista:  {previsto}")