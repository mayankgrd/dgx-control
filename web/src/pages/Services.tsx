import { useEffect, useState } from "react";
import { useSection, useStream } from "../api/stream";
import { api } from "../api/client";
import { ActionButton, Empty, ExposureBadge, Panel } from "../components/ui";
import { AccessBlock, servicePlan } from "../components/access";
import { since } from "../format";
import type {
  CatalogEntry, HostAddressInfo, PyEnvInfo, PyEnvSection, ServiceCategory,
  ServiceInfo, ServiceSection,
} from "../api/types";

const CATEGORY_ORDER: ServiceCategory[] = ["llm", "notebook", "agent", "tool"];
const CATEGORY_LABELS: Record<ServiceCategory, string> = {
  llm: "Model servers",
  notebook: "Notebooks",
  agent: "Agents",
  tool: "Tools",
  infrastructure: "Infrastructure",
  unknown: "Unrecognised",
};

const HEALTH = {
  ok: ["text-emerald-300", "reachable"],
  unreachable: ["text-rose-300", "unreachable"],
  unprobed: ["text-[var(--color-ink-faint)]", "not probed"],
} as const;

function ServiceCard({
  svc, host, controlOn, onAction,
}: {
  svc: ServiceInfo; host: HostAddressInfo; controlOn: boolean; onAction: (m: string) => void;
}) {
  const [cls, healthLabel] = HEALTH[svc.health];
  return (
    <div className={`flex flex-col rounded-lg border bg-[var(--color-panel-2)] p-3 ${
      svc.online ? "border-[var(--color-edge)]" : "border-[var(--color-edge)]/50"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-medium">{svc.label || svc.name}</div>
          <div className="text-xs text-[var(--color-ink-faint)]">
            {svc.name !== svc.label && svc.name !== `${svc.kind}:${svc.port}` ? `${svc.name} · ` : ""}
            port {svc.port}
          </div>
        </div>
        {svc.online
          ? <ExposureBadge exposure={svc.exposure} />
          : <span className="shrink-0 rounded border border-[var(--color-edge)] px-1.5 py-0.5 text-[11px] text-[var(--color-ink-faint)]">offline</span>}
      </div>

      <p className="mt-1.5 text-xs text-[var(--color-ink-dim)]">{svc.summary}</p>

      {svc.online && svc.health !== "unprobed" && (
        <div className={`mt-1 text-[11px] ${cls}`}>{healthLabel}</div>
      )}

      {svc.served_models.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {svc.served_models.map((m) => (
            <span key={m} className="rounded bg-[var(--color-surface)] px-1.5 py-0.5 text-[11px] text-[var(--color-ink-dim)]">
              {m}
            </span>
          ))}
        </div>
      )}

      <div className="mt-3 border-t border-[var(--color-edge)]/60 pt-2">
        {svc.online ? <AccessBlock svc={svc} host={host} /> : svc.launchable ? (
          <ActionButton
            label="Start" confirmText={`start ${svc.label || svc.name}`}
            disabledReason={controlOn ? undefined
              : "Control actions are disabled. Set control_enabled = true in config.toml and restart."}
            onConfirm={async () => {
              try {
                const r = await api.post<{ message: string }>(
                  `/api/actions/service/${svc.id}/launch`);
                onAction(r.message);
              } catch (e) {
                onAction(e instanceof Error ? e.message : String(e));
              }
            }} />
        ) : (
          <span className="text-xs text-[var(--color-ink-faint)]">
            Not running. Start it and it appears here.
          </span>
        )}
      </div>
    </div>
  );
}

function LaunchableEntry({
  entry, envs, controlOn, onAction,
}: {
  entry: CatalogEntry; envs: PyEnvInfo[]; controlOn: boolean; onAction: (m: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const running = entry.running;

  const disabled = controlOn ? undefined
    : "Control actions are disabled. Set control_enabled = true in config.toml and restart.";

  return (
    <div className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel-2)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="font-medium">{entry.name}</div>
          <div className="text-xs text-[var(--color-ink-faint)]">{entry.description}</div>
        </div>
        {running ? (
          <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[11px] text-emerald-300">
            running{running.origin === "external" ? " (started elsewhere)" : ""}
          </span>
        ) : null}
      </div>

      {running ? (
        <div className="mt-2 space-y-2">
          <div className="text-xs text-[var(--color-ink-dim)]">
            {running.pid && <>pid {running.pid}</>}
            {running.port && <> · port {running.port}</>}
            {running.started_at && <> · up {since(running.started_at)}</>}
          </div>
          {running.origin === "dgxctl" ? (
            <ActionButton label="Stop" tone="danger" confirmText={`stop ${entry.name}`}
              disabledReason={disabled}
              onConfirm={async () => {
                try {
                  const r = await api.post<{ message: string }>(
                    `/api/actions/entry/${entry.id}/stop`);
                  onAction(r.message);
                } catch (e) { onAction(e instanceof Error ? e.message : String(e)); }
              }} />
          ) : (
            <span className="text-xs text-[var(--color-ink-faint)]">
              Started outside dgxctl, so it is shown but not managed here. Its link is in
              Running services above.
            </span>
          )}
        </div>
      ) : !open ? (
        <button onClick={() => setOpen(true)} disabled={!!disabled} title={disabled}
          className={`mt-3 rounded border border-[var(--color-edge)] px-3 py-1.5 text-sm ${
            disabled ? "cursor-not-allowed text-[var(--color-ink-faint)]"
                     : "hover:bg-[var(--color-panel)]"}`}>
          Launch {entry.name}
        </button>
      ) : (
        <div className="mt-3 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            {entry.params.map((p) => (
              <label key={p.name} className="block text-xs">
                <span className="text-[var(--color-ink-dim)]">{p.name}</span>
                {p.kind === "venv_ref" ? (
                  <select value={values[p.name] ?? p.default ?? ""}
                    onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                    className="mt-1 w-full rounded border border-[var(--color-edge)] bg-[var(--color-surface)] px-2 py-1.5 text-sm">
                    <option value={p.default ?? ""}>{p.default} (default)</option>
                    {envs.map((env) => (
                      <option key={env.path} value={env.path}>
                        {env.path}{env.gpu_capable ? " — GPU" : ""}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input value={values[p.name] ?? ""} placeholder={p.default ?? ""}
                    onChange={(e) => setValues({ ...values, [p.name]: e.target.value })}
                    className="mt-1 w-full rounded border border-[var(--color-edge)] bg-[var(--color-surface)] px-2 py-1.5 text-sm" />
                )}
                {p.description && (
                  <span className="mt-0.5 block text-[11px] text-[var(--color-ink-faint)]">
                    {p.description}
                  </span>
                )}
              </label>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <ActionButton label="Launch" confirmText={`launch ${entry.name}`}
              disabledReason={disabled}
              onConfirm={async () => {
                try {
                  const r = await api.post<{ ok: boolean; message: string }>(
                    `/api/actions/launch/${entry.id}`, { params: values });
                  onAction(r.message);
                  if (r.ok) setOpen(false);
                } catch (e) { onAction(e instanceof Error ? e.message : String(e)); }
              }} />
            <button onClick={() => setOpen(false)}
              className="text-xs text-[var(--color-ink-dim)]">cancel</button>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Services() {
  const services = useSection<ServiceSection>("services");
  const pyenvs = useSection<PyEnvSection>("pyenvs");
  const { reconnect } = useStream();
  const [showAll, setShowAll] = useState(false);
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [controlOn, setControlOn] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const load = () =>
    api.get<{ entries: CatalogEntry[] }>("/api/catalog")
      .then((c) => setCatalog(c.entries)).catch(() => undefined);

  useEffect(() => {
    load();
    api.get<{ control_enabled: boolean }>("/api/config")
      .then((c) => setControlOn(c.control_enabled)).catch(() => undefined);
  }, []);

  const onAction = (m: string) => { setNote(m); load(); reconnect(); };
  const launchables = catalog.filter((e) => e.kind === "process");
  const envs = (pyenvs?.data?.envs ?? []).filter((e) => e.gpu_capable);

  return (
    <div className="space-y-6">
      {note && (
        <p className="whitespace-pre-wrap rounded border border-teal-500/30 bg-teal-500/10 px-3 py-2 text-sm text-teal-200">
          {note} <button onClick={() => setNote(null)} className="ml-2 text-xs underline">dismiss</button>
        </p>
      )}

      <Panel title="Services" envelope={services} interval={60}
        subtitle="what is running, and how to reach it from where you are"
        actions={
          <label className="flex items-center gap-1.5 text-xs text-[var(--color-ink-dim)]">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            show infrastructure
          </label>
        }>
        {(data) => {
          const host = data.host;
          const hidden = data.services.filter((s) => !s.notable);
          const visible = showAll ? data.services : data.services.filter((s) => s.notable);
          if (visible.length === 0) return <Empty>No services detected.</Empty>;

          const categories = (showAll
            ? ([...CATEGORY_ORDER, "infrastructure", "unknown"] as ServiceCategory[])
            : CATEGORY_ORDER
          ).filter((c) => visible.some((s) => s.category === c));

          const position = visible.length ? servicePlan(visible[0], host).viewerNote : "";

          return (
            <div className="space-y-6">
              {position && (
                <p className="text-xs text-[var(--color-ink-faint)]">{position}</p>
              )}
              {categories.map((cat) => (
                <div key={cat}>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-faint)]">
                    {CATEGORY_LABELS[cat]}
                  </h3>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {visible.filter((s) => s.category === cat).map((s) => (
                      <ServiceCard key={`${s.bind_ip}:${s.port}`} svc={s} host={host}
                        controlOn={controlOn} onAction={onAction} />
                    ))}
                  </div>
                </div>
              ))}
              {!showAll && hidden.length > 0 && (
                <p className="text-xs text-[var(--color-ink-faint)]">
                  {hidden.length} infrastructure or unrecognised listener(s) hidden — SSH, DNS,
                  Tailscale, notebook kernels and the like. Tick “show infrastructure” to see them.
                </p>
              )}
            </div>
          );
        }}
      </Panel>

      {launchables.length > 0 && (
        <section className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)]">
          <header className="flex items-center gap-2 border-b border-[var(--color-edge)] px-4 py-2.5">
            <h2 className="text-sm font-semibold tracking-wide">Launch</h2>
            <span className="text-xs text-[var(--color-ink-faint)]">
              host processes with direct GPU access
            </span>
          </header>
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            {launchables.map((e) => (
              <LaunchableEntry key={e.id} entry={e} envs={envs}
                controlOn={controlOn} onAction={onAction} />
            ))}
          </div>
        </section>
      )}

      <Panel title="Python environments" envelope={pyenvs} interval={300}
        subtitle="torch detected from on-disk metadata, never imported">
        {(data) =>
          data.envs.length === 0 ? <Empty>No environments found under the configured roots.</Empty> : (
            <ul className="space-y-2 text-sm">
              {data.envs.map((e) => (
                <li key={e.path} className="flex flex-wrap items-center gap-2">
                  <span className={e.gpu_capable ? "text-emerald-300" : "text-[var(--color-ink-faint)]"}>
                    {e.gpu_capable ? "GPU" : "CPU"}
                  </span>
                  <span className="font-medium">{e.path}</span>
                  <span className="text-xs text-[var(--color-ink-dim)]">
                    {e.kind}{e.python_version && ` · py${e.python_version}`}
                    {e.torch_version ? ` · torch ${e.torch_version}` : ` · ${e.note ?? ""}`}
                  </span>
                </li>
              ))}
            </ul>
          )
        }
      </Panel>
    </div>
  );
}
