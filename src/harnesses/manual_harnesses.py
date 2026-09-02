from __future__ import annotations
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models import BaseChatModel
from src.task_base import TaskInstance
from src.harnesses.harness_base import HarnessBase, HarnessOutput
from src.llm_text import texto_da_resposta


# ------------------------------------------------------------------
# Configurações globais
# ------------------------------------------------------------------

KB_DIR     = Path("knowledge_base")   # ACE
POKEDEX_DIR = Path("pokedex")         # MCE
MAX_TOKENS  = 1000
BATCH_SIZE  = 5

SYSTEM_PROMPTS = {
    "classification": "Você é um classificador preciso. Siga estritamente o formato pedido.",
    "market_search":  "Você é um analista de mercado sênior com expertise em finanças corporativas.",
    "legal_analysis": "Você é um especialista jurídico. Baseie sua análise em fundamentos legais.",
}
DEFAULT_SYSTEM = "Você é um assistente especializado. Responda com precisão e clareza."

FORMAT_INSTRUCTIONS = {
    "single_label":  "Responda com APENAS UMA palavra ou label.",
    "long_prose":    "Responda em prosa longa e bem estruturada.",
    "bullet_points": "Responda em tópicos com bullet points.",
}


def _system(instance: TaskInstance) -> str:
    """
    System prompt da instância.

    `system_override` permite trocar o system prompt sem alterar o resto do
    pipeline — usado pelo harness de sensibilidade de prompt (módulo 4 do
    servidor), que precisa rodar a mesma tarefa com variações do prompt para
    medir a contribuição de cada cláusula por ablação.
    """
    override = instance.metadata.get("system_override")
    if override is not None:
        return override
    return SYSTEM_PROMPTS.get(instance.task_type, DEFAULT_SYSTEM)

def _fmt(instance: TaskInstance) -> str:
    base = FORMAT_INSTRUCTIONS.get(instance.response_format, "")
    valid_labels = instance.metadata.get("valid_labels")
    if valid_labels:
        base += f" Use exatamente um destes rótulos: {', '.join(valid_labels)}."
    return base

def _count_tokens(text: str) -> int:
    """Estimativa: 1 token ≈ 4 caracteres."""
    return len(text) // 4

def _trim_to_limit(text: str) -> str:
    """Remove linhas do início até caber em MAX_TOKENS."""
    if _count_tokens(text) <= MAX_TOKENS:
        return text
    lines = text.splitlines()
    while lines and _count_tokens("\n".join(lines)) > MAX_TOKENS:
        lines.pop(0)
    return "\n".join(lines)


# ------------------------------------------------------------------
# 1. Zero-shot
# ------------------------------------------------------------------

class ZeroShotHarness(HarnessBase):
    """
    Prompt direto sem exemplos.
    Baseline mais simples — lower bound esperado.
    """

    name = "zero_shot"

    def build_messages(self, instance: TaskInstance) -> HarnessOutput:
        content = f"{instance.input}\n\n{_fmt(instance)}".strip()
        return HarnessOutput(
            messages=[
                SystemMessage(content=_system(instance)),
                HumanMessage(content=content),
            ],
            metadata={"harness": self.name, "task_type": instance.task_type},
        )


# ------------------------------------------------------------------
# 2. Few-shot
# ------------------------------------------------------------------

class FewShotHarness(HarnessBase):
    """
    Injeta N exemplos estáticos de instance.metadata['examples'].
    Exemplos fixos — não aprendem com execuções anteriores.
    """

    name = "few_shot"

    def __init__(self, n_examples: int | None = None):
        self.n_examples = n_examples

    def build_messages(self, instance: TaskInstance) -> HarnessOutput:
        examples: list[dict] = instance.metadata.get("examples", [])
        if self.n_examples is not None:
            examples = examples[: self.n_examples]

        examples_block = ""
        if examples:
            examples_block = "--- EXEMPLOS ---\n"
            for i, ex in enumerate(examples, 1):
                examples_block += (
                    f"\nExemplo {i}:\n"
                    f"Entrada: {ex['input']}\n"
                    f"Resposta: {ex['output']}\n"
                )
            examples_block += "\n--- FIM DOS EXEMPLOS ---\n\n"

        content = f"{examples_block}Agora resolva:\n{instance.input}\n\n{_fmt(instance)}".strip()
        return HarnessOutput(
            messages=[
                SystemMessage(content=_system(instance)),
                HumanMessage(content=content),
            ],
            metadata={
                "harness":      self.name,
                "task_type":    instance.task_type,
                "num_examples": len(examples),
            },
        )


# ------------------------------------------------------------------
# 3. ACE — Knowledge Base (memória de exemplos reais)
# ------------------------------------------------------------------

def _kb_path(task_name: str) -> Path:
    KB_DIR.mkdir(exist_ok=True)
    return KB_DIR / f"knowledge_base_{task_name}.md"

def _read_kb(task_name: str) -> str:
    path = _kb_path(task_name)
    return path.read_text(encoding="utf-8") if path.exists() else ""

def _write_kb(task_name: str, content: str) -> None:
    _kb_path(task_name).write_text(content, encoding="utf-8")


class AceHarness(HarnessBase):
    """
    ACE — Agentic Context Engineering (Zhang et al., 2025).

    Mantém uma Knowledge Base de exemplos reais (input + output + score).
    O modelo aprende por analogia — vê o que funcionou e o que não funcionou
    em execuções anteriores e usa isso para calibrar a resposta atual.

    Arquivo: knowledge_base/knowledge_base_{task_name}.md

    Loop a cada BATCH_SIZE instâncias:
        Generator  → lê KB + monta prompt com exemplos relevantes
        llm_judge  → avalia (score + feedback) — feito pelo runner
        Curator    → atualiza KB com novos exemplos respeitando MAX_TOKENS
    """

    name = "ace"

    def __init__(self, llm: BaseChatModel, task_name: str):
        self.llm       = llm
        self.task_name = task_name
        self._buffer: list[dict] = []

    # --- Generator ---

    def build_messages(self, instance: TaskInstance) -> HarnessOutput:
        """Injeta Knowledge Base como exemplos contextuais."""
        kb = _read_kb(self.task_name)
        system  = _system(instance)
        content = self._build_content(instance, kb)
        return HarnessOutput(
            messages=[
                SystemMessage(content=system),
                HumanMessage(content=content),
            ],
            metadata={
                "harness":   self.name,
                "task_type": instance.task_type,
                "kb_tokens": _count_tokens(kb),
            },
        )

    def _build_content(self, instance: TaskInstance, kb: str) -> str:
        kb_block = ""
        if kb:
            kb_block = (
                "=== KNOWLEDGE BASE — exemplos de execuções anteriores ===\n"
                f"{kb}\n"
                "=== FIM DA KNOWLEDGE BASE ===\n\n"
                "Use esses exemplos para calibrar o formato e qualidade da sua resposta.\n\n"
            )
        return f"{kb_block}Tarefa atual:\n{instance.input}\n\n{_fmt(instance)}".strip()

    # --- Interface para o runner ---

    def record_result(
        self,
        instance: TaskInstance,
        output: str,
        score: float,
        feedback: str,
    ) -> None:
        self._buffer.append({
            "instance": instance,
            "output":   output,
            "score":    score,
            "feedback": feedback,
        })
        if len(self._buffer) >= BATCH_SIZE:
            self._update_kb()
            self._buffer = []

    def flush(self) -> None:
        if self._buffer:
            self._update_kb()
            self._buffer = []

    # --- Curator ---

    def _update_kb(self) -> None:
        """
        Curator: adiciona novos exemplos à KB.
        Mantém exemplos bons (score >= 0.7) e ruins (score < 0.4)
        para o modelo aprender dos dois.
        """
        current = _read_kb(self.task_name)

        # Formata novos exemplos do batch
        new_entries = ""
        for entry in self._buffer:
            inst  = entry["instance"]
            score = entry["score"]
            label = "✓ BOM" if score >= 0.7 else ("✗ RUIM" if score < 0.4 else "~ MÉDIO")
            problem = f"\n**Problema:** {entry['feedback']}" if score < 0.7 else ""
            new_entries += (
                f"\n### {inst.id} (score: {score:.2f}) {label}\n"
                f"**Input:** {inst.input[:300]}\n"
                f"**Output:** {entry['output'][:400]}"
                f"{problem}\n"
            )

        response = self.llm.invoke([
            SystemMessage(content=(
                "Você é um Curator de uma Knowledge Base de exemplos. "
                "Integre os novos exemplos na KB existente. "
                "Regras: preserve exemplos com scores extremos (muito bons ou muito ruins) "
                "pois são mais informativos. Remova exemplos medianos se necessário "
                "para caber no limite de tokens. "
                "Mantenha o formato markdown com ### para cada exemplo. "
                "Responda APENAS com o conteúdo atualizado, sem títulos extras."
            )),
            HumanMessage(content=(
                f"## Knowledge Base — {self.task_name}\n\n"
                f"CONTEÚDO ATUAL ({_count_tokens(current)} tokens):\n"
                f"{current if current else '(vazia)'}\n\n"
                f"NOVOS EXEMPLOS:\n{new_entries}\n\n"
                f"Retorne a KB atualizada com no máximo {MAX_TOKENS} tokens "
                f"(aprox. {MAX_TOKENS * 4} caracteres)."
            )),
        ])

        updated = _trim_to_limit(texto_da_resposta(response))
        _write_kb(self.task_name, updated)


# ------------------------------------------------------------------
# 4. MCE — Pokédex (memória de skills causais)
# ------------------------------------------------------------------

def _pokedex_path(task_name: str) -> Path:
    POKEDEX_DIR.mkdir(exist_ok=True)
    return POKEDEX_DIR / f"pokedex_{task_name}.md"

def _read_pokedex(task_name: str) -> str:
    path = _pokedex_path(task_name)
    return path.read_text(encoding="utf-8") if path.exists() else ""

def _write_pokedex(task_name: str, content: str) -> None:
    _pokedex_path(task_name).write_text(content, encoding="utf-8")


class MceHarness(HarnessBase):
    """
    MCE — Meta Context Engineering (Ye et al., 2026).

    Mantém uma Pokédex de skills causais — procedimentos que causaram
    acerto ou erro em execuções anteriores. O modelo aprende O PORQUÊ
    das respostas boas e ruins, não apenas os exemplos em si.

    Arquivo: pokedex/pokedex_{task_name}.md

    Loop a cada BATCH_SIZE instâncias:
        Generator  → lê Pokédex + monta prompt com skills relevantes
        llm_judge  → avalia (score + feedback) — feito pelo runner
        Evolver    → analisa batch, identifica causas, propõe skills
        Curator    → atualiza Pokédex respeitando MAX_TOKENS
    """

    name = "mce"

    def __init__(self, llm: BaseChatModel, task_name: str):
        self.llm       = llm
        self.task_name = task_name
        self._buffer: list[dict] = []

    # --- Generator ---

    def build_messages(self, instance: TaskInstance) -> HarnessOutput:
        """Injeta Pokédex de skills como guia de execução."""
        pokedex = _read_pokedex(self.task_name)
        system  = _system(instance)
        content = self._build_content(instance, pokedex)
        return HarnessOutput(
            messages=[
                SystemMessage(content=system),
                HumanMessage(content=content),
            ],
            metadata={
                "harness":        self.name,
                "task_type":      instance.task_type,
                "pokedex_tokens": _count_tokens(pokedex),
            },
        )

    def _build_content(self, instance: TaskInstance, pokedex: str) -> str:
        pokedex_block = ""
        if pokedex:
            pokedex_block = (
                "=== POKÉDEX — skills aprendidas de execuções anteriores ===\n"
                f"{pokedex}\n"
                "=== FIM DA POKÉDEX ===\n\n"
                "Aplique as skills relevantes ao executar sua resposta.\n\n"
            )
        return f"{pokedex_block}Tarefa atual:\n{instance.input}\n\n{_fmt(instance)}".strip()

    # --- Interface para o runner ---

    def record_result(
        self,
        instance: TaskInstance,
        output: str,
        score: float,
        feedback: str,
    ) -> None:
        self._buffer.append({
            "instance": instance,
            "output":   output,
            "score":    score,
            "feedback": feedback,
        })
        if len(self._buffer) >= BATCH_SIZE:
            self._update_pokedex()
            self._buffer = []

    def flush(self) -> None:
        if self._buffer:
            self._update_pokedex()
            self._buffer = []

    # --- Evolver ---

    def _evolve(self) -> str:
        """
        Analisa o batch e identifica causalmente quais decisões
        na resposta causaram acerto ou erro. Converte em skills nomeadas.
        """
        batch_text = ""
        for i, entry in enumerate(self._buffer, 1):
            inst  = entry["instance"]
            score = entry["score"]
            batch_text += (
                f"\n--- Instância {i} (score: {score:.2f}) ---\n"
                f"Input: {inst.input[:300]}\n"
                f"Critérios: {', '.join(inst.eval_criteria)}\n"
                f"Output: {entry['output'][:400]}\n"
                f"Feedback do juiz: {entry['feedback']}\n"
            )

        current_pokedex = _read_pokedex(self.task_name)

        response = self.llm.invoke([
            SystemMessage(content=(
                "Você é um Evolver de skills. Analise respostas de um agente "
                "e identifique CAUSALMENTE quais decisões na resposta causaram "
                "scores altos ou baixos. Converta essas causas em skills nomeadas.\n\n"
                "Uma skill tem:\n"
                "- Nome descritivo (ex: skill_wacc_analysis)\n"
                "- Trigger: quando aplicar esta skill\n"
                "- Causou acerto em: IDs das instâncias onde ajudou\n"
                "- Causou erro quando ausente em: IDs onde sua falta prejudicou\n"
                "- Procedimento: passos concretos a seguir\n\n"
                "Seja causal e específico — não proponha skills genéricas."
            )),
            HumanMessage(content=(
                f"POKÉDEX ATUAL:\n"
                f"{current_pokedex if current_pokedex else '(vazia)'}\n\n"
                f"BATCH (tarefa: {self.task_name}):\n{batch_text}\n\n"
                f"Proponha 1 a 2 skills novas ou refinamentos de skills existentes. "
                f"Formato markdown:\n\n"
                f"### skill_[nome]\n"
                f"**Trigger:** [quando usar]\n"
                f"**Causou acerto em:** [IDs ou 'nenhum ainda']\n"
                f"**Causou erro quando ausente em:** [IDs ou 'nenhum ainda']\n"
                f"**Procedimento:** [passo 1] → [passo 2] → [passo 3]"
            )),
        ])
        return texto_da_resposta(response)

    # --- Curator ---

    def _curate(self, new_skills: str) -> None:
        current = _read_pokedex(self.task_name)

        response = self.llm.invoke([
            SystemMessage(content=(
                "Você é um Curator da Pokédex de skills. "
                "Integre as novas skills na Pokédex existente. "
                "Regras: não duplique skills similares — refine a existente. "
                "Preserve skills com mais evidências (mais IDs de acerto/erro). "
                "Remova skills sem evidências se necessário para caber no limite. "
                "Mantenha o formato markdown com ### para cada skill. "
                "Responda APENAS com o conteúdo atualizado, sem títulos extras."
            )),
            HumanMessage(content=(
                f"## Pokédex — {self.task_name}\n\n"
                f"CONTEÚDO ATUAL ({_count_tokens(current)} tokens):\n"
                f"{current if current else '(vazia)'}\n\n"
                f"NOVAS SKILLS:\n{new_skills}\n\n"
                f"Retorne a Pokédex atualizada com no máximo {MAX_TOKENS} tokens "
                f"(aprox. {MAX_TOKENS * 4} caracteres)."
            )),
        ])

        updated = _trim_to_limit(texto_da_resposta(response))
        _write_pokedex(self.task_name, updated)

    def _update_pokedex(self) -> None:
        new_skills = self._evolve()
        if new_skills:
            self._curate(new_skills)


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

HARNESSES: dict[str, type[HarnessBase]] = {
    "zero_shot": ZeroShotHarness,
    "few_shot":  FewShotHarness,
    "ace":       AceHarness,
    "mce":       MceHarness,
}


def get_harness(name: str, **kwargs) -> HarnessBase:
    """
    Retorna instância do harness pelo nome.

    ACE e MCE requerem llm e task_name:
        get_harness("ace", llm=llm, task_name="finance_agent")
        get_harness("mce", llm=llm, task_name="finance_agent")

    meta_harness é tratado pelo runner, não aqui.
    """
    if name == "meta_harness":
        raise ValueError(
            "Harness 'meta_harness' é gerenciado pelo runner. "
            "Use harness: meta_harness no config.yaml."
        )
    if name not in HARNESSES:
        available = list(HARNESSES.keys()) + ["meta_harness"]
        raise KeyError(
            f"Harness '{name}' não encontrado. Disponíveis: {available}"
        )
    return HARNESSES[name](**kwargs)