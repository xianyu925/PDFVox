import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.credentials import LLM_KEY_NAME, TTS_KEY_NAME
from app.routers import app_settings
from app.services.settings_service import SettingsService


class MemoryCredentialStore:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return self.values.get(name)

    def set(self, name, value):
        self.values[name] = value

    def delete(self, name):
        self.values.pop(name, None)


class SettingsServiceTests(unittest.TestCase):
    def setUp(self):
        self.old_llm_key = settings.LLM_API_KEY
        self.old_tts_key = settings.TTS_API_KEY

    def tearDown(self):
        settings.LLM_API_KEY = self.old_llm_key
        settings.TTS_API_KEY = self.old_tts_key

    def test_saves_and_clears_api_keys_without_exposing_them(self):
        store = MemoryCredentialStore()
        service = SettingsService(store)

        status = service.save_api_keys("llm-secret", "tts-secret")

        self.assertTrue(status.configured)
        self.assertEqual("llm-secret", store.get(LLM_KEY_NAME))
        self.assertEqual("tts-secret", store.get(TTS_KEY_NAME))
        cleared = service.clear_api_keys()
        self.assertFalse(cleared.configured)
        self.assertEqual({}, store.values)

    def test_settings_endpoint_reconfigures_clients_after_saving(self):
        store = MemoryCredentialStore()
        api = FastAPI()
        api.include_router(app_settings.router, prefix="/settings")

        with (
            patch.object(app_settings, "service", SettingsService(store)),
            patch.object(app_settings, "reconfigure_api_clients") as reconfigure,
        ):
            response = TestClient(api).post(
                "/settings/configure",
                json={
                    "llm_api_key": "llm-secret",
                    "tts_api_key": "tts-secret",
                },
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual({"configured": True}, response.json())
        reconfigure.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
