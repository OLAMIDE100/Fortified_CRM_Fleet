from pydantic import BaseModel, Field

from helper_scripts.vector_search import search_player_history


def _retrieve_rag_context(lead_id: str) -> str:
    # Embeddings live in Postgres/pgvector (seed via data_ingestion/generate_embeddings.py)
    lag_contexts = search_player_history(
        lead_id, query="server lag crash connection latency performance", limit=3
    )
    billing_contexts = search_player_history(
        lead_id, query="price spend cost subscription refund billing", limit=2
    )
    combined = list(set(lag_contexts + billing_contexts))
    return "\n".join(combined) if combined else "No prior relevant history found."


class RAGTranscriptAnalysisResult(BaseModel):
    sentiment: str = Field(description="Overall sentiment based on history: Positive, Neutral, or Negative")
    churn_risk: str = Field(description="Risk rating: Low, Medium, High, or Critical")
    recurring_issues: list[str] = Field(description="List of persistent or recurring issues across historical logs")
    summary: str = Field(description="Contextual summary synthesizing past and recent player interactions")


RAG_TRANSCRIPT_INSTRUCTION = """
You are an advanced Customer Success AI Agent. Analyze the historical chat logs retrieved for player '{lead_name}' (ID: {lead_id}):

--- RETRIEVED HISTORICAL CHAT LOGS (RAG) ---
{formatted_context}
--- END CONTEXT ---

Analyze if there is a pattern of escalation or negative sentiment over time.
Identify specific recurring complaints and assess churn risk.
Respond strictly in JSON matching the schema.
"""
