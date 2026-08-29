"""
datasets.py — construção dos datasets True/False em EN e PT-BR

Cada dataset retorna um DataFrame com colunas:
    statement (str), label (int), lang (str), dataset (str)

Uso:
    from src.datasets import build_all_datasets
    dfs = build_all_datasets()
    dfs["cities"].to_csv("data/raw/cities.csv", index=False)
"""

import random
import pandas as pd
from pathlib import Path

# ── Seed para reprodutibilidade ──────────────────────────────────────────────
random.seed(42)

# ── Dados brutos ─────────────────────────────────────────────────────────────

# Cidades EN (cidade → país correto)
CITIES_EN: dict[str, str] = {
    "Tokyo": "Japan", "Beijing": "China", "Mumbai": "India",
    "São Paulo": "Brazil", "Cairo": "Egypt", "Lagos": "Nigeria",
    "Mexico City": "Mexico", "Buenos Aires": "Argentina", "Dhaka": "Bangladesh",
    "Osaka": "Japan", "Karachi": "Pakistan", "Istanbul": "Turkey",
    "Kinshasa": "DR Congo", "Jakarta": "Indonesia", "London": "United Kingdom",
    "New York": "United States", "Paris": "France", "Moscow": "Russia",
    "Bangkok": "Thailand", "Lima": "Peru", "Bogotá": "Colombia",
    "Chicago": "United States", "Toronto": "Canada", "Sydney": "Australia",
    "Berlin": "Germany", "Madrid": "Spain", "Rome": "Italy",
    "Seoul": "South Korea", "Nairobi": "Kenya", "Johannesburg": "South Africa",
    "Riyadh": "Saudi Arabia", "Tehran": "Iran", "Baghdad": "Iraq",
    "Casablanca": "Morocco", "Algiers": "Algeria", "Addis Ababa": "Ethiopia",
    "Dar es Salaam": "Tanzania", "Khartoum": "Sudan", "Accra": "Ghana",
    "Abidjan": "Ivory Coast", "Santiago": "Chile", "Caracas": "Venezuela",
    "Havana": "Cuba", "Guadalajara": "Mexico", "Monterrey": "Mexico",
    "Barcelona": "Spain", "Munich": "Germany", "Vienna": "Austria",
    "Warsaw": "Poland", "Kiev": "Ukraine", "Bucharest": "Romania",
}

# Cidades PT-BR (cidade → estado)
CIDADES_BR: dict[str, str] = {
    "São Paulo": "São Paulo", "Rio de Janeiro": "Rio de Janeiro",
    "Brasília": "Distrito Federal", "Salvador": "Bahia",
    "Fortaleza": "Ceará", "Belo Horizonte": "Minas Gerais",
    "Manaus": "Amazonas", "Curitiba": "Paraná",
    "Recife": "Pernambuco", "Porto Alegre": "Rio Grande do Sul",
    "Belém": "Pará", "Goiânia": "Goiás",
    "Guarulhos": "São Paulo", "Campinas": "São Paulo",
    "São Luís": "Maranhão", "São Gonçalo": "Rio de Janeiro",
    "Maceió": "Alagoas", "Duque de Caxias": "Rio de Janeiro",
    "Natal": "Rio Grande do Norte", "Teresina": "Piauí",
    "Campo Grande": "Mato Grosso do Sul", "Nova Iguaçu": "Rio de Janeiro",
    "Santo André": "São Paulo", "João Pessoa": "Paraíba",
    "Osasco": "São Paulo", "São Bernardo do Campo": "São Paulo",
    "Jaboatão dos Guararapes": "Pernambuco", "Ribeirão Preto": "São Paulo",
    "Uberlândia": "Minas Gerais", "Contagem": "Minas Gerais",
    "Sorocaba": "São Paulo", "Aracaju": "Sergipe",
    "Feira de Santana": "Bahia", "Cuiabá": "Mato Grosso",
    "Joinville": "Santa Catarina", "Juiz de Fora": "Minas Gerais",
    "Londrina": "Paraná", "Ananindeua": "Pará",
    "Niterói": "Rio de Janeiro", "Porto Velho": "Rondônia",
    "Macapá": "Amapá", "Florianópolis": "Santa Catarina",
    "Belford Roxo": "Rio de Janeiro", "Serra": "Espírito Santo",
    "Mogi das Cruzes": "São Paulo", "Vitória": "Espírito Santo",
    "Caxias do Sul": "Rio Grande do Sul", "São João de Meriti": "Rio de Janeiro",
    "Betim": "Minas Gerais", "Carapicuíba": "São Paulo",
}

# Artigos por estado (para "fica no/na/em")
ARTIGO_ESTADO: dict[str, str] = {
    "São Paulo": "em", "Rio de Janeiro": "no", "Distrito Federal": "no",
    "Bahia": "na", "Ceará": "no", "Minas Gerais": "em",
    "Amazonas": "no", "Paraná": "no", "Pernambuco": "em",
    "Rio Grande do Sul": "no", "Pará": "no", "Goiás": "em",
    "Maranhão": "no", "Alagoas": "em", "Rio Grande do Norte": "no",
    "Piauí": "no", "Mato Grosso do Sul": "no", "Paraíba": "na",
    "Sergipe": "em", "Mato Grosso": "no", "Santa Catarina": "em",
    "Espírito Santo": "no", "Rondônia": "em", "Amapá": "no",
}

# Vocabulário EN→PT para traduções
VOCAB_EN_PT: dict[str, str] = {
    "house": "casa", "water": "água", "sun": "sol", "moon": "lua",
    "tree": "árvore", "book": "livro", "door": "porta", "window": "janela",
    "car": "carro", "dog": "cachorro", "cat": "gato", "bird": "pássaro",
    "river": "rio", "mountain": "montanha", "fire": "fogo", "stone": "pedra",
    "bread": "pão", "milk": "leite", "chair": "cadeira", "table": "mesa",
    "hand": "mão", "eye": "olho", "heart": "coração", "head": "cabeça",
    "road": "estrada", "bridge": "ponte", "cloud": "nuvem", "rain": "chuva",
    "night": "noite", "day": "dia", "week": "semana", "year": "ano",
    "child": "criança", "father": "pai", "mother": "mãe", "friend": "amigo",
    "city": "cidade", "street": "rua", "school": "escola", "hospital": "hospital",
    "food": "comida", "fish": "peixe", "flower": "flor", "garden": "jardim",
    "sea": "mar", "island": "ilha", "sand": "areia", "wind": "vento",
}


# ── Funções auxiliares ────────────────────────────────────────────────────────

def _amostrar_falso(correto: str, opcoes: list[str], n: int = 1) -> list[str]:
    """Sorteia valores falsos excluindo o valor correto."""
    falsos = [o for o in opcoes if o != correto]
    return random.sample(falsos, min(n, len(falsos)))


# ── Construtores de datasets ──────────────────────────────────────────────────

def build_cities_en() -> pd.DataFrame:
    """
    "The city of [city] is in [country]."
    1 afirmação verdadeira + 1 falsa por cidade.
    """
    paises = list(CITIES_EN.values())
    rows = []
    for cidade, pais_correto in CITIES_EN.items():
        rows.append({
            "statement": f"The city of {cidade} is in {pais_correto}.",
            "label": 1, "lang": "en", "dataset": "cities",
        })
        pais_falso = _amostrar_falso(pais_correto, paises)[0]
        rows.append({
            "statement": f"The city of {cidade} is in {pais_falso}.",
            "label": 0, "lang": "en", "dataset": "cities",
        })
    return pd.DataFrame(rows)


def build_neg_cities_en() -> pd.DataFrame:
    """
    Negações de cities: "The city of [city] is not in [country]."
    Verdadeiro = negação de uma afirmação falsa do dataset cities.
    """
    paises = list(CITIES_EN.values())
    rows = []
    for cidade, pais_correto in CITIES_EN.items():
        # "not in país_errado" → verdadeiro
        pais_falso = _amostrar_falso(pais_correto, paises)[0]
        rows.append({
            "statement": f"The city of {cidade} is not in {pais_falso}.",
            "label": 1, "lang": "en", "dataset": "neg_cities",
        })
        # "not in país_correto" → falso
        rows.append({
            "statement": f"The city of {cidade} is not in {pais_correto}.",
            "label": 0, "lang": "en", "dataset": "neg_cities",
        })
    return pd.DataFrame(rows)


def build_larger_than_en() -> pd.DataFrame:
    """
    "X is larger than Y." para X, Y em {51..99}, X ≠ Y, nenhum múltiplo de 10.
    """
    nums = [n for n in range(51, 100) if n % 10 != 0]
    num_words = {
        51: "fifty-one", 52: "fifty-two", 53: "fifty-three", 54: "fifty-four",
        55: "fifty-five", 56: "fifty-six", 57: "fifty-seven", 58: "fifty-eight",
        59: "fifty-nine", 61: "sixty-one", 62: "sixty-two", 63: "sixty-three",
        64: "sixty-four", 65: "sixty-five", 66: "sixty-six", 67: "sixty-seven",
        68: "sixty-eight", 69: "sixty-nine", 71: "seventy-one", 72: "seventy-two",
        73: "seventy-three", 74: "seventy-four", 75: "seventy-five", 76: "seventy-six",
        77: "seventy-seven", 78: "seventy-eight", 79: "seventy-nine",
        81: "eighty-one", 82: "eighty-two", 83: "eighty-three", 84: "eighty-four",
        85: "eighty-five", 86: "eighty-six", 87: "eighty-seven", 88: "eighty-eight",
        89: "eighty-nine", 91: "ninety-one", 92: "ninety-two", 93: "ninety-three",
        94: "ninety-four", 95: "ninety-five", 96: "ninety-six", 97: "ninety-seven",
        98: "ninety-eight", 99: "ninety-nine",
    }
    rows = []
    pares = [(x, y) for x in nums for y in nums if x != y]
    pares_sample = random.sample(pares, min(300, len(pares)))
    for x, y in pares_sample:
        label = 1 if x > y else 0
        rows.append({
            "statement": f"{num_words[x]} is larger than {num_words[y]}.",
            "label": label, "lang": "en", "dataset": "larger_than",
        })
    df = pd.DataFrame(rows)
    # Balancear
    n_min = min(df["label"].value_counts())
    df = pd.concat([
        df[df["label"] == 1].sample(n_min, random_state=42),
        df[df["label"] == 0].sample(n_min, random_state=42),
    ]).sample(frac=1, random_state=42).reset_index(drop=True)
    return df


def build_cidades_br() -> pd.DataFrame:
    """
    "A cidade de [cidade] fica [em/no/na] [estado]."
    1 afirmação verdadeira + 1 falsa por cidade.
    """
    estados = list(CIDADES_BR.values())
    rows = []
    for cidade, estado_correto in CIDADES_BR.items():
        artigo = ARTIGO_ESTADO.get(estado_correto, "em")
        rows.append({
            "statement": f"A cidade de {cidade} fica {artigo} {estado_correto}.",
            "label": 1, "lang": "pt", "dataset": "cidades_br",
        })
        estado_falso = _amostrar_falso(estado_correto, estados)[0]
        artigo_falso = ARTIGO_ESTADO.get(estado_falso, "em")
        rows.append({
            "statement": f"A cidade de {cidade} fica {artigo_falso} {estado_falso}.",
            "label": 0, "lang": "pt", "dataset": "cidades_br",
        })
    return pd.DataFrame(rows)


def build_neg_cidades_br() -> pd.DataFrame:
    """
    Negações de cidades_br: "A cidade de [X] não fica [em/no/na] [estado]."
    """
    estados = list(CIDADES_BR.values())
    rows = []
    for cidade, estado_correto in CIDADES_BR.items():
        estado_falso = _amostrar_falso(estado_correto, estados)[0]
        artigo_falso = ARTIGO_ESTADO.get(estado_falso, "em")
        # "não fica em estado_errado" → verdadeiro
        rows.append({
            "statement": f"A cidade de {cidade} não fica {artigo_falso} {estado_falso}.",
            "label": 1, "lang": "pt", "dataset": "neg_cidades_br",
        })
        artigo = ARTIGO_ESTADO.get(estado_correto, "em")
        # "não fica em estado_correto" → falso
        rows.append({
            "statement": f"A cidade de {cidade} não fica {artigo} {estado_correto}.",
            "label": 0, "lang": "pt", "dataset": "neg_cidades_br",
        })
    return pd.DataFrame(rows)


def build_traducoes_en_pt() -> pd.DataFrame:
    """
    "A palavra em inglês '[word]' significa '[tradução]'."
    1 verdadeiro + 1 falso por palavra.
    """
    traducoes = list(VOCAB_EN_PT.values())
    rows = []
    for palavra_en, trad_correta in VOCAB_EN_PT.items():
        rows.append({
            "statement": f"A palavra em inglês '{palavra_en}' significa '{trad_correta}'.",
            "label": 1, "lang": "pt", "dataset": "traducoes_en_pt",
        })
        trad_falsa = _amostrar_falso(trad_correta, traducoes)[0]
        rows.append({
            "statement": f"A palavra em inglês '{palavra_en}' significa '{trad_falsa}'.",
            "label": 0, "lang": "pt", "dataset": "traducoes_en_pt",
        })
    return pd.DataFrame(rows)


# ── Função principal ──────────────────────────────────────────────────────────

def build_all_datasets() -> dict[str, pd.DataFrame]:
    """Constrói e retorna todos os datasets."""
    return {
        "cities":          build_cities_en(),
        "neg_cities":      build_neg_cities_en(),
        "larger_than":     build_larger_than_en(),
        "cidades_br":      build_cidades_br(),
        "neg_cidades_br":  build_neg_cidades_br(),
        "traducoes_en_pt": build_traducoes_en_pt(),
    }


def save_all_datasets(output_dir: str = "data/raw") -> None:
    """Salva todos os datasets como CSV."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    datasets = build_all_datasets()
    for name, df in datasets.items():
        path = out / f"{name}.csv"
        df.to_csv(path, index=False)
        n_true = df["label"].sum()
        n_false = len(df) - n_true
        print(f"  {name:<22} {len(df):>4} statements  "
              f"(true={n_true}, false={n_false})  → {path}")


if __name__ == "__main__":
    print("Construindo datasets...\n")
    save_all_datasets()
    print("\nPronto.")
