"""Renderizza la distribuzione statica di Nuova-Norma.ch con il design autentico della triade."""

import os
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["NN_SITO"] = "https://nuova-norma.pagine.ch"
os.environ["ANORMA_SITO"] = "https://anorma.pagine.ch"
os.environ["PPATOS_SITO"] = "https://ppatos.pagine.ch"

from nn import cli, store, web

DIST = ROOT / "dist"
if DIST.exists():
    shutil.rmtree(DIST)
DIST.mkdir(parents=True, exist_ok=True)

con = store.connect(cli.DB)

# 1. Homepage Archivio Nuova-Norma (Design autentico triade verde)
home_html = web.home(con)
(DIST / "index.html").write_bytes(home_html)
print(f"✅ Generato dist/index.html ({len(home_html):,} bytes)")

# 2. Pagina Chiedi (ricerca guidata con menu triade)
chiedi_dir = DIST / "chiedi"
chiedi_dir.mkdir(parents=True, exist_ok=True)
chiedi_html = web.chiedi_page(con)
(chiedi_dir / "index.html").write_bytes(chiedi_html)
print(f"✅ Generato dist/chiedi/index.html ({len(chiedi_html):,} bytes)")

# 3. Risorse statiche condivise della triade (citazioni, copia, favicon, logo)
nn_static = DIST / "nn"
nn_static.mkdir(parents=True, exist_ok=True)

for name in ["citazioni.js", "copia.js", "favicon.js", "logo.css"]:
    src = ROOT / "nn" / name
    if src.exists():
        shutil.copy2(src, nn_static / name)
        shutil.copy2(src, DIST / name)

# 4. Copia configurazione pch.json
shutil.copy2(ROOT / "pch.json", DIST / "pch.json")
print("✅ Risorse e pch.json sincronizzati in dist/")
