import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification


# =========================
# 1. CONFIGURAÇÕES
# =========================

MODEL_PATH = "models/saved/bertimbau-teste"


# =========================
# 2. CARREGAR MODELO
# =========================

print("Carregando modelo...")

tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)

model.eval()

print("Modelo carregado!\n")


# =========================
# 3. TEXTO PARA TESTAR
# =========================

texto = input("Digite um texto para analisar: ")


# =========================
# 4. TOKENIZAÇÃO
# =========================

inputs = tokenizer(
    texto,
    return_tensors="pt",
    truncation=True,
    max_length=128
)


# =========================
# 5. PREDIÇÃO
# =========================

with torch.no_grad():
    outputs = model(**inputs)

probabilidades = torch.softmax(outputs.logits, dim=1)

classe = torch.argmax(probabilidades, dim=1).item()

probabilidade = probabilidades[0][classe].item()


# =========================
# 6. RESULTADO
# =========================

if classe == 1:
    resultado = "MANIPULADOR"
else:
    resultado = "NÃO MANIPULADOR"


print("\n-----------------------------")
print("RESULTADO")
print("-----------------------------")
print(f"Classificação: {resultado}")
print(f"Probabilidade: {probabilidade:.2%}")