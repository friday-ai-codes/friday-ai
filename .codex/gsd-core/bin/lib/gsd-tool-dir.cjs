"use strict";
/**
 * Tool-owned `.gsd/` directory owner (#5757).
 *
 * gsd-core keeps small tool state under `<project>/.gsd/` (the dispatch
 * isolation sentinel, the harness fork-probe cache). A user project does not
 * inherit gsd-core's own root `.gitignore`, and the project may contain a
 * `.gsd` symlink, so every writer needs the same two guarantees before it
 * writes anything there:
 *
 *   1. the directory is a real directory that resolves inside the project
 *      (never write through a project-supplied symlink or ancestor redirect);
 *   2. the directory is ignored by git (`.gsd/.gitignore`), without clobbering
 *      rules a user already put there.
 *
 * This module is the single owner of both. Callers pass their own ignore-file
 * `marker` comment and the `rules` they need; the owner appends only the rules
 * that are missing.
 */
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.GSD_IGNORE_SYMLINK = exports.GSD_DIR_UNSAFE = void 0;
exports.ignoreAdditions = ignoreAdditions;
exports.ensureToolOwnedGsdDir = ensureToolOwnedGsdDir;
const node_crypto_1 = __importDefault(require("node:crypto"));
const node_fs_1 = __importDefault(require("node:fs"));
const node_path_1 = __importDefault(require("node:path"));
const shell_command_projection_cjs_1 = require("./shell-command-projection.cjs");
const SYMLINK_IGNORE_MESSAGE = '.gsd/.gitignore is a symlink';
/** Stable `code` values on the refusal errors; callers translate by code, never by message. */
exports.GSD_DIR_UNSAFE = 'GSD_DIR_UNSAFE';
exports.GSD_IGNORE_SYMLINK = 'GSD_IGNORE_SYMLINK';
function codedError(message, code) {
    return Object.assign(new Error(message), { code });
}
function hasLine(text, line) {
    return text.split('\n').some((l) => l.replace(/\r$/, '') === line);
}
/**
 * Pure merge: the text to append to an existing ignore file so that `marker`
 * and every rule are present, or '' when nothing is missing. A file that
 * already ignores everything (`*` line) needs nothing.
 */
function ignoreAdditions(current, { marker, rules }) {
    if (hasLine(current, '*'))
        return '';
    const missing = rules.filter((rule) => !hasLine(current, rule));
    if (missing.length === 0)
        return '';
    const lead = current === '' || current.endsWith('\n') ? '' : '\n';
    const markerLine = current.includes(marker) ? '' : `${marker}\n`;
    return `${lead}${markerLine}${missing.join('\n')}\n`;
}
function isLinkError(err) {
    const e = err;
    return !!e && (e.code === 'ELOOP' || e.message === SYMLINK_IGNORE_MESSAGE);
}
function mergeExistingIgnore(ignorePath, options) {
    let fd;
    let tmpPath = null;
    try {
        if (node_fs_1.default.lstatSync(ignorePath).isSymbolicLink())
            throw new Error(SYMLINK_IGNORE_MESSAGE);
        // Read through an fd opened without following links where supported
        // (O_NOFOLLOW is absent on Windows, hence `|| 0`), then replace by rename
        // rather than append through the path, so a link swapped in after the
        // check cannot redirect a write elsewhere.
        fd = node_fs_1.default.openSync(ignorePath, node_fs_1.default.constants.O_RDONLY | (node_fs_1.default.constants.O_NOFOLLOW || 0));
        if (!node_fs_1.default.fstatSync(fd).isFile())
            throw new Error('.gsd/.gitignore is not a regular file');
        const current = node_fs_1.default.readFileSync(fd, 'utf8');
        node_fs_1.default.closeSync(fd);
        fd = undefined;
        const additions = ignoreAdditions(current, options);
        if (additions === '')
            return;
        // `tmpPath` is assigned only once the exclusive create succeeded, so an
        // EEXIST never unlinks an entry this process did not create.
        const candidateTmp = `${ignorePath}.tmp-${process.pid}-${node_crypto_1.default.randomBytes(6).toString('hex')}`;
        const tmpFd = node_fs_1.default.openSync(candidateTmp, 'wx');
        tmpPath = candidateTmp;
        try {
            node_fs_1.default.writeFileSync(tmpFd, current + additions);
        }
        finally {
            node_fs_1.default.closeSync(tmpFd);
        }
        if (node_fs_1.default.lstatSync(ignorePath).isSymbolicLink())
            throw new Error(SYMLINK_IGNORE_MESSAGE);
        (0, shell_command_projection_cjs_1.retryRenameSync)(tmpPath, ignorePath);
        tmpPath = null;
    }
    catch (err) {
        if (isLinkError(err))
            throw codedError(SYMLINK_IGNORE_MESSAGE, exports.GSD_IGNORE_SYMLINK);
        // Ignore seeding is best-effort; the caller's state is still useful if
        // this path cannot be read or updated.
    }
    finally {
        if (fd !== undefined)
            node_fs_1.default.closeSync(fd);
        if (tmpPath) {
            try {
                node_fs_1.default.unlinkSync(tmpPath);
            }
            catch { /* best-effort cleanup */ }
        }
    }
}
/**
 * Ensure `<cwd>/.gsd` exists as a real, project-contained, git-ignored
 * directory and return its path. Throws when `.gsd` is a symlink, resolves
 * outside the project, or `.gsd/.gitignore` is a symlink.
 */
function ensureToolOwnedGsdDir(cwd, options) {
    const dir = node_path_1.default.join(cwd, '.gsd');
    node_fs_1.default.mkdirSync(dir, { recursive: true });
    if (node_fs_1.default.lstatSync(dir).isSymbolicLink() ||
        node_path_1.default.relative(node_fs_1.default.realpathSync(cwd), node_fs_1.default.realpathSync(dir)) !== '.gsd') {
        throw codedError('.gsd directory is a symlink or resolves outside the project', exports.GSD_DIR_UNSAFE);
    }
    const ignorePath = node_path_1.default.join(dir, '.gitignore');
    try {
        node_fs_1.default.writeFileSync(ignorePath, '*\n', { flag: 'wx' });
    }
    catch (err) {
        if (err.code === 'EEXIST')
            mergeExistingIgnore(ignorePath, options);
        // Any other ignore-file IO failure must not prevent the caller's write.
    }
    return dir;
}
