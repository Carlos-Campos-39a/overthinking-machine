"""
text_classification.py — Task de classificação de sentimento/tópico

task_type      : classification
response_format: single_label
eval_criteria  : accuracy, label_match
Avaliador      : binary (comparação exata com ground_truth)

Instâncias incluem análise de sentimento de notícias financeiras e
reviews de produtos — análogas ao benchmark de classificação de texto
do Paper 2 (Meta-Harness, Lee et al., 2026).

Labels válidos:
  Sentimento : Positivo | Negativo | Neutro
  Tópico     : Economia | Tecnologia | Saude | Politica | Esporte | Entretenimento
"""
from __future__ import annotations
import re
from src.task_base import TaskBase, TaskInstance

# ── Labels aceitos ────────────────────────────────────────────────────────────

SENTIMENT_LABELS = {"positivo", "negativo", "neutro"}
TOPIC_LABELS = {"economia", "tecnologia", "saude", "politica", "esporte", "entretenimento"}
ALL_LABELS = SENTIMENT_LABELS | TOPIC_LABELS

# ── Few-shot examples ─────────────────────────────────────────────────────────

_FEW_SHOT_EXAMPLES = [
    # Sentimento
    {
        "input": "Notícia: Itaú Unibanco bate recorde de lucro no trimestre com crescimento de 15%.",
        "output": "Positivo",
    },
    {
        "input": "Notícia: Inflação sobe pelo 4º mês consecutivo e corrói poder de compra das famílias.",
        "output": "Negativo",
    },
    {
        "input": "Notícia: Banco Central mantém taxa Selic em 13,75% em reunião do Copom.",
        "output": "Neutro",
    },
    # Tópico
    {
        "input": "Manchete: Reforma tributária aprovada no Congresso promete simplificar sistema fiscal.",
        "output": "Economia",
    },
    {
        "input": "Manchete: Apple lança novo iPhone com chip dedicado à inteligência artificial.",
        "output": "Tecnologia",
    },
]

# ── Instâncias ────────────────────────────────────────────────────────────────

_RAW_INSTANCES = [
    # ── Sentimento financeiro ────────────────────────────────────────────────
    {
        "id": "cls_s01",
        "input": (
            "Notícia: Petrobras anuncia distribuição de dividendos extraordinários "
            "de R$ 3,27 por ação, superando expectativas do mercado."
        ),
        "ground_truth": "Positivo",
        "task_subtype": "sentiment",
    },
    {
        "id": "cls_s02",
        "input": (
            "Notícia: Vale registra queda de 22% no lucro líquido devido ao "
            "desempenho fraco do minério de ferro e custos crescentes com segurança."
        ),
        "ground_truth": "Negativo",
        "task_subtype": "sentiment",
    },
    {
        "id": "cls_s03",
        "input": (
            "Notícia: Embraer entrega número de aeronaves em linha com o guidance "
            "anual. Empresa reitera previsões para o próximo trimestre."
        ),
        "ground_truth": "Neutro",
        "task_subtype": "sentiment",
    },
    {
        "id": "cls_s04",
        "input": (
            "Notícia: Nubank atinge 100 milhões de clientes e anuncia expansão "
            "para novos países da América Latina com aporte de US$ 150 milhões."
        ),
        "ground_truth": "Positivo",
        "task_subtype": "sentiment",
    },
    {
        "id": "cls_s05",
        "input": (
            "Notícia: Magazine Luiza tem prejuízo de R$ 400 milhões no trimestre, "
            "impactada por juros altos e aumento da inadimplência no crediário."
        ),
        "ground_truth": "Negativo",
        "task_subtype": "sentiment",
    },
    {
        "id": "cls_s06",
        "input": (
            "Notícia: Selic permanece em 10,5% ao ano após reunião do Copom, "
            "em linha com o consenso dos analistas de mercado."
        ),
        "ground_truth": "Neutro",
        "task_subtype": "sentiment",
    },
    {
        "id": "cls_s07",
        "input": (
            "Notícia: WEG bate estimativas com lucro 18% acima do esperado e "
            "eleva guidance para o ano inteiro citando demanda recorde por motores elétricos."
        ),
        "ground_truth": "Positivo",
        "task_subtype": "sentiment",
    },
    {
        "id": "cls_s08",
        "input": (
            "Notícia: Americanas divulga rombo contábil de R$ 20 bilhões e pede "
            "recuperação judicial em uma das maiores fraudes corporativas do Brasil."
        ),
        "ground_truth": "Negativo",
        "task_subtype": "sentiment",
    },
    {
        "id": "cls_s09",
        "input": (
            "Notícia: Bradesco publica resultado em linha com o projetado. "
            "Margem financeira cresce 3% no período enquanto inadimplência se estabiliza."
        ),
        "ground_truth": "Neutro",
        "task_subtype": "sentiment",
    },
    {
        "id": "cls_s10",
        "input": (
            "Notícia: Localiza reporta aumento de 40% na frota de veículos elétricos "
            "e assina parceria com montadora europeia para renovação antecipada."
        ),
        "ground_truth": "Positivo",
        "task_subtype": "sentiment",
    },
    # ── Classificação de tópico ──────────────────────────────────────────────
    {
        "id": "cls_t01",
        "input": (
            "Manchete: Governo anuncia novo programa de desonerações fiscais para "
            "o setor industrial visando retomada do crescimento do PIB."
        ),
        "ground_truth": "Economia",
        "task_subtype": "topic",
    },
    {
        "id": "cls_t02",
        "input": (
            "Manchete: Google lança modelo de linguagem Gemini Ultra 2 com "
            "capacidade de raciocínio científico avançado."
        ),
        "ground_truth": "Tecnologia",
        "task_subtype": "topic",
    },
    {
        "id": "cls_t03",
        "input": (
            "Manchete: Ministério da Saúde aprova vacina nacional contra dengue "
            "com eficácia de 79% em testes clínicos de fase 3."
        ),
        "ground_truth": "Saude",
        "task_subtype": "topic",
    },
    {
        "id": "cls_t04",
        "input": (
            "Manchete: Congresso Nacional aprova reforma administrativa com "
            "mudanças nas regras de estabilidade para novos servidores públicos."
        ),
        "ground_truth": "Politica",
        "task_subtype": "topic",
    },
    {
        "id": "cls_t05",
        "input": (
            "Manchete: Seleção brasileira vence Argentina por 2x1 e avança "
            "para a final da Copa América."
        ),
        "ground_truth": "Esporte",
        "task_subtype": "topic",
    },
    {
        "id": "cls_t06",
        "input": (
            "Manchete: Netflix anuncia série brasileira com orçamento recorde "
            "de R$ 80 milhões produzida em parceria com a Globo."
        ),
        "ground_truth": "Entretenimento",
        "task_subtype": "topic",
    },
    {
        "id": "cls_t07",
        "input": (
            "Manchete: Banco Central publica relatório mostrando desaceleração "
            "do crédito ao consumo e queda nas concessões de financiamento imobiliário."
        ),
        "ground_truth": "Economia",
        "task_subtype": "topic",
    },
    {
        "id": "cls_t08",
        "input": (
            "Manchete: Meta apresenta óculos de realidade aumentada com "
            "integração de IA generativa para uso corporativo."
        ),
        "ground_truth": "Tecnologia",
        "task_subtype": "topic",
    },
    {
        "id": "cls_t09",
        "input": (
            "Manchete: ANVISA aprova novo medicamento para tratamento de "
            "Alzheimer com resultado positivo em estudos de fase 3."
        ),
        "ground_truth": "Saude",
        "task_subtype": "topic",
    },
    {
        "id": "cls_t10",
        "input": (
            "Manchete: Flamengo contrata técnico europeu por € 4 milhões anuais "
            "em maior investimento do clube na história."
        ),
        "ground_truth": "Esporte",
        "task_subtype": "topic",
    },
]


class TextClassificationTask(TaskBase):
    """
    Tarefa de classificação de texto (sentimento e tópico).

    Avaliador recomendado: binary (comparação exata, case-insensitive).
    Labels esperados: Positivo, Negativo, Neutro, Economia, Tecnologia,
    Saude, Politica, Esporte, Entretenimento.
    """

    name = "text_classification"

    def load(self) -> None:
        self._instances = [
            TaskInstance(
                id=r["id"],
                input=r["input"],
                ground_truth=r["ground_truth"],
                task_type="classification",
                response_format="single_label",
                eval_criteria=["accuracy", "label_match"],
                metadata={
                    "examples": _FEW_SHOT_EXAMPLES,
                    "task_subtype": r.get("task_subtype", "sentiment"),
                    "valid_labels": (
                        list(SENTIMENT_LABELS)
                        if r.get("task_subtype") == "sentiment"
                        else list(TOPIC_LABELS)
                    ),
                },
            )
            for r in _RAW_INSTANCES
        ]

    def score(self, output: str, instance: TaskInstance) -> float:
        """
        Avaliação binária: extrai o primeiro label reconhecido do output
        e compara com o ground_truth (case-insensitive).
        """
        clean = output.strip().lower()
        # Tenta match exato primeiro
        if clean == instance.ground_truth.lower():
            return 1.0
        # Tenta encontrar label em qualquer posição do output
        for label in ALL_LABELS:
            if re.search(r"\b" + re.escape(label) + r"\b", clean):
                return 1.0 if label == instance.ground_truth.lower() else 0.0
        # Sem label reconhecido — score 0
        return 0.0
