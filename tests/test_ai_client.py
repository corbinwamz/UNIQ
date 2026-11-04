import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from app.ai_client import AIError, GeminiClient, SMOKE_SCHEMA
from app.config import ai_settings


class AIClientTests(unittest.TestCase):
    def test_rest_shape_and_structured_response(self):
        requests = []
        def transport(request, timeout):
            requests.append((request, timeout))
            return io.BytesIO(json.dumps({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"ok":true}'}]}}]}).encode())
        client = GeminiClient({"GEMINI_API_KEY": "test-secret", "GEMINI_MODEL": "test-model"}, transport)
        self.assertTrue(client.smoke_test()["ok"])
        request, timeout = requests[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent")
        self.assertNotIn("test-secret", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "test-secret")
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["responseJsonSchema"], SMOKE_SCHEMA)
        self.assertIn("systemInstruction", payload)
        self.assertEqual(timeout, 90)

    def test_missing_configuration_and_sanitized_error(self):
        with self.assertRaises(AIError):
            GeminiClient({}).require_configuration()
        def transport(request, timeout):
            raise HTTPError(request.full_url, 401, "test-secret", {}, None)
        with self.assertRaises(AIError) as error:
            GeminiClient({"GEMINI_API_KEY": "test-secret", "GEMINI_MODEL": "test-model"}, transport).smoke_test()
        self.assertNotIn("test-secret", str(error.exception))

    def test_incomplete_refusal_and_bad_json(self):
        for response in ({"candidates": [{"finishReason": "MAX_TOKENS"}]}, {"promptFeedback": {"blockReason": "SAFETY"}}, {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not json"}]}}]}):
            with self.subTest(response=response), self.assertRaises(AIError):
                GeminiClient({"GEMINI_API_KEY": "test", "GEMINI_MODEL": "test"}, lambda *args, **kwargs: io.BytesIO(json.dumps(response).encode())).smoke_test()

    def test_dotenv_loading_and_shell_precedence(self):
        # Mock file IO so this check never reads or writes a real secret file.
        text = '# local\nGEMINI_API_KEY="test-local"\nGEMINI_MODEL=local-model\nOPENAI_API_KEY=ignored-old-key\nIGNORED=anything\n'
        with patch.object(Path, "exists", return_value=True), patch.object(Path, "read_text", return_value=text), patch.dict("os.environ", {"GEMINI_MODEL": "shell-model"}, clear=True):
            values = ai_settings()
        self.assertEqual(values, {"GEMINI_API_KEY": "test-local", "GEMINI_MODEL": "shell-model"})

    def test_thoughts_are_not_parsed_as_final_json(self):
        response = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "private thought", "thought": True}, {"text": '{"ok":true}'}]}}]}
        client = GeminiClient({"GEMINI_API_KEY": "test", "GEMINI_MODEL": "models/test-model"}, lambda *args, **kwargs: io.BytesIO(json.dumps(response).encode()))
        self.assertTrue(client.smoke_test()["ok"])


if __name__ == "__main__":
    unittest.main()
