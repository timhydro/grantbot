from __future__ import annotations

import os
import unittest
from grantbot.knowledge.fact_registry import FactRegistry

class TestFactRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.test_db = "tests/test_facts.json"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self.registry = FactRegistry(data_path=self.test_db)

    def tearDown(self) -> None:
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_set_and_get_fact(self) -> None:
        self.registry.set_fact("tiny_homes_built", 12)
        self.assertEqual(self.registry.get_fact("tiny_homes_built"), 12)

if __name__ == "__main__":
    unittest.main()
