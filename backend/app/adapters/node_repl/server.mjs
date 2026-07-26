// Persistent Node REPL server for AgentZoo's node_repl tool family.
//
// Why this exists: codex plugins (see ../../../codex_plugins/) bootstrap by
// importing scripts/browser-client.mjs and calling setupBrowserRuntime({
// globals: globalThis }), then reuse globalThis.agent.browsers ACROSS turns.
// A bash-style fresh-subprocess-per-call would drop that state, so we keep one
// long-lived Node process per session and evaluate snippets against a single
// shared context.
//
// Protocol: newline-delimited JSON on stdin, one JSON response per request on
// stdout. Requests:
//   {"id":"..","op":"eval","code":"..","timeout_ms":120000}
//   {"id":"..","op":"reset"}
//   {"id":"..","op":"add_module_dir","dir":".."}
// Responses:
//   {"id":"..","ok":true,"result":"..","logs":[".."]}
//   {"id":"..","ok":false,"error":".."}

import { createRequire } from "node:module";
import { inspect } from "node:util";
import readline from "node:readline";
import Module from "node:module";

const require = createRequire(import.meta.url);

// The single shared context. `agent`, imported modules, and any globals the
// plugin sets up live here and persist between eval calls.
function freshGlobals() {
  // We evaluate in this process's own globalThis so top-level `import()` and
  // require resolution behave normally. reset() clears user-set keys rather
  // than swapping realms (a true VM realm can't import ESM by absolute path
  // the way the plugins need).
  return globalThis;
}

let baseKeys = new Set(Object.keys(globalThis));

function serialize(value) {
  if (value === undefined) return "undefined";
  try {
    return JSON.stringify(value, null, 2) ?? inspect(value, { depth: 4 });
  } catch {
    return inspect(value, { depth: 4, breakLength: 120 });
  }
}

async function doEval(code, timeoutMs) {
  const logs = [];
  const origLog = console.log;
  const origErr = console.error;
  console.log = (...a) => logs.push(a.map((x) => (typeof x === "string" ? x : inspect(x))).join(" "));
  console.error = console.log;
  try {
    // Wrap in an async function so the snippet gets top-level await. The shared
    // globalThis means `const x = ...` at snippet scope does NOT persist, but
    // `globalThis.x = ...` / `agent.* = ...` does — matching the plugins, which
    // stash everything under globalThis.agent.
    const fn = new Function(
      "require",
      `return (async () => { ${code}\n })();`
    );
    const runPromise = Promise.resolve(fn(require));
    let timer;
    const timeout = new Promise((_, rej) => {
      timer = setTimeout(() => rej(new Error(`eval timed out after ${timeoutMs}ms`)), timeoutMs);
    });
    const result = await Promise.race([runPromise, timeout]);
    clearTimeout(timer);
    return { ok: true, result: serialize(result), logs };
  } catch (err) {
    return { ok: false, error: (err && err.stack) || String(err), logs };
  } finally {
    console.log = origLog;
    console.error = origErr;
  }
}

function doReset() {
  for (const k of Object.keys(globalThis)) {
    if (!baseKeys.has(k)) {
      try {
        delete globalThis[k];
      } catch {
        /* non-configurable global, leave it */
      }
    }
  }
  return { ok: true, result: "reset" };
}

function doAddModuleDir(dir) {
  // Prepend to the global module resolution paths so require()/import of bare
  // package names resolves against the plugin's node_modules.
  if (!Module.globalPaths.includes(dir)) {
    Module.globalPaths.unshift(dir);
  }
  const nodePath = process.env.NODE_PATH ? `${dir}:${process.env.NODE_PATH}` : dir;
  process.env.NODE_PATH = nodePath;
  Module._initPaths();
  return { ok: true, result: `added ${dir}` };
}

const rl = readline.createInterface({ input: process.stdin });

rl.on("line", async (line) => {
  line = line.trim();
  if (!line) return;
  let req;
  try {
    req = JSON.parse(line);
  } catch {
    process.stdout.write(JSON.stringify({ ok: false, error: "bad json request" }) + "\n");
    return;
  }
  let res;
  try {
    if (req.op === "eval") {
      res = await doEval(req.code ?? "", req.timeout_ms ?? 120000);
    } else if (req.op === "reset") {
      res = doReset();
    } else if (req.op === "add_module_dir") {
      res = doAddModuleDir(req.dir ?? "");
    } else {
      res = { ok: false, error: `unknown op: ${req.op}` };
    }
  } catch (err) {
    res = { ok: false, error: (err && err.stack) || String(err) };
  }
  res.id = req.id;
  process.stdout.write(JSON.stringify(res) + "\n");
});

rl.on("close", () => process.exit(0));
process.stdout.write(JSON.stringify({ ok: true, result: "ready", ready: true }) + "\n");
