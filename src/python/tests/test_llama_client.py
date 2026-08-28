import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.llama_client import LlamaClient


class TestLlamaClient(unittest.TestCase):
    def test_llama_client_mock_non_stream(self):
        mock_llama = MagicMock()
        mock_llama.create_chat_completion.return_value = {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello from Llama!"},
                    "finish_reason": "stop",
                }
            ]
        }

        with patch.object(LlamaClient, "_load_model"):
            client = LlamaClient(model_path="dummy.gguf")
            client.llama = mock_llama
            client.chat.completions.llama = mock_llama

            messages = [{"role": "system", "content": "You are AI."}, {"role": "user", "content": "Hello"}]
            response = client.chat.completions.create(messages=messages, temperature=0.1, stream=False)

            self.assertEqual(response.choices[0].message.content, "Hello from Llama!")
            self.assertEqual(response.choices[0].finish_reason, "stop")

    def test_llama_client_mock_stream(self):
        mock_llama = MagicMock()
        mock_llama.create_chat_completion.return_value = iter([
            {"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]},
            {"choices": [{"delta": {"content": " World"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        ])

        with patch.object(LlamaClient, "_load_model"):
            client = LlamaClient(model_path="dummy.gguf")
            client.llama = mock_llama
            client.chat.completions.llama = mock_llama

            messages = [{"role": "user", "content": "Hi"}]
            stream = client.chat.completions.create(messages=messages, stream=True)

            chunks = list(stream)
            self.assertEqual(len(chunks), 3)
            self.assertEqual(chunks[0].choices[0].delta.content, "Hello")
            self.assertEqual(chunks[1].choices[0].delta.content, " World")
            self.assertEqual(chunks[2].choices[0].finish_reason, "stop")


if __name__ == "__main__":
    unittest.main()
