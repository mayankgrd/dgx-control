import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Panel, ExposureBadge, SegmentBar } from "../components/ui";
import { bytes, percent, clampPercent, since } from "../format";
import type { Envelope, Exposure } from "../api/types";

const env = <T,>(p: Partial<Envelope<T>>): Envelope<T> => ({
  status: "ok", data: null, error: null, collected_at: new Date().toISOString(),
  duration_ms: 1, ...p,
});

describe("FE-C7 numbers are honest", () => {
  it("formats bytes in binary units", () => {
    expect(bytes(0)).toBe("0 B");
    expect(bytes(1024)).toBe("1.0 KiB");
    expect(bytes(127600744 * 1024)).toBe("121.7 GiB"); // a real 121 GB unified pool
    expect(bytes(null)).toBe("—");
  });
  it("never renders a percentage above 100 or below 0", () => {
    expect(clampPercent(140)).toBe(100);
    expect(clampPercent(-5)).toBe(0);
    expect(percent(140)).toBe("100%");
  });
  it("renders a missing duration as an em dash, not NaN", () => {
    expect(since(null)).toBe("—");
    expect(since("not a date")).toBe("—");
  });
});

describe("FE-C4 exposure vocabulary", () => {
  const cases: Exposure[] = ["loopback", "lan", "tailnet", "all", "unknown"];
  it("renders every level with a distinct label", () => {
    const labels = cases.map((e) => {
      const { unmount, container } = render(<ExposureBadge exposure={e} />);
      const text = container.textContent!;
      unmount();
      return text;
    });
    expect(new Set(labels).size).toBe(cases.length);
  });
  it("marks a wildcard bind as the alert case", () => {
    const { container } = render(<ExposureBadge exposure="all" />);
    expect(container.textContent).toContain("0.0.0.0");
    expect(container.firstElementChild?.className).toContain("rose");
  });
  it("does not style loopback as an alert", () => {
    const { container } = render(<ExposureBadge exposure="loopback" />);
    expect(container.firstElementChild?.className).not.toContain("rose");
  });
});

describe("FE-C2/C3 panels own their state", () => {
  it("renders unavailable calmly, not as an error", () => {
    render(
      <Panel title="Tailscale" envelope={env({ status: "unavailable", error: "not installed" })}>
        {() => <div>never</div>}
      </Panel>,
    );
    expect(screen.getByText(/Not available on this host/)).toBeTruthy();
    expect(screen.queryByText("never")).toBeNull();
  });

  it("keeps rendering the last good data when a section errors", () => {
    render(
      <Panel title="GPU" envelope={env({ status: "error", error: "NVML gone", data: { v: 7 } })}>
        {(d: { v: number }) => <div>value {d.v}</div>}
      </Panel>,
    );
    expect(screen.getByText("value 7")).toBeTruthy();
    expect(screen.getByText(/NVML gone/)).toBeTruthy();
    expect(screen.getByText(/last good reading/)).toBeTruthy();
  });

  it("shows a staleness badge instead of hiding old data", () => {
    const old = new Date(Date.now() - 600_000).toISOString();
    render(
      <Panel title="GPU" interval={5} envelope={env({ data: { v: 1 }, collected_at: old })}>
        {(d: { v: number }) => <div>value {d.v}</div>}
      </Panel>,
    );
    expect(screen.getByText(/stale/)).toBeTruthy();
    expect(screen.getByText("value 1")).toBeTruthy();
  });

  it("waits without a spinner before the first reading", () => {
    render(<Panel title="GPU">{() => <div>never</div>}</Panel>);
    expect(screen.getByText(/Waiting for first reading/)).toBeTruthy();
  });
});

describe("FE-C7 unified memory is one pool", () => {
  it("segments never exceed the total", () => {
    const total = 1000;
    const segs = [
      { label: "a", value: 400, color: "#000" },
      { label: "b", value: 300, color: "#111" },
    ];
    const { container } = render(<SegmentBar segments={segs} total={total} />);
    const widths = [...container.querySelectorAll<HTMLElement>("div[style*='width']")]
      .map((el) => parseFloat(el.style.width));
    expect(widths.reduce((a, b) => a + b, 0)).toBeLessThanOrEqual(100.001);
  });
});
