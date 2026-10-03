export type RunStatus =
  | "running"
  | "awaiting_approval"
  | "completed"
  | "blocked"
  | "error";

export interface Seo {
  title: string;
  metadata: string;
  keywords: string[];
  slug: string;
}

export interface RunValues {
  topic?: string;
  initial_route?: string;
  research_notes?: string;
  plan?: { tasks: string[]; node: string }[];
  markdown_content?: string;
  writer_editor_iterations?: number;
  writer_human_iterations?: number;
  editor_feedback?: string;
  editor_score?: number;
  seo?: Seo;
  human_approval?: { human_approved: boolean; human_feedback: string | null };
}

export interface Run {
  thread_id: string;
  status: RunStatus;
  values: RunValues;
  interrupt: { approval: string; "markdown content": string } | null;
  error: string | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export const startRun = (topic: string) =>
  request<{ thread_id: string }>("/runs", {
    method: "POST",
    body: JSON.stringify({ topic }),
  });

export const getRun = (id: string) => request<Run>(`/runs/${id}`);

export const resumeRun = (id: string, approved: boolean, feedback?: string) =>
  request<{ status: string }>(`/runs/${id}/resume`, {
    method: "POST",
    body: JSON.stringify({ approved, feedback: feedback || null }),
  });
