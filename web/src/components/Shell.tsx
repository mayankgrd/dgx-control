/** FE-C1: one shell owns nav, the connection indicator and the node switcher. */
import { NavLink, Outlet } from "react-router-dom";
import { useState } from "react";
import { useStream } from "../api/stream";
import type { ConnState } from "../api/stream";
import { setToken, getToken } from "../api/client";

const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/gpu", label: "GPU" },
  { to: "/containers", label: "Containers" },
  { to: "/storage", label: "Storage" },
  { to: "/models", label: "Models" },
  { to: "/services", label: "Services" },
  { to: "/network", label: "Network" },
  { to: "/settings", label: "Settings" },
];

function ConnectionDot() {
  const { conn, reconnect } = useStream();
  const map = {
    live: ["bg-emerald-400", "live"],
    connecting: ["bg-amber-400 animate-pulse", "connecting"],
    retrying: ["bg-amber-400 animate-pulse", "reconnecting"],
    unauthorized: ["bg-rose-500", "not authenticated"],
    offline: ["bg-rose-500", "offline"],
  } as const;
  const [cls, label] = map[conn];
  return (
    <button onClick={reconnect} title="Click to reconnect"
      className="inline-flex items-center gap-1.5 text-xs text-[var(--color-ink-dim)]">
      <span className={`inline-block h-2 w-2 rounded-full ${cls}`} />
      {label}
    </button>
  );
}

function NodeSwitcher() {
  const { nodes, nodeId, setNodeId } = useStream();
  if (nodes.length <= 1) return null;
  return (
    <select value={nodeId} onChange={(e) => setNodeId(e.target.value)}
      className="rounded border border-[var(--color-edge)] bg-[var(--color-panel)] px-2 py-1 text-xs">
      {nodes.map((n) => (
        <option key={n.id} value={n.id}>
          {n.name}{n.reachable ? "" : " (unreachable)"}
        </option>
      ))}
    </select>
  );
}

function TokenPrompt({ rejected }: { rejected: boolean }) {
  const [value, setValue] = useState("");
  return (
    <div className="mx-auto mt-24 max-w-md rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)] p-6">
      <h1 className="text-lg font-semibold">
        {rejected ? "Stored token was rejected" : "Authentication required"}
      </h1>
      <p className="mt-2 text-sm text-[var(--color-ink-dim)]">
        {rejected
          ? "The token saved in this browser is no longer valid — it was probably rotated. Enter the current one:"
          : "Every request to this instance needs the API token."}{" "}
        Get it on the DGX with{" "}
        <code className="rounded bg-[var(--color-panel-2)] px-1">dgxctl token --show</code>.
      </p>
      <form className="mt-4 flex gap-2"
        onSubmit={(e) => { e.preventDefault(); setToken(value.trim()); window.location.reload(); }}>
        <input type="password" value={value} onChange={(e) => setValue(e.target.value)}
          placeholder="API token" autoComplete="off"
          className="flex-1 rounded border border-[var(--color-edge)] bg-[var(--color-surface)] px-3 py-2 text-sm" />
        <button type="submit" className="rounded bg-teal-500 px-3 py-2 text-sm font-medium text-slate-900">
          Save
        </button>
      </form>
    </div>
  );
}

/**
 * Prompt on ANY unauthorized state, not only a missing token. Gating on "no token stored"
 * strands anyone whose token was rotated: the stale value is non-empty, so the app renders
 * an empty shell with no way back except the Settings page.
 */
export function shouldPromptForToken(conn: ConnState): boolean {
  return conn === "unauthorized";
}

export function Shell() {
  const { conn, snapshot } = useStream();
  if (shouldPromptForToken(conn)) return <TokenPrompt rejected={Boolean(getToken())} />;

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10 border-b border-[var(--color-edge)] bg-[var(--color-surface)]/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold tracking-tight">DGX Control</span>
            {snapshot && (
              <span className="text-xs text-[var(--color-ink-faint)]">{snapshot.node.name}</span>
            )}
          </div>
          <nav className="order-3 -mx-1 flex w-full gap-1 overflow-x-auto sm:order-none sm:w-auto">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded px-2.5 py-1 text-sm transition ${
                    isActive ? "bg-[var(--color-panel-2)] text-[var(--color-ink)]"
                             : "text-[var(--color-ink-dim)] hover:text-[var(--color-ink)]"}`}>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <NodeSwitcher />
            <ConnectionDot />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
