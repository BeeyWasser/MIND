import pandas as pd
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_FILE = DATA_DIR / "processed" / "mind_dataset.csv"

MENTALMANIP_FILE = DATA_DIR / "mentalmanip" / "mentalmanip_detailed.csv"


def maioria(valores):
    """
    Retorna a maioria entre os rótulos dos anotadores.
    """
    valores = pd.to_numeric(pd.Series(valores), errors="coerce").dropna()

    if len(valores) == 0:
        return None

    return int(valores.mean() >= 0.5)


def main():

    print("Carregando MentalManip...")

    df = pd.read_csv(MENTALMANIP_FILE)

    print(f"Total de exemplos: {len(df)}")

    dados = []

    for _, row in df.iterrows():

        texto = str(row["dialogue"]).strip()

        if not texto:
            continue

        manipulador = maioria([
            row["manipulative_1"],
            row["manipulative_2"],
            row["manipulative_3"]
        ])

        if manipulador is None:
            continue

        dados.append({
            "texto": texto,
            "manipulador": manipulador
        })

    dataset = pd.DataFrame(dados)

    # Remove textos duplicados
    dataset = dataset.drop_duplicates(subset="texto")

    # Embaralha os exemplos
    dataset = dataset.sample(
        frac=1,
        random_state=42
    ).reset_index(drop=True)

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    dataset.to_csv(
        OUTPUT_FILE,
        index=False,
        encoding="utf-8"
    )

    print("\nDataset criado!")
    print(f"Textos: {len(dataset)}")
    print(
        f"Manipuladores: "
        f"{(dataset['manipulador'] == 1).sum()}"
    )
    print(
        f"Não manipuladores: "
        f"{(dataset['manipulador'] == 0).sum()}"
    )

    print("\nDistribuição:")
    print(dataset["manipulador"].value_counts())

    print(f"\nSalvo em: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()