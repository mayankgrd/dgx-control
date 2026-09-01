import { useState } from "react";
import { useSection } from "../api/stream";
import { Empty, ExposureBadge, Panel, Table } from "../components/ui";
import type { NetworkSection, TailscaleSection } from "../api/types";

export default function Network() {
  const network = useSection<NetworkSection>("network");
  const tailscale = useSection<TailscaleSection>("tailscale");
  const [showAll, setShowAll] = useState(false);

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
        <strong>A tailnet is not a trust boundary.</strong> It can include machines belonging to
        other people. Anything below that is not <em>loopback</em> is reachable by every host that
        can route to this machine — for an inference server, that means free use of the GPU and
        visibility into whatever passes through it.
      </div>

      <Panel title="Listening sockets" envelope={network} interval={15}
        subtitle={showAll ? "all sockets" : "non-loopback first"}
        actions={
          <label className="flex items-center gap-1.5 text-xs text-[var(--color-ink-dim)]">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            show loopback too
          </label>
        }>
        {(data) => {
          const rows = showAll ? data.listeners : data.listeners.filter((l) => l.is_finding);
          if (rows.length === 0) {
            return <p className="text-sm text-emerald-300/80">
              Nothing is listening beyond loopback. {data.listeners.length} loopback socket(s) hidden.
            </p>;
          }
          return (
            <Table head={["Exposure", "Bind", "Port", "Proto", "Owner"]}>
              {rows.map((l, i) => (
                <tr key={`${l.protocol}-${l.bind_ip}-${l.port}-${i}`}>
                  <td className="px-2 py-2"><ExposureBadge exposure={l.exposure} /></td>
                  <td className="px-2 py-2 font-mono text-xs">{l.bind_ip}</td>
                  <td className="px-2 py-2 font-medium">{l.port}</td>
                  <td className="px-2 py-2 text-xs text-[var(--color-ink-dim)]">{l.protocol}</td>
                  <td className="px-2 py-2 text-[var(--color-ink-dim)]">
                    {l.process ?? l.container_name ?? (
                      <span className="text-[var(--color-ink-faint)]"
                        title="Owned by another user; an unprivileged `ss` cannot see its PID.">
                        not visible to this user
                      </span>
                    )}
                    {l.pid && <span className="text-xs text-[var(--color-ink-faint)]"> · pid {l.pid}</span>}
                  </td>
                </tr>
              ))}
            </Table>
          );
        }}
      </Panel>

      <Panel title="Tailscale" envelope={tailscale} interval={15}>
        {(data) => (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div>
                <div className="text-xs uppercase tracking-wider text-[var(--color-ink-faint)]">State</div>
                <div className={`mt-1 font-semibold ${data.backend_state === "Running" ? "text-emerald-300" : "text-amber-300"}`}>
                  {data.backend_state}
                </div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wider text-[var(--color-ink-faint)]">This node</div>
                <div className="mt-1 font-semibold">{data.self_hostname ?? "—"}</div>
                <div className="text-xs text-[var(--color-ink-dim)]">{data.self_dns_name}</div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wider text-[var(--color-ink-faint)]">Addresses</div>
                <div className="mt-1 font-mono text-xs">{data.self_ips.join(" ") || "—"}</div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wider text-[var(--color-ink-faint)]">Exit node</div>
                <div className="mt-1">{data.exit_node_active ? "active" : "not in use"}</div>
              </div>
            </div>
            {data.peers.length === 0 ? <Empty>No peers.</Empty> : (
              <Table head={["Peer", "OS", "Addresses", "Status"]}>
                {data.peers.map((p) => (
                  <tr key={p.hostname}>
                    <td className="px-2 py-2">
                      <div className="font-medium">{p.hostname}</div>
                      <div className="text-xs text-[var(--color-ink-faint)]">{p.dns_name}</div>
                    </td>
                    <td className="px-2 py-2 text-xs text-[var(--color-ink-dim)]">{p.os ?? "—"}</td>
                    <td className="px-2 py-2 font-mono text-xs text-[var(--color-ink-dim)]">{p.ips.join(" ")}</td>
                    <td className="px-2 py-2 text-xs">
                      <span className={p.online ? "text-emerald-300" : "text-[var(--color-ink-faint)]"}>
                        {p.online ? "online" : "offline"}
                      </span>
                      {p.exit_node && <span className="ml-2 text-amber-300">exit node</span>}
                    </td>
                  </tr>
                ))}
              </Table>
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}
