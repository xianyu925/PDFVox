import unittest
from unittest.mock import Mock, patch

from app.services.asr_service import ASRService


class ASRServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_models_are_not_loaded_during_construction(self):
        service = ASRService()

        self.assertIsNone(service._vad_function)
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

    def test_vad_uses_faster_whisper_without_torch(self):
        service = ASRService()
        service._vad_options = object()
        detector = Mock(return_value=[{"start": 0, "end": 10}])
        pcm = (1000).to_bytes(2, "little", signed=True) * 512

        with patch.object(service, "_get_vad", return_value=detector):
            result = service._vad_check(pcm, 16_000)

        self.assertTrue(result)
        samples, options = detector.call_args.args
        self.assertEqual((512,), samples.shape)
        self.assertIs(service._vad_options, options)
        self.assertEqual(16_000, detector.call_args.kwargs["sampling_rate"])


if __name__ == "__main__":
    unittest.main()
