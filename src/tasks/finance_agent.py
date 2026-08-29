"""
finance_agent.py — Task de análise financeira (market_search)

task_type      : market_search
response_format: long_prose
eval_criteria  : accuracy, depth, clarity
Avaliador      : llm_judge (recomendado)

Instâncias cobrem análise de empresas, setores, risco e valuation,
cobrindo o benchmark Finance-Agent do Paper 1 (Bigeard et al., 2025,
"Finance Agent Benchmark: Benchmarking LLMs on Real-World Financial
Research Tasks", arXiv:2508.00828).
"""
from __future__ import annotations
from src.task_base import TaskBase, TaskInstance

_FEW_SHOT_EXAMPLES = [
    {
        "input": (
            "Analise a estrutura de capital da Ambev S.A. e avalie se o nível "
            "atual de endividamento é sustentável dado o contexto setorial."
        ),
        "output": (
            "A Ambev mantém uma estrutura de capital conservadora com dívida líquida/EBITDA "
            "inferior a 0.5x, muito abaixo do setor de bens de consumo (1.5-2.5x). "
            "Com geração de caixa operacional robusta (~R$ 15 bi/ano) e margens EBITDA de "
            "37%, o endividamento atual é amplamente sustentável. A principal pressão vem "
            "da volatilidade cambial nos insumos (alumínio, cevada), mas o hedging sistemático "
            "mitiga esse risco. Conclusão: estrutura saudável com capacidade de alavancagem "
            "adicional se necessário para M&A ou capex de expansão."
        ),
    },
    {
        "input": (
            "Quais são os principais riscos e oportunidades para o setor bancário "
            "brasileiro com a implementação do Open Finance?"
        ),
        "output": (
            "Riscos: (1) Compressão de margens — portabilidade facilitada aumenta "
            "competição por spread; (2) Custo de adaptação tecnológica para bancos legados; "
            "(3) Risco de concentração de dados com BigTechs. "
            "Oportunidades: (1) Cross-selling baseado em dados de comportamento financeiro; "
            "(2) Redução do custo de aquisição de clientes via APIs abertas; "
            "(3) Desenvolvimento de produtos personalizados. Bancos digitais tendem a se "
            "beneficiar mais pela agilidade em explorar APIs, enquanto bancões tradicionais "
            "precisam acelerar transformação digital para não perder participação."
        ),
    },
]

_RAW_INSTANCES = [
    # ── Análise de empresas ──────────────────────────────────────────
    {
        "id": "fin_001",
        "input": (
            "Avalie o potencial de crescimento da Embraer nos próximos 5 anos "
            "considerando a demanda por aeronaves regionais e a concorrência "
            "da ATR e Bombardier."
        ),
        "ground_truth": (
            "análise que mencione: carteira de pedidos E-Jet E2, demanda por "
            "jatos regionais eficientes, parcerias com companhias aéreas low-cost, "
            "riscos cambiais (receita em dólar, custo em real), e concorrência."
        ),
    },
    {
        "id": "fin_002",
        "input": (
            "Analise o impacto da taxa Selic no custo de capital das empresas "
            "listadas no Ibovespa. Quais setores são mais sensíveis a este fator?"
        ),
        "ground_truth": (
            "análise de: transmissão da Selic para custo de dívida, setores "
            "sensíveis (utilities, imobiliário, consumo alavancado), e impacto "
            "no WACC e múltiplos de valuation."
        ),
    },
    {
        "id": "fin_003",
        "input": (
            "Compare o modelo de negócios do Nubank com o de um banco tradicional "
            "como o Bradesco. Quais são as vantagens competitivas estruturais de cada um?"
        ),
        "ground_truth": (
            "comparação cobrindo: custo de operação (Nubank 10x menor por cliente), "
            "base de clientes jovens vs. relacionamento corporativo, "
            "receita de serviços vs. spread, e escala de plataforma digital."
        ),
    },
    {
        "id": "fin_004",
        "input": (
            "Qual o impacto esperado da transição energética nos resultados da "
            "Petrobras para 2030? Considere o cronograma global de descarbonização."
        ),
        "ground_truth": (
            "análise de: reservas de longo prazo (pré-sal), planos de investimento "
            "em renováveis, risco de ativos encalhados, dividendos históricos, "
            "e posição competitiva em petróleo de baixo custo de extração."
        ),
    },
    {
        "id": "fin_005",
        "input": (
            "Avalie a atratividade de investimento da Magazine Luiza no atual "
            "cenário de juros altos e competição crescente do e-commerce asiático."
        ),
        "ground_truth": (
            "análise de: endividamento histórico da MGLU, impacto de juros no "
            "financiamento ao consumidor, concorrência Shopee/Shein, "
            "estratégia omnichannel e lucratividade por canal."
        ),
    },
    # ── Análise setorial ─────────────────────────────────────────────
    {
        "id": "fin_006",
        "input": (
            "Analise as perspectivas do setor de agronegócio brasileiro para os "
            "próximos 3 anos, incluindo riscos climáticos e dinâmica de preços "
            "das commodities."
        ),
        "ground_truth": (
            "cobertura de: ciclo de preços de soja/milho, exposição a La Niña, "
            "demanda chinesa, câmbio e competição Argentina/EUA, "
            "e empresas listadas como AGRO3, SLC Agrícola."
        ),
    },
    {
        "id": "fin_007",
        "input": (
            "Qual é o outlook do setor de saúde suplementar no Brasil após "
            "os aumentos de sinistralidade pós-pandemia? Avalie Hapvida e REDE D'OR."
        ),
        "ground_truth": (
            "análise de: sinistralidade (>90% em 2022-23), repasse de reajustes, "
            "estratégia verticalizada Hapvida vs. hospitalização premium REDE D'OR, "
            "regulação ANS, e recuperação de margens."
        ),
    },
    {
        "id": "fin_008",
        "input": (
            "Avalie o potencial do mercado de crédito para PMEs no Brasil. "
            "Quais fintechs estão melhor posicionadas para capturar este mercado?"
        ),
        "ground_truth": (
            "análise de: gap de crédito para PMEs (~R$ 300 bi), taxa de inadimplência, "
            "players como Creditas, BizCapital, Open Co, vantagens de dados "
            "alternativos e Open Finance para scoring."
        ),
    },
    {
        "id": "fin_009",
        "input": (
            "Como a elevação dos preços da energia elétrica impacta a "
            "competitividade das indústrias intensivas em energia no Brasil, "
            "como alumínio e papel/celulose?"
        ),
        "ground_truth": (
            "análise de: participação da energia no custo total (~30-40% em alumínio), "
            "PCHs e energia autoproducida, impacto na EBITDA de empresas como "
            "CBA, Klabin, Suzano, e comparação com competidores globais."
        ),
    },
    {
        "id": "fin_010",
        "input": (
            "Analise o mercado de fundos imobiliários (FIIs) no Brasil em 2025. "
            "Como o nível de juros afeta a atratividade desta classe de ativo?"
        ),
        "ground_truth": (
            "análise de: dividend yield médio FIIs vs. Selic, tipos (tijolo, papel, "
            "híbrido), impacto da vacância em FIIs de lajes corporativas, "
            "benchmark IFIX, e comparação risco/retorno com renda fixa."
        ),
    },
    # ── Valuation e M&A ──────────────────────────────────────────────
    {
        "id": "fin_011",
        "input": (
            "Explique os principais métodos de valuation utilizados para "
            "startups de tecnologia no Brasil e suas limitações práticas "
            "no contexto atual de mercado."
        ),
        "ground_truth": (
            "cobertura de: DCF (limitações em early stage), múltiplos de receita "
            "(EV/Revenue), comparáveis de mercado, venture DCF, e como o "
            "ambiente de juros altos comprime múltiplos de crescimento."
        ),
    },
    {
        "id": "fin_012",
        "input": (
            "Avalie os riscos e benefícios da fusão entre Hapvida e NotreDame "
            "Intermédica (GNDI). O deal gerou valor para os acionistas?"
        ),
        "ground_truth": (
            "análise de: sinergias prometidas (~R$ 1,5 bi), execução difícil, "
            "destruição de valor em 2022-23, integração de sistemas, "
            "sinistralidade combinada, e lições aprendidas sobre M&A no setor."
        ),
    },
    {
        "id": "fin_013",
        "input": (
            "Qual o impacto das mudanças regulatórias no mercado de "
            "telecomunicações brasileiro sobre a estrutura competitiva "
            "e os resultados das operadoras?"
        ),
        "ground_truth": (
            "análise de: consolidação Oi/TIM/Claro, regulação ANATEL, "
            "investimentos em 5G, evolução de ARPU, compressão de margens "
            "em voz vs. crescimento em dados."
        ),
    },
    {
        "id": "fin_014",
        "input": (
            "Como avaliar o risco soberano do Brasil no contexto de "
            "deterioração fiscal? Qual o impacto no custo de capital das empresas?"
        ),
        "ground_truth": (
            "análise de: trajetória da dívida/PIB, spread CDS, rating Moody's/S&P, "
            "transmissão para taxa livre de risco doméstica, impacto no WACC "
            "das empresas e prêmio de risco do equity brasileiro."
        ),
    },
    {
        "id": "fin_015",
        "input": (
            "Analise a estratégia de internacionalização da WEG S.A. "
            "e seu impacto nos resultados financeiros dos últimos 5 anos."
        ),
        "ground_truth": (
            "análise de: receita internacional (>60% do total), aquisições "
            "estratégicas na Europa e EUA, mix de motores industriais vs. "
            "energia renovável, vantagem cambial na exportação, e múltiplos "
            "premium justificados pelo crescimento composto."
        ),
    },
]


class FinanceAgentTask(TaskBase):
    """
    Tarefa de análise financeira — avalia profundidade analítica, precisão
    e clareza das respostas sobre mercados, empresas e estratégia financeira.

    Avaliador recomendado: llm_judge (respostas abertas em prosa).
    """

    name = "finance_agent"

    def load(self) -> None:
        self._instances = [
            TaskInstance(
                id=r["id"],
                input=r["input"],
                ground_truth=r["ground_truth"],
                task_type="market_search",
                response_format="long_prose",
                eval_criteria=["accuracy", "depth", "clarity"],
                metadata={"examples": _FEW_SHOT_EXAMPLES},
            )
            for r in _RAW_INSTANCES
        ]

    def score(self, output: str, instance: TaskInstance) -> float:
        """
        Heurística simples de fallback — verifica se palavras-chave do
        ground_truth aparecem no output. Para avaliação real, use llm_judge.
        """
        keywords = [
            w.strip(".,;:()")
            for w in instance.ground_truth.lower().split()
            if len(w) > 5
        ]
        if not keywords:
            return 0.5
        matches = sum(1 for kw in keywords if kw in output.lower())
        return min(1.0, matches / max(len(keywords), 1))
