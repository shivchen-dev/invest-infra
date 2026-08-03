export const EXCLUSION_REASON_LABELS: Record<string, string> = {
  no_data: "无当日行情",
  suspended: "当日停牌",
  invalid_price: "收盘价无效",
  low_volume: "成交量不足",
  low_amount: "成交额不足",
};

function normalize(value: string): string {
  return value.toLocaleLowerCase();
}

export function exclusionReasonLabel(code: string): string {
  return EXCLUSION_REASON_LABELS[normalize(code)] ?? code;
}

export function reasonFilterLabel(code: string): string {
  const label = exclusionReasonLabel(code);
  return label === code ? code : `${label}（${code}）`;
}