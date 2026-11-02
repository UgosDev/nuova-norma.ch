import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

async function deploy() {
  const pchPath = path.join(rootDir, 'pch.json');
  const pch = fs.existsSync(pchPath)
    ? JSON.parse(fs.readFileSync(pchPath, 'utf8'))
    : {
        projectId: 'nuova-norma',
        name: 'Nuova-Norma.ch — Archivio e Motore Giuridico Svizzero',
        framework: 'html',
        outputDir: 'dist',
      };

  console.log(`🇨🇭 Avvio build per progetto ${pch.name}...`);
  execSync('node scripts/build-dist.mjs', { cwd: rootDir, stdio: 'inherit' });

  const outputDir = path.join(rootDir, pch.outputDir || 'dist');
  if (!fs.existsSync(outputDir)) {
    throw new Error(`Directory output ${outputDir} non trovata.`);
  }

  const zipPath = path.join(rootDir, 'temp-deploy.zip');
  if (fs.existsSync(zipPath)) {
    fs.unlinkSync(zipPath);
  }

  console.log(`📦 Compressione bundle statico da ${pch.outputDir}...`);
  if (process.platform === 'win32') {
    execSync(
      `powershell -NoProfile -Command "Compress-Archive -Path '${outputDir}\\*' -DestinationPath '${zipPath}' -Force"`,
      { stdio: 'inherit' }
    );
  } else {
    execSync(`cd "${outputDir}" && zip -r "${zipPath}" ./*`, { stdio: 'inherit' });
  }

  const stat = fs.statSync(zipPath);
  console.log(`📦 Archivio pronto: ${(stat.size / 1024).toFixed(2)} KB`);

  console.log('🚀 Invio bundle all\'infrastruttura sovrana pagine.ch (83.228.228.33 dc4-a Ginevra)...');
  const fileBuffer = fs.readFileSync(zipPath);
  const blob = new Blob([fileBuffer], { type: 'application/zip' });
  const fd = new FormData();
  fd.append('projectId', pch.projectId);
  fd.append('name', pch.name);
  fd.append('framework', pch.framework || 'html');
  fd.append('deployedBy', 'UnHub');
  fd.append('bundle', blob, `${pch.projectId}.zip`);

  const res = await fetch('https://pagine.ch/api/deploy', {
    method: 'POST',
    body: fd,
  });

  if (fs.existsSync(zipPath)) {
    try {
      fs.unlinkSync(zipPath);
    } catch {}
  }

  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`Deploy su pagine.ch fallito (${res.status}): ${errorText}`);
  }

  const data = await res.json();
  console.log('========================================================');
  console.log('✅ DEPLOY SU PAGINE.CH COMPLETATO CON SUCCESSO!');
  console.log(`🔗 URL Primario:   ${data.primaryUrl}`);
  console.log(`🆔 Deployment ID:  ${data.deploymentId}`);
  console.log(`📄 File caricati:  ${data.filesCount}`);
  console.log(`📊 Dimensione:     ${((data.sizeBytes || 0) / 1024).toFixed(1)} KB`);
  if (data.aliasUrls && data.aliasUrls.length > 0) {
    console.log(`🌐 Alias attivi:   ${data.aliasUrls.join(', ')}`);
  }
  console.log('========================================================');
  return data;
}

deploy().catch((err) => {
  console.error('❌ Errore durante il deploy:', err.message);
  process.exit(1);
});
