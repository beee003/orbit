import type { PersonInfo } from "@/types/orbit";

function getBaseUrl(): string {
  if (import.meta.env.VITE_ENRICHMENT_URL) return import.meta.env.VITE_ENRICHMENT_URL;
  if (import.meta.env.VITE_WS_URL)
    return import.meta.env.VITE_WS_URL.replace(/^ws/, "http").replace(/\/ws$/, "");
  return `${location.protocol}//${location.host}`;
}

export interface EnrichResult {
  info: PersonInfo | null;
  linkedinAuth: boolean;
}

export async function enrichPersonByName(
  name: string,
): Promise<PersonInfo | null> {
  const url = `${getBaseUrl().replace(/\/$/, "")}/api/enrich`;

  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });

  if (!res.ok) {
    throw new Error(`Enrichment failed: ${res.status} ${res.statusText}`);
  }

  const data = (await res.json()) as EnrichResult;
  return data.info ?? null;
}
