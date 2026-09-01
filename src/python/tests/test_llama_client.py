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


class TestLlamaClientMultimodalStripping(unittest.TestCase):
    """本地文字模型看不懂 image_url parts，這裡只該把它們安全地丟掉、保留文字部分。

    圖片存成暫存檔＋附上呼叫視覺工具的說明，現在統一在 _build_user_content
    （agent_llm_client.py）那一層處理，跟用哪個 client 無關；到了這裡收到的
    content parts 時，那段說明早就已經是一個 type: text 的 part 了，所以這裡
    的職責很單純：把所有 text parts 接起來、把 image_url parts 丟掉。
    """

    def _make_client_with_mock(self, response_content="ok"):
        mock_llama = MagicMock()
        mock_llama.create_chat_completion.return_value = {
            "choices": [{"message": {"content": response_content}, "finish_reason": "stop"}]
        }
        with patch.object(LlamaClient, "_load_model"):
            client = LlamaClient(model_path="dummy.gguf")
        client.llama = mock_llama
        client.chat.completions.llama = mock_llama
        return client, mock_llama

    def test_image_url_part_is_dropped_text_parts_are_kept_and_joined(self):
        client, mock_llama = self._make_client_with_mock()
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": "這張截圖是什麼？"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
                {"type": "text", "text": "[系統：這則訊息附上了 1 張圖片，已存成暫存檔：\n- /tmp/x.png\n如果你看不到圖片內容，請呼叫 analyze_image_visuals(...)]"},
            ]},
        ]

        client.chat.completions.create(messages=messages, stream=False)

        sent_content = mock_llama.create_chat_completion.call_args.kwargs["messages"][0]["content"]
        self.assertIn("這張截圖是什麼", sent_content)
        # 上游已經組好的說明文字（本身就是 type: text）應該原封不動被保留、送到模型
        self.assertIn("analyze_image_visuals", sent_content)
        self.assertIn("/tmp/x.png", sent_content)
        # image_url 本身的原始資料不該出現在送給模型的文字裡
        self.assertNotIn("aGVsbG8=", sent_content)

    def test_text_only_message_unaffected(self):
        """純文字訊息（content 直接是字串，不是 list）不該被這段邏輯影響。"""
        client, mock_llama = self._make_client_with_mock()
        messages = [{"role": "user", "content": "普通的文字訊息，沒有附圖"}]

        client.chat.completions.create(messages=messages, stream=False)

        sent_content = mock_llama.create_chat_completion.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(sent_content, "普通的文字訊息，沒有附圖")

    def test_only_image_url_parts_no_text_falls_back_to_str_content(self):
        """理論上不該發生（_build_user_content 一定會有至少一個 text part），
        但防禦性地確保就算真的整個 content 都沒有 text part，也不會拋例外。
        """
        client, mock_llama = self._make_client_with_mock()
        messages = [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}},
            ]},
        ]

        client.chat.completions.create(messages=messages, stream=False)  # 不該拋例外
        sent_content = mock_llama.create_chat_completion.call_args.kwargs["messages"][0]["content"]
        self.assertNotIn("aGVsbG8=", sent_content)


if __name__ == "__main__":
    unittest.main()
