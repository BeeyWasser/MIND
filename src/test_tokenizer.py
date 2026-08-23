from transformers import AutoTokenizer

MODEL_NAME = "neuralmind/bert-base-portuguese-cased"

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

texto = "Compartilhe agora! Esta é uma informação importante."

resultado = tokenizer(texto)

print("Texto original:")
print(texto)

print("\nTokens:")
print(tokenizer.tokenize(texto))

print("\nIDs dos tokens:")
print(resultado["input_ids"])