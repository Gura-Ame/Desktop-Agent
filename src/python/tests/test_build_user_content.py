import base64
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.agent_llm_client import AgentLLMClientMixin


class _FakeAgent(AgentLLMClientMixin):
    def __init__(self):
        self.logs = []

    def emit(self, event_type, data):
        self.logs.append((event_type, data))


class TestBuildUserContentImageHandling(unittest.TestCase):
    """_build_user_content 是唯一一個組「使用者這輪訊息」的地方，不管接下來走哪個
    client（本地 Llama 直接載入、還是 remote_api 指到任何 OpenAI 相容端點）都會
    先經過這裡。圖片存成暫存檔＋附上呼叫視覺工具的說明文字，統一在這裡處理一次，
    而不是每個 client adapter 各做各的——這樣不管背後是不是真的多模態模型，
    模型都至少有辦法透過文字＋工具呼叫「看到」使用者附的圖，不會被靜悄悄地丟掉。
    """

    def _png_data_url(self, raw: bytes) -> str:
        return f"data:image/png;base64,{base64.b64encode(raw).decode()}"

    def test_no_images_returns_plain_text_unchanged(self):
        agent = _FakeAgent()
        result = agent._build_user_content("普通問題", images=[])
        self.assertEqual(result, "普通問題")
        self.assertEqual(agent._build_user_content("普通問題", images=None), "普通問題")

    def test_image_produces_multimodal_parts_including_raw_image_url(self):
        """多模態模型還是要能直接拿到原始 image_url part——這個修正不能反而讓
        真正支援看圖的模型也看不到圖片本身。
        """
        agent = _FakeAgent()
        raw = b"\x89PNG\r\n\x1a\n" + b"fakeimg"
        result = agent._build_user_content("這是什麼？", images=[self._png_data_url(raw)])

        self.assertIsInstance(result, list)
        image_parts = [p for p in result if p.get("type") == "image_url"]
        self.assertEqual(len(image_parts), 1)
        self.assertIn(base64.b64encode(raw).decode(), image_parts[0]["image_url"]["url"])

    def test_image_saved_to_temp_file_with_correct_bytes(self):
        agent = _FakeAgent()
        raw = b"\x89PNG\r\n\x1a\n" + b"realbytes12345"
        result = agent._build_user_content("看看這張圖", images=[self._png_data_url(raw)])

        note_parts = [p["text"] for p in result if p.get("type") == "text"]
        note = "\n".join(note_parts)
        self.assertIn("analyze_image_visuals", note)
        self.assertIn("analyze_image_ocr", note)

        import re
        m = re.search(r"- (\S+\.png)", note)
        self.assertIsNotNone(m, "說明文字裡應該要附上實際的暫存檔路徑")
        saved_path = m.group(1)
        try:
            self.assertTrue(os.path.exists(saved_path))
            with open(saved_path, "rb") as f:
                self.assertEqual(f.read(), raw)
        finally:
            if os.path.exists(saved_path):
                os.remove(saved_path)

    def test_note_explicitly_allows_multimodal_model_to_ignore_it(self):
        """措辭上要明確講『如果你已經看得到圖片，這段話可以忽略』，
        不能讓真正的多模態模型誤以為自己看不到圖、反而畫蛇添足去呼叫視覺工具。
        """
        agent = _FakeAgent()
        result = agent._build_user_content("圖片內容", images=[self._png_data_url(b"x" * 20)])
        note = "\n".join(p["text"] for p in result if p.get("type") == "text")
        try:
            self.assertIn("可以直接忽略", note)
        finally:
            import re
            for p in re.findall(r"- (\S+\.png)", note):
                if os.path.exists(p):
                    os.remove(p)

    def test_note_covers_tool_failure_fallback_to_asking_user(self):
        """視覺工具本身失敗/不可用時，說明文字要引導模型如實告知使用者，
        而不是默默跳過或編造圖片內容。
        """
        agent = _FakeAgent()
        result = agent._build_user_content("圖片內容", images=[self._png_data_url(b"y" * 20)])
        note = "\n".join(p["text"] for p in result if p.get("type") == "text")
        try:
            self.assertIn("不可用", note)
            self.assertIn("如實", note)
        finally:
            import re
            for p in re.findall(r"- (\S+\.png)", note):
                if os.path.exists(p):
                    os.remove(p)

    def test_multiple_images_each_saved_separately_and_counted_correctly(self):
        agent = _FakeAgent()
        raw_a, raw_b = b"AAAA_IMAGE_ONE_XYZ", b"BBBB_IMAGE_TWO_XYZ"
        result = agent._build_user_content(
            "比較這兩張圖", images=[self._png_data_url(raw_a), self._png_data_url(raw_b)]
        )
        note = "\n".join(p["text"] for p in result if p.get("type") == "text")
        self.assertIn("附上了 2 張圖片", note)

        import re
        paths = re.findall(r"- (\S+\.png)", note)
        self.assertEqual(len(paths), 2)
        try:
            contents = set()
            for p in paths:
                with open(p, "rb") as f:
                    contents.add(f.read())
            self.assertEqual(contents, {raw_a, raw_b})
        finally:
            for p in paths:
                if os.path.exists(p):
                    os.remove(p)

    def test_malformed_image_data_does_not_crash_and_produces_no_note(self):
        """圖片格式壞掉時不該拋例外；既然存不下去，也不該生出一段指向不存在檔案的說明。"""
        agent = _FakeAgent()
        result = agent._build_user_content(
            "你好", images=["data:image/png;base64,不是合法的base64!!!"]
        )
        self.assertIsInstance(result, list)
        text_parts = [p["text"] for p in result if p.get("type") == "text"]
        self.assertIn("你好", text_parts[0])
        # 存不下去就不該出現「附上了 N 張圖片」這種誤導性的說明
        self.assertFalse(any("附上了" in t for t in text_parts))

    def test_bare_base64_without_data_url_prefix_is_normalized(self):
        """前端有時候可能只傳裸 base64（沒有 data: 前綴），也要能正常處理。"""
        agent = _FakeAgent()
        raw = b"bare base64 content here"
        bare_b64 = base64.b64encode(raw).decode()
        result = agent._build_user_content("圖片", images=[bare_b64])

        image_parts = [p for p in result if p.get("type") == "image_url"]
        self.assertEqual(len(image_parts), 1)
        self.assertTrue(image_parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

        note = "\n".join(p["text"] for p in result if p.get("type") == "text")
        import re
        for p in re.findall(r"- (\S+\.jpe?g)", note):
            if os.path.exists(p):
                os.remove(p)

    def test_none_or_empty_url_in_images_list_is_skipped_safely(self):
        agent = _FakeAgent()
        result = agent._build_user_content("測試", images=[None, "", self._png_data_url(b"real")])
        image_parts = [p for p in result if p.get("type") == "image_url"]
        self.assertEqual(len(image_parts), 1, "None/空字串應該被跳過，不該產生空的 image_url part")

        note = "\n".join(p["text"] for p in result if p.get("type") == "text")
        import re
        for p in re.findall(r"- (\S+\.png)", note):
            if os.path.exists(p):
                os.remove(p)


if __name__ == "__main__":
    unittest.main()
