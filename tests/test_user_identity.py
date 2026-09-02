import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from app import create_app
from routes.b30_ebeam import _dataset_to_row as ebeam_dataset_to_row
from routes.b30_sem import _dataset_to_row as sem_dataset_to_row
from routes.b30_sputter import _dataset_to_row as sputter_dataset_to_row
from routes.shared import format_user


class UserLoginTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = self.app.test_client()
        self.user = {
            "unique_id": "0000-0001-2345-6789",
            "email": "first.last@lbl.gov",
            "username": "firstlast",
            "first_name": "First",
            "last_name": "Lastname",
        }

    def test_login_accepts_email_or_username(self):
        for user_ref in ("first.last@lbl.gov", "firstlast"):
            with self.subTest(user_ref=user_ref), \
                 patch("routes.shared.cruc_client.users.get", return_value=self.user) as get_user, \
                 patch("routes.shared.cruc_client.projects.list", return_value=[{"project_id": "project-1"}]):
                response = self.client.post("/api/user/login", json={"user_ref": user_ref})

            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            payload = response.get_json()
            self.assertEqual(payload["user_name"], "First Lastname (@firstlast)")
            self.assertEqual(payload["login_reference"], user_ref)
            self.assertEqual(payload["username"], "firstlast")
            get_user.assert_called_once_with(user_ref)

    def test_legacy_email_request_field_remains_accepted(self):
        with patch("routes.shared.cruc_client.users.get", return_value=self.user) as get_user, \
             patch("routes.shared.cruc_client.projects.list", return_value=[]):
            response = self.client.post("/api/user/login", json={"email": self.user["email"]})

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        get_user.assert_called_once_with(self.user["email"])

    def test_login_forms_submit_on_enter(self):
        for url in (
            "/b30-sem/",
            "/b30-ebeam/",
            "/b30-aja-sputter/",
            "/giwaxs/",
            "/rga/",
            "/print/",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                html = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertIn('onsubmit="loginUser(event)"', html)
                self.assertIn('<button type="submit" class="btn btn-primary">Login</button>', html)


class UserDisplayTests(unittest.TestCase):
    def setUp(self):
        self.owner = {
            "unique_id": "0000-0001-2345-6789",
            "username": "firstlast",
            "first_name": "First",
            "last_name": "Lastname",
        }
        self.dataset = {
            "owner": self.owner,
            "owner_orcid": self.owner["unique_id"],
            "scientific_metadata": {},
            "timestamp": "2026-09-02T10:00:00-07:00",
        }

    def test_formats_api_user(self):
        self.assertEqual(format_user(self.owner), "First Lastname (@firstlast)")
        self.assertEqual(format_user(None, self.owner["unique_id"]), self.owner["unique_id"])

    def test_b30_logbooks_use_api_owner(self):
        self.assertEqual(sputter_dataset_to_row(self.dataset)["User"], "First Lastname (@firstlast)")
        self.assertEqual(ebeam_dataset_to_row(self.dataset)["User"], "First Lastname (@firstlast)")
        self.assertEqual(sem_dataset_to_row(self.dataset)["User"], "First Lastname (@firstlast)")


if __name__ == "__main__":
    unittest.main()
