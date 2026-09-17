import unittest
from unittest.mock import patch

from app.services.asr_service import ASRService


class ASRServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_models_are_not_loaded_during_construction(self):
        with patch("app.services.asr_service.load_silero_vad") as loader:
            service = ASRService()

        loader.assert_not_called()
        self.assertIsNone(service.vad_model)
        self.assertIsNone(service.whisper_model)

    async def test_empty_audio_is_rejected_without_loading_models(self):
        service = ASRService()
        with patch.object(service, "_get_vad") as vad_loader, patch.object(
            service, "_get_whisper"
        ) as whisper_loader:
            self.assertFalse(await service.detect_speaking_from_pcm(b""))
            self.assertEqual("", await service.transcribe_pcm_to_text(b""))

        vad_loader.assert_not_called()
        whisper_loader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
