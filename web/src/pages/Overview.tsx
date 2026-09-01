import { useEffect, useState } from "react";
import { useSection } from "../api/stream";
import { api } from "../api/client";
import { Bar, Empty, ExposureBadge, Panel, StatTile, Sparkline, Table } from "../components/ui";
import { bytes, percent, since } from "../format";
import type {
  ContainerSection, DiskSection, GpuSection, NetworkSection, ProcessSection,
} from "../api/types";

function useHistory(metric: string) {
  const [points, setPoints] = useState<{ ts: number; value: number }[]>([]);
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api.get<{ points: { ts: number; value: number }[] }>(
        `/api/history?metric=${encodeURIComponent(metric)}&window=3600`)
        .then((r) => !cancelled && setPoints(r.points))
        .catch(() => undefined);
    load();
    const t = setInterval(load, 20_000);
    return () => { cancelled = true; clearInterval(t); };
  }, [metric]);
  return points;
}

export default function Overview() {
  const gpu = useSection<GpuSection>("gpu");
  const disk = useSection<DiskSection>("disk");
  const containers = useSection<ContainerSection>("containers");
  const network = useSection<NetworkSection>("network");
  const processes = useSection<ProcessSection>("processes");

  const util = useHistory("gpu.utilization");
  const memHist = useHistory("memory.used_percent");

  const device = gpu?.data?.devices?.[0];
  const mem = gpu?.data?.memory;
  const biggestFs = [...(disk?.data?.filesystems ?? [])].sort((a, b) => b.percent - a.percent)[0];
  // A dual-stack daemon appears once per address family. On the overview that is noise:
  // one line per (port, exposure), with the Network page holding the full detail.
  const rawFindings = network?.data?.findings ?? [];
  const findings = Object.values(
    rawFindings.reduce<Record<string, (typeof rawFindings)[number]>>((acc, f) => {
      const key = `${f.exposure}:${f.port}`;
      if (!acc[key] || (!acc[key].process && f.process)) acc[key] = f;
      return acc;
    }, {}),
  ).sort((a, b) => (a.exposure === "all" ? -1 : 1) - (b.exposure === "all" ? -1 : 1));
  const FINDING_LIMIT = 6;
  const overFull = (disk?.data?.filesystems ?? []).filter((f) => f.over_threshold);
  const looping = (containers?.data?.containers ?? []).filter(
    (c) => c.restart_count > 3 && c.state === "running");
  const memPct = mem && mem.total_bytes ? (mem.used_bytes / mem.total_bytes) * 100 : null;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <a href="/gpu" className="block">
          <div className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)] p-4 transition hover:bg-[var(--color-panel-2)]">
            <div className="text-xs uppercase tracking-wider text-[var(--color-ink-faint)]">GPU utilization</div>
            <div className="mt-1 text-2xl font-semibold">{percent(device?.utilization_percent)}</div>
            <div className="mt-2"><Sparkline points={util} max={100} /></div>
          </div>
        </a>
        <a href="/gpu" className="block">
          <div className="rounded-lg border border-[var(--color-edge)] bg-[var(--color-panel)] p-4 transition hover:bg-[var(--color-panel-2)]">
            <div className="text-xs uppercase tracking-wider text-[var(--color-ink-faint)]">
              {mem?.unified ? "Unified memory" : "Memory"}
            </div>
            <div className="mt-1 text-2xl font-semibold">{percent(memPct)}</div>
            <div className="text-xs text-[var(--color-ink-dim)]">
              {bytes(mem?.used_bytes)} of {bytes(mem?.total_bytes)}
            </div>
            <div className="mt-2"><Sparkline points={memHist} max={100} /></div>
          </div>
        </a>
        <StatTile label="Disk" href="/storage"
          value={percent(biggestFs?.percent)}
          tone={biggestFs?.over_threshold ? "warn" : "neutral"}
          sub={biggestFs ? `${bytes(biggestFs.free_bytes)} free on ${biggestFs.mountpoint}` : "—"} />
        <StatTile label="Containers" href="/containers"
          value={containers?.data?.running ?? "—"}
          sub={`${containers?.data?.stopped ?? 0} stopped`} />
      </div>

      <Panel title="Findings" envelope={network} interval={15}
        subtitle="things worth knowing about right now">
        {() => {
          const empty = findings.length === 0 && overFull.length === 0 && looping.length === 0;
          if (empty) return <p className="text-sm text-emerald-300/80">No findings. Nothing is bound beyond loopback, no filesystem is over threshold, and no container is restart-looping.</p>;
          return (
            <ul className="space-y-2 text-sm">
              {findings.slice(0, FINDING_LIMIT).map((f) => (
                <li key={`${f.exposure}-${f.port}`} className="flex flex-wrap items-center gap-2">
                  <ExposureBadge exposure={f.exposure} />
                  <span className="font-medium">:{f.port}</span>
                  <span className="text-[var(--color-ink-dim)]">
                    {f.process ?? f.container_name ?? "owner not visible to this user"}
                  </span>
                </li>
              ))}
              {findings.length > FINDING_LIMIT && (
                <li>
                  <a href="/network" className="text-xs text-teal-300 hover:underline">
                    {findings.length - FINDING_LIMIT} more on the Network page →
                  </a>
                </li>
              )}
              {overFull.map((f) => (
                <li key={f.mountpoint} className="text-amber-300">
                  {f.mountpoint} is {percent(f.percent)} full — {bytes(f.free_bytes)} free
                </li>
              ))}
              {looping.map((c) => (
                <li key={c.id} className="text-amber-300">
                  {c.name} has restarted {c.restart_count} times
                </li>
              ))}
            </ul>
          );
        }}
      </Panel>

      <Panel title="Top GPU consumers" envelope={processes} interval={5}>
        {(data) =>
          data.gpu_processes.length === 0 ? (
            <Empty>No process is holding GPU memory.</Empty>
          ) : (
            <Table head={["Process", "GPU memory", "Container", "User", "Uptime"]}>
              {data.gpu_processes.slice(0, 5).map((p) => (
                <tr key={p.pid}>
                  <td className="px-2 py-2">
                    <div className="font-medium">{p.name}</div>
                    <div className="text-xs text-[var(--color-ink-faint)]">pid {p.pid}</div>
                  </td>
                  <td className="px-2 py-2">
                    <div>{bytes(p.gpu_memory_bytes)}</div>
                    <div className="mt-1 w-24">
                      <Bar value={p.gpu_memory_bytes ?? 0} max={mem?.total_bytes ?? 1} />
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    {p.container_name
                      ? <a className="text-teal-300 hover:underline" href="/containers">{p.container_name}</a>
                      : <span className="text-[var(--color-ink-faint)]">—</span>}
                  </td>
                  <td className="px-2 py-2 text-[var(--color-ink-dim)]">{p.username ?? "—"}</td>
                  <td className="px-2 py-2 text-[var(--color-ink-dim)]">{since(p.started_at)}</td>
                </tr>
              ))}
            </Table>
          )
        }
      </Panel>
    </div>
  );
}
