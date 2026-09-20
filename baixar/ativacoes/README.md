# Hook real, na sua máquina

O módulo de ativações do site roda **simulação didática**: as ativações
são ruído gaussiano com uma curva de separabilidade desenhada à mão, e o
payload diz isso (`mode: "simulacao"`). Ler o residual stream de verdade
exige os pesos do modelo residentes — coisa que uma instância pública
compartilhada não faz.

O experimento de verdade existe e roda local:

```bash
git clone https://github.com/Carlos-Campos-39a/overthinking-machine.git
cd overthinking-machine/geometry-of-truth/experiments/sas_classifier
pip install -r requirements.txt
python experimento_multi.py
```

Ele usa TransformerLens, lê `blocks.N.hook_resid_post` e grava
`otm_results_<dataset>_<arquitetura>.json`. Importe esse arquivo na
página de ativações do site (https://overthinking-machine-chi.vercel.app/pesquisa-avancada) — o botão de
importar já entende o formato.

## Três coisas que vão te pegar

1. **Roda em CPU** (`device="cpu"` no script). Não precisa de GPU, mas
   também não é rápido.
2. **Precisa de internet**: os datasets vêm do HuggingFace em tempo de
   execução, não do repositório.
3. **O modelo padrão é *gated*** (`meta-llama/Llama-3.2-1B`): é preciso
   aceitar os termos no HuggingFace e autenticar (`huggingface-cli
   login`) antes. Para evitar isso, troque por um modelo aberto — o
   `gpt2-small` do TransformerLens roda sem autenticação nenhuma.

## O que uma probe linear mostra — e o que não mostra

Uma probe que acerta bem indica que a informação está **linearmente
legível** naquela camada. Não indica que o modelo a **usa** para decidir,
nem estabelece causalidade.

E leia sempre contra a linha de base: com poucas amostras e muitas
dimensões, uma probe pontuada no próprio treino dá ~100% até em ruído
puro. Foi o que acontecia aqui antes da validação cruzada — em ruído
gaussiano sem sinal nenhum, a probe antiga dava 1,000 nas cinco
sementes com n=30. Por isso o módulo usa 3-fold e reporta acurácia fora
da amostra.

Referência: Marks & Tegmark, *The Geometry of Truth* (arXiv:2310.06824).
