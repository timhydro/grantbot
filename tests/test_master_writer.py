import unittest
import json

from grantbot.writing.master_writer import write_answer


class MockProvider:
    def __init__(self):
        self.config = {"provider": "mock", "model": "mock-1"}

    def health(self):
        return {"available": True, "model_installed": True}

    def generate(self, prompt: str, system: str, temperature: float = 0.3, max_tokens=None) -> str:
        # Return a deterministic JSON envelope matching the expected schema
        envelope = {
            "draft": "Community need: This community faces a shortage of transitional housing and job supports.",
            "facts_used": ["f1"],
            "style": {"tone": "professional", "persuasion_level": "moderate"},
            "checks": {"no_invented_numbers": True},
        }
        return json.dumps(envelope)


class MasterWriterTests(unittest.TestCase):
    def test_structured_output_and_facts_used(self):
        facts = [
            {"id": "f1", "value": "Community transitional housing shortage.", "status": "VERIFIED", "category": "need", "key": "stat1", "source": "internal"}
        ]
        result = write_answer(
            question="Describe the community need",
            section="statement_of_need",
            facts=facts,
            provider=MockProvider(),
        )
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.draft)
        self.assertIn("Community need", result.draft)
        # facts_used should map to fact objects and include the fact with id f1
        self.assertTrue(any(f.get("id") == "f1" for f in result.facts_used))
        # quality should be present as a dict-like
        self.assertIsNotNone(result.quality)
        # status should be either READY_FOR_HUMAN_REVIEW or REVISION_REQUIRED
        self.assertIn(result.status, {"READY_FOR_HUMAN_REVIEW", "REVISION_REQUIRED"})


if __name__ == "__main__":
    unittest.main()
