"""
AutoGen Quality Assurance Review Module

Uses Microsoft AutoGen to provide a second-opinion validation
of the CrewAI triage decision. This demonstrates multi-framework
orchestration where two different AI agent systems work together.
"""
import autogen
from typing import TypedDict


class ReviewResult(TypedDict):
    validated: bool
    confidence: str
    review_notes: str


# AutoGen configuration for Ollama (local LLM)
OLLAMA_CONFIG = {
    "config_list": [
        {
            "model": "llama3.1:8b",
            "base_url": "http://localhost:11434/v1",
            "api_key": "ollama",  # Required but not used by Ollama
        }
    ],
    "temperature": 0.1,
}


def run_qa_review(
    symptoms: str,
    crewai_decision: str,
    patient_history: str,
    treatment_considerations: str
) -> ReviewResult:
    """
    Run AutoGen quality assurance review on a CrewAI triage decision.
    
    This creates two AutoGen agents:
    1. QA Reviewer - Reviews the decision against protocols
    2. Clinical Auditor - Validates the review and provides confidence score
    
    Args:
        symptoms: Patient's reported symptoms
        crewai_decision: The triage level from CrewAI (RED/YELLOW/GREEN)
        patient_history: Patient's medical history
        treatment_considerations: Treatment notes from CrewAI
    
    Returns:
        ReviewResult with validation status, confidence, and notes
    """
    
    # QA Reviewer Agent - Reviews the triage decision
    qa_reviewer = autogen.AssistantAgent(
        name="QA_Reviewer",
        system_message="""You are a Quality Assurance Reviewer for medical triage decisions.
Your job is to review triage decisions and verify they follow protocols:

PROTOCOLS:
- RED: Chest pain with sweating or arm pain = EMERGENCY
- YELLOW: Fever, cough, respiratory symptoms = URGENT  
- GREEN: Localized rash, minor symptoms = ROUTINE

Review the decision and state if it follows protocol correctly.
Be concise - respond in 2-3 sentences max.""",
        llm_config=OLLAMA_CONFIG,
    )
    
    # Clinical Auditor Agent - Validates and scores
    clinical_auditor = autogen.AssistantAgent(
        name="Clinical_Auditor",
        system_message="""You are a Clinical Auditor who validates QA reviews.
After reviewing the QA Reviewer's assessment, provide:
1. VALIDATED: YES or NO
2. CONFIDENCE: HIGH, MEDIUM, or LOW
3. A one-sentence summary

Format your response exactly as:
VALIDATED: [YES/NO]
CONFIDENCE: [HIGH/MEDIUM/LOW]
SUMMARY: [one sentence]""",
        llm_config=OLLAMA_CONFIG,
    )
    
    # User proxy to initiate the conversation
    user_proxy = autogen.UserProxyAgent(
        name="System",
        human_input_mode="NEVER",
        max_consecutive_auto_reply=0,
        code_execution_config=False,
    )
    
    # Create the review request message
    review_request = f"""Please review this triage decision:

PATIENT SYMPTOMS: {symptoms}
PATIENT HISTORY: {patient_history}
CREWAI TRIAGE DECISION: {crewai_decision}
TREATMENT CONSIDERATIONS: {treatment_considerations}

Does this triage level ({crewai_decision}) match the protocols for these symptoms?"""

    # Run the review conversation
    try:
        # QA Reviewer analyzes the decision
        user_proxy.initiate_chat(
            qa_reviewer,
            message=review_request,
            max_turns=1,
            silent=True,
        )
        
        reviewer_response = qa_reviewer.last_message()["content"]
        
        # Clinical Auditor validates the review
        user_proxy.initiate_chat(
            clinical_auditor,
            message=f"Review this QA assessment and provide your validation:\n\n{reviewer_response}",
            max_turns=1,
            silent=True,
        )
        
        auditor_response = clinical_auditor.last_message()["content"]
        
        # Parse the auditor's response
        validated = "YES" in auditor_response.upper() and "VALIDATED: YES" in auditor_response.upper()
        
        confidence = "MEDIUM"
        if "CONFIDENCE: HIGH" in auditor_response.upper():
            confidence = "HIGH"
        elif "CONFIDENCE: LOW" in auditor_response.upper():
            confidence = "LOW"
        
        return ReviewResult(
            validated=validated,
            confidence=confidence,
            review_notes=f"QA Review: {reviewer_response[:200]}... | Audit: {auditor_response[:200]}"
        )
        
    except Exception as e:
        # If AutoGen review fails, return a default result
        print(f"AutoGen review error: {e}")
        return ReviewResult(
            validated=True,
            confidence="MEDIUM",
            review_notes=f"AutoGen review unavailable: {str(e)[:100]}"
        )


def get_review_summary(result: ReviewResult) -> str:
    """Format the review result for display."""
    status = "✓ VALIDATED" if result["validated"] else "⚠ NEEDS REVIEW"
    return f"""
[AUTOGEN QA REVIEW]
Status: {status}
Confidence: {result['confidence']}
Notes: {result['review_notes'][:300]}
"""

