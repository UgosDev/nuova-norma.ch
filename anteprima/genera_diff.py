"""Anteprima pubblica di Nuova-Norma: la storia di alcuni articoli mostrata come un diff di codice.

Uso (dalla cartella nuova-norma):  py anteprima/genera_diff.py
Scrive anteprima/diff-articoli.html, una pagina unica senza dipendenze esterne.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from nn import store, web  # noqa: E402

SCELTI = [
    ("220", "art_329_b", "CO", "Quando il datore di lavoro non può ridurre le vacanze"),
    ("642.11", "art_33", "LIFD", "Interessi su debiti e altre deduzioni"),
    ("642.11", "art_24", "LIFD", "Redditi esenti dall'imposta"),
    ("312.0", "art_269", "CPP", "Sorveglianza del traffico delle telecomunicazioni: condizioni"),
]
LANG = "it"
OGGI = date.today().isoformat()


def _norm(t: str) -> str:
    return re.sub(r"[\s;,.:]+", "", t).lower()


def raccogli(con) -> list[dict]:
    out = []
    for sr, eid, sigla, descr in SCELTI:
        act = con.execute("SELECT uri, title FROM acts WHERE sr_number=?", (sr,)).fetchone()
        if not act:
            continue
        versioni, prev = [], None
        num = heading = ""
        for d in store.list_dates(con, act["uri"], LANG):
            arts = [a for a in store.load_articles(con, act["uri"], LANG, d) if a.eid == eid]
            if not arts:
                continue
            a = arts[0]
            num, heading = a.num or num, a.heading or heading
            if a.text == prev:
                continue
            versioni.append({
                "data": d,
                "testo": a.text,
                "hash": hashlib.sha256(a.text.encode("utf-8")).hexdigest()[:7],
                "redazionale": prev is not None and _norm(prev) == _norm(a.text),
                "futura": d > OGGI,
            })
            prev = a.text
        if len(versioni) < 2:
            continue
        out.append({
            "id": f"{sr}-{eid}", "sr": sr, "sigla": sigla, "num": num, "rubrica": heading, "descr": heading or descr,
            "atto": act["title"], "fedlex": act["uri"].replace("fedlex.data.admin.ch", "www.fedlex.admin.ch") + f"/{LANG}",
            "versioni": versioni,
        })
    return out


PAGE_CSS = """
main{max-width:1180px}
.intro{max-width:760px}
.scelta{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0 18px}
.scelta button{background:var(--card);color:var(--fg);border-color:var(--line);font-size:14px;padding:7px 14px}
.scelta button[aria-pressed=true]{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.grid{display:grid;grid-template-columns:300px 1fr;gap:20px;align-items:start}
@media (max-width:900px){.grid{grid-template-columns:1fr}}
.log{list-style:none;margin:0;padding:0}
.log li{border-top:1px solid var(--line)}
.log li:first-child{border-top:0}
.log button{all:unset;box-sizing:border-box;display:block;width:100%;padding:10px 12px;border-radius:12px;cursor:pointer}
.log button:hover{background:var(--soft)}
.log button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.log button[aria-current=true]{background:var(--soft);box-shadow:inset 3px 0 0 var(--accent)}
.log .h{font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;color:var(--accent)}
.log .d{font-weight:600}
.log .m{font-size:14px;color:var(--muted);line-height:1.45}
.log .st{font:12px ui-monospace,Consolas,monospace;margin-left:6px}
.st .p{color:var(--ins-fg)} .st .n{color:var(--del-fg)}
.tag.red{border-style:dashed}
.tag.fut{border-color:var(--warn);color:var(--warn)}
.tag.vig{border-color:var(--accent);color:var(--accent)}
.barra{display:none}
.barra label{font-size:14px;color:var(--muted);display:inline-flex;gap:6px;align-items:center}
.barra select{padding:6px 10px;font-size:14px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:999px;overflow:hidden;margin-left:auto}
.seg button{background:transparent;color:var(--fg);border:0;border-radius:0;font-size:13px;padding:6px 14px}
.seg button[aria-pressed=true]{background:var(--fg);color:var(--bg)}
.file{border:1px solid var(--line);border-radius:16px;overflow:hidden;background:var(--card)}
.file .testa{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:10px 14px;border-bottom:1px solid var(--line);background:var(--soft);font:13px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}
.file .testa .st{margin:0}
.codice{width:100%;border-collapse:collapse;font:13.5px/1.6 ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;table-layout:fixed}
.codice td{vertical-align:top;padding:0 10px}
.codice td.n{width:44px;text-align:right;color:var(--muted);user-select:none;opacity:.75;padding:0 8px}
.codice td.s{width:22px;user-select:none;padding:0 0 0 6px;color:var(--muted)}
.codice td.t{white-space:pre-wrap;word-break:break-word}
.codice tr.add td{background:var(--ins-bg)} .codice tr.add td.s,.codice tr.add td.t{color:var(--ins-fg)}
.codice tr.del td{background:var(--del-bg)} .codice tr.del td.s,.codice tr.del td.t{color:var(--del-fg)}
.codice tr.add ins{background:color-mix(in srgb,var(--ins-fg) 22%,transparent);color:inherit;text-decoration:none;padding:0 1px}
.codice tr.del del{background:color-mix(in srgb,var(--del-fg) 22%,transparent);color:inherit;padding:0 1px}
.codice tr.hunk td{background:var(--soft);color:var(--muted);font-size:12.5px;padding:3px 10px}
.codice.affiancato td.t{width:calc(50% - 66px)}
.codice tr.vuota td{background:repeating-linear-gradient(135deg,transparent 0 6px,var(--soft) 6px 12px)}
.codice td.sep{width:1px;padding:0;background:var(--line)}
.codice button.apri{all:unset;cursor:pointer;color:var(--accent);font:inherit;padding:2px 0}
.codice button.apri:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.confronto{display:flex;flex-direction:column;gap:10px;margin:0 0 10px}
.confronto .riga{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.confronto .lab{font-size:14px;color:var(--muted);min-width:104px}
.anni{display:flex;flex-wrap:wrap;gap:6px}
.anni button{background:var(--card);color:var(--fg);border:1px solid var(--line);font-size:13px;padding:5px 12px;display:inline-flex;gap:6px;align-items:center}
.anni button[aria-pressed=true]{background:var(--fg);color:var(--bg);border-color:var(--fg)}
.anni button.fut{border-style:dashed;border-color:var(--warn)}
.anni button.fut[aria-pressed=true]{background:var(--warn);border-color:var(--warn);color:var(--bg)}
.anni button[disabled]{opacity:.45;cursor:default}
.anni .nv{font-size:11px;line-height:1;padding:2px 5px;border-radius:99px;background:var(--soft);color:var(--muted)}
.anni button[aria-pressed=true] .nv{background:transparent;color:inherit;border:1px solid currentColor}
.confronto select{padding:6px 10px;font-size:14px}
button.link{all:unset;cursor:pointer;color:var(--accent);font-size:14px;text-decoration:underline;text-underline-offset:3px}
button.link:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.sommario{margin:0 0 12px;font-size:15px}
.log li.base{box-shadow:inset 3px 0 0 var(--line)}
.tag.rif{border-color:var(--fg);color:var(--fg)}
.nota{font-size:14px;color:var(--muted);margin:14px 2px 0}
.fonte{margin-top:28px;border-left:4px solid var(--warn)}
"""

PAGE_JS = r"""
const D = JSON.parse(document.getElementById('dati').textContent);
const $ = s => document.querySelector(s);
let cur = 0, base = 0, altra = 0, vista = 'unificato';

function tok(s){ return s.match(/\s+|[\wÀ-ÿ’']+|[^\w\s]/g) || []; }
function lcs(A,B,eq){ const n=A.length,m=B.length,T=Array.from({length:n+1},()=>new Uint16Array(m+1));
  for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)T[i][j]=eq(A[i],B[j])?T[i+1][j+1]+1:Math.max(T[i+1][j],T[i][j+1]);
  const ops=[];let i=0,j=0;while(i<n&&j<m){if(eq(A[i],B[j])){ops.push(['=',i++,j++]);}else if(T[i+1][j]>=T[i][j+1])ops.push(['-',i++,-1]);else ops.push(['+',-1,j++]);}
  while(i<n)ops.push(['-',i++,-1]);while(j<m)ops.push(['+',-1,j++]);return ops;}
const esc = s => s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function parole(o,n){ const A=tok(o),B=tok(n),ops=lcs(A,B,(x,y)=>x===y); let L='',R='';
  for(const [k,i,j] of ops){ if(k==='=') {L+=esc(A[i]);R+=esc(B[j]);} else if(k==='-') L+='<del>'+esc(A[i])+'</del>'; else R+='<ins>'+esc(B[j])+'</ins>'; }
  const pul=(x,t)=>x.replace(new RegExp('</'+t+'><'+t+'>','g'),'').replace(new RegExp('<'+t+'>(\\s+)','g'),'$1<'+t+'>').replace(new RegExp('(\\s+)</'+t+'>','g'),'</'+t+'>$1').replace(new RegExp('<'+t+'></'+t+'>','g'),'');
  return [pul(L,'del'),pul(R,'ins')]; }
function simile(o,n){ const A=tok(o).filter(t=>t.trim()),B=tok(n).filter(t=>t.trim()); if(!A.length||!B.length)return 0;
  const k=lcs(A,B,(x,y)=>x===y).filter(x=>x[0]==='=').length; return 2*k/(A.length+B.length); }

// righe del diff: {k:'='|'-'|'+', o, n, ol, nl, hl, hr}
function righe(oldT,newT){ const A=oldT.split('\n'),B=newT.split('\n'),ops=lcs(A,B,(x,y)=>x===y),out=[];
  let k=0; while(k<ops.length){ if(ops[k][0]==='='){out.push({k:'=',ol:ops[k][1]+1,nl:ops[k][2]+1,o:A[ops[k][1]],n:B[ops[k][2]]});k++;continue;}
    const dels=[],adds=[]; while(k<ops.length&&ops[k][0]!=='='){ (ops[k][0]==='-'?dels:adds).push(ops[k]); k++; }
    const pairs=Math.min(dels.length,adds.length); const bloc=[];
    for(let p=0;p<dels.length;p++){ const r={k:'-',ol:dels[p][1]+1,o:A[dels[p][1]]};
      if(p<pairs && simile(r.o,B[adds[p][2]])>0.45){ const [L,R]=parole(r.o,B[adds[p][2]]); r.hl=L; r.pair=R; r.pn=adds[p][2]+1; r.pt=B[adds[p][2]]; }
      bloc.push(r); }
    const usati=new Set(bloc.filter(r=>r.pn).map(r=>r.pn));
    for(const r of bloc) out.push(r);
    for(const r of bloc) if(r.pn) out.push({k:'+',nl:r.pn,n:r.pt,hr:r.pair});
    for(const ad of adds) if(!usati.has(ad[2]+1)) out.push({k:'+',nl:ad[2]+1,n:B[ad[2]]});
  } return out; }

function etichetta(line,ctx){ const m=line.match(/^(\d+\s?(?:bis|ter|quater)?)\s/); if(m){ctx.c=m[1].replace(/\s/,'');return 'cpv. '+ctx.c;}
  const l=line.match(/^([a-z](?:\s?(?:bis|ter|quater))?)\.\s/); if(l) return 'lett. '+l[1].replace(/\s/,'')+(ctx.c?' (cpv. '+ctx.c+')':''); return ctx.c?'cpv. '+ctx.c:'testo'; }
function messaggio(oldT,newT){ const R=righe(oldT,newT),ctxO={c:''},ctxN={c:''},agg=[],tol=[],mod=[];
  const etO=oldT.split('\n').map(l=>etichetta(l,ctxO)), etN=newT.split('\n').map(l=>etichetta(l,ctxN));
  for(const r of R){ if(r.k==='-'&&r.pn) mod.push(etN[r.pn-1]); else if(r.k==='-') tol.push(etO[r.ol-1]); else if(r.k==='+'&&!r.hr) agg.push(etN[r.nl-1]); }
  const u=a=>[...new Set(a)], p=[]; if(agg.length)p.push('aggiunto '+u(agg).join(', ')); if(mod.length)p.push('modificato '+u(mod).join(', ')); if(tol.length)p.push('tolto '+u(tol).join(', '));
  const piu=R.filter(r=>r.k==='+').length, meno=R.filter(r=>r.k==='-').length; return {testo:p.join('; ')||'nessuna differenza',piu,meno}; }

const fmt = d => { const [y,m,g]=d.split('-'); return `${+g}.${+m}.${y}`; };
function inVigore(v){ let k=0; v.forEach((x,i)=>{ if(!x.futura) k=i; }); return k; }

function reset(){ const v=D[cur].versioni; base=inVigore(v); altra=base>0?base-1:Math.min(base+1,v.length-1); aperti=new Set(); }
function scegli(i){ const v=D[cur].versioni; altra = i!==base ? i : (base>0?base-1:Math.min(base+1,v.length-1)); aperti=new Set(); disegnaVista(); }

function disegnaScelta(){ $('#scelta').innerHTML = D.map((x,i)=>`<button type="button" aria-pressed="${i===cur}" data-i="${i}">${x.sigla} ${esc(x.num.replace(/\s/g,''))}</button>`).join('');
  $('#scelta').querySelectorAll('button').forEach(b=>b.onclick=()=>{cur=+b.dataset.i; reset(); tutto();}); }

function disegnaLog(){ const x=D[cur], v=x.versioni, iv=inVigore(v);
  $('#log').innerHTML = v.map((ver,i)=>{ const msg = i===0 ? {testo:'prima versione in archivio',piu:ver.testo.split('\n').length,meno:0} : messaggio(v[i-1].testo,ver.testo);
    const tags = (i===iv?'<span class="tag vig">in vigore</span>':'')+(ver.futura?'<span class="tag fut">futura</span>':'')+(ver.redazionale?'<span class="tag red">solo redazionale</span>':'')+(i===base&&i!==iv?'<span class="tag rif">riferimento</span>':'');
    const stato = i===altra ? 'aria-current="true"' : '';
    return `<li class="${i===base?'base':''}"><button type="button" data-i="${i}" ${stato} title="${i===base?'Versione di riferimento':'Confronta con la versione di riferimento'}">
      <span class="h">${ver.hash}</span> <span class="d">${fmt(ver.data)}</span><span class="st"><span class="p">+${msg.piu}</span> <span class="n">−${msg.meno}</span></span><br>
      <span class="m">${esc(msg.testo)}</span>${tags?'<br>'+tags:''}</button></li>`; }).reverse().join('');
  $('#log').querySelectorAll('button').forEach(b=>b.onclick=()=>scegli(+b.dataset.i)); }

function disegnaConfronto(){ const v=D[cur].versioni, iv=inVigore(v);
  // un pulsante per anno: punta all'ultima versione di quell'anno diversa dalla versione di riferimento
  const anni=[]; v.forEach((x,i)=>{ const y=x.data.slice(0,4); let e=anni.find(z=>z.y===y); if(!e){e={y,idx:[]};anni.push(e);} e.idx.push(i); });
  $('#anni').innerHTML = anni.map(e=>{ const c=e.idx.filter(i=>i!==base); const t=c.length?c[c.length-1]:-1; const fut=e.idx.every(i=>v[i].futura);
    const on = e.idx.includes(altra);
    return `<button type="button" data-i="${t}" aria-pressed="${on}" ${t<0?'disabled title="Contiene solo la versione di riferimento"':''} class="${fut?'fut':''}">${e.y}${e.idx.length>1?`<span class="nv">${e.idx.length}</span>`:''}</button>`; }).join('');
  $('#anni').querySelectorAll('button:not([disabled])').forEach(b=>b.onclick=()=>scegli(+b.dataset.i));
  const et=(x,i)=>`${fmt(x.data)}${i===iv?' · in vigore':x.futura?' · futura':''}`;
  $('#altra').innerHTML = v.map((x,i)=>i===base?'':`<option value="${i}" ${i===altra?'selected':''}>${et(x,i)} · ${x.hash}</option>`).join('');
  $('#rif').innerHTML = v.map((x,i)=>`<option value="${i}" ${i===base?'selected':''}>${et(x,i)}</option>`).join('');
  $('#torna').hidden = base===iv;
}
function disegnaVista(){ disegnaLog(); disegnaConfronto(); disegnaDiff(); }

function riga(r,lato){ // lato per affiancato: 'L' o 'R'
  const t = r.k==='-' ? (r.hl ?? esc(r.o)) : r.k==='+' ? (r.hr ?? esc(r.n)) : esc(r.o);
  return t || ' '; }
let aperti=new Set();
function comprimi(R){ const C=2, out=[]; let i=0; while(i<R.length){ if(R[i].k!=='='){out.push(R[i]);i++;continue;}
    let j=i; while(j<R.length&&R[j].k==='=')j++; const run=R.slice(i,j), testa=i===0?0:C, coda=j===R.length?0:C, key=i;
    if(run.length>testa+coda+1 && !aperti.has(key)){ out.push(...run.slice(0,testa)); out.push({k:'…',n:run.length-testa-coda,key}); out.push(...run.slice(run.length-coda)); }
    else out.push(...run); i=j; } return out; }
function disegnaDiff(){ const x=D[cur], v=x.versioni, i0=Math.min(base,altra), i1=Math.max(base,altra), O=v[i0], N=v[i1], iv=inVigore(v);
  let R = i0===i1 ? righe(N.testo,N.testo) : righe(O.testo,N.testo); const msg=messaggio(O.testo,N.testo);
  if(i0!==i1) R=comprimi(R);
  const nome=i=>i===iv?'versione in vigore ('+fmt(v[i].data)+')':(i===base?'versione di riferimento ('+fmt(v[i].data)+')':'versione del '+fmt(v[i].data));
  const passi=i1-i0;
  $('#sommario').innerHTML = i0===i1 ? '' : (altra<base
    ? `Che cosa è cambiato dalla ${esc(nome(altra))} alla ${esc(nome(base))}`
    : `Che cosa ${v[altra].futura?'cambierà':'è cambiato'} dalla ${esc(nome(base))} alla ${esc(nome(altra))}`)
    + (i0===i1?'':` <span class="muted">· ${passi===1?'una modifica':passi+' modifiche successive'}: ${esc(msg.testo)}</span>`);
  $('#testa').innerHTML = `<span>RS ${x.sr} · ${esc(x.num)} · <span class="muted">${O.hash}..${N.hash}</span></span><span>${fmt(O.data)} → ${fmt(N.data)} <span class="st"><span class="p">+${i0===i1?0:msg.piu}</span> <span class="n">−${i0===i1?0:msg.meno}</span></span></span>`;
  let h='';
  if(vista==='unificato'){ h='<colgroup><col style="width:44px"><col style="width:44px"><col style="width:22px"><col></colgroup>';
    h+=`<tr class="hunk"><td colspan="4">@@ ${esc(x.sigla)} ${esc(x.num)} @@ ${esc(x.rubrica||'')}</td></tr>`;
    for(const r of R){ if(r.k==='…'){h+=`<tr class="hunk"><td colspan="4"><button type="button" class="apri" data-k="${r.key}">⋯ ${r.n} righe invariate</button></td></tr>`;continue;}
      const c=r.k==='+'?'add':r.k==='-'?'del':''; const s=r.k==='='?' ':r.k==='+'?'+':'−';
      h+=`<tr class="${c}"><td class="n">${r.k!=='+'?r.ol:''}</td><td class="n">${r.k!=='-'?r.nl:''}</td><td class="s">${s}</td><td class="t">${riga(r)}</td></tr>`; }
    $('#codice').className='codice'; }
  else { h='<colgroup><col style="width:44px"><col style="width:22px"><col><col style="width:1px"><col style="width:44px"><col style="width:22px"><col></colgroup>';
    h+=`<tr class="hunk"><td colspan="7">@@ ${esc(x.sigla)} ${esc(x.num)} @@ ${esc(x.rubrica||'')}</td></tr>`;
    const L=[],Rr=[]; let i=0; while(i<R.length){ const r=R[i]; if(r.k==='='||r.k==='…'){L.push(r);Rr.push(r);i++;continue;}
      const ds=[],as=[]; while(i<R.length&&R[i].k!=='='){(R[i].k==='-'?ds:as).push(R[i]);i++;} const n=Math.max(ds.length,as.length);
      for(let k=0;k<n;k++){L.push(ds[k]||null);Rr.push(as[k]||null);} }
    for(let k=0;k<L.length;k++){ const l=L[k], r=Rr[k];
      if(l&&l.k==='…'){h+=`<tr class="hunk"><td colspan="7"><button type="button" class="apri" data-k="${l.key}">⋯ ${l.n} righe invariate</button></td></tr>`;continue;}
      const cl=l?(l.k==='-'?'del':''):'vuota', cr=r?(r.k==='+'?'add':''):'vuota';
      const tl=l?(l.k==='-'?(l.hl??esc(l.o)):esc(l.o)):'', tr=r?(r.k==='+'?(r.hr??esc(r.n)):esc(r.n)):'';
      h+=`<tr><td class="n ${cl}">${l?l.ol:''}</td><td class="s ${cl}">${l&&l.k==='-'?'−':''}</td><td class="t ${cl}">${tl||' '}</td><td class="sep"></td>`+
         `<td class="n ${cr}">${r?r.nl:''}</td><td class="s ${cr}">${r&&r.k==='+'?'+':''}</td><td class="t ${cr}">${tr||' '}</td></tr>`; }
    $('#codice').className='codice affiancato'; }
  $('#codice').innerHTML=h;
  $('#codice').querySelectorAll('button.apri').forEach(b=>b.onclick=()=>{aperti.add(+b.dataset.k);disegnaDiff();});
  if(vista!=='unificato'){ $('#codice').querySelectorAll('td.del').forEach(t=>t.parentElement&&t.classList.add('cdel')); }
  $('#nota').textContent = N.redazionale && i1===i0+1 ? 'Questa modifica è solo redazionale: cambiano spazi o punteggiatura, non il contenuto.' : (N.futura ? 'Versione futura: già pubblicata, entra in vigore il '+fmt(N.data)+'.' : '');
  $('#titolo').textContent = `${x.sigla} ${x.num.replace(/\s/g,'')} · ${x.descr}`;
  $('#atto').innerHTML = `RS ${x.sr} · ${esc(x.atto)} · ${v.length} versioni distinte dal ${fmt(v[0].data)}`;
  $('#fedlex').href = x.fedlex;
}
function tutto(){ aperti=new Set(); disegnaScelta(); disegnaVista(); }
$('#altra').onchange=e=>scegli(+e.target.value);
$('#rif').onchange=e=>{ base=+e.target.value; if(altra===base) altra=base>0?base-1:Math.min(base+1,D[cur].versioni.length-1); aperti=new Set(); disegnaVista(); };
$('#torna').onclick=()=>{ reset(); disegnaVista(); };
document.querySelectorAll('.seg button').forEach(b=>b.onclick=()=>{vista=b.dataset.v;document.querySelectorAll('.seg button').forEach(x=>x.setAttribute('aria-pressed',x===b));disegnaDiff();});
reset(); tutto();
"""

# Nel modo affiancato le classi stanno sulle celle: stessi colori delle righe.
PAGE_CSS += """
.codice td.add{background:var(--ins-bg)} .codice td.t.add,.codice td.s.add{color:var(--ins-fg)}
.codice td.del{background:var(--del-bg)} .codice td.t.del,.codice td.s.del{color:var(--del-fg)}
.codice td.add ins{background:color-mix(in srgb,var(--ins-fg) 22%,transparent);color:inherit;text-decoration:none;padding:0 1px}
.codice td.del del{background:color-mix(in srgb,var(--del-fg) 22%,transparent);color:inherit;padding:0 1px}
.codice td.vuota{background:repeating-linear-gradient(135deg,transparent 0 6px,var(--soft) 6px 12px)}
"""


def pagina(dati: list[dict]) -> str:
    j = json.dumps(dati, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!DOCTYPE html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Come cambia una legge · Nuova-Norma</title>
<style>{web.CSS}{web.LOGO_CSS}{PAGE_CSS}</style></head>
<body><header><div class="in" style="max-width:1180px"><span class="marchio" style="display:inline-flex;align-items:center;gap:9px;font-weight:500">{web.logo_svg(18)}Nuova-Norma</span>
<span class="muted small">anteprima</span></div></header>
<main>
<div class="intro">
<p class="muted small" style="margin:0 0 6px">Storia di un articolo</p>
<h1 id="titolo"></h1>
<p class="muted small" id="atto" style="margin:0"></p>
<p style="margin:16px 0 0">Le leggi cambiano come il codice di un programma. Qui ogni versione è un passo nella cronologia: si parte dal testo in vigore oggi; scegli un anno per vedere che cosa è stato aggiunto, modificato o tolto da allora, riga per riga e parola per parola.</p>
</div>
<div class="scelta" id="scelta" role="group" aria-label="Articolo"></div>
<div class="grid">
<section aria-label="Cronologia delle versioni"><h2 style="margin:0 0 8px">Cronologia</h2><ul class="log" id="log"></ul></section>
<section aria-label="Differenze">
<div class="confronto">
<div class="riga"><span class="lab">Confronta con</span><div class="anni" id="anni" role="group" aria-label="Anno da confrontare"></div>
<select id="altra" aria-label="Data esatta della versione da confrontare"></select></div>
<div class="riga"><span class="lab">Riferimento</span><select id="rif" aria-label="Versione di riferimento"></select>
<button type="button" id="torna" class="link" hidden>torna alla versione in vigore</button>
<div class="seg" role="group" aria-label="Vista"><button type="button" data-v="unificato" aria-pressed="true">Unificata</button><button type="button" data-v="affiancato" aria-pressed="false">Affiancata</button></div></div>
</div>
<p class="sommario" id="sommario"></p>
<div class="file"><div class="testa" id="testa"></div><div class="wrap"><table class="codice" id="codice"></table></div></div>
<p class="nota" id="nota"></p>
<p class="legend"><ins>verde</ins> testo aggiunto · <del>arancione</del> testo tolto. Le date sono quelle da cui si applica il testo consolidato.</p>
</section></div>
<div class="card fonte small"><strong>Valore giuridico.</strong> Anteprima costruita dall'archivio di Nuova-Norma sui testi consolidati della Raccolta sistematica, in italiano. Il testo consolidato non è vincolante: fa fede la pubblicazione nella Raccolta ufficiale. <a id="fedlex" href="#" rel="noopener">Testo su Fedlex</a>.</div>
</main>
<script type="application/json" id="dati">{j}</script>
<script>{PAGE_JS}</script></body></html>"""


def main() -> None:
    con = store.connect(ROOT / "data" / "nuova-norma.sqlite")
    dati = raccogli(con)
    out = Path(__file__).with_name("diff-articoli.html")
    out.write_text(pagina(dati), encoding="utf-8")
    for x in dati:
        print(x["sigla"], x["num"], len(x["versioni"]), "versioni")
    print("Scritto:", out)


if __name__ == "__main__":
    main()
