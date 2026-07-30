export type Instrument = {
  symbol: string;
  name: string;
  exchange: string;
  instrument_type: string;
  is_active: boolean;
};

export type InstrumentList = {
  items: Instrument[];
  limit: number;
  offset: number;
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export async function fetchInstruments(): Promise<InstrumentList> {
  const response = await fetch(`${API_BASE}/v1/instruments`);
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  return response.json() as Promise<InstrumentList>;
}
