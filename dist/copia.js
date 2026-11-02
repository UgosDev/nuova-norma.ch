/*
  Copia e incolla della triade (Nuova-Norma, Anorma, PPaToS) — dal canvas «Copia e incolla — menu della triade».

  1. Ctrl C: la maggior parte delle persone non apre il menu, quindi la fonte arriva anche con la copia normale.
     Negli appunti vanno due versioni: testo semplice con due righe di fonte in fondo (riferimento, data, link) per
     qualsiasi programma, e HTML con la citazione cliccabile. La copia non viene mai bloccata: se qualcosa va storto
     resta la copia del browser.
  2. Clic destro su un testo da leggere: il menu della triade al posto di quello del browser.
     Restano al browser: Maiusc + clic destro, i campi dove si scrive (correttore ortografico), i link senza
     selezione. Da tastiera: tasto Menu o Maiusc F10; frecce, Invio, Esc.

  Configurazione (nn/triade.py, copia_init):
    window.NNCopia = { prodotto, nome, sitoNN, sitoAtrium, azione: { etichetta, tipo } }
  «Porta in Atrium» (se sitoAtrium c'e): apre una questione su Atrium con il testo selezionato e la sua fonte, in una
  scheda nuova. Il testo viaggia nel frammento del link (#o=...), che non arriva a nessun server.
  Tipi di azione: "chiedi" (Anorma: riempie il messaggio a Ugo), "nota" (PPaToS: domanda per l'avvocato, POST
  a azione.url), "versioni" (Nuova-Norma: apre le versioni dell'atto, azione.url).

  Da dove viene la fonte del testo selezionato, in quest'ordine:
    - l'elemento piu vicino con data-fonte (testo) e data-fonte-url;
    - i riferimenti .cite dentro la selezione o nel blocco che la contiene (data-nn-cita, data-nn-url, href).
*/
(function () {
  'use strict';
  var C = window.NNCopia || {};
  var NOME = C.nome || 'Nuova-Norma';
  var DELTA = 'M121.85,0L0,248.78h243.7L121.85,0ZM121.85,37.81l64.88,196.29H25.71L121.85,37.81Z';
  var menu = null, toastEl = null, toastT = 0, rangeSalvato = null, modo = null, ultimoFuoco = null;

  function oggi() {
    var d = new Date();
    return d.getDate() + '.' + (d.getMonth() + 1) + '.' + d.getFullYear();
  }
  function pulisci(s) { return String(s || '').replace(/\s+/g, ' ').trim(); }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }
  function scrivibile(el) {
    for (; el && el.nodeType === 1; el = el.parentElement) {
      if (el.isContentEditable) return true;
      var t = el.tagName;
      if (t === 'TEXTAREA' || t === 'SELECT') return true;
      if (t === 'INPUT' && !/^(button|submit|reset|checkbox|radio|range|color|file|image)$/i.test(el.type)) return true;
    }
    return false;
  }
  function blocco(n) {
    var el = n && n.nodeType === 1 ? n : n && n.parentElement;
    while (el && el !== document.body) {
      if (/^(P|LI|SECTION|ARTICLE|BLOCKQUOTE|TD|DD|DIV)$/.test(el.tagName) && (el.textContent || '').length > 40) return el;
      el = el.parentElement;
    }
    return el;
  }
  function urlAssoluto(u) {
    if (!u) return '';
    try { return new URL(u, location.href).href; } catch (e) { return u; }
  }
  function senzaProtocollo(u) { return String(u || '').replace(/^https?:\/\//, ''); }

  // La fonte della selezione: [{rif, url}] senza doppioni, al massimo 3
  function fonti(range) {
    var out = [], visti = {};
    function metti(rif, url) {
      rif = pulisci(rif).replace(/^\[|\]$/g, '');
      if (!rif || visti[rif]) return;
      visti[rif] = 1;
      out.push({ rif: rif, url: urlAssoluto(url) });
    }
    if (!range) return out;
    var nodo = range.commonAncestorContainer;
    var el = nodo.nodeType === 1 ? nodo : nodo.parentElement;
    var df = el && el.closest ? el.closest('[data-fonte]') : null;
    if (df) metti(df.getAttribute('data-fonte'), df.getAttribute('data-fonte-url'));
    var dentro = [];
    try {
      var frag = range.cloneContents();
      dentro = Array.prototype.slice.call(frag.querySelectorAll('.cite,[data-nn-cita]'));
      // nel frammento i link perdono l'indirizzo assoluto: si ritrovano nel documento per testo
    } catch (e) {}
    var b = blocco(range.startContainer);
    var nelBlocco = b ? Array.prototype.slice.call(b.querySelectorAll('.cite,[data-nn-cita]')) : [];
    var scelti = dentro.length ? nelBlocco.filter(function (x) {
      return dentro.some(function (y) { return pulisci(y.textContent) === pulisci(x.textContent); });
    }) : nelBlocco;
    if (!scelti.length && dentro.length) scelti = dentro;
    scelti.forEach(function (c) {
      metti(c.getAttribute('data-nn-cita') || c.getAttribute('data-fonte') || c.textContent,
            c.getAttribute('data-nn-url') || c.getAttribute('data-fonte-url') || c.getAttribute('href') || '');
    });
    return out.slice(0, 3);
  }

  function linkAlPunto(testo) {
    var base = location.href.split('#')[0];
    var parole = pulisci(testo).split(' ');
    if (!parole[0]) return base;
    var frammento = parole.length <= 8 ? encodeURIComponent(parole.join(' '))
      : encodeURIComponent(parole.slice(0, 4).join(' ')) + ',' + encodeURIComponent(parole.slice(-4).join(' '));
    return base + '#:~:text=' + frammento.replace(/-/g, '%2D');
  }

  function versioni(testo, range) {
    var f = fonti(range);
    var piede = f.map(function (x) {
      return 'Fonte: ' + x.rif + ' · testo in vigore, letto il ' + oggi() + (x.url ? '\n' + senzaProtocollo(x.url) : '');
    });
    if (!piede.length) piede = ['Da ' + NOME + ', ' + oggi() + '\n' + senzaProtocollo(location.href.split('#')[0])];
    var semplice = testo + '\n\n' + piede.join('\n');
    var html = '<blockquote>' + esc(testo) + '</blockquote><p style="font-size:90%">' + (f.length ? f.map(function (x) {
      return 'Fonte: ' + (x.url ? '<a href="' + esc(x.url) + '">' + esc(x.rif) + '</a>' : esc(x.rif)) +
             ', testo in vigore, letto il ' + oggi();
    }).join('<br>') : 'Da <a href="' + esc(location.href.split('#')[0]) + '">' + esc(NOME) + '</a>, ' + oggi()) + '</p>';
    var ricca = JSON.stringify({ formato: 'triade-citazione/1', prodotto: C.prodotto || '', testo: testo, fonti: f,
                                 pagina: location.href.split('#')[0], letto_il: new Date().toISOString().slice(0, 10) });
    return { semplice: semplice, html: html, ricca: ricca, fonti: f };
  }

  // Ctrl C e copia dal menu: la stessa strada (evento copy), cosi il browser resta il padrone degli appunti
  document.addEventListener('copy', function (e) {
    var m = modo; modo = null;
    try {
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.rangeCount || !e.clipboardData) return;
      if (scrivibile(sel.anchorNode && (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement))) return;
      var testo = pulisci(sel.toString());
      if (!testo) return;
      if (m === 'testo') {
        e.clipboardData.setData('text/plain', testo);
      } else if (m === 'link') {
        e.clipboardData.setData('text/plain', linkAlPunto(testo));
      } else {
        var v = versioni(testo, sel.getRangeAt(0));
        e.clipboardData.setData('text/plain', v.semplice);
        e.clipboardData.setData('text/html', v.html);
        try { e.clipboardData.setData('application/x-triade-citazione+json', v.ricca); } catch (err) {}
        if (m === 'fonte') avvisa('Copiato con la fonte' + (v.fonti[0] ? ' · ' + v.fonti[0].rif : ''));
      }
      e.preventDefault();
      if (m === 'testo') avvisa('Copiato solo il testo');
      if (m === 'link') avvisa('Link a questo punto copiato');
    } catch (err) { /* resta la copia normale del browser */ }
  });

  function avvisa(testo, errore) {
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.setAttribute('role', 'status');
      toastEl.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastEl);
    }
    clearTimeout(toastT);
    toastEl.className = 'tr-toast' + (errore ? ' tr-errore' : '');
    toastEl.hidden = false;
    toastEl.innerHTML = (errore
      ? '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 3.5l8 14H3z"/><path d="M11 9v4M11 15.5v.5"/></svg>'
      : '<svg aria-hidden="true" width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="10" cy="10" r="7.5"/><path d="M6.8 10.2l2.2 2.2 4.2-4.6"/></svg>')
      + '<span>' + esc(testo) + '</span>';
    toastT = setTimeout(function () { toastEl.hidden = true; }, 2600);
  }

  function ripristina() {
    if (!rangeSalvato) return false;
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(rangeSalvato);
    return true;
  }
  function copia(m) {
    var testo = rangeSalvato ? pulisci(rangeSalvato.toString()) : '';
    chiudi(true);
    if (!testo) return;
    ripristina();
    modo = m;
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) {}
    if (!ok) {
      modo = null;
      var v = m === 'testo' ? testo : m === 'link' ? linkAlPunto(testo) : versioni(testo, rangeSalvato).semplice;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(v).then(function () { avvisa(m === 'link' ? 'Link a questo punto copiato' : 'Copiato'); },
          function () { avvisa('Il browser non mi lascia copiare: usa Ctrl C', true); });
      } else {
        avvisa('Il browser non mi lascia copiare: usa Ctrl C', true);
      }
    }
  }

  var IC = {
    fonte: '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M13 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/>',
    testo: '<path d="M4 5h12M10 5v11M7 16h6"/>',
    link: '<path d="M8.5 11.5l3-3M7.5 9L6 10.5a2.5 2.5 0 0 0 3.5 3.5L11 12.5M12.5 11L14 9.5A2.5 2.5 0 0 0 10.5 6L9 7.5"/>',
    incolla: '<rect x="5" y="4" width="10" height="13" rx="2"/><path d="M8 4V3h4v1"/>',
    cerca: '<circle cx="9" cy="9" r="5"/><path d="M13 13l4 4"/>',
    chiedi: '<path d="M4 5h12v8H9l-4 3v-3H4z"/>',
    nota: '<path d="M10 3l7 14H3z"/><path d="M10 9v3M10 14.5v.01"/>',
    versioni: '<path d="M4 6h8M4 10h12M4 14h6"/><path d="M14 13l2 2 3-4"/>',
    atrium: '<circle cx="7.5" cy="7" r="2.5"/><circle cx="13.5" cy="8" r="2"/><path d="M3 15.5c.6-2.4 2.4-3.8 4.5-3.8s3.9 1.4 4.5 3.8M12 12.2c2 0 3.6 1.1 4.2 3.3"/>'
  };
  function icona(k, accento) {
    return '<svg aria-hidden="true" width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"' +
           (accento ? ' style="color:var(--accent)"' : '') + '>' + IC[k] + '</svg>';
  }
  function voce(id, ic, etichetta, opz) {
    opz = opz || {};
    return '<button type="button" role="menuitem" class="tr-voce" data-v="' + id + '"' + (opz.off ? ' disabled' : '') + '>' +
           icona(ic, opz.accento) + '<span' + (opz.princ ? ' class="tr-princ"' : '') + '>' + esc(etichetta) + '</span>' +
           (opz.tasto ? '<span class="tr-tasto">' + esc(opz.tasto) + '</span>' : '') + '</button>';
  }

  function apri(x, y, range) {
    chiudi(false);
    rangeSalvato = range ? range.cloneRange() : null;
    var testo = rangeSalvato ? pulisci(rangeSalvato.toString()) : '';
    var vuota = !testo;
    var f = vuota ? [] : fonti(rangeSalvato);
    var n = vuota ? 0 : testo.split(' ').length;
    var az = C.azione;
    if (az && az.tipo === 'chiedi' && !document.querySelector('textarea[name="messaggio"]')) az = null;
    var h = '<div class="tr-testa">' +
      '<svg aria-hidden="true" width="16" height="16" viewBox="0 0 243.7 248.78"><path fill="currentColor" fill-rule="evenodd" d="' + DELTA + '"/></svg>' +
      '<div style="display:flex;flex-direction:column;gap:4px;min-width:0"><span class="tr-ant">' +
      (vuota ? 'Nessun testo selezionato' : '«' + esc(testo.length > 110 ? testo.slice(0, 110) + '…' : testo) + '»') + '</span>' +
      '<span class="tr-info">' + (vuota ? 'seleziona una frase per copiarla' :
        (f[0] ? esc(f[0].rif) + ' · ' : '') + (n === 1 ? '1 parola' : n + ' parole')) + '</span></div></div>' +
      voce('fonte', 'fonte', 'Copia con la fonte', { princ: true, accento: true, off: vuota, tasto: 'Ctrl C' }) +
      voce('testo', 'testo', 'Copia solo il testo', { off: vuota }) +
      voce('link', 'link', 'Copia il link a questo punto', { off: vuota }) +
      voce('incolla', 'incolla', 'Incolla', { off: true, tasto: 'qui si legge soltanto' }) +
      '<div class="tr-sep" role="separator"></div>' +
      (C.sitoNN || C.prodotto === 'nuova-norma' ? voce('cerca', 'cerca', 'Cerca in Nuova-Norma', { off: vuota }) : '') +
      (az ? voce('azione', az.tipo in IC ? az.tipo : 'nota', az.etichetta, { off: vuota }) : '') +
      (C.sitoAtrium ? voce('atrium', 'atrium', 'Porta in Atrium', { off: vuota }) : '') +
      '<p class="tr-nota">Menu del browser: Maiusc + clic destro</p>';
    menu = document.createElement('div');
    menu.className = 'tr-menu';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'Azioni sul testo selezionato');
    menu.innerHTML = h;
    document.body.appendChild(menu);
    var w = menu.offsetWidth, hh = menu.offsetHeight;
    menu.style.left = Math.max(8, Math.min(x, window.innerWidth - w - 8)) + 'px';
    menu.style.top = Math.max(8, Math.min(y + 6, window.innerHeight - hh - 8)) + 'px';
    menu.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-v]');
      if (!b || b.disabled) return;
      fai(b.getAttribute('data-v'), testo, f);
    });
    menu.addEventListener('keydown', tasti);
    menu.addEventListener('mousedown', function (e) { e.preventDefault(); });   // la selezione resta com'e
    ultimoFuoco = document.activeElement;
    var primo = menu.querySelector('button:not([disabled])');
    if (primo) primo.focus(); else menu.setAttribute('tabindex', '-1'), menu.focus();
  }

  function chiudi(rifuoca) {
    if (!menu) return;
    menu.remove();
    menu = null;
    if (rifuoca && ultimoFuoco && ultimoFuoco.focus) try { ultimoFuoco.focus({ preventScroll: true }); } catch (e) {}
  }

  function tasti(e) {
    if (e.key === 'Escape' || e.key === 'Tab') { e.preventDefault(); chiudi(true); return; }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return;
    e.preventDefault();
    var voci = Array.prototype.slice.call(menu.querySelectorAll('button:not([disabled])'));
    if (!voci.length) return;
    var i = voci.indexOf(document.activeElement);
    var j = e.key === 'Home' ? 0 : e.key === 'End' ? voci.length - 1
      : e.key === 'ArrowDown' ? (i + 1) % voci.length : (i - 1 + voci.length) % voci.length;
    voci[j].focus();
  }

  function fai(v, testo, f) {
    if (v === 'fonte' || v === 'testo' || v === 'link') return copia(v);
    chiudi(false);
    if (v === 'cerca') {
      var base = C.prodotto === 'nuova-norma' ? '' : (C.sitoNN || '');
      window.open(base + '/chiedi?' + new URLSearchParams({ domanda: testo.slice(0, 300) }).toString(), '_blank', 'noopener');
      return avvisa('Apro la ricerca in Nuova-Norma');
    }
    if (v === 'atrium') {
      var prod = ['anorma', 'nuova-norma', 'ppatos'].indexOf(C.prodotto) >= 0 ? C.prodotto : 'anorma';
      var ogg = { prodotto: prod, titolo: 'Da ' + NOME + (f[0] ? ' · ' + f[0].rif : ''), testo: testo.slice(0, 1800),
                  fonte: f[0] ? f[0].rif : '', url: f[0] && f[0].url ? f[0].url : '' };
      var b64 = btoa(unescape(encodeURIComponent(JSON.stringify(ogg)))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
      window.open(C.sitoAtrium + '/#o=' + b64, '_blank', 'noopener');
      return avvisa('Apro Atrium: prima di aprire la questione vedi che cosa porti');
    }
    var az = C.azione || {};
    if (az.tipo === 'chiedi') {
      var t = document.querySelector('textarea[name="messaggio"]');
      t.value = 'Mi spieghi meglio questo punto? «' + testo.slice(0, 600) + '»';
      t.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      t.focus();
      return avvisa('Ho preparato la domanda per Ugo: controllala e inviala');
    }
    if (az.tipo === 'nota' && az.url) {
      var dati = new URLSearchParams({ testo: testo.slice(0, 1200), fonte: f[0] ? f[0].rif : '' });
      if (az.campi) Object.keys(az.campi).forEach(function (k) { dati.set(k, az.campi[k]); });
      fetch(az.url, { method: 'POST', body: dati, headers: { 'Accept': 'application/json' } })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then(function (d) {
          avvisa(az.fatto || 'Aggiunto');
          document.dispatchEvent(new CustomEvent('triade:azione', { detail: d }));
        })
        .catch(function () { avvisa('Non sono riuscito a salvarlo: riprova tra un momento', true); });
      return;
    }
    if (az.tipo === 'versioni' && az.url) { location.href = az.url; return; }
  }

  function dentroLettura(el) {
    if (!el || scrivibile(el)) return false;
    if (el.closest && el.closest('.tr-menu,.nn-nota,.nn-bolla,[data-menu-browser]')) return false;
    return true;
  }

  document.addEventListener('contextmenu', function (e) {
    if (e.shiftKey || !dentroLettura(e.target)) return;
    var sel = window.getSelection();
    var range = sel && sel.rangeCount && !sel.isCollapsed ? sel.getRangeAt(0) : null;
    if (!range && e.target.closest && e.target.closest('a[href],img,video,audio,canvas')) return;   // menu del link
    if (range && !dentroLettura(range.commonAncestorContainer.nodeType === 1 ? range.commonAncestorContainer
                                                                              : range.commonAncestorContainer.parentElement)) return;
    e.preventDefault();
    var x = e.clientX, y = e.clientY;
    if (!x && !y && range) { var r = range.getBoundingClientRect(); x = r.left; y = r.bottom; }
    apri(x, y, range);
  });

  document.addEventListener('keydown', function (e) {
    if (menu) return;
    var tastoMenu = e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey);
    if (!tastoMenu || !dentroLettura(document.activeElement === document.body ? e.target : document.activeElement)) return;
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    e.preventDefault();
    var range = sel.getRangeAt(0), r = range.getBoundingClientRect();
    apri(r.left, r.bottom, range);
  });

  document.addEventListener('mousedown', function (e) { if (menu && !menu.contains(e.target)) chiudi(false); }, true);
  window.addEventListener('scroll', function () { chiudi(false); }, { passive: true });
  window.addEventListener('resize', function () { chiudi(false); });
  window.addEventListener('blur', function () { chiudi(false); });

  window.NNCopia = Object.assign(C, { apri: apri, avvisa: avvisa, versioni: versioni });
})();
