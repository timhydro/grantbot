import unittest

from grantbot.core.database import (
    initialize_database,
)
from grantbot.knowledge.seed_brokengrowth import (
    seed,
)
from grantbot.knowledge.question_bank import (
    question_count,
)
from grantbot.knowledge.repository import (
    get_fact,
    verified_facts,
    missing_facts,
)
from grantbot.knowledge.service import (
    knowledge_summary,
    readiness_score,
    grant_safe_profile,
)


class KnowledgeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        initialize_database()
        seed()

    def test_question_bank_is_large(self):
        self.assertGreaterEqual(
            question_count(),
            120,
        )

    def test_org_name(self):
        fact = get_fact(
            "organization_name"
        )

        self.assertEqual(
            fact["value"],
            "BrokenGrowthMinistries",
        )

        self.assertEqual(
            fact["status"],
            "APPROVED",
        )

    def test_funding_scope(self):
        fact = get_fact(
            "funding_source_scope"
        )

        self.assertIn(
            "angel investors",
            fact["value"],
        )

        self.assertIn(
            "county grants",
            fact["value"],
        )

        self.assertIn(
            "city and municipal grants",
            fact["value"],
        )

    def test_missing_queue(self):
        rows = missing_facts()

        self.assertGreater(
            len(rows),
            50,
        )

    def test_grant_safe(self):
        profile = grant_safe_profile()

        self.assertIn(
            "organization_name",
            profile,
        )

        self.assertNotIn(
            "employment_model",
            profile,
        )

    def test_readiness_score(self):
        result = readiness_score()

        self.assertIn(
            "score",
            result,
        )

        self.assertGreaterEqual(
            result["score"],
            0,
        )

        self.assertLessEqual(
            result["score"],
            100,
        )

    def test_summary(self):
        summary = knowledge_summary()

        self.assertGreaterEqual(
            summary["question_bank_size"],
            120,
        )


if __name__ == "__main__":
    unittest.main()
