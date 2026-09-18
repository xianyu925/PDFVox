import unittest

from app import tts_server
from app.version import __version__


class StandaloneTTSServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_endpoint_and_service_contract(self):
        health = await tts_server.health_check()

        self.assertEqual("ok", health["status"])
        self.assertEqual(__version__, health["version"])
        self.assertEqual(__version__, tts_server.app.version)
        self.assertTrue(hasattr(tts_server.tts_service, "synthesize_to_wav"))


if __name__ == "__main__":
    unittest.main()
