// globalThis.nodeRepl — the host interface codex plugins require.
//
// Why this lives in the server rather than in agent-authored JS: the plugins'
// only requirement on their host is this object (codex's own node_repl.exe
// injects it; a plain node.exe does not). Making the agent paste a 50-line shim
// before every bootstrap is both fragile and wasted tokens, and its SKILL.md
// explicitly assumes `nodeRepl` already exists (it calls `nodeRepl.write(...)`
// for documentation). So we install it at process start.
//
// See docs/codex_chrome/host-interface.md for the field-by-field rationale.

import net from "node:net";
import os from "node:os";
import crypto from "node:crypto";

export function installNodeReplHost({ sessionId, emit }) {
  if (globalThis.nodeRepl != null) return globalThis.nodeRepl;

  // Tab ownership is scoped by session_id: it MUST stay stable across turns or
  // tabs.list() comes back empty every time. Augentia's session id is the
  // natural key, so the REPL process and the plugin agree on scope.
  const sid = sessionId || crypto.randomUUID();

  globalThis.nodeRepl = {
    env: process.env,
    cwd: process.cwd(),
    tmpDir: os.tmpdir(),

    // The plugin's ve() only checks `config != null`; these stubs pass the gate
    // at the cost of the plugin seeing "no policy" — its domain allow/deny lists
    // and remembered approvals all go through empty branches, so every sensitive
    // action falls through to createElicitation. See pitfalls.md #2.
    config: {
      read: async () => ({}),
      readRequirements: async () => ({}),
      readToml: async () => ({}),
      writeToml: async () => {},
    },

    // Without this the plugin refuses with "Missing required Codex turn metadata".
    requestMeta: {
      "x-codex-turn-metadata": {
        session_id: sid,
        turn_id: crypto.randomUUID(),
        thread_id: sid,
        thread_source: "main",
      },
    },

    addAfterSubmittedCodeHook: () => {},
    setResponseMeta: () => {},
    emitContentItem: (item) => emit(typeof item === "string" ? item : JSON.stringify(item)),
    emitImage: () => emit("[image omitted]"),

    // SKILL.md drives documentation reads through this, so it must land in the
    // tool result the model sees, not in a dropped stdout write.
    write: (text) => emit(typeof text === "string" ? text : String(text)),

    // Human confirmation for navigation / form submit / uploads / history reads.
    // AUGENTIA_BROWSER_ELICIT=deny refuses everything; anything else accepts.
    // NOTE: accepting unconditionally bypasses the plugin's entire safety layer
    // on the user's live logged-in Chrome (pitfalls.md #1). The outer guard is
    // that node_repl_js is itself TOOL_CONFIRM-gated, so a human already approved
    // the snippet that triggers this.
    createElicitation: async (req) => {
      const msg = req?.message ?? req?.title ?? JSON.stringify(req);
      if ((process.env.AUGENTIA_BROWSER_ELICIT || "").toLowerCase() === "deny") {
        emit(`[elicitation DENIED by host policy] ${msg}`);
        return { action: "decline" };
      }
      emit(`[elicitation auto-approved] ${msg}`);
      return { action: "accept" };
    },

    // The "privileged" channel is length-prefixed JSON over a named pipe, which
    // node:net satisfies — no native module needed. The path comes from the
    // plugin; never hardcode it and never log it (pitfalls.md #3).
    nativePipe: {
      createConnection(path) {
        return new Promise((resolve, reject) => {
          const sock = net.connect(path);
          sock.once("connect", () => resolve(sock));
          sock.once("error", reject);
        });
      },
    },
  };
  return globalThis.nodeRepl;
}
