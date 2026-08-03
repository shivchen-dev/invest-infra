const FIXED_FOUR = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

const FIXED_TWO = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const INT = new Intl.NumberFormat("zh-CN");

const MARKET_DATE_TIME = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

function toFiniteNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = typeof value === "string" ? Number(value) : value;
  return Number.isFinite(n) ? n : null;
}

export function formatAmount(
  value: string | number | null | undefined,
): string {
  const n = toFiniteNumber(value);
  if (n === null) return "—";
  if (n >= 1_0000_0000) return `${(n / 1_0000_0000).toFixed(2)} 亿`;
  if (n >= 1_0000) return `${(n / 1_0000).toFixed(2)} 万`;
  return INT.format(n);
}

export function formatCount(
  value: string | number | null | undefined,
): string {
  const n = toFiniteNumber(value);
  if (n === null) return "—";
  return INT.format(Math.trunc(n));
}

export function formatDecimal(
  value: string | number | null | undefined,
  digits: 2 | 4 = 4,
): string {
  const n = toFiniteNumber(value);
  if (n === null) return "—";
  return digits === 4 ? FIXED_FOUR.format(n) : FIXED_TWO.format(n);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return value;
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const parts = Object.fromEntries(
    MARKET_DATE_TIME.formatToParts(d).map(({ type, value: part }) => [
      type,
      part,
    ]),
  );
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

export function formatDuration(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  if (!start || !end) return "—";
  const s = new Date(start).getTime();
  const e = new Date(end).getTime();
  if (!Number.isFinite(s) || !Number.isFinite(e) || e < s) return "—";
  const totalSeconds = Math.round((e - s) / 1000);
  if (totalSeconds < 60) return `${totalSeconds} 秒`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes} 分 ${seconds} 秒`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return `${hours} 小时 ${remMinutes} 分`;
}
