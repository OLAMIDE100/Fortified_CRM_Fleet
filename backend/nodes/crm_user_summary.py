from pydantic import BaseModel, Field


class UserSummarySchema(BaseModel):
    profile_overview: str = Field(description="Short overview of the player based on CRM profile fields")
    interaction_insights: str = Field(description="Key themes from retrieved chat/transcript history")
    risk_and_opportunity: str = Field(description="Churn risk signals and retention opportunities")
    recommended_next_steps: list[str] = Field(description="Concrete next actions for the CRM team")
    executive_summary: str = Field(description="One-paragraph summary combining profile + RAG history")


USER_SUMMARY_INSTRUCTION = """
You are a CRM analyst. Summarize this player using BOTH their database profile and retrieved chat history.

--- CRM PROFILE ---
Lead ID: {lead_id}
Name: {lead_name}
Genre Preference: {game_preference}
Monthly Spend: ${monthly_spend}
Play Hours / Week: {play_hours}
Current Status: {status}
Qualification Score: {existing_qualification_score}
Existing Churn Risk: {existing_churn_risk_level}
--- END PROFILE ---

--- RETRIEVED CHAT HISTORY (RAG) ---
{formatted_context}
--- END HISTORY ---

Produce a clear, actionable summary for the CRM team.
"""
