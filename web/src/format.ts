/** FE-C7: numbers are honest. Binary units, fixed precision, percentages clamped. */

export function bytes(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (value === 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  const i = Math.min(Math.floor(Math.log2(Math.abs(value)) / 10), units.length - 1);
  const scaled = value / 1024 ** i;
  return `${scaled.toFixed(i === 0 ? 0 : digits)} ${units[i]}`;
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${clampPercent(value).toFixed(digits)}%`;
}

export function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value));
}

export function num(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

/** Datetimes arrive as UTC and are rendered local in exactly one place: here. */
export function localTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function since(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  let s = Math.max(0, (Date.now() - then) / 1000);
  if (s < 60) return `${Math.floor(s)}s`;
  s /= 60;
  if (s < 60) return `${Math.floor(s)}m`;
  s /= 60;
  if (s < 24) return `${Math.floor(s)}h ${Math.floor((s % 1) * 60)}m`;
  return `${Math.floor(s / 24)}d ${Math.floor(s % 24)}h`;
}

export function ageSeconds(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? null : (Date.now() - t) / 1000;
}
