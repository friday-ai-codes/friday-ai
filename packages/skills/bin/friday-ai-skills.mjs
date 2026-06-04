#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(__dirname, '..');
const packageJson = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8'));
function usage {
 console.log(`
Friday AI Skills
Usage:
 npx @friday-ai/skills [install] [options]
 npx @friday-ai/skills list
 npx @friday-ai/skills --version
Default install target:
 all bundled Friday AI skills -> Codex global skills dir
Examples:
 npx @friday-ai/skills
 npx @friday-ai/skills install
 npx @friday-ai/skills install --project
 npx @friday-ai/skills install --skill friday-feishu-agent
 npx @friday-ai/skills list
Options:
 --project Install into the current project instead of ~/tooling/skills
 --global, -g Install globally (default)
 --agent <name> Forward an agent target to skills CLI (default: codex)
 --skill <name> Install one skill; repeatable. Default: '*'
 --all-agents Install to every agent supported by skills CLI
 --copy Copy instead of symlink when skills CLI supports both
 --interactive Do not pass -y; let skills CLI ask selection questions
 --help, -h Show this help
 --version, -v Show package version
`);
}
function resolveSkillsCli {
 try {
 return require.resolve('skills/bin/cli.mjs');
 } catch {
 return null;
 }
}
function hasArg(args, names) {
 return args.some((arg) => names.includes(arg));
}
function hasValuedArg(args, names) {
 return args.some((arg, index) => {
 if (names.includes(arg)) return true;
 return names.some((name) => arg.startsWith(`${name}=`)) || names.includes(args[index - 1]);
 });
}
function normalizeInstallArgs(inputArgs) {
 const args =;
 let installGlobally = true;
 let interactive = false;
 let allAgents = false;
 for (let index = 0; index < inputArgs.length; index += 1) {
 const arg = inputArgs[index];
 if (arg === '--project') {
 installGlobally = false;
 continue;
 }
 if (arg === '--interactive') {
 interactive = true;
 continue;
 }
 if (arg === '--all-agents') {
 allAgents = true;
 continue;
 }
 args.push(arg);
 }
 if (installGlobally && !hasArg(args, ['--global', '-g'])) {
 args.push('-g');
 }
 if (allAgents) {
 args.push('--agent', '*');
 } else if (!hasValuedArg(args, ['--agent', '-a'])) {
 args.push('-a', 'codex');
 }
 if (!hasValuedArg(args, ['--skill', '-s']) && !hasArg(args, ['--all'])) {
 args.push('--skill', '*');
 }
 if (!interactive && !hasArg(args, ['--yes', '-y'])) {
 args.push('-y');
 }
 return args;
}
function runSkills(args) {
 const skillsCli = resolveSkillsCli;
 const command = skillsCli ? process.execPath: (process.platform === 'win32' ? 'npx.cmd': 'npx');
 const commandArgs = skillsCli ? [skillsCli, ...args]: ['-y', 'skills@^1.5.10', ...args];
 const result = spawnSync(command, commandArgs, {
 stdio: 'inherit',
 cwd: process.cwd,
 env: process.env,
 });
 if (result.error) {
 console.error(result.error.message);
 process.exit(1);
 }
 process.exit(result.status ?? 0);
}
const [rawCommand, ...rest] = process.argv.slice(2);
const command = rawCommand && !rawCommand.startsWith('-') ? rawCommand: 'install';
const passthrough = command === rawCommand ? rest: process.argv.slice(2);
if (command === 'help' || hasArg(process.argv.slice(2), ['--help', '-h'])) {
 usage;
 process.exit(0);
}
if (command === 'version' || hasArg(process.argv.slice(2), ['--version', '-v'])) {
 console.log(packageJson.version);
 process.exit(0);
}
if (command === 'list' || command === 'ls') {
 runSkills(['add', packageRoot, '--list', ...passthrough]);
}
if (command === 'install' || command === 'add') {
 runSkills(['add', packageRoot, ...normalizeInstallArgs(passthrough)]);
}
console.error(`Unknown command: ${command}`);
usage;
process.exit(1);
