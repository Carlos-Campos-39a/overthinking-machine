"""
propostas_iniciais.py — as 5 arquiteturas de Kim et al. (2025) como especificação.

Não são exemplos ilustrativos: os prompts abaixo foram transcritos literalmente
das classes em src/agents/, para que rodar a proposta produza os MESMOS prompts
que rodar a classe. O teste de equivalência em validate_platform compara as
duas execuções byte a byte.

Servem a dois propósitos:
  1. provar que os quatro tipos de estágio bastam para expressar as cinco
     topologias do paper — se não bastassem, a linguagem estaria incompleta;
  2. dar ao usuário um ponto de partida editável. Carregar "centralized",
     mudar um prompt e rodar é o caminho mais curto para a primeira topologia
     própria de alguém.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# Fidelidade
#
# `entrada_bruta: true` em sas e independent não é detalhe: SingleAgentSystem e
# IndependentMAS chamam llm.invoke(messages) com a lista ORIGINAL do harness.
# Reconstruir um par [System, Human] daria um prompt diferente sempre que o
# harness emitisse mais de duas mensagens. É a diferença entre "parecido" e
# "idêntico".
# ─────────────────────────────────────────────────────────────────────────────

SAS = {
    "nome": "sas",
    "titulo": "Single Agent System",
    "descricao": (
        "Um único LLM recebe o contexto completo do harness e responde. "
        "Baseline de referência: overhead de coordenação zero."
    ),
    "autor": "Kim et al. (2025)",
    "estagios": [
        {
            "id": "agente",
            "tipo": "unico",
            "rotulo": "Agente único",
            "entrada_bruta": True,
            "final": True,
        }
    ],
}

INDEPENDENT = {
    "nome": "independent",
    "titulo": "Independent MAS",
    "descricao": (
        "N agentes respondem à mesma tarefa sem se comunicar; um agregador "
        "concatena. Sem validação cruzada, amplifica erros 17,2× (Kim et al.)."
    ),
    "autor": "Kim et al. (2025)",
    "estagios": [
        {
            "id": "agente",
            "tipo": "paralelo",
            "rotulo": "Agentes independentes",
            "n": 3,
            "entrada_bruta": True,
        },
        {
            "id": "aggregator",
            "tipo": "reduzir",
            "rotulo": "Agregador",
            "formato_bloco": "=== Agente {j} ===\n{saida}",
            "prompt": (
                "TAREFA:\n{task_content}\n\n"
                "Abaixo estão {n:agente} respostas independentes para esta tarefa. "
                "Combine-as em uma resposta unificada e coerente.\n\n"
                "{blocos}\n\n"
                "Resposta combinada (sem mencionar que são múltiplas fontes):"
            ),
            "final": True,
        },
    ],
}

CENTRALIZED = {
    "nome": "centralized",
    "titulo": "Centralized MAS",
    "descricao": (
        "Um orquestrador decompõe a tarefa, workers executam as partes e o "
        "orquestrador sintetiza. O gargalo de validação reduz a amplificação "
        "de erro de 17,2× para 4,4×."
    ),
    "autor": "Kim et al. (2025)",
    "estagios": [
        {
            "id": "orchestrator",
            "tipo": "unico",
            "rotulo": "Orquestrador decompõe",
            "prompt": (
                "Você é um orquestrador especialista. Decomponha a tarefa abaixo em "
                "exatamente {n:worker} subtarefas independentes e complementares.\n\n"
                "TAREFA PRINCIPAL:\n{task_content}\n\n"
                "Responda APENAS com as {n:worker} subtarefas, uma por linha, "
                "numeradas de 1 a {n:worker}. Cada subtarefa deve ser autocontida "
                "e contribuir para a resposta final."
            ),
        },
        {
            "id": "worker",
            "tipo": "paralelo",
            "rotulo": "Workers executam",
            "n": 3,
            "dividir": True,
            "prompt": (
                "TAREFA ORIGINAL:\n{task_content}\n\n"
                "SUA SUBTAREFA:\n{subtarefa}\n\n"
                "Execute sua subtarefa considerando o contexto da tarefa original acima."
            ),
        },
        {
            "id": "sintese",
            "tipo": "reduzir",
            "rotulo": "Orquestrador sintetiza",
            "formato_bloco": "=== Worker {j} ===\n{saida}",
            "prompt": (
                "Você recebeu análises de {n:worker} especialistas para a tarefa abaixo.\n\n"
                "TAREFA ORIGINAL:\n{task_content}\n\n"
                "ANÁLISES DOS WORKERS:\n{blocos}\n\n"
                "Sintetize as análises em uma resposta final coesa, completa e sem "
                "redundâncias. Resolva contradições usando seu próprio julgamento. "
                "Responda diretamente sem mencionar os workers ou o processo de síntese."
            ),
            "final": True,
        },
    ],
}

DECENTRALIZED = {
    "nome": "decentralized",
    "titulo": "Decentralized MAS",
    "descricao": (
        "N pares com personas distintas debatem entre si por r rodadas antes de "
        "consolidar. Alta exploração, custo alto.\n"
        "Equivale à classe embutida para n>=2 e rodadas>=1: com n=1 ou 0 rodadas "
        "a classe pula a consolidação, e a especificação não."
    ),
    "autor": "Kim et al. (2025)",
    "estagios": [
        {
            "id": "agente",
            "tipo": "paralelo",
            "rotulo": "Posições iniciais",
            "n": 3,
            # A persona entra como o ângulo pedido no fim do prompt, não como
            # cabeçalho — é assim que DecentralizedMAS monta a perspectiva.
            "papeis": [
                "crítico e conservador",
                "otimista e prospectivo",
                "equilibrado e baseado em dados",
            ],
            "prompt": (
                "{task_content}\n\n"
                "[Perspectiva {i}/{n}: analise a partir de um ângulo {papel}]"
            ),
        },
        {
            "id": "debate",
            "tipo": "debate",
            "rotulo": "Debate entre pares",
            "n": 3,
            "rodadas": 1,
            "formato_par": "--- Resposta do Agente {j} ---\n{saida}",
            # {rodada_anterior} e não {rodada}: a classe rotula a resposta prévia
            # com round_num-1, ou seja "Round 0" na primeira rodada de debate.
            "prompt": (
                "TAREFA ORIGINAL:\n{task_content}\n\n"
                "SUA RESPOSTA ANTERIOR (Round {rodada_anterior}):\n{resposta_anterior}\n\n"
                "RESPOSTAS DOS OUTROS AGENTES:\n{pares}\n\n"
                "Revise sua resposta incorporando insights válidos dos outros agentes. "
                "Mantenha seus pontos corretos e corrija erros identificados. "
                "Produza uma resposta revisada e aprimorada."
            ),
        },
        {
            "id": "consensus",
            "tipo": "reduzir",
            "rotulo": "Consenso",
            "formato_bloco": "--- Agente {j} ---\n{saida}",
            "prompt": (
                "TAREFA:\n{task_content}\n\n"
                "Após {rodadas:debate} round(s) de debate entre {n:debate} agentes, "
                "estas são as respostas finais:\n\n"
                "{blocos}\n\n"
                "Produza a resposta de consenso final, representando o melhor "
                "entendimento coletivo após o debate."
            ),
            "final": True,
        },
    ],
}

HYBRID = {
    "nome": "hybrid",
    "titulo": "Hybrid MAS",
    "descricao": (
        "Hierarquia e debate combinados: o orquestrador decompõe, os workers "
        "executam, debatem entre si por p rodadas e o orquestrador sintetiza. "
        "Melhor desempenho médio no paper, e o mais caro."
    ),
    "autor": "Kim et al. (2025)",
    "estagios": [
        {
            "id": "orchestrator",
            "tipo": "unico",
            "rotulo": "Orquestrador decompõe",
            "prompt": (
                "Você é um orquestrador especialista. Decomponha a tarefa abaixo em "
                "exatamente {n:worker} subtarefas independentes e complementares.\n\n"
                "TAREFA:\n{task_content}\n\n"
                "Responda com {n:worker} subtarefas numeradas (1 a {n:worker}), "
                "uma por linha. Cada subtarefa deve ser autocontida."
            ),
        },
        {
            "id": "worker",
            "tipo": "paralelo",
            "rotulo": "Workers executam",
            "n": 3,
            "dividir": True,
            "prompt": (
                "TAREFA ORIGINAL:\n{task_content}\n\n"
                "SUA SUBTAREFA:\n{subtarefa}\n\n"
                "Execute sua subtarefa considerando o contexto da tarefa original acima."
            ),
        },
        {
            "id": "debate",
            "tipo": "debate",
            "rotulo": "Debate entre workers",
            "n": 3,
            "rodadas": 1,
            "formato_par": "--- Worker {j} (subtarefa: {subtarefa_j}) ---\n{saida}",
            "prompt": (
                "TAREFA ORIGINAL:\n{task_content}\n\n"
                "SUA SUBTAREFA:\n{subtarefa}\n\n"
                "SUA RESPOSTA ATUAL:\n{resposta_anterior}\n\n"
                "ANÁLISES DOS WORKERS PARCEIROS (Round {rodada}):\n{pares}\n\n"
                "Refine sua análise considerando os pontos válidos dos parceiros. "
                "Foque em sua subtarefa mas incorpore contexto relevante dos outros. "
                "Mantenha o formato de resposta exigido pela tarefa original."
            ),
        },
        {
            "id": "sintese",
            "tipo": "reduzir",
            "rotulo": "Orquestrador sintetiza",
            "formato_bloco": "=== Worker {j} (após {rodadas:debate} round(s) de debate) ===\n{saida}",
            "prompt": (
                "TAREFA ORIGINAL:\n{task_content}\n\n"
                "Os workers produziram as seguintes análises após debate peer-to-peer:\n\n"
                "{blocos}\n\n"
                "Sintetize em uma resposta final coesa, completa e sem redundâncias. "
                "Aproveite a complementaridade das análises. "
                "Responda diretamente, sem mencionar workers, rounds ou o processo."
            ),
            "final": True,
        },
    ],
}


PROPOSTAS_INICIAIS: dict[str, dict] = {
    "sas":           SAS,
    "independent":   INDEPENDENT,
    "centralized":   CENTRALIZED,
    "decentralized": DECENTRALIZED,
    "hybrid":        HYBRID,
}


def listar_propostas() -> list[dict]:
    """Resumos, para a interface e para semear a biblioteca."""
    from src.agents.topologia_spec import chamadas_por_instancia, validar_topologia
    saida = []
    for spec in PROPOSTAS_INICIAIS.values():
        modelo = validar_topologia(spec)
        saida.append({
            "nome": modelo.nome,
            "titulo": modelo.titulo,
            "descricao": modelo.descricao,
            "autor": modelo.autor,
            "origem": "proposta_inicial",
            "chamadas_inst": chamadas_por_instancia(modelo),
            "estagios": len(modelo.estagios),
        })
    return saida
