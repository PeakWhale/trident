from typing import TypedDict
from langgraph.graph import StateGraph, END
from medical_crew import run_medical_analysis
from hospital_mcp import get_patient_record, get_treatment_considerations
from autogen_review import run_qa_review, get_review_summary


class TridentState(TypedDict):
    patient_id: str
    symptoms: str
    patient_history: str
    treatment_considerations: str
    final_diagnosis: str
    action_plan: str
    # AutoGen QA Review fields
    qa_validated: bool
    qa_confidence: str
    qa_notes: str


def gather_patient_context(state: TridentState):
    """First node: Gather patient history and treatment considerations."""
    patient_id = state['patient_id']
    
    # Get patient record
    patient_history = get_patient_record(patient_id)
    print(f"\n[TRIDENT] Retrieved patient record: {patient_history}")
    
    # Get treatment considerations based on history
    treatment_considerations = get_treatment_considerations(patient_id)
    print(f"\n[TRIDENT] Treatment considerations: {treatment_considerations[:100]}...")
    
    return {
        "patient_history": patient_history,
        "treatment_considerations": treatment_considerations
    }


def call_medical_crew(state: TridentState):
    """Second node: Run CrewAI agents to determine triage level."""
    print(f"\n[CREWAI] Activating Medical Team (Triage Nurse + ER Physician)...")
    
    # Pass both symptoms and patient history to the medical crew
    result = run_medical_analysis(
        state['symptoms'], 
        state['patient_id'],
        state.get('patient_history', '')
    )
    
    # Parse Result
    text = str(result).upper()
    level = "GREEN"
    if "RED" in text: level = "RED"
    elif "YELLOW" in text: level = "YELLOW"
        
    return {"final_diagnosis": level}


def route_logic(state: TridentState):
    """Route to appropriate action node based on diagnosis."""
    level = state.get('final_diagnosis', 'GREEN')
    if level == "RED": return "emergency"
    elif level == "YELLOW": return "urgent"
    else: return "routine"


def node_emergency(state: TridentState):
    """RED path: Emergency response with treatment considerations."""
    base_plan = "EMERGENCY RESPONSE: Dispatch ambulance immediately (911)"
    
    considerations = state.get('treatment_considerations', '')
    if considerations and "no significant medical history" not in considerations.lower():
        plan = f"{base_plan}\n\n{considerations}"
    else:
        plan = f"{base_plan}\n\nNo special treatment considerations."
    
    return {"action_plan": plan}


def node_urgent(state: TridentState):
    """YELLOW path: Urgent care referral with treatment considerations."""
    base_plan = "URGENT CARE: Refer to urgent care facility within 2 hours"
    
    considerations = state.get('treatment_considerations', '')
    if considerations and "no significant medical history" not in considerations.lower():
        plan = f"{base_plan}\n\n{considerations}"
    else:
        plan = f"{base_plan}\n\nNo special treatment considerations."
    
    return {"action_plan": plan}


def node_routine(state: TridentState):
    """GREEN path: Home care with treatment considerations."""
    base_plan = "ROUTINE CARE: Home care instructions with follow-up as needed"
    
    considerations = state.get('treatment_considerations', '')
    if considerations and "no significant medical history" not in considerations.lower():
        plan = f"{base_plan}\n\n{considerations}"
    else:
        plan = f"{base_plan}\n\nNo special treatment considerations."
    
    return {"action_plan": plan}


def autogen_qa_review(state: TridentState):
    """
    Final node: AutoGen Quality Assurance Review
    
    Uses Microsoft AutoGen agents (QA Reviewer + Clinical Auditor)
    to validate the CrewAI triage decision.
    """
    print(f"\n[AUTOGEN] Running QA Review (QA Reviewer + Clinical Auditor)...")
    
    review_result = run_qa_review(
        symptoms=state['symptoms'],
        crewai_decision=state['final_diagnosis'],
        patient_history=state.get('patient_history', ''),
        treatment_considerations=state.get('treatment_considerations', '')
    )
    
    print(get_review_summary(review_result))
    
    return {
        "qa_validated": review_result['validated'],
        "qa_confidence": review_result['confidence'],
        "qa_notes": review_result['review_notes']
    }


# Build the workflow
workflow = StateGraph(TridentState)

# Add nodes
workflow.add_node("gather_context", gather_patient_context)
workflow.add_node("medical_board", call_medical_crew)  # CrewAI
workflow.add_node("emergency", node_emergency)
workflow.add_node("urgent", node_urgent)
workflow.add_node("routine", node_routine)
workflow.add_node("qa_review", autogen_qa_review)  # AutoGen

# Set entry point and edges
workflow.set_entry_point("gather_context")
workflow.add_edge("gather_context", "medical_board")
workflow.add_conditional_edges("medical_board", route_logic, {
    "emergency": "emergency", "urgent": "urgent", "routine": "routine"
})
# All action nodes flow to QA review
workflow.add_edge("emergency", "qa_review")
workflow.add_edge("urgent", "qa_review")
workflow.add_edge("routine", "qa_review")
workflow.add_edge("qa_review", END)

# Compile
app = workflow.compile()


def process_patient_request(patient_id, symptoms):
    """Main entry point for processing a patient triage request."""
    return app.invoke({
        "patient_id": patient_id, 
        "symptoms": symptoms,
        "patient_history": "",
        "treatment_considerations": "",
        "final_diagnosis": "",
        "action_plan": "",
        "qa_validated": False,
        "qa_confidence": "",
        "qa_notes": ""
    })
