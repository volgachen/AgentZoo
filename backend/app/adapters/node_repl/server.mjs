// Persistent Node REPL server for Augentia's node_repl tool family.
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
import path from "node:path";

const require = createRequire(import.meta.url);

// stdout is the protocol channel, so nothing else may write to it. Plugins do:
// codex's chrome bundle keeps retrying Statsig telemetry and prints warnings
// ASYNCHRONOUSLY, i.e. after the eval that started them already replied. Those
// stray lines would be read as the *next* request's response and desync the
// protocol permanently. So: capture the real writer for protocol frames, and
// redirect every other write into the current eval's log buffer (or drop it
// once no eval is in flight).
const _protocolWrite = process.stdout.write.bind(process.stdout);
let _sink = null; // string[] while an eval is running

function _capture(chunk, enc, cb) {
  const text = typeof chunk === "string" ? chunk : Buffer.from(chunk).toString("utf8");
  if (_sink) {
    for (const l of text.split("\n")) if (l) _sink.push(l);
  }
  if (typeof enc === "function") enc();
  else if (typeof cb === "function") cb();
  return true;
}
process.stdout.write = _capture;
process.stderr.write = _capture;

function reply(res) {
  _protocolWrite(JSON.stringify(res) + "\n");
}

// Lines pushed here reach the current eval's tool result. Used by the codex host
// shim (nodeRepl.write / emitContentItem), which is how the plugins hand their
// documentation back to the model.
function emit(text) {
  if (_sink) for (const l of String(text).split("\n")) _sink.push(l);
}

// The single shared context. `agent`, imported modules, and any globals the
// plugin sets up live here and persist between eval calls.
function freshGlobals() {
  // We evaluate in this process's own globalThis so top-level `import()` and
  // require resolution behave normally. reset() clears user-set keys rather
  // than swapping realms (a true VM realm can't import ESM by absolute path
  // the way the plugins need).
  return globalThis;
}

// Install the codex plugin host interface BEFORE snapshotting baseKeys, so that
// node_repl_reset treats `nodeRepl` as part of the base environment and does not
// delete it (the plugins can't bootstrap without it).
const { installNodeReplHost } = await import("./host_shim.mjs");
installNodeReplHost({ sessionId: process.env.AUGENTIA_SESSION_ID, emit });

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
  // Anything the snippet (or a plugin's background retry loop) writes straight
  // to stdout/stderr lands here instead of corrupting the protocol stream.
  _sink = logs;
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
    _sink = null;
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
  // Normalize: the plugin docs hand out forward-slash paths even on Windows.
  dir = path.resolve(dir);
  if (!Module.globalPaths.includes(dir)) {
    Module.globalPaths.unshift(dir);
  }
  // path.delimiter, not ":" — on Windows the separator is ";" and a hardcoded
  // ":" would also split "C:/..." apart on the second call.
  const sep = path.delimiter;
  const existing = (process.env.NODE_PATH || "").split(sep).filter(Boolean);
  process.env.NODE_PATH = [dir, ...existing.filter((p) => p !== dir)].join(sep);
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
    reply({ ok: false, error: "bad json request" });
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
  reply(res);
});

rl.on("close", () => process.exit(0));
// Plugin teardown (Statsig flush, playwright) can throw after we already
// answered; dying here would kill a session that is otherwise fine.
process.on("unhandledRejection", (e) => {
  if (_sink) _sink.push(`[unhandledRejection] ${e && e.message ? e.message : String(e)}`);
});
process.on("uncaughtException", (e) => {
  if (_sink) _sink.push(`[uncaughtException] ${e && e.message ? e.message : String(e)}`);
});
reply({ ok: true, result: "ready", ready: true });
