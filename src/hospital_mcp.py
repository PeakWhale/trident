from mcp.server.fastmcp import FastMCP

# Define the Service
mcp = FastMCP("Trident Hospital DB")

# Mock Patient Records
PATIENT_DB = {
    "P-101": {"name": "Sarah Connor", "history": "Hypertension, Penicillin Allergy", "age": 45},
    "P-102": {"name": "Logan Roy", "history": "Previous Stroke, Diabetes Type 2", "age": 82},
    "P-999": {"name": "Doe John", "history": "None", "age": 25}
}

# Treatment contraindications and considerations based on patient history
TREATMENT_RULES = {
    "penicillin allergy": {
        "avoid": ["Penicillin", "Amoxicillin", "Ampicillin"],
        "use_instead": "Azithromycin or Fluoroquinolones",
        "note": "ALLERGY ALERT: Avoid all penicillin-based antibiotics"
    },
    "hypertension": {
        "monitor": "Blood pressure",
        "caution": ["NSAIDs", "Decongestants"],
        "note": "Monitor BP closely; avoid medications that raise blood pressure"
    },
    "diabetes": {
        "monitor": "Blood glucose levels",
        "caution": ["Corticosteroids", "High-dose diuretics"],
        "note": "Check blood glucose; steroids may elevate sugar levels"
    },
    "previous stroke": {
        "monitor": "Neurological status",
        "priority": "High - assess for new stroke symptoms",
        "note": "High risk patient; rapid neuro assessment required"
    }
}


@mcp.tool()
def get_patient_record(patient_id: str) -> str:
    """Retrieves confidential medical history for a given Patient ID."""
    record = PATIENT_DB.get(patient_id)
    if not record:
        return "No record found."
    return f"Patient: {record['name']}, Age: {record['age']}, Medical History: {record['history']}"


@mcp.tool()
def get_treatment_considerations(patient_id: str) -> str:
    """
    Analyzes patient history and returns treatment considerations,
    contraindications, and monitoring requirements.
    """
    record = PATIENT_DB.get(patient_id)
    if not record:
        return "No patient record found. Proceed with standard treatment protocols."
    
    history = record.get("history", "").lower()
    considerations = []
    
    # Check each known condition
    for condition, rules in TREATMENT_RULES.items():
        if condition in history:
            consideration = f"[{condition.upper()}]\n"
            if "avoid" in rules:
                consideration += f"  - AVOID: {', '.join(rules['avoid'])}\n"
            if "use_instead" in rules:
                consideration += f"  - USE INSTEAD: {rules['use_instead']}\n"
            if "monitor" in rules:
                consideration += f"  - MONITOR: {rules['monitor']}\n"
            if "caution" in rules:
                consideration += f"  - CAUTION WITH: {', '.join(rules['caution'])}\n"
            if "priority" in rules:
                consideration += f"  - PRIORITY: {rules['priority']}\n"
            consideration += f"  - NOTE: {rules['note']}"
            considerations.append(consideration)
    
    if not considerations:
        return f"Patient {record['name']} has no significant medical history. Standard treatment protocols apply."
    
    return f"TREATMENT CONSIDERATIONS FOR {record['name']}:\n\n" + "\n\n".join(considerations)


@mcp.tool()
def get_triage_guidelines(symptom: str) -> str:
    """Returns clinical protocols for specific symptoms. MUST follow these exactly."""
    s = symptom.lower()
    
    # RED is ONLY for cardiac emergencies - chest + sweating/arm pain
    if "chest" in s or "cardiac" in s or "heart" in s or "arm pain" in s or "sweating" in s or "diaphoresis" in s or "crushing" in s or "radiating" in s:
        return "RED PROTOCOL: Chest pain with sweating or arm pain = RED EMERGENCY. Output: RED"
    
    # YELLOW is for respiratory/fever - NOT RED
    if "fever" in s or "cough" in s or "spo2" in s or "respiratory" in s or "breath" in s:
        return "YELLOW PROTOCOL: Fever/Cough/Low SPO2 WITHOUT chest pain = YELLOW URGENT (not RED). Output: YELLOW"
    
    # GREEN is for skin/minor issues
    if "rash" in s or "itch" in s or "skin" in s or "gardening" in s or "allergy" in s or "dermat" in s:
        return "GREEN PROTOCOL: Localized rash/dermatological issue with no systemic symptoms = GREEN ROUTINE. Output: GREEN"
    
    return "PROTOCOL: Assess symptom severity and choose appropriate level."


if __name__ == "__main__":
    mcp.run()
