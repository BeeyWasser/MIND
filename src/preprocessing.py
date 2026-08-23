import pandas as pd
from sklearn.model_selection import train_test_split


# Caminho do dataset
CAMINHO_DATASET = "data/processed/mind_dataset.csv"


# Carrego o dataset primeiro
df = pd.read_csv(CAMINHO_DATASET)

print("Dataset carregado!")
print(f"Quantidade de textos: {len(df)}")


# Verifico as colunas
print("\nColunas:")
print(df.columns.tolist())


# Verifico os valores ausentes
print("\nValores ausentes:")
print(df.isnull().sum())


# Separo textos e classificações
X = df["texto"]
y = df["manipulador"]


# Divido os dados em treino e teste
X_treino, X_teste, y_treino, y_teste = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42,
    stratify=y
)


# Por último, mostro a divisão dos dados e a distribuição das classes
print("\nDivisão dos dados:")
print(f"Treinamento: {len(X_treino)} textos")
print(f"Teste: {len(X_teste)} textos")

print("\nDistribuição no treinamento:")
print(y_treino.value_counts())

print("\nDistribuição no teste:")
print(y_teste.value_counts())