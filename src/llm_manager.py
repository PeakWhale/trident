from crewai import LLM

def get_ollama():
    """Returns the Local Llama 3.1 8B Model via CrewAI's LLM wrapper"""
    return LLM(
        model="ollama/llama3.1:8b",
        base_url="http://localhost:11434"
    )
