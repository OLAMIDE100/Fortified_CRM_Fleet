export type CrmAction = "outreach" | "update" | "summarize";

export type LeadProfile = {
  id: string;
  name: string;
  email?: string | null;
  game_genre_preference?: string | null;
  monthly_spend?: number | null;
  play_time_hours_wk?: number | null;
  status?: string | null;
  qualification_score?: number | null;
  churn_risk_level?: string | null;
  last_outreach?: string | null;
};

export type LeadFilters = {
  game_genre_preference: string[];
  status: string[];
  churn_risk_level: string[];
};

export type LeadQuery = {
  limit?: number;
  id?: string;
  email?: string;
  game_genre_preference?: string;
  status?: string;
  churn_risk_level?: string;
};

export type CrmRunResponse = {
  action: string;
  lead_id: string;
  lead_name: string;
  lead_email: string;
  game_preference: string;
  monthly_spend: number;
  play_hours: number;
  status: string;
  qualification_score: number;
  qualification_reasoning: string;
  outreach_subject?: string | null;
  outreach_body?: string | null;
  critic_feedback?: string | null;
  is_approved: boolean;
  revision_attempts: number;
  email_sent: boolean;
  email_status: string;
  human_approved?: boolean | null;
  awaiting_human_approval?: boolean;
  thread_id?: string | null;
  sentiment: string;
  churn_risk: string;
  recurring_issues: string;
  summary: string;
  user_summary: string;
};

export type CrmBatchRunResponse = {
  action: string;
  count: number;
  results: CrmRunResponse[];
  pending_approvals?: number;
};

export type HumanDecision = "approve" | "reject";

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
    return JSON.stringify(data.detail ?? data);
  } catch {
    return res.statusText || "Request failed";
  }
}

export async function fetchLeadFilterOptions(): Promise<LeadFilters> {
  const res = await fetch("/api/v1/lead-filters");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchLeads(query: LeadQuery = {}): Promise<LeadProfile[]> {
  const params = new URLSearchParams();
  params.set("limit", String(query.limit ?? 150));
  if (query.id?.trim()) params.set("id", query.id.trim());
  if (query.email?.trim()) params.set("email", query.email.trim());
  if (query.game_genre_preference)
    params.set("game_genre_preference", query.game_genre_preference);
  if (query.status) params.set("status", query.status);
  if (query.churn_risk_level)
    params.set("churn_risk_level", query.churn_risk_level);

  const res = await fetch(`/api/v1/leads?${params}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function runCrm(
  leadIds: string[],
  action: CrmAction,
): Promise<CrmBatchRunResponse> {
  const body =
    action === "summarize"
      ? { action, lead_id: leadIds[0] }
      : { action, lead_ids: leadIds };

  const res = await fetch("/api/v1/crm/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function submitHumanDecision(
  threadId: string,
  decision: HumanDecision,
): Promise<CrmRunResponse> {
  const res = await fetch("/api/v1/crm/human-decision", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, decision }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}
