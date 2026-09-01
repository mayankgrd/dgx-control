import { useState } from "react";
import { useSection } from "../api/stream";
import { Empty, Panel, Table } from "../components/ui";
import { bytes, localTime } from "../format";
import type { ModelSection, ServiceSection } from "../api/types";

export default function Models() {
  const models = useSection<ModelSection>("models");
  const services = useSection<ServiceSection>("services");
  const [filter, setFilter] = useState("");

  const servedNames = new Set(
    (services?.data?.services ?? []).flatMap((s) => s.served_models.map((m) => m.toLowerCase())));

  return (
    <div className="space-y-6">
      <Panel title="Models" envelope={models} interval={600}
        subtitle={models?.data?.scanned_at ? `scanned ${localTime(models.data.scanned_at)}` : "scanning…"}
        actions={
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="filter"
            className="rounded border border-[var(--color-edge)] bg-[var(--color-surface)] px-2 py-1 text-xs" />
        }>
        {(data) => {
          const groups = ["huggingface", "ollama", "scan"].filter((g) => data.totals_by_source[g]);
          const shown = data.models.filter((m) => m.id.toLowerCase().includes(filter.toLowerCase()));
          if (data.models.length === 0) {
            return <Empty>{data.scanning ? "Scanning the cache…" : "No models found."}</Empty>;
          }
          return (
            <div className="space-y-6">
              <div className="flex flex-wrap gap-4 text-xs text-[var(--color-ink-dim)]">
                {groups.map((g) => (
                  <span key={g}>{g}: <strong className="text-[var(--color-ink)]">{bytes(data.totals_by_source[g])}</strong></span>
                ))}
              </div>
              {groups.map((source) => {
                const rows = shown.filter((m) => m.source === source);
                if (!rows.length) return null;
                return (
                  <div key={source}>
                    <h3 className="mb-2 text-xs uppercase tracking-wider text-[var(--color-ink-faint)]">{source}</h3>
                    <Table head={["Model", "Size", "Context", "Architecture", "Quant", "Last used", ""]}>
                      {rows.map((m) => {
                        const served = servedNames.has(m.id.toLowerCase()) ||
                          [...servedNames].some((s) => m.id.toLowerCase().endsWith(s));
                        return (
                          <tr key={`${m.source}-${m.id}`}>
                            <td className="px-2 py-2">
                              <div className="font-medium">{m.id}</div>
                              {m.revision && <div className="text-xs text-[var(--color-ink-faint)]">{m.revision}</div>}
                            </td>
                            <td className="px-2 py-2">{bytes(m.size_bytes)}</td>
                            <td className="px-2 py-2 text-[var(--color-ink-dim)]">
                              {m.max_position_embeddings ? m.max_position_embeddings.toLocaleString() : "—"}
                            </td>
                            <td className="px-2 py-2 text-xs text-[var(--color-ink-dim)]">{m.architecture ?? "—"}</td>
                            <td className="px-2 py-2 text-xs text-[var(--color-ink-dim)]">{m.quantization ?? "—"}</td>
                            <td className="px-2 py-2 text-xs text-[var(--color-ink-dim)]">{localTime(m.last_used)}</td>
                            <td className="px-2 py-2">
                              {served && <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[11px] text-emerald-300">served</span>}
                            </td>
                          </tr>
                        );
                      })}
                    </Table>
                  </div>
                );
              })}
            </div>
          );
        }}
      </Panel>
    </div>
  );
}
