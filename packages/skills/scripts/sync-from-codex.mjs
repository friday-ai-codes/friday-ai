#!/usr/bin/env node
import { cpSync, existsSync, rmSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(__dirname, '..');
const repoRoot = resolve(packageRoot, '..', '..');
const skills = ['friday-codebase-agent', 'friday-feishu-agent'];
for (const skill of skills) {
 const source = resolve(repoRoot, '.codex', 'skills', skill);
 const target = resolve(packageRoot, 'skills', skill);
 if (!existsSync(source)) {
 throw new Error(`Missing source skill: ${source}`);
 }
 rmSync(target, { recursive: true, force: true });
 cpSync(source, target, { recursive: true });
 console.log(`synced ${skill}`);
}
