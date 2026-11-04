import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from app.ai_client import AIError, OpenAIClient, SMOKE_SCHEMA
from app.config import ai_settings


class AIClientTests(unittest.TestCase):
    def test_rest_shape_and_structured_response(self):
        requests = []
        def transport(request, timeout):
            requests.append((request, timeout))
            return io.BytesIO(json.dumps({"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"ok":true}'}]}]}).encode())
        client = OpenAIClient({"OPENAI_API_KEY": "test-secret", "OPENAI_MODEL": "test-model"}, transport)
        self.assertTrue(client.smoke_test()["ok"])
        request, timeout = requests[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(payload["text"]["format"]["schema"], SMOKE_SCHEMA)
        self.assertEqual(timeout, 90)

    def test_missing_configuration_and_sanitized_error(self):
        with self.assertRaises(AIError):
            OpenAIClient({}).require_configuration()
        def transport(request, timeout):
            raise HTTPError(request.full_url, 401, "test-secret", {}, None)
        with self.assertRaises(AIError) as error:
            OpenAIClient({"OPENAI_API_KEY": "test-secret", "OPENAI_MODEL": "test-model"}, transport).smoke_test()
        self.assertNotIn("test-secret", str(error.exception))

    def test_incomplete_refusal_and_bad_json(self):
        for response in ({"status": "incomplete"}, {"status": "completed", "output": [{"content": [{"type": "refusal"}]}]}, {"status": "completed", "output": [{"content": [{"type": "output_text", "text": "not json"}]}]}):
            with self.subTest(response=response), self.assertRaises(AIError):
                OpenAIClient({"OPENAI_API_KEY": "test", "OPENAI_MODEL": "test"}, lambda *args, **kwargs: io.BytesIO(json.dumps(response).encode())).smoke_test()

    def test_dotenv_loading_and_shell_precedence(self):
        # Mock file IO so this check never reads or writes a real secret file.
        text = '# local\nOPENAI_API_KEY="test-local"\nOPENAI_MODEL=local-model\nIGNORED=anything\n'
        with patch.object(Path, "exists", return_value=True), patch.object(Path, "read_text", return_value=text), patch.dict("os.environ", {"OPENAI_MODEL": "shell-model"}, clear=True):
            values = ai_settings()
        self.assertEqual(values, {"OPENAI_API_KEY": "test-local", "OPENAI_MODEL": "shell-model"})


if __name__ == "__main__":
    unittest.main()
