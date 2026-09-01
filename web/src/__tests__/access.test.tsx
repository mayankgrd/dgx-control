import { describe, expect, it, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AccessBlock, apiBase } from "../components/access";
import { classifyViewer, planAccess, serviceScope } from "../reachability";
import type { HostAddressInfo, ServiceInfo } from "../api/types";

const HOST: HostAddressInfo = {
  hostname: "dgx-01",
  loopback: "127.0.0.1",
  lan: ["192.0.2.10", "192.0.2.11"],
  tailnet_ip: "100.64.0.1",
  tailnet_name: "dgx-01.example.ts.net",
};

const svc = (over: Partial<ServiceInfo> = {}): ServiceInfo => ({
  id: null, name: "jupyter-lab", label: "JupyterLab",
  summary: "Notebook server with direct GPU access.", category: "notebook",
  recognised: true, is_self: false,
  kind: "jupyter", port: 11002, bind_ip: "127.0.0.1", exposure: "loopback",
  pid: 1, container_name: null, health: "ok", served_models: [], path: "/",
  notable: true, linkable: true, auth_query: "?token=SECRETTOKEN123", auth_hint: null,
  base_url: null, declared: false, online: true, launchable: false, ...over,
});

function setHost(hostname: string) {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { hostname, protocol: "http:" },
  });
}

/* ---- R16: the matrix, as a pure function ---- */

describe("where is the viewer", () => {
  it("recognises loopback, tailnet and LAN origins", () => {
    expect(classifyViewer("127.0.0.1", HOST)).toBe("loopback");
    expect(classifyViewer("localhost", HOST)).toBe("loopback");
    expect(classifyViewer("dgx-01.example.ts.net", HOST)).toBe("tailnet");
    expect(classifyViewer("100.64.0.9", HOST)).toBe("tailnet");
    expect(classifyViewer("192.0.2.50", HOST)).toBe("lan");
  });
});

describe("what can reach the service", () => {
  it("treats a Docker bridge bind as host-only", () => {
    expect(serviceScope("172.17.0.1")).toBe("host-only");
    expect(serviceScope("127.0.0.1")).toBe("host-only");
    expect(serviceScope("0.0.0.0")).toBe("all");
    expect(serviceScope("100.64.0.1")).toBe("tailnet-only");
  });
});

describe("R16 reachability matrix", () => {
  it("LAN viewer, service on all interfaces → the DGX's LAN address", () => {
    const p = planAccess("0.0.0.0", 6006, "192.0.2.50", HOST);
    expect(p.routes.map((r) => r.url)).toEqual([
      "http://192.0.2.10:6006/",
      "http://192.0.2.11:6006/",
    ]);
    expect(p.forwardCommand).toBeUndefined();
  });

  it("LAN viewer, loopback service → forward naming the LAN address", () => {
    const p = planAccess("127.0.0.1", 8010, "192.0.2.50", HOST);
    expect(p.routes).toHaveLength(0);
    expect(p.forwardCommand).toBe("ssh -N -L 8010:127.0.0.1:8010 192.0.2.10");
    expect(p.forwardUrl).toBe("http://127.0.0.1:8010/");
  });

  it("tailnet viewer, service on all → the MagicDNS name", () => {
    const p = planAccess("0.0.0.0", 6006, "dgx-01.example.ts.net", HOST);
    expect(p.routes[0].url).toBe("http://dgx-01.example.ts.net:6006/");
  });

  it("tailnet viewer, loopback service → forward via the tailnet name", () => {
    const p = planAccess("127.0.0.1", 11434, "100.64.0.1", HOST);
    expect(p.forwardCommand).toBe("ssh -N -L 11434:127.0.0.1:11434 dgx-01.example.ts.net");
  });

  it("127.0.0.1 viewer is told BOTH cases, because Sync and on-box look identical", () => {
    const p = planAccess("127.0.0.1", 8010, "127.0.0.1", HOST);
    expect(p.routes[0].label).toContain("on the DGX itself");
    expect(p.routes[0].caveat).toContain("NVIDIA Sync");
    expect(p.forwardCommand).toBeTruthy();
  });

  it("127.0.0.1 viewer, service on all interfaces → real addresses too, no forward needed", () => {
    const p = planAccess("0.0.0.0", 6006, "127.0.0.1", HOST);
    const urls = p.routes.map((r) => r.url);
    expect(urls).toContain("http://127.0.0.1:6006/");
    expect(urls).toContain("http://192.0.2.10:6006/");
    expect(urls).toContain("http://dgx-01.example.ts.net:6006/");
  });

  it("tailnet-only service is unreachable from the LAN, and says so", () => {
    const p = planAccess("100.64.0.1", 443, "192.0.2.50", HOST);
    expect(p.routes).toHaveLength(0);
    expect(p.unreachableReason).toContain("cannot be reached");
  });

  it("never emits a placeholder host in a forward command", () => {
    for (const origin of ["127.0.0.1", "192.0.2.50", "dgx-01.example.ts.net"]) {
      const p = planAccess("127.0.0.1", 8010, origin, HOST);
      expect(p.forwardCommand).not.toContain("<");
    }
  });

  it("states the viewer's position for every origin", () => {
    for (const origin of ["127.0.0.1", "192.0.2.50", "dgx-01.example.ts.net"]) {
      expect(planAccess("0.0.0.0", 1, origin, HOST).viewerNote).toBeTruthy();
    }
  });
});

/* ---- FE-10 / FE-C11 rendering ---- */

describe("the access block", () => {
  beforeEach(() => {
    setHost("127.0.0.1");
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
  });

  it("masks a token until revealed, but the link still carries it", () => {
    const { container } = render(<AccessBlock svc={svc()} host={HOST} />);
    expect(container.textContent).not.toContain("SECRETTOKEN123");
    expect(screen.getByText("includes token")).toBeTruthy();
    const link = screen.getByText("Open ↗") as HTMLAnchorElement;
    expect(link.href).toContain("token=SECRETTOKEN123");
    fireEvent.click(screen.getByText("reveal"));
    expect(screen.getByText(/SECRETTOKEN123/)).toBeTruthy();
  });

  it("offers the forward command for a loopback service seen from the LAN", () => {
    setHost("192.0.2.50");
    render(<AccessBlock svc={svc()} host={HOST} />);
    expect(screen.getByText(/ssh -N -L 11002:127.0.0.1:11002 192.0.2.10/)).toBeTruthy();
    expect(screen.queryByText("Open ↗")).toBeNull();
  });

  it("shows an OpenAI base URL on the same origin as the link, not the docs path", () => {
    setHost("192.0.2.50");
    const vllm = svc({
      kind: "vllm", label: "vLLM", category: "llm", bind_ip: "0.0.0.0", port: 8010,
      path: "/docs", base_url: "/v1", served_models: ["qwen3"], auth_query: null,
    });
    render(<AccessBlock svc={vllm} host={HOST} />);
    expect(screen.getByText("http://192.0.2.10:8010/v1")).toBeTruthy();
    expect(screen.getByText(/qwen3/)).toBeTruthy();
  });

  it("api base is derived from the route origin, never string-concatenated onto the path", () => {
    const vllm = svc({ path: "/docs", base_url: "/v1", bind_ip: "0.0.0.0" });
    expect(apiBase("http://192.0.2.10:8010/docs", vllm)).toBe("http://192.0.2.10:8010/v1");
  });

  it("tells you a browser is the wrong client, instead of offering a dead link", () => {
    const hermes = svc({
      kind: "hermes", label: "Hermes", category: "agent", linkable: false, auth_query: null,
      auth_hint: "Authenticates with a per-session token; a browser gets 401.",
    });
    render(<AccessBlock svc={hermes} host={HOST} />);
    expect(screen.getByText(/per-session token/)).toBeTruthy();
    expect(screen.queryByText("Open ↗")).toBeNull();
  });
});

describe("model servers always say how to call them", () => {
  it("shows the API base behind the tunnel when the service is loopback-only", () => {
    setHost("192.0.2.50");
    const vllm = svc({
      kind: "vllm", label: "vLLM", category: "llm", bind_ip: "127.0.0.1", port: 8010,
      path: "/docs", base_url: "/v1", served_models: ["qwen3.6-35b"], auth_query: null,
    });
    render(<AccessBlock svc={vllm} host={HOST} />);
    // No direct route exists from the LAN, but the endpoint must still be stated.
    expect(screen.getByText(/OpenAI base URL \(once forwarded\)/)).toBeTruthy();
    expect(screen.getByText("http://127.0.0.1:8010/v1")).toBeTruthy();
    expect(screen.getByText(/qwen3\.6-35b/)).toBeTruthy();
  });
});
