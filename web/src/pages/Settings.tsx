import { useEffect, useState } from "react";
import { api, setToken } from "../api/client";
import { Empty, Panel, Table } from "../components/ui";
import { localTime } from "../format";
import type { ActionLogEntry, DoctorReport, Envelope } from "../api/types";

const STATUS_CLS: Record<string, string> = {
  ok: "text-emerald-300",
  degraded: "text-amber-300",
  unavailable: "text-[var(--color-ink-faint)]",
  error: "text-rose-300",
};

export default function Settings() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [doctor, setDoctor] = useState<DoctorReport | null>(null);
  const [log, setLog] = useState<ActionLogEntry[]>([]);

  useEffect(() => {
    api.get<Record<string, unknown>>("/api/config").then(setConfig).catch(() => undefined);
    api.get<DoctorReport>("/api/doctor").then(setDoctor).catch(() => undefined);
    api.get<ActionLogEntry[]>("/api/actions/log?limit=100").then(setLog).catch(() => undefined);
  }, []);

  const wrap = <T,>(data: T | null): Envelope<T> | undefined =>
    data === null ? undefined : { status: "ok", data, error: null, collected_at: null, duration_ms: null };

  return (
    <div className="space-y-6">
      <Panel title="Diagnostics" envelope={wrap(doctor)}>
        {(d) => (
          <Table head={["Check", "Status", "Detail"]}>
            {d.checks.map((c) => (
              <tr key={c.name}>
                <td className="px-2 py-2 font-medium">{c.name}</td>
                <td className={`px-2 py-2 ${STATUS_CLS[c.status]}`}>{c.status}</td>
                <td className="px-2 py-2 text-xs text-[var(--color-ink-dim)]">
                  {c.detail}
                  {c.fix && <div className="mt-0.5 text-[var(--color-ink-faint)]">fix: {c.fix}</div>}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>

      <Panel title="Effective configuration" envelope={wrap(config)}
        subtitle="the token is never sent to the browser">
        {(c) => (
          <pre className="overflow-x-auto rounded bg-[var(--color-surface)] p-3 text-xs text-[var(--color-ink-dim)]">
            {JSON.stringify(c, null, 2)}
          </pre>
        )}
      </Panel>

      <Panel title="Action log" envelope={wrap(log)}>
        {(entries) =>
          entries.length === 0 ? <Empty>No actions have been taken.</Empty> : (
            <Table head={["When", "Identity", "Action", "Target", "Result"]}>
              {entries.map((e, i) => (
                <tr key={i}>
                  <td className="px-2 py-2 text-xs text-[var(--color-ink-dim)]">{localTime(e.ts)}</td>
                  <td className="px-2 py-2 text-xs">{e.identity}</td>
                  <td className="px-2 py-2">{e.action}</td>
                  <td className="px-2 py-2 text-xs text-[var(--color-ink-dim)]">{e.target}</td>
                  <td className={`px-2 py-2 text-xs ${e.ok ? "text-emerald-300" : "text-rose-300"}`}>{e.message}</td>
                </tr>
              ))}
            </Table>
          )
        }
      </Panel>

      <section className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)] p-4">
        <h2 className="text-sm font-semibold">Session</h2>
        <p className="mt-1 text-xs text-[var(--color-ink-dim)]">
          The API token is stored in this browser only. Clearing it signs this browser out.
        </p>
        <button onClick={() => { setToken(""); window.location.reload(); }}
          className="mt-3 rounded border border-[var(--color-edge)] px-3 py-1.5 text-sm text-[var(--color-ink-dim)] hover:bg-[var(--color-panel-2)]">
          Clear stored token
        </button>
      </section>
    </div>
  );
}
