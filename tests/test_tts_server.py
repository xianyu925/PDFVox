import unittest

from app import tts_server


class StandaloneTTSServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_endpoint_and_service_contract(self):
        health = await tts_server.health_check()

        self.assertEqual("ok", health["status"])
        self.assertEqual("1.0.0", health["version"])
        self.assertEqual("1.0.0", tts_server.app.version)
        self.assertTrue(hasattr(tts_server.tts_service, "synthesize_to_wav"))


if __name__ == "__main__":
    unittest.main()
