import { useEffect, useState } from "react";
import { useSection, useStream } from "../api/stream";
import { api } from "../api/client";
import { ActionButton, Empty, ExposureBadge, Panel, Table } from "../components/ui";
import { bytes, localTime, percent, since } from "../format";
import type { CatalogEntry, ContainerSection, ImageSection, ModelSection } from "../api/types";

function Ports({ ports }: { ports: ContainerSection["containers"][0]["ports"] }) {
  if (!ports.length) return <span className="text-[var(--color-ink-faint)]">—</span>;
  return (
    <div className="space-y-1">
      {ports.map((p, i) => (
        <div key={i} className="flex items-center gap-1.5 whitespace-nowrap">
          <ExposureBadge exposure={p.exposure} />
          <span className="text-xs">
            {p.host_port ? `${p.host_ip}:${p.host_port} → ` : ""}{p.container_port}/{p.protocol}
          </span>
        </div>
      ))}
    </div>
  );
}

function LaunchDialog({ entries, onDone }: { entries: CatalogEntry[]; onDone: (m: string) => void }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const models = useSection<ModelSection>("models");
  const entry = entries.find((e) => e.id === openId);

  if (!entry) {
    return (
      <div className="flex flex-wrap gap-2">
        {entries.map((e) => (
          <button key={e.id} onClick={() => { setOpenId(e.id); setValues({}); }}
            className="rounded border border-[var(--color-edge)] px-3 py-1.5 text-sm hover:bg-[var(--color-panel-2)]">
            Launch {e.name}
          </button>
        ))}
      </div>
    );
  }

  const preview = [
    `docker run -d --name dgxctl-${entry.id}-${values.port ?? entry.port}`,
    entry.port ? `  -p ${entry.bind}:${values.port ?? entry.port}:${values.port ?? entry.port}` : "",
    `  ${entry.image}`,
    ...entry.params.filter((p) => values[p.name]).map((p) => `  ${p.name}=${values[p.name]}`),
  ].filter(Boolean).join("\n");

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">{entry.name}</h3>
        <button onClick={() => setOpenId(null)} className="text-xs text-[var(--color-ink-dim)]">close</button>
      </div>
      {entry.warnings.map((w, i) => (
        <p key={i} className="rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">{w}</p>
      ))}
      <div className="grid gap-3 sm:grid-cols-2">
        {entry.params.map((p) => (
          <label key={p.name} className="block text-xs">
            <span className="text-[var(--color-ink-dim)]">
              {p.name}{p.required && <span className="text-rose-400"> *</span>}
            </span>
            {p.kind === "model_ref" ? (
              <input list="dgxctl-models" value={values[p.name] ?? ""} placeholder={p.default ?? ""}
                onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                className="mt-1 w-full rounded border border-[var(--color-edge)] bg-[var(--color-surface)] px-2 py-1.5 text-sm" />
            ) : (
              <input value={values[p.name] ?? ""} placeholder={p.default ?? ""}
                onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                className="mt-1 w-full rounded border border-[var(--color-edge)] bg-[var(--color-surface)] px-2 py-1.5 text-sm" />
            )}
            {p.description && <span className="mt-0.5 block text-[11px] text-[var(--color-ink-faint)]">{p.description}</span>}
          </label>
        ))}
      </div>
      <datalist id="dgxctl-models">
        {(models?.data?.models ?? []).filter((m) => m.source === "huggingface")
          .map((m) => <option key={m.id} value={m.id} />)}
      </datalist>
      <div>
        <div className="text-xs text-[var(--color-ink-faint)]">Will run:</div>
        <pre className="mt-1 overflow-x-auto rounded bg-[var(--color-surface)] p-3 text-xs text-[var(--color-ink-dim)]">{preview}</pre>
      </div>
      <ActionButton label="Launch" confirmText={`launch ${entry.id}`}
        onConfirm={async () => {
          try {
            const r = await api.post<{ ok: boolean; message: string; detail: Record<string, unknown> | null }>(
              `/api/actions/launch/${entry.id}`, { params: values });
            const url = (r.detail as { url?: string } | null)?.url;
            onDone(r.message + (url ? ` — ${url}` : ""));
            if (r.ok) setOpenId(null);
          } catch (e) {
            onDone(e instanceof Error ? e.message : String(e));
          }
        }} />
    </div>
  );
}

export default function Containers() {
  const containers = useSection<ContainerSection>("containers");
  const images = useSection<ImageSection>("images");
  const { reconnect } = useStream();
  const [tab, setTab] = useState<"containers" | "images">("containers");
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [controlOn, setControlOn] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [logs, setLogs] = useState<{ name: string; text: string } | null>(null);

  useEffect(() => {
    api.get<{ entries: CatalogEntry[] }>("/api/catalog").then((c) => setCatalog(c.entries)).catch(() => undefined);
    api.get<{ control_enabled: boolean }>("/api/config").then((c) => setControlOn(c.control_enabled)).catch(() => undefined);
  }, []);

  const disabled = controlOn ? undefined
    : "Control actions are disabled. Set control_enabled = true in config.toml and restart.";

  const act = async (name: string, verb: string) => {
    try {
      const r = await api.post<{ message: string }>(`/api/actions/container/${name}/${verb}`);
      setNote(r.message);
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    }
    reconnect();
  };

  return (
    <div className="space-y-6">
      <div className="flex gap-1">
        {(["containers", "images"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`rounded px-3 py-1.5 text-sm capitalize ${
              tab === t ? "bg-[var(--color-panel-2)]" : "text-[var(--color-ink-dim)]"}`}>
            {t}
          </button>
        ))}
      </div>

      {note && (
        <p className="rounded border border-teal-500/30 bg-teal-500/10 px-3 py-2 text-sm text-teal-200">
          {note} <button onClick={() => setNote(null)} className="ml-2 text-xs underline">dismiss</button>
        </p>
      )}

      {tab === "containers" ? (
        <>
          <Panel title="Containers" envelope={containers} interval={5}
            subtitle={containers?.data && !containers.data.stats_available ? "resource stats unavailable" : undefined}>
            {(data) =>
              data.containers.length === 0 ? <Empty>No containers.</Empty> : (
                <Table head={["Name", "Image", "State", "CPU", "Memory", "Net I/O", "Ports", "Uptime", ""]}>
                  {data.containers.map((c) => (
                    <tr key={c.id} className={c.state === "running" ? "" : "opacity-60"}>
                      <td className="px-2 py-2">
                        <div className="font-medium">{c.name}</div>
                        {c.restart_count > 0 && (
                          <div className="text-xs text-amber-400">{c.restart_count} restarts</div>)}
                      </td>
                      <td className="max-w-[16rem] truncate px-2 py-2 text-xs text-[var(--color-ink-dim)]" title={c.image}>{c.image}</td>
                      <td className="px-2 py-2">
                        <span className={c.state === "running" ? "text-emerald-300" : "text-[var(--color-ink-faint)]"}>
                          {c.status}
                        </span>
                      </td>
                      <td className="px-2 py-2">{percent(c.cpu_percent, 1)}</td>
                      <td className="px-2 py-2">
                        {bytes(c.memory_bytes)}
                        {c.memory_limit_bytes ? <span className="text-xs text-[var(--color-ink-faint)]"> / {bytes(c.memory_limit_bytes)}</span> : null}
                      </td>
                      <td className="px-2 py-2 text-xs">
                        ↓{bytes(c.net_rx_bytes)} ↑{bytes(c.net_tx_bytes)}
                      </td>
                      <td className="px-2 py-2"><Ports ports={c.ports} /></td>
                      <td className="px-2 py-2 text-[var(--color-ink-dim)]">{c.state === "running" ? since(c.started_at) : "—"}</td>
                      <td className="px-2 py-2">
                        <div className="flex justify-end gap-1">
                          <button onClick={async () => {
                            const text = await api.get<string>(`/api/containers/${c.name}/logs?tail=300`);
                            setLogs({ name: c.name, text });
                          }} className="rounded border border-[var(--color-edge)] px-2 py-1 text-xs text-[var(--color-ink-dim)]">
                            logs
                          </button>
                          {c.state === "running" ? (
                            <>
                              <ActionButton label="restart" confirmText={`restart ${c.name}`}
                                disabledReason={disabled} onConfirm={() => act(c.name, "restart")} />
                              <ActionButton label="stop" tone="danger" confirmText={`stop ${c.name}`}
                                disabledReason={disabled} onConfirm={() => act(c.name, "stop")} />
                            </>
                          ) : (
                            <ActionButton label="start" confirmText={`start ${c.name}`}
                              disabledReason={disabled} onConfirm={() => act(c.name, "start")} />
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </Table>
              )
            }
          </Panel>

          {logs && (
            <section className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)]">
              <header className="flex items-center justify-between border-b border-[var(--color-edge)] px-4 py-2.5">
                <h2 className="text-sm font-semibold">Logs — {logs.name}</h2>
                <button onClick={() => setLogs(null)} className="text-xs text-[var(--color-ink-dim)]">close</button>
              </header>
              <pre className="max-h-96 overflow-auto p-4 text-xs leading-relaxed text-[var(--color-ink-dim)]">{logs.text}</pre>
            </section>
          )}

          <section className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)] p-4">
            <h2 className="mb-3 text-sm font-semibold">Launch from catalog</h2>
            {controlOn ? <LaunchDialog entries={catalog} onDone={setNote} />
              : <p className="text-sm text-[var(--color-ink-faint)]">{disabled}</p>}
          </section>
        </>
      ) : (
        <Panel title="Images" envelope={images} interval={60}
          subtitle={images?.data ? `${bytes(images.data.total_bytes)} total` : undefined}>
          {(data) =>
            data.images.length === 0 ? <Empty>No images.</Empty> : (
              <Table head={["Repository", "Tag", "Size", "Created", "In use"]}>
                {data.images.map((im, i) => (
                  <tr key={`${im.id}-${i}`}>
                    <td className="px-2 py-2">{im.repository}</td>
                    <td className="px-2 py-2 text-[var(--color-ink-dim)]">{im.tag}</td>
                    <td className="px-2 py-2">{bytes(im.size_bytes)}</td>
                    <td className="px-2 py-2 text-xs text-[var(--color-ink-dim)]">{localTime(im.created_at)}</td>
                    <td className="px-2 py-2">
                      {im.in_use ? <span className="text-emerald-300">in use</span>
                        : <span className="text-[var(--color-ink-faint)]">unused</span>}
                    </td>
                  </tr>
                ))}
              </Table>
            )
          }
        </Panel>
      )}
    </div>
  );
}
