/* Riferimenti leggibili nel testo (nuova-norma, Anorma, PPaToS).
   1 bolla al passaggio del mouse o al fuoco, 2 nota a fianco al clic, 3 articolo completo, 4 originale con ancora.
   Senza JavaScript i riferimenti restano link normali. */
(function () {
  "use strict";
  var CFG = window.NNCitazioni || {};
  var SITO = CFG.sito || "";
  var SEL = ".cite[data-nn-cita], .cite[data-nn-eid]";
  var cache = {};
  var bolla = null, nota = null, sopra = null, aperto = null, tApri = 0, tChiudi = 0, tocco = false, dati = null;
  var MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
    "ottobre", "novembre", "dicembre"];
  var LIVELLI = { articolo: "Legge", sentenza: "Giurisprudenza", legge_cantonale: "Legge cantonale",
    oggetto_parlamentare: "Parlamento", consultazione: "Consultazione", pubblicazione: "Pubblicazione",
    atto_ue: "Diritto UE", prassi: "Prassi", decisione: "Decisione", dottrina: "Dottrina", informativo: "Informativo" };
  var ICO_X = '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M5 5l10 10M15 5L5 15"/></svg>';
  var ICO_EST = '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 4H4v12h12v-4M11 4h5v5M16 4l-7 7"/></svg>';
  var ICO_OK = '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 11.5l4 4 8-9"/></svg>';
  var ICO_AVV = '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 3l8 14H2z"/><path d="M10 8v4M10 14.5v.5"/></svg>';
  var ICO_IND = '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4l-6 6 6 6"/></svg>';

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function data(d) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d || "");
    if (!m) return d || "";
    var g = parseInt(m[3], 10);
    return (g === 1 ? "1°" : g) + " " + MESI[parseInt(m[2], 10) - 1] + " " + m[1];
  }
  function sigla(c) { return (c.textContent || "").replace(/\s+/g, " ").trim(); }
  function passi(c) {
    var p = c.getAttribute("data-nn-passo") || "";
    return p ? p.split("␞").slice(0, 4).map(function (x) { return x.slice(0, 300); }) : [];
  }
  function query(c) {
    var q = [];
    ["cita", "uri", "eid", "lingua", "data", "parte", "impronta"].forEach(function (k) {
      var v = c.getAttribute("data-nn-" + k);
      if (v) q.push(k + "=" + encodeURIComponent(v));
    });
    passi(c).forEach(function (p) { q.push("passo=" + encodeURIComponent(p)); });
    return q.join("&");
  }
  /* La scheda dall'archivio; se la fonte non c'e (sentenze, prassi...) si usa quello che la pagina sa gia. */
  function carica(c) {
    var q = query(c);
    var tipo = c.getAttribute("data-nn-tipo") || "articolo";
    var ripiego = {
      tipo: tipo, ripiego: true, estratto: (passi(c)[0] || c.getAttribute("data-nn-estratto") || "").slice(0, 600),
      originale: c.getAttribute("data-nn-url") || c.getAttribute("href") || "", fonte_originale: ""
    };
    if (tipo !== "articolo" && !c.getAttribute("data-nn-eid")) return Promise.resolve(ripiego);
    if (!cache[q]) {
      cache[q] = fetch("/nn/citazione?" + q, { headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; });
    }
    return cache[q].then(function (d) { return d || ripiego; });
  }
  function livello(d) { return LIVELLI[d.tipo] || LIVELLI[d.livello] || "Fonte"; }
  function stato(d) {
    if (d.ripiego) return livello(d);
    if (d.abrogato_il || d.atto_abrogato) return livello(d) + " · non più in vigore";
    if (d.futura) return livello(d) + " · modifica decisa dal " + data(d.futura);
    return livello(d) + " · testo in vigore";
  }

  /* ---- 1 la bolla ---- */
  function mostraBolla(c) {
    clearTimeout(tChiudi);
    if (!bolla) {
      bolla = document.createElement("div");
      bolla.className = "nn-bolla";
      bolla.id = "nn-bolla";
      bolla.setAttribute("role", "tooltip");
      bolla.addEventListener("mouseenter", function () { clearTimeout(tChiudi); });
      bolla.addEventListener("mouseleave", function () { nascondiBolla(200); });
      document.body.appendChild(bolla);
    }
    sopra = c;
    carica(c).then(function (d) {
      if (sopra !== c) return;
      if (!d.estratto) { bolla.hidden = true; return; }
      bolla.innerHTML = '<div class="testa"><span class="t">' + esc(sigla(c)) + "</span>" +
        (d.rs ? '<span class="rs">RS ' + esc(d.rs) + "</span>" : "") + "</div>" +
        '<div class="es">' + esc(d.estratto) + "</div>" +
        '<div class="pie"><span>' + esc(stato(d)) + "</span><span>" + (tocco ? "" : "Clic per la frase intera") + "</span></div>";
      bolla.hidden = false;
      c.setAttribute("aria-describedby", "nn-bolla");
      posiziona(c);
    });
  }
  function posiziona(c) {
    var r = c.getBoundingClientRect(), w = bolla.offsetWidth, h = bolla.offsetHeight;
    var x = Math.max(8, Math.min(r.left, window.innerWidth - w - 8));
    var y = r.bottom + 8;
    if (y + h > window.innerHeight - 8 && r.top - h - 8 > 8) y = r.top - h - 8;
    bolla.style.left = (x + window.scrollX) + "px";
    bolla.style.top = (y + window.scrollY) + "px";
  }
  function nascondiBolla(ritardo) {
    clearTimeout(tApri);
    clearTimeout(tChiudi);
    tChiudi = setTimeout(function () {
      if (bolla) bolla.hidden = true;
      if (sopra) sopra.removeAttribute("aria-describedby");
      sopra = null;
    }, ritardo || 0);
  }

  /* ---- 2 la nota, 3 l'articolo ---- */
  function pannello() {
    if (!nota) {
      nota = document.createElement("aside");
      nota.className = "nn-nota";
      nota.id = "nn-nota";
      nota.setAttribute("aria-labelledby", "nn-nota-tit");
      nota.tabIndex = -1;
      nota.hidden = true;
      nota.addEventListener("click", azione);
      document.body.appendChild(nota);
    }
    return nota;
  }
  function apri(c) {
    nascondiBolla(0);
    if (aperto && aperto !== c) aperto.setAttribute("aria-expanded", "false");
    aperto = c;
    c.setAttribute("aria-expanded", "true");
    c.setAttribute("aria-controls", "nn-nota");
    var p = pannello();
    p.innerHTML = '<p class="nn-attesa">Apro la fonte…</p>';
    p.hidden = false;
    p.classList.remove("piena");
    document.body.classList.add("nn-con-nota");
    carica(c).then(function (d) {
      if (aperto !== c) return;
      dati = d;
      vistaNota(c, d);
    });
  }
  function chiudi() {
    if (!nota || nota.hidden) return;
    nota.hidden = true;
    document.body.classList.remove("nn-con-nota");
    if (aperto) {
      aperto.setAttribute("aria-expanded", "false");
      try { aperto.focus({ preventScroll: true }); } catch (e) { aperto.focus(); }
    }
    aperto = null;
  }
  function testa(titolo, indietro) {
    return '<div class="nn-testa">' +
      (indietro ? '<button type="button" class="nn-indietro" data-az="nota">' + ICO_IND + "Torna alla nota</button>"
        : '<h2 id="nn-nota-tit">Nota · ' + esc(titolo) + "</h2>") +
      '<button type="button" class="nn-chiudi" data-az="chiudi" aria-label="Chiudi la nota">' + ICO_X + "</button></div>";
  }
  function linkOriginale(d, testo) {
    if (!d.originale) return "";
    var nome = testo || (d.fonte_originale ? "Testo ufficiale su " + d.fonte_originale : "Apri la fonte ufficiale");
    return '<a class="nn-btn" href="' + esc(d.originale) + '" target="_blank" rel="noopener" aria-label="' +
      esc(nome) + ', si apre in una nuova scheda">' + esc(nome) + ICO_EST + "</a>";
  }
  function avvisi(d) {
    var out = [];
    if (d.vigore_dal) out.push('<li class="ok">' + ICO_OK + "<span>Testo in vigore dal " + esc(data(d.vigore_dal)) +
      (d.versione && d.versione !== d.vigore_dal ? ", versione del " + esc(data(d.versione)) + " in archivio" : "") + "</span></li>");
    if (d.diversa || d.cambiato_il) out.push('<li class="avv">' + ICO_AVV + "<span>Il testo è cambiato" +
      (d.cambiato_il ? " il " + esc(data(d.cambiato_il)) : "") + ", dopo la versione citata.</span></li>");
    if (d.futura) out.push('<li class="avv">' + ICO_AVV + "<span>Modifica già decisa per questo articolo: in vigore dal " +
      esc(data(d.futura)) + '. <a href="' + esc(SITO + "/differenze?uri=" + encodeURIComponent(d.atto) + "&lingua=" +
      encodeURIComponent(d.lingua) + "&da=" + d.versione + "&a=" + d.futura) + '">Vedi cosa cambia</a></span></li>');
    if (d.abrogato_il) out.push('<li class="avv">' + ICO_AVV + "<span>Non più in vigore dal " + esc(data(d.abrogato_il)) + ".</span></li>");
    else if (d.atto_abrogato) out.push('<li class="avv">' + ICO_AVV + "<span>La legge non è più in vigore.</span></li>");
    return out.length ? '<ul class="nn-stato">' + out.join("") + "</ul>" : "";
  }
  function citazione(d) {
    var righe = d.righe || [], out = [], ultimo = -2, scelte;
    scelte = righe.filter(function (r) { return r.citata || r.contesto; });
    if (!scelte.length) scelte = righe.slice(0, 2);
    if (scelte.length && scelte[0].n > 0) out.push('<span class="salto">[…]</span>');
    scelte.forEach(function (r) {
      if (ultimo >= 0 && r.n !== ultimo + 1) out.push('<span class="salto">[…]</span>');
      var t = (r.sigla ? r.sigla + " " : "") + r.testo;
      out.push(r.citata ? "<mark>" + esc(t) + "</mark>" : '<span class="ctx">' + esc(t) + "</span>");
      ultimo = r.n;
    });
    if (scelte.length < righe.length && ultimo < righe.length - 1) out.push('<span class="salto">[…]</span>');
    return out.join("\n");
  }
  function vistaNota(c, d) {
    var p = pannello(), h = testa(sigla(c), false);
    p.classList.remove("piena");
    if (d.ripiego) {
      h += '<p class="nn-liv">' + esc(livello(d)) + "</p>" +
        (d.estratto ? '<blockquote class="nn-cit">' + esc(d.estratto) + "</blockquote>"
          : '<p class="nn-vuoto">Questo testo non è ancora nel nostro archivio: puoi leggerlo sull’originale.</p>') +
        '<div class="nn-azioni">' + linkOriginale(d) + "</div>" +
        '<p class="nn-fede">Fa fede la pubblicazione ufficiale.</p>';
    } else {
      h += '<div class="nn-fonte"><span>' + esc(d.legge) + "</span><span>RS " + esc(d.rs) + "</span></div>" +
        (d.percorso ? '<p class="nn-percorso">' + esc(d.percorso) + "</p>" : "") +
        '<blockquote class="nn-cit">' + citazione(d) + "</blockquote>" +
        (d.parte_trovata ? "" : '<p class="nn-percorso">Il riferimento è all’intero articolo.</p>') +
        avvisi(d) +
        '<div class="nn-azioni"><button type="button" class="nn-btn pieno" data-az="articolo">Apri l’articolo completo</button>' +
        linkOriginale(d) + "</div>" +
        '<p class="nn-fede">Fa fede la pubblicazione ufficiale' + (d.eid ? " · ancora <code>#" + esc(d.eid) + "</code>" : "") + ".</p>";
    }
    p.innerHTML = h;
    var t = p.querySelector("#nn-nota-tit");
    if (t) { t.tabIndex = -1; t.focus({ preventScroll: true }); }
  }
  function vistaArticolo(d) {
    var p = pannello(), righe = (d.righe || []).map(function (r) {
      return '<p class="nn-riga l' + r.livello + (r.citata ? " citata" : "") + '"' + (r.citata ? ' aria-label="Parte citata"' : "") +
        '><span class="sg">' + esc(r.sigla) + "</span>" + esc(r.testo) + "</p>";
    }).join("");
    p.classList.add("piena");
    p.innerHTML = testa("", true) +
      '<h2 id="nn-nota-tit" class="nn-art" tabindex="-1">' + esc(d.num) + "</h2>" +
      '<p class="nn-percorso">' + esc(d.rubrica || "") + " · " + esc(d.legge) + "</p>" +
      '<div class="nn-pill">' + (d.vigore_dal ? "<span>In vigore dal " + esc(data(d.vigore_dal)) + "</span>" : "") +
      (d.versioni ? "<span>" + d.versioni + (d.versioni === 1 ? " versione" : " versioni") + " in archivio</span>" : "") +
      (d.futura ? '<span class="avv">Modifica dal ' + esc(data(d.futura)) + "</span>" : "") + "</div>" +
      '<div class="nn-testo">' + righe + "</div>" +
      '<div class="nn-azioni">' + linkOriginale(d, d.fonte_originale ? "Testo ufficiale su " + d.fonte_originale + ", all’" +
        String(d.num || "").toLowerCase() : "") +
      '<a class="nn-nn" href="' + esc(SITO + d.nn) + '">Apri in nuova-norma, con versioni e storia</a></div>';
    var prima = p.querySelector(".nn-riga.citata");
    var tit = p.querySelector("#nn-nota-tit");
    if (tit) tit.focus({ preventScroll: true });
    p.scrollTop = 0;
    if (prima) {
      var box = p.querySelector(".nn-testo");
      box.scrollTop = Math.max(0, prima.offsetTop - box.offsetTop - 12);
    }
  }
  function azione(e) {
    var b = e.target.closest("[data-az]");
    if (!b || !dati) return;
    var az = b.getAttribute("data-az");
    if (az === "chiudi") chiudi();
    else if (az === "articolo") vistaArticolo(dati);
    else if (az === "nota" && aperto) {
      vistaNota(aperto, dati);
      var x = nota.querySelector('[data-az="articolo"]');
      if (x) x.focus();
    }
  }

  /* ---- collegamento ai riferimenti della pagina ---- */
  function prepara(root) {
    (root || document).querySelectorAll(SEL).forEach(function (c) {
      if (c.classList.contains("nn-rif")) return;
      c.classList.add("nn-rif");
      if (c.title) { c.setAttribute("data-nn-titolo", c.title); c.removeAttribute("title"); }
      c.setAttribute("aria-expanded", "false");
      if (c.tagName !== "A" && c.tagName !== "BUTTON") {
        c.tabIndex = 0;
        c.setAttribute("role", "button");
      }
    });
  }
  function rif(e) { return e.target && e.target.closest ? e.target.closest(".nn-rif") : null; }
  document.addEventListener("pointerdown", function (e) { tocco = e.pointerType === "touch"; }, true);
  document.addEventListener("mouseover", function (e) {
    var c = rif(e);
    if (!c || tocco || c === sopra) return;
    clearTimeout(tApri);
    tApri = setTimeout(function () { if (aperto !== c) mostraBolla(c); }, 300);
  });
  document.addEventListener("mouseout", function (e) {
    var c = rif(e);
    if (c && !c.contains(e.relatedTarget)) { clearTimeout(tApri); nascondiBolla(200); }
  });
  document.addEventListener("focusin", function (e) {
    var c = rif(e);
    if (c && !tocco && aperto !== c) mostraBolla(c);
  });
  document.addEventListener("focusout", function (e) { if (rif(e)) nascondiBolla(100); });
  document.addEventListener("click", function (e) {
    var c = rif(e);
    if (!c) return;
    if (c.tagName === "A" && (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1)) return;
    e.preventDefault();
    apri(c);
  });
  document.addEventListener("keydown", function (e) {
    var c = rif(e);
    if (c && c.tagName !== "A" && c.tagName !== "BUTTON" && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      apri(c);
      return;
    }
    if (e.key === "Escape") {
      if (bolla && !bolla.hidden) nascondiBolla(0);
      else if (nota && !nota.hidden) chiudi();
    }
  });
  window.addEventListener("scroll", function () { if (bolla && !bolla.hidden && sopra) posiziona(sopra); }, { passive: true });
  function avvia() {
    prepara();
    if (window.MutationObserver) {
      new MutationObserver(function (m) {
        for (var i = 0; i < m.length; i++) if (m[i].addedNodes.length) { prepara(); break; }
      }).observe(document.body, { childList: true, subtree: true });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvia);
  else avvia();
  window.NNCitazioni = Object.assign(CFG, { prepara: prepara, chiudi: chiudi });
})();
