from pydantic import BaseModel, Field


# ==========================================
# STRUCTURED SCHEMAS (Pydantic)
# ==========================================

class QualificationSchema(BaseModel):
    score: int = Field(description="Score from 0 to 100")
    reasoning: str = Field(description="Brief explanation for score")

class OutreachSchema(BaseModel):
    subject: str = Field(description="Compelling email subject line")
    body: str = Field(description="Personalized outreach body")

class CriticSchema(BaseModel):
    is_approved: bool = Field(description="True if draft meets criteria, False otherwise")
    feedback: str = Field(description="Detailed critique or guidance for improvement if rejected")


QUALIFY_INSTRUCTION = """
Score this player for premium outreach (0-100):
Name: {lead_name} | Favorite Genre: {game_preference} | Monthly Spend: ${monthly_spend} | Play Hours/Wk: {play_hours}

Criteria: Spend > $50 or Hours > 15 = Score >= 70.
Return a score and brief reasoning.
"""

OUTREACH_INSTRUCTION = """
Write a personalized outreach email to {lead_name} who loves {game_preference}.
Qualification Context: {qualification_reasoning}

Previous Feedback (if revising): {critic_feedback}

Ensure:
1. Short, engaging, and relevant to {game_preference}.
2. Clear call-to-action (CTA).
3. Do NOT sound overly generic or aggressive.
4. message must be between 30 and 100 words.
"""

CRITIC_INSTRUCTION = """
You are the Lead Marketing Manager reviewing an email draft written for player {lead_name}:

Subject: {outreach_subject}
Body: {outreach_body}

Rules for Approval:
- Must directly reference their preferred genre ({game_preference}).
- Must contain a clear CTA.
- Body must be between 30 and 100 words. Reject if greater than 100 words or less than 30 words.
"""
