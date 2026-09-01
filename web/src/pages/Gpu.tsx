import { useSection, useStream } from "../api/stream";
import { api } from "../api/client";
import { ActionButton, Empty, Panel, SegmentBar, StatTile, Table } from "../components/ui";
import { bytes, num, percent, since } from "../format";
import type { GpuSection, ProcessSection } from "../api/types";
import { useEffect, useState } from "react";

export default function Gpu() {
  const gpu = useSection<GpuSection>("gpu");
  const processes = useSection<ProcessSection>("processes");
  const { reconnect } = useStream();
  const [controlOn, setControlOn] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    api.get<{ control_enabled: boolean }>("/api/config")
      .then((c) => setControlOn(c.control_enabled)).catch(() => undefined);
  }, []);

  const mem = gpu?.data?.memory;
  const gpuReserved = mem?.gpu_reserved_bytes ?? 0;
  const other = Math.max((mem?.used_bytes ?? 0) - gpuReserved, 0);

  return (
    <div className="space-y-6">
      <Panel title="Devices" envelope={gpu} interval={2}
        subtitle={gpu?.data?.driver_version ? `driver ${gpu.data.driver_version}` : undefined}>
        {(data) => (
          <div className="space-y-4">
            {data.devices.map((d) => (
              <div key={d.index} className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
                <StatTile label="Device" value={<span className="text-base">{d.name}</span>} />
                <StatTile label="Utilization" value={percent(d.utilization_percent)} />
                <StatTile label="Temperature" value={d.temperature_c != null ? `${num(d.temperature_c)}°C` : "—"} />
                <StatTile label="Power" value={d.power_w != null ? `${num(d.power_w, 1)} W` : "—"}
                  sub={d.power_limit_w ? `limit ${num(d.power_limit_w)} W` : undefined} />
                <StatTile label="SM clock" value={d.sm_clock_mhz ? `${num(d.sm_clock_mhz)} MHz` : "—"} />
                <StatTile label="Memory source" value={<span className="text-base">{d.memory_source}</span>}
                  sub={d.memory_source === "system" ? "unified pool" : "dedicated"} />
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={mem?.unified ? "Unified memory — one shared pool" : "Memory"} envelope={gpu} interval={2}>
        {(data) => {
          const m = data.memory;
          if (!m) return <Empty>No memory reading.</Empty>;
          return (
            <div className="space-y-3">
              {m.unified && (
                <p className="text-xs text-[var(--color-ink-dim)]">
                  This device shares one memory pool between CPU and GPU. What a model server
                  reserves is unavailable to Docker, to other processes and to the page cache —
                  so budget across everything, not per-device.
                </p>
              )}
              <SegmentBar total={m.total_bytes} segments={[
                { label: "GPU reserved", value: gpuReserved, color: "#5eead4" },
                { label: "Other processes", value: other, color: "#38bdf8" },
                { label: "Cache", value: m.cached_bytes, color: "#334155" },
                { label: "Free", value: Math.max(m.available_bytes - m.cached_bytes, 0), color: "#1b2027" },
              ]} />
              <div className="text-xs text-[var(--color-ink-dim)]">
                {bytes(m.used_bytes)} used of {bytes(m.total_bytes)} · {bytes(m.available_bytes)} available
              </div>
            </div>
          );
        }}
      </Panel>

      <Panel title="Processes" envelope={processes} interval={5}
        subtitle="sorted by GPU memory">
        {(data) => (
          <>
            {note && <p className="mb-3 rounded border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">{note}</p>}
            {data.gpu_processes.length === 0 && data.top_cpu.length === 0 ? (
              <Empty>Nothing notable running.</Empty>
            ) : (
              <Table head={["Process", "GPU memory", "CPU", "RSS", "Container", "User", "Uptime", ""]}>
                {[...data.gpu_processes, ...data.top_cpu].map((p) => (
                  <tr key={`${p.pid}-${p.gpu_memory_bytes ?? "c"}`}>
                    <td className="px-2 py-2">
                      <div className="font-medium">{p.name}</div>
                      <div className="max-w-[28rem] truncate text-xs text-[var(--color-ink-faint)]" title={p.cmdline}>
                        {p.cmdline}
                      </div>
                    </td>
                    <td className="px-2 py-2">{p.gpu_memory_bytes ? bytes(p.gpu_memory_bytes) : "—"}</td>
                    <td className="px-2 py-2">{percent(p.cpu_percent, 1)}</td>
                    <td className="px-2 py-2">{bytes(p.rss_bytes)}</td>
                    <td className="px-2 py-2">{p.container_name ?? "—"}</td>
                    <td className="px-2 py-2 text-[var(--color-ink-dim)]">{p.username ?? "—"}</td>
                    <td className="px-2 py-2 text-[var(--color-ink-dim)]">{since(p.started_at)}</td>
                    <td className="px-2 py-2 text-right">
                      <ActionButton label="kill" tone="danger"
                        confirmText={`kill ${p.pid}`}
                        disabledReason={controlOn ? undefined
                          : "Control actions are disabled. Set control_enabled = true in config.toml and restart."}
                        onConfirm={async () => {
                          try {
                            const r = await api.post<{ ok: boolean; message: string }>(
                              `/api/actions/process/${p.pid}/kill`);
                            setNote(r.message);
                          } catch (e) {
                            setNote(e instanceof Error ? e.message : String(e));
                          }
                          reconnect();
                        }} />
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </>
        )}
      </Panel>
    </div>
  );
}
