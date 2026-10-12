"""PEAKWHALE(TM) TRIDENT - a fail-safe "AI plus rules" triage engine.

The LLM only reads the text and picks a category. Rules from an editable
rule pack decide the level and the action. A second LLM check reviews
the decision. Anything unclear goes to a human.
"""

__version__ = "0.2.0"

HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
DECIDED = "DECIDED"
