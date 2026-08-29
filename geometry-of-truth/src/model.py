from transformer_lens import HookedTransformer

model = HookedTransformer.from_pretrained(
    "meta-llama/Llama-3.2-1B",
)

print("Número de camadas:", model.cfg.n_layers)
print("Tamanho do d_model:", model.cfg.d_model)
print("Número de cabeças:", model.cfg.n_heads)
print("Tamanho do vocabulário:", model.cfg.d_vocab)