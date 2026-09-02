/**
 * config.js — configuração de runtime do frontend.
 *
 * Faz três coisas, para as 4 páginas de uma vez:
 *   1. resolve o endereço da API
 *   2. guarda as chaves do visitante (BYOK) no navegador dele
 *   3. injeta essas chaves nos headers de toda chamada à API
 *
 * MODELO BYOK: a instância publicada NÃO tem chave de API. Cada visitante usa
 * a própria, guardada apenas no localStorage do próprio navegador e enviada
 * por requisição. Nada de chave trafega para outro lugar nem é persistido no
 * servidor — por isso a plataforma pode ser pública sem gastar a cota de ninguém.
 *
 * NO DEPLOY: troque API_PADRAO pela URL pública do backend.
 * Este arquivo é servido como estático — nunca coloque segredo aqui.
 */
(function () {
  "use strict";

  var API_PADRAO = "https://overthinking-machine-production.up.railway.app";

  // ── 1. Endereço da API ────────────────────────────────────────────────────
  var param = new URLSearchParams(window.location.search).get("api");
  window.OTM_API_URL = (param || API_PADRAO).replace(/\/$/, "");

  // ── 2. Chaves do visitante ────────────────────────────────────────────────
  var STORE = "otm_api_keys";
  var PROVIDERS = [
    { id: "google",    rotulo: "Google — Gemini e Gemma", header: "X-Google-Key",
      ajuda: "aistudio.google.com/apikey", oss: true },
    { id: "moonshot",  rotulo: "Moonshot — Kimi",  header: "X-Moonshot-Key",
      ajuda: "platform.moonshot.ai", oss: true },
    { id: "zai",       rotulo: "Z.ai — GLM",       header: "X-Zai-Key",
      ajuda: "z.ai/model-api", oss: true },
    { id: "groq",      rotulo: "Groq — Llama e outros abertos", header: "X-Groq-Key",
      ajuda: "console.groq.com/keys", oss: true },
    { id: "openai",    rotulo: "OpenAI",           header: "X-OpenAI-Key",
      ajuda: "platform.openai.com/api-keys" },
    { id: "anthropic", rotulo: "Anthropic",        header: "X-Anthropic-Key",
      ajuda: "console.anthropic.com" },
  ];

  function lerChaves() {
    try { return JSON.parse(localStorage.getItem(STORE) || "{}"); }
    catch (e) { return {}; }
  }
  function salvarChaves(k) {
    try { localStorage.setItem(STORE, JSON.stringify(k)); } catch (e) {}
  }

  window.otmKeys = {
    get: lerChaves,
    set: function (id, valor) {
      var k = lerChaves();
      if (valor) { k[id] = valor; } else { delete k[id]; }
      salvarChaves(k);
    },
    limpar: function () { try { localStorage.removeItem(STORE); } catch (e) {} },
    algumaDefinida: function () { return Object.keys(lerChaves()).length > 0; },
  };

  // ── 3. Injeta as chaves nos headers das chamadas à API ────────────────────
  // Intercepta o fetch em um ponto só, em vez de alterar cada chamada nas
  // páginas — inclui as que ainda venham a ser escritas.
  var fetchOriginal = window.fetch.bind(window);
  window.fetch = function (entrada, opcoes) {
    try {
      var url = typeof entrada === "string" ? entrada : (entrada && entrada.url) || "";
      if (url.indexOf(window.OTM_API_URL) === 0) {
        opcoes = opcoes || {};
        var h = new Headers(opcoes.headers || (typeof entrada !== "string" && entrada.headers) || {});
        var chaves = lerChaves();
        PROVIDERS.forEach(function (p) {
          if (chaves[p.id]) h.set(p.header, chaves[p.id]);
        });
        opcoes.headers = h;
      }
    } catch (e) { /* nunca quebrar a chamada por causa do wrapper */ }
    return fetchOriginal(entrada, opcoes);
  };

  // ── 4. UI mínima para o visitante informar a chave ────────────────────────
  function montarUI() {
    var nav = document.querySelector("header nav");
    if (!nav || document.getElementById("otm-keys-btn")) return;

    var css = document.createElement("style");
    css.textContent = [
      "#otm-keys-btn{display:flex;align-items:center;gap:6px;background:rgba(93,63,211,.07);",
      "border:1.5px solid rgba(93,63,211,.18);border-radius:50px;padding:5px 12px;cursor:pointer;",
      "font-family:Inter,sans-serif;font-size:.72rem;font-weight:700;color:#6B6B80;transition:all .2s}",
      "#otm-keys-btn:hover{background:rgba(93,63,211,.12)}",
      "#otm-keys-btn.tem-chave{background:rgba(10,122,92,.1);border-color:#0a7a5c;color:#0a7a5c}",
      "#otm-keys-modal{position:fixed;inset:0;background:rgba(20,20,35,.55);backdrop-filter:blur(3px);",
      "display:none;align-items:center;justify-content:center;z-index:9999}",
      "#otm-keys-modal.aberto{display:flex}",
      ".otm-kx{background:#fff;border-radius:16px;padding:26px;width:min(460px,92vw);",
      "box-shadow:0 20px 60px rgba(0,0,0,.25);font-family:Inter,sans-serif}",
      ".otm-kx h3{font-family:Montserrat,sans-serif;font-size:1.05rem;color:#1F1F2E;margin-bottom:6px}",
      ".otm-kx .sub{font-size:.75rem;color:#6B6B80;line-height:1.6;margin-bottom:18px}",
      ".otm-kx label{display:block;font-size:.7rem;font-weight:600;color:#1F1F2E;margin:12px 0 5px}",
      ".otm-kx input{width:100%;border:1.5px solid #E8E8F5;border-radius:8px;padding:8px 10px;",
      "font-family:'JetBrains Mono',monospace;font-size:.7rem;outline:none}",
      ".otm-kx input:focus{border-color:#5D3FD3}",
      ".otm-kx .hint{font-size:.62rem;color:#6B6B80;margin-top:3px}",
      ".otm-kx .acoes{display:flex;gap:8px;margin-top:20px}",
      ".otm-kx button{flex:1;padding:9px;border-radius:9px;border:none;cursor:pointer;",
      "font-family:Inter,sans-serif;font-weight:700;font-size:.75rem}",
      ".otm-kx .salvar{background:#5D3FD3;color:#fff}",
      ".otm-kx .limpar{background:#fff;color:#6B6B80;border:1.5px solid #E8E8F5}",
      ".otm-kx .aviso{background:rgba(10,122,92,.07);border:1px solid rgba(10,122,92,.2);",
      "border-radius:8px;padding:9px 11px;font-size:.65rem;color:#0a7a5c;line-height:1.55;margin-top:14px}",
    ].join("");
    document.head.appendChild(css);

    var btn = document.createElement("button");
    btn.id = "otm-keys-btn";
    btn.type = "button";
    btn.innerHTML = "🔑 <span>Chaves</span>";
    btn.onclick = abrir;
    nav.insertBefore(btn, nav.firstChild);

    var modal = document.createElement("div");
    modal.id = "otm-keys-modal";
    modal.innerHTML =
      '<div class="otm-kx" onclick="event.stopPropagation()">' +
        "<h3>Suas chaves de API</h3>" +
        '<div class="sub">Esta instância não tem chave própria — cada pessoa usa a sua. ' +
        "As chaves ficam <strong>só no seu navegador</strong> e são enviadas apenas nas " +
        "chamadas que você mesmo dispara. Preencha só os provedores que for usar.</div>" +
        PROVIDERS.map(function (p) {
          return '<label>' + p.rotulo +
            (p.oss ? ' <span style="color:#0a7a5c;font-weight:700;font-size:.85em">· peso aberto</span>' : '') +
            "</label>" +
            '<input type="password" id="otm-k-' + p.id + '" placeholder="deixe vazio se não for usar">' +
            '<div class="hint">obtenha em ' + p.ajuda + "</div>";
        }).join("") +
        '<div class="aviso">Nada é enviado ao servidor da plataforma para armazenamento. ' +
        "Você paga apenas o que consumir no seu próprio provedor.</div>" +
        '<div class="acoes">' +
          '<button class="limpar" id="otm-k-limpar">Apagar</button>' +
          '<button class="salvar" id="otm-k-salvar">Salvar</button>' +
        "</div>" +
      "</div>";
    modal.onclick = fechar;
    document.body.appendChild(modal);

    document.getElementById("otm-k-salvar").onclick = function () {
      PROVIDERS.forEach(function (p) {
        window.otmKeys.set(p.id, document.getElementById("otm-k-" + p.id).value.trim());
      });
      atualizarBotao();
      fechar();
    };
    document.getElementById("otm-k-limpar").onclick = function () {
      window.otmKeys.limpar();
      PROVIDERS.forEach(function (p) { document.getElementById("otm-k-" + p.id).value = ""; });
      atualizarBotao();
    };

    atualizarBotao();
  }

  function abrir() {
    var k = lerChaves();
    PROVIDERS.forEach(function (p) {
      var el = document.getElementById("otm-k-" + p.id);
      if (el) el.value = k[p.id] || "";
    });
    document.getElementById("otm-keys-modal").classList.add("aberto");
  }
  function fechar() {
    document.getElementById("otm-keys-modal").classList.remove("aberto");
  }
  function atualizarBotao() {
    var btn = document.getElementById("otm-keys-btn");
    if (!btn) return;
    var n = Object.keys(lerChaves()).length;
    btn.classList.toggle("tem-chave", n > 0);
    btn.querySelector("span").textContent = n > 0 ? n + " chave" + (n > 1 ? "s" : "") : "Chaves";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", montarUI);
  } else {
    montarUI();
  }
})();
