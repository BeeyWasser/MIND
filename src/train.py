import pandas as pd
from sklearn.model_selection import train_test_split
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    Trainer,
    TrainingArguments,
)
import torch # Inicialização



# 1. CONFIGURAÇÕES

MODEL_NAME = "neuralmind/bert-base-portuguese-cased"

DATASET_PATH = "data/processed/mind_dataset.csv"

MODEL_OUTPUT = "models/saved/bertimbau-teste"



# 2. CARREGAR DATASET

print("Carregando dataset...")

df = pd.read_csv(DATASET_PATH)

textos = df["texto"].tolist()
labels = df["manipulador"].tolist()

print(f"Total de textos: {len(textos)}")



# 3. DIVIDIR OS DADOS

X_treino, X_teste, y_treino, y_teste = train_test_split(
    textos,
    labels,
    test_size=0.2,
    random_state=42,
    stratify=labels
)

print(f"Treinamento: {len(X_treino)}")
print(f"Teste: {len(X_teste)}")



# 4. TOKENIZER

print("\nCarregando tokenizer...")

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)


treino_tokenizado = tokenizer(
    X_treino,
    padding=True,
    truncation=True,
    max_length=256
)


teste_tokenizado = tokenizer(
    X_teste,
    padding=True,
    truncation=True,
    max_length=256
)



# 5. DATASET PARA PYTORCH

class TextDataset(torch.utils.data.Dataset):

    def __init__(self, encodings, labels):
        self.encodings = encodings
        self.labels = labels

    def __getitem__(self, index):

        item = {
            key: torch.tensor(value[index])
            for key, value in self.encodings.items()
        }

        item["labels"] = torch.tensor(
            self.labels[index],
            dtype=torch.long
        )

        return item

    def __len__(self):
        return len(self.labels)


dataset_treino = TextDataset(
    treino_tokenizado,
    y_treino
)


dataset_teste = TextDataset(
    teste_tokenizado,
    y_teste
)



# 6. CARREGAR BERTIMBAU

print("\nCarregando BERTimbau...")

model = AutoModelForSequenceClassification.from_pretrained(
    MODEL_NAME,
    num_labels=2
)

# 7. CONFIGURAR TREINAMENTO

training_args = TrainingArguments(
    output_dir=MODEL_OUTPUT,

    num_train_epochs=3,

    per_device_train_batch_size=2,
    per_device_eval_batch_size=2,

    learning_rate=2e-5,

    logging_steps=20,

    save_strategy="no",

    report_to="none"
)

# 8. TRAINER

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=dataset_treino,
    eval_dataset=dataset_teste,
)


# 9. TREINAR

print("\nIniciando treinamento...")

trainer.train()


# 10. SALVAR MODELO

print("\nSalvando modelo...")

trainer.save_model(MODEL_OUTPUT)

tokenizer.save_pretrained(MODEL_OUTPUT)


print("\nTreinamento concluído!")

print(f"Modelo salvo em: {MODEL_OUTPUT}")