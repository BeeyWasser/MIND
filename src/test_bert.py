from transformers import AutoTokenizer, AutoModel


MODEL_NAME = "neuralmind/bert-base-portuguese-cased"

print("Carregando o tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

print("Carregando o BERTimbau...")
model = AutoModel.from_pretrained(MODEL_NAME)

texto = "Este é o primeiro teste do nosso projeto."

tokens = tokenizer(texto, return_tensors="pt")

print("\nTexto:")
print(texto)

print("\nTokens:")
print(tokens)

print("\nBERTimbau carregado com sucesso!")