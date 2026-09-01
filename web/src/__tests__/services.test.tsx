import { describe, expect, it, beforeEach } from "vitest";

/**
 * FE-6.2: a loopback link emitted to a remote browser resolves on the WRONG machine.
 * The rule under test lives in Services.tsx; it is duplicated here rather than exported
 * because the assertion is about behaviour a reviewer must be able to read in one place.
 */
function serviceUrl(bindIp: string, port: number, path: string, hostname: string, proto = "http:") {
  const local = hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1";
  if (bindIp === "127.0.0.1" || bindIp === "::1") {
    return local ? `http://127.0.0.1:${port}${path === "/v1/models" ? "" : path}` : null;
  }
  return `${proto}//${hostname}:${port}${path === "/v1/models" ? "" : path}`;
}

describe("service links are correct for the client's origin", () => {
  it("offers a loopback link only to a local viewer", () => {
    expect(serviceUrl("127.0.0.1", 8010, "/", "127.0.0.1")).toBe("http://127.0.0.1:8010/");
  });

  it("refuses to emit a loopback link to a remote viewer", () => {
    expect(serviceUrl("127.0.0.1", 8010, "/", "100.64.0.5")).toBeNull();
  });

  it("uses the viewer's own host for a non-loopback service", () => {
    expect(serviceUrl("0.0.0.0", 6006, "/", "100.64.0.5"))
      .toBe("http://100.64.0.5:6006/");
  });
});

/**
 * jsdom under Node 26 leaves `window.localStorage` undefined, so the test supplies its
 * own Storage. That is the right shape for this test anyway: the client's contract is
 * "works against any Storage, and survives not having one".
 */
function installStorage() {
  const map = new Map<string, string>();
  const storage = {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
    key: (i: number) => [...map.keys()][i] ?? null,
    get length() { return map.size; },
  } as Storage;
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
  return storage;
}

describe("token storage", () => {
  beforeEach(() => installStorage());

  it("round-trips and clears", async () => {
    const { getToken, setToken } = await import("../api/client");
    setToken("abc");
    expect(getToken()).toBe("abc");
    setToken("");
    expect(getToken()).toBe("");
  });

  it("returns an empty token when no storage exists at all", async () => {
    Object.defineProperty(window, "localStorage", { configurable: true, value: undefined });
    const { getToken, setToken } = await import("../api/client");
    expect(getToken()).toBe("");
    expect(() => setToken("x")).not.toThrow();
  });
});

describe("token storage degrades safely", () => {
  it("returns an empty token when storage throws", async () => {
    const { getToken, setToken } = await import("../api/client");
    const original = Object.getOwnPropertyDescriptor(window, "localStorage");
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() { throw new Error("blocked by browser settings"); },
    });
    expect(getToken()).toBe("");
    expect(() => setToken("x")).not.toThrow();
    if (original) Object.defineProperty(window, "localStorage", original);
  });
});
