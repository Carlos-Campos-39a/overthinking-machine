"""
propostas_operacionais.py — topologias propostas para a triagem de cobrança.

As cinco de Kim et al. são genéricas: decompor, debater, agregar. Estas três
foram desenhadas contra o modo de falha ESPECÍFICO desta tarefa — errar a
PRECEDÊNCIA da política, aplicando a regra mais chamativa em vez da primeira
que casa.

É esse o teste real da plataforma: ela deixa alguém propor uma topologia com
uma hipótese própria sobre por que a tarefa é difícil, e medir se a hipótese se
sustenta? Cada uma abaixo carrega uma hipótese explícita e falsificável.
"""
from __future__ import annotations


# ─────────────────────────────────────────────────────────────────────────────
# HIPÓTESE 1 — o erro é de revisão, não de conhecimento.
#
# O modelo sabe a política; escorrega ao aplicar. Um segundo par de olhos que
# só confere a precedência deveria pegar isso. Custa 2× o SAS — se ganhar
# menos que isso em acerto, não compensa.
# ─────────────────────────────────────────────────────────────────────────────

VERIFICADOR = {
    "tipo": "topologia",
    "nome": "verificador-precedencia",
    "titulo": "Decisão + verificação de precedência",
    "descricao": (
        "Um agente decide; um segundo confere se alguma regra ANTERIOR à "
        "escolhida também casava. Ataca o erro de precedência sem refazer a "
        "análise. Custo: 2 chamadas por caso."
    ),
    "autor": "proposta operacional",
    "estagios": [
        {
            "id": "decisor",
            "tipo": "unico",
            "rotulo": "Decide",
            "entrada_bruta": True,
        },
        {
            "id": "revisor",
            "tipo": "unico",
            "rotulo": "Confere a precedência",
            "prompt": (
                "{task_content}\n\n"
                "Um analista respondeu: {resposta_anterior}\n\n"
                "Confira SÓ a precedência: existe alguma regra ANTERIOR à que ele "
                "usou que também casa com este caso? Percorra da regra 1 em diante "
                "e pare na primeira que casar.\n\n"
                "Responda apenas com o rótulo correto."
            ),
            "final": True,
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# HIPÓTESE 2 — separar "quais regras casam" de "qual vale".
#
# Errar precedência é fazer duas coisas ao mesmo tempo: avaliar as condições e
# ordenar. Separar em dois passos deveria reduzir o erro. Mesmo custo do
# verificador — a comparação entre os dois isola QUAL intervenção funciona.
# ─────────────────────────────────────────────────────────────────────────────

CASCATA = {
    "tipo": "topologia",
    "nome": "cascata-de-regras",
    "titulo": "Levantar regras, depois ordenar",
    "descricao": (
        "O primeiro agente só LISTA as regras que casam, sem decidir. O segundo "
        "só escolhe a de menor número. Separa avaliação de ordenação. "
        "Custo: 2 chamadas por caso."
    ),
    "autor": "proposta operacional",
    "estagios": [
        {
            "id": "levantamento",
            "tipo": "unico",
            "rotulo": "Quais regras casam",
            "prompt": (
                "{task_content}\n\n"
                "NÃO decida ainda. Liste APENAS os números das regras cujas condições "
                "este caso satisfaz, em ordem crescente, separados por vírgula. "
                "Confira uma por uma, da 1 à 7. Não justifique."
            ),
        },
        {
            "id": "ordenador",
            "tipo": "unico",
            "rotulo": "A primeira vale",
            "prompt": (
                "{task_content}\n\n"
                "As regras que casam com este caso são: {resposta_anterior}\n\n"
                "A política manda valer a PRIMEIRA — a de menor número. "
                "Responda apenas com o rótulo correspondente a ela."
            ),
            "final": True,
        },
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# HIPÓTESE 3 — o erro é aleatório, e votar resolve.
#
# Se os erros forem independentes entre execuções, três decisões e um voto
# corrigem. Se forem sistemáticos — o modelo erra SEMPRE o mesmo caso do mesmo
# jeito —, votar não corrige nada e só triplica a conta. Esta é a hipótese que
# eu mais espero ver falhar, e é por isso que vale medir: é o desenho que a
# intuição mais recomenda.
# ─────────────────────────────────────────────────────────────────────────────

VOTACAO = {
    "tipo": "topologia",
    "nome": "voto-triplo",
    "titulo": "Três decisões independentes + voto",
    "descricao": (
        "Três agentes decidem sem se ver; um quarto reporta o rótulo majoritário. "
        "Só ajuda se os erros forem aleatórios. Custo: 4 chamadas por caso."
    ),
    "autor": "proposta operacional",
    "estagios": [
        {
            "id": "analista",
            "tipo": "paralelo",
            "rotulo": "Três decisões",
            "n": 3,
            "entrada_bruta": True,
        },
        {
            "id": "apurador",
            "tipo": "reduzir",
            "rotulo": "Voto majoritário",
            "formato_bloco": "Analista {j}: {saida}",
            "prompt": (
                "Três analistas classificaram o mesmo caso:\n\n{blocos}\n\n"
                "Responda apenas com o rótulo que apareceu mais vezes. "
                "Em caso de empate, escolha o do primeiro analista."
            ),
            "final": True,
        },
    ],
}


PROPOSTAS_OPERACIONAIS = {
    "verificador-precedencia": VERIFICADOR,
    "cascata-de-regras": CASCATA,
    "voto-triplo": VOTACAO,
}
