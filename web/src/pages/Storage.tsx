import { useSection } from "../api/stream";
import { Bar, Empty, Panel, Table } from "../components/ui";
import { bytes, percent } from "../format";
import type { DiskSection } from "../api/types";

export default function Storage() {
  const disk = useSection<DiskSection>("disk");
  return (
    <div className="space-y-6">
      <Panel title="Filesystems" envelope={disk} interval={60}>
        {(data) =>
          data.filesystems.length === 0 ? <Empty>No filesystems reported.</Empty> : (
            <Table head={["Mount", "Device", "Type", "Used", "Free", "Total", ""]}>
              {data.filesystems.map((f) => (
                <tr key={f.mountpoint} className={f.over_threshold ? "text-amber-300" : ""}>
                  <td className="px-2 py-2 font-medium">{f.mountpoint}</td>
                  <td className="px-2 py-2 text-xs text-[var(--color-ink-dim)]">{f.device}</td>
                  <td className="px-2 py-2 text-xs text-[var(--color-ink-dim)]">{f.fstype}</td>
                  <td className="px-2 py-2">{bytes(f.used_bytes)} <span className="text-xs text-[var(--color-ink-faint)]">({percent(f.percent)})</span></td>
                  <td className="px-2 py-2">{bytes(f.free_bytes)}</td>
                  <td className="px-2 py-2">{bytes(f.total_bytes)}</td>
                  <td className="w-40 px-2 py-2">
                    <Bar value={f.percent} tone={f.percent >= 90 ? "bad" : f.over_threshold ? "warn" : undefined} />
                  </td>
                </tr>
              ))}
            </Table>
          )
        }
      </Panel>

      <Panel title="Large consumers" envelope={disk} interval={60}
        subtitle="directory sizes, cached — these are expensive to measure">
        {(data) =>
          data.sized_roots.length === 0 ? <Empty>No roots configured.</Empty> : (
            <Table head={["Path", "Size"]}>
              {data.sized_roots.map((r) => (
                <tr key={r.path}>
                  <td className="px-2 py-2">
                    <div className="font-medium">{r.label}</div>
                    <div className="text-xs text-[var(--color-ink-faint)]">{r.path}</div>
                  </td>
                  <td className="px-2 py-2">
                    {r.error ? <span className="text-xs text-[var(--color-ink-faint)]">{r.error}</span>
                      : bytes(r.size_bytes)}
                  </td>
                </tr>
              ))}
            </Table>
          )
        }
      </Panel>

      <Panel title="Docker usage" envelope={disk} interval={60}>
        {(data) =>
          !data.docker ? <Empty>Docker usage unavailable.</Empty> : (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
              {[
                ["Images", data.docker.images_bytes],
                ["Containers", data.docker.containers_bytes],
                ["Volumes", data.docker.volumes_bytes],
                ["Build cache", data.docker.build_cache_bytes],
                ["Reclaimable", data.docker.reclaimable_bytes],
              ].map(([label, value]) => (
                <div key={label as string}>
                  <div className="text-xs uppercase tracking-wider text-[var(--color-ink-faint)]">{label}</div>
                  <div className="mt-1 text-lg font-semibold">{bytes(value as number)}</div>
                </div>
              ))}
            </div>
          )
        }
      </Panel>
    </div>
  );
}
