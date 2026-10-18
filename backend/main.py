from pathlib import Path
import re

import torch
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
)


# ==========================================
# 1. CONFIGURAÇÕES
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

MODEL_PATH = (
    PROJECT_ROOT
    / "models"
    / "saved"
    / "bertimbau-teste"
)

MAX_CHARACTERS = 10000
MAX_LENGTH = 128


# ==========================================
# 2. CRIAÇÃO DA API
# ==========================================

app = FastAPI(
    title="MIND API",
    description="API de classificação de conteúdos digitais.",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:5501",
        "http://localhost:5501",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# ==========================================
# 3. CARREGAMENTO DO MODELO
# ==========================================

print("Carregando o modelo do MIND...")

if not MODEL_PATH.is_dir():
    raise FileNotFoundError(
        f"Modelo não encontrado em: {MODEL_PATH}"
    )

tokenizer = AutoTokenizer.from_pretrained(
    str(MODEL_PATH)
)

model = AutoModelForSequenceClassification.from_pretrained(
    str(MODEL_PATH)
)

device = torch.device("cpu")

model.to(device)
model.eval()

print("Modelo carregado com sucesso!")


# ==========================================
# 4. ESTRUTURA DA REQUISIÇÃO
# ==========================================

class AnalysisRequest(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=MAX_CHARACTERS,
    )


# ==========================================
# 5. FUNÇÃO DE CLASSIFICAÇÃO
# ==========================================

def classify_text(text: str) -> dict:

    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=MAX_LENGTH,
    )

    inputs = {
        key: value.to(device)
        for key, value in inputs.items()
    }

    with torch.inference_mode():
        outputs = model(**inputs)

    probabilities = torch.softmax(
        outputs.logits,
        dim=1,
    )[0]

    predicted_class = int(
        torch.argmax(probabilities).item()
    )

    return {
        "class_id": predicted_class,
        "classification": (
            "MANIPULADOR"
            if predicted_class == 1
            else "NÃO MANIPULADOR"
        ),
        "manipulative_probability": round(
            float(probabilities[1].item()),
            4,
        ),
        "non_manipulative_probability": round(
            float(probabilities[0].item()),
            4,
        ),
        "confidence": round(
            float(probabilities[predicted_class].item()),
            4,
        ),
    }


# ==========================================
# 6. ROTAS DA API
# ==========================================

@app.get("/")
def home():

    return {
        "name": "MIND API",
        "status": "online",
        "model_loaded": True,
    }


@app.get("/api/health")
def health():

    return {
        "status": "online",
        "model_loaded": True,
    }


@app.post("/api/analyze")
def analyze(request: AnalysisRequest):

    text = request.text.strip()

    if not text:
        raise HTTPException(
            status_code=422,
            detail="O texto não pode estar vazio.",
        )

    # Classificação geral.
    overall_result = classify_text(text)

    # Divide o conteúdo em frases.
    sentences = re.split(
        r'(?<=[.!?])\s+',
        text,
    )

    sentences = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
    ]

    # Classifica cada frase individualmente.
    identified_segments = []

    for sentence in sentences:

        result = classify_text(sentence)

        if result["class_id"] == 1:

            identified_segments.append({
                "text": sentence,
                "classification": (
                    "POTENCIALMENTE MANIPULADOR"
                ),
                "manipulative_probability": (
                    result["manipulative_probability"]
                ),
                "confidence": result["confidence"],
            })

    # Devolve os resultados ao front-end.
    return {
        "classification": (
            overall_result["classification"]
        ),
        "class_id": overall_result["class_id"],
        "confidence": overall_result["confidence"],
        "probabilities": {
            "manipulative": (
                overall_result[
                    "manipulative_probability"
                ]
            ),
            "non_manipulative": (
                overall_result[
                    "non_manipulative_probability"
                ]
            ),
        },
        "identified_segments": identified_segments,
        "segments_analyzed": len(sentences),
        "model": "BERTimbau",
        "analysis_note": (
            "Os resultados são indicativos. "
            "As probabilidades representam as saídas "
            "do classificador e não uma medida objetiva "
            "de manipulação. O modelo não identifica "
            "estratégias específicas."
        ),
    }