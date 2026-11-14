import {cp, mkdir, rm, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const destination = path.join(root, 'dist');
const raw = (process.env.USAGI_API_BASE_URL || '').replace(/\/$/, '');
if (raw) {
  const url = new URL(raw);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('USAGI_API_BASE_URL must be the server origin, without a path or credentials.');
}
await rm(destination, {recursive:true, force:true});
await mkdir(destination, {recursive:true});
for (const filename of ['index.html', 'style.css', 'script.js']) await cp(path.join(root, filename), path.join(destination, filename));
await cp(path.join(root, 'assets'), path.join(destination, 'assets'), {recursive:true});
await writeFile(path.join(destination, 'config.js'), `window.USAGI_CONFIG = ${JSON.stringify({apiBaseUrl:raw})};\n`);
console.log('Prepared dist/ with static site files and assets. No deployment was performed.');
