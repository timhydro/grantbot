from __future__ import annotations

import unittest
from unittest.mock import patch

from grantbot.discovery.grants_gov import (
    fetch_opportunity,
    normalize_opportunity,
    search_keyword,
)


SEARCH_RESPONSE = {
    "errorcode": 0,
    "msg": "Webservice Succeeds",
    "data": {
        "oppHits": [
            {
                "id": "12345",
                "number": "ABC-123",
                "title": "Reentry Workforce Program",
                "agencyCode": "HHS",
                "agencyName": "Health & Human Services",
                "openDate": "08/01/2026",
                "closeDate": "12/01/2099",
                "oppStatus": "posted",
            }
        ]
    },
}

DETAIL_RESPONSE = {
    "errorcode": 0,
    "msg": "Webservice Succeeds",
    "data": {
        "id": 12345,
        "opportunityNumber": "ABC-123",
        "opportunityTitle": "Reentry Workforce Program",
        "synopsis": {
            "agencyName": "Health & Human Services",
            "synopsisDesc": (
                "Supports reentry, homelessness, housing, "
                "employment and workforce development."
            ),
            "responseDateDesc": "12/01/2099",
            "awardCeiling": "500000",
            "awardFloor": "100000",
            "costSharing": False,
            "applicantTypes": [
                {
                    "id": "12",
                    "description": "Nonprofits having a 501(c)(3) status",
                }
            ],
        },
    },
}


class DiscoveryV6Tests(unittest.TestCase):
    @patch(
        "grantbot.discovery.grants_gov._post_json",
        return_value=SEARCH_RESPONSE,
    )
    def test_search_keyword(self, mock_post) -> None:
        hits = search_keyword(
            "reentry",
            rows=10,
        )

        self.assertEqual(
            len(hits),
            1,
        )

        self.assertEqual(
            hits[0]["id"],
            "12345",
        )

        mock_post.assert_called_once()

    @patch(
        "grantbot.discovery.grants_gov._post_json",
        return_value=DETAIL_RESPONSE,
    )
    def test_fetch_opportunity(self, mock_post) -> None:
        detail = fetch_opportunity(
            "12345"
        )

        self.assertEqual(
            detail["opportunityNumber"],
            "ABC-123",
        )

        mock_post.assert_called_once()

    def test_normalize(self) -> None:
        hit = SEARCH_RESPONSE[
            "data"
        ]["oppHits"][0]

        detail = DETAIL_RESPONSE[
            "data"
        ]

        opportunity = normalize_opportunity(
            hit,
            detail,
        )

        self.assertEqual(
            opportunity.id,
            "12345",
        )

        self.assertEqual(
            opportunity.amount,
            500000.0,
        )

        self.assertIn(
            "501(c)(3)",
            opportunity.eligibility,
        )

    def test_invalid_rows(self) -> None:
        with self.assertRaises(
            ValueError
        ):
            search_keyword(
                "reentry",
                rows=0,
            )


if __name__ == "__main__":
    unittest.main()
