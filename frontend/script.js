const analysisForm = document.getElementById("analysis-form");
const contentInput = document.getElementById("content-input");
const characterCount = document.getElementById("character-count");
const analyzeButton = document.getElementById("analyze-button");
const resultArea = document.getElementById("result-area");
const resultTitle = document.getElementById("result-title");
const resultContent = document.getElementById("result-content");

const MAX_CHARACTERS = 10000;
const API_URL = "http://127.0.0.1:8000/api/analyze";

function updateCharacterCount() {
    const currentLength = contentInput.value.length;
    characterCount.textContent =
        `${currentLength.toLocaleString("pt-BR")} / ` +
        `${MAX_CHARACTERS.toLocaleString("pt-BR")} caracteres`;
}

contentInput.addEventListener("input", updateCharacterCount);

document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", (event) => {
        const targetId = link.getAttribute("href");
        const targetElement = document.querySelector(targetId);
        if (!targetElement) return;
        event.preventDefault();
        targetElement.scrollIntoView({ behavior: "smooth", block: "start" });
    });
});

function setLoading(isLoading) {
    analyzeButton.disabled = isLoading;
    contentInput.disabled = isLoading;

    if (isLoading) {
        analyzeButton.innerHTML =
            '<span class="button-spinner" aria-hidden="true"></span> Analisando...';
        analyzeButton.setAttribute("aria-busy", "true");
    } else {
        analyzeButton.innerHTML = 'Analisar conteúdo <span aria-hidden="true">→</span>';
        analyzeButton.removeAttribute("aria-busy");
    }
}

function addText(parent, tag, text, className = "") {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    parent.appendChild(element);
    return element;
}

function formatPercent(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return `${(number * 100).toLocaleString("pt-BR", {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1
    })}%`;
}

function renderResults(data) {
    resultContent.replaceChildren();

    const overall = document.createElement("div");
    overall.className = "overall-result";
    resultContent.appendChild(overall);

    addText(overall, "p", `Classificação geral: ${data.classification || "Indisponível"}`, "overall-classification");

    const probabilities = data.probabilities || {};
    addText(
        overall,
        "p",
        `Probabilidade estimada de classe manipuladora: ${formatPercent(probabilities.manipulative)}`
    );
    addText(
        overall,
        "p",
        `Probabilidade estimada de classe não manipuladora: ${formatPercent(probabilities.non_manipulative)}`
    );
    addText(
        overall,
        "p",
        `Frases analisadas: ${Number.isInteger(data.segments_analyzed) ? data.segments_analyzed : 0}`
    );

    const heading = addText(resultContent, "h4", "Trechos potencialmente manipuladores", "table-heading");
    heading.id = "identified-segments-heading";

    const segments = Array.isArray(data.identified_segments) ? data.identified_segments : [];

    if (segments.length === 0) {
        addText(
            resultContent,
            "p",
            "Nenhum trecho foi classificado como potencialmente manipulador nesta análise. Isso não garante que o conteúdo esteja livre de manipulação.",
            "empty-segments"
        );
    } else {
        const wrapper = document.createElement("div");
        wrapper.className = "results-table-wrapper";

        const table = document.createElement("table");
        table.className = "results-table";
        table.setAttribute("aria-labelledby", heading.id);

        const thead = document.createElement("thead");
        const headerRow = document.createElement("tr");
        ["Trecho identificado", "Classificação", "Probabilidade estimada"].forEach((label) => {
            addText(headerRow, "th", label);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement("tbody");
        segments.forEach((segment) => {
            const row = document.createElement("tr");
            addText(row, "td", segment.text || "—", "segment-text");
            addText(row, "td", segment.classification || "Potencialmente manipulador");
            addText(row, "td", formatPercent(segment.manipulative_probability));
            tbody.appendChild(row);
        });

        table.appendChild(tbody);
        wrapper.appendChild(table);
        resultContent.appendChild(wrapper);
    }

    if (data.analysis_note) {
        addText(resultContent, "p", data.analysis_note, "analysis-note");
    }

    addText(
        resultContent,
        "p",
        "Importante: o resultado é indicativo. O modelo classifica o texto, mas não comprova intenção nem identifica estratégias específicas de manipulação.",
        "analysis-note"
    );

    resultArea.hidden = false;
    resultArea.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function showError(title, message) {
    resultContent.replaceChildren();
    addText(resultContent, "p", message);
    resultArea.hidden = false;
    resultTitle.textContent = title;
    resultArea.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

analysisForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = contentInput.value.trim();

    if (!content) {
        showError("Texto necessário", "Insira um conteúdo antes de iniciar a análise.");
        contentInput.focus();
        return;
    }

    if (content.length > MAX_CHARACTERS) {
        showError("Limite excedido", "O conteúdo ultrapassa o limite de 10.000 caracteres.");
        return;
    }

    setLoading(true);
    resultTitle.textContent = "Analisando conteúdo...";
    resultContent.replaceChildren();
    resultArea.hidden = false;

    try {
        const response = await fetch(API_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: content })
        });

        let data;
        try {
            data = await response.json();
        } catch {
            throw new Error("A API retornou uma resposta que não pôde ser lida.");
        }

        if (!response.ok) {
            const detail = typeof data.detail === "string"
                ? data.detail
                : "Confira o texto e tente novamente.";
            throw new Error(detail);
        }

        resultTitle.textContent = "Resultado da análise";
        renderResults(data);
    } catch (error) {
        console.error("Erro ao analisar conteúdo:", error);
        resultTitle.textContent = "Não foi possível concluir a análise";

        if (error instanceof TypeError) {
            showError(
                "Falha de conexão",
                "Não foi possível acessar a API. Confirme que o back-end está rodando em http://127.0.0.1:8000 e abra o front-end pelo Live Server."
            );
        } else {
            showError("Erro na análise", error.message || "Ocorreu um erro inesperado.");
        }
    } finally {
        setLoading(false);
    }
});

updateCharacterCount();
console.log("MIND: front-end conectado ao endpoint de análise.");
