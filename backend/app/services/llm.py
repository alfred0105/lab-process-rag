from abc import ABC, abstractmethod

EVIDENCE_SYSTEM_INSTRUCTION = """You may reason only from the supplied evidence context. Do not use outside scientific knowledge as supporting evidence. Every scientific or process claim must cite one or more provided evidence IDs. If the evidence does not support the claim, return UNKNOWN. Do not invent citations. Do not infer exact numerical values unless they are present in evidence or calculated by the deterministic calculator."""

class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, evidence_context: list[dict]) -> dict:
        """Implementations must return validated evidence-bound claims."""
