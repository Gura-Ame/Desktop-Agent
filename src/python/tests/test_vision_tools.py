import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure src/python is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools import vision_tools
from tools.vision_tools import (
    unload_florence_model,
    unload_paddleocr_model,
    unload_all_vision_models,
    analyze_image_visuals,
    analyze_image_ocr,
)
from agent.agent_core import AgentWorker
from agent.tool_docs import get_tool_doc


class TestVisionTools(unittest.TestCase):
    def setUp(self):
        # Reset globals before each test
        vision_tools.florence_model = None
        vision_tools.florence_processor = None
        vision_tools.paddle_ocr_reader = None

    def tearDown(self):
        vision_tools.florence_model = None
        vision_tools.florence_processor = None
        vision_tools.paddle_ocr_reader = None

    def test_unload_when_not_loaded(self):
        msg_f = unload_florence_model()
        self.assertIn("無需卸載", msg_f)

        msg_p = unload_paddleocr_model()
        self.assertIn("無需卸載", msg_p)

        msg_all = unload_all_vision_models()
        self.assertIn("視覺模組卸載結果", msg_all)

    def test_unload_when_loaded(self):
        # Simulate loaded state
        vision_tools.florence_model = MagicMock()
        vision_tools.florence_processor = MagicMock()
        vision_tools.paddle_ocr_reader = MagicMock()

        msg_f = unload_florence_model()
        self.assertIn("已成功將 Florence-2 從顯存", msg_f)
        self.assertIsNone(vision_tools.florence_model)

        msg_p = unload_paddleocr_model()
        self.assertIn("已成功將 PaddleOCR 從記憶體/顯存卸載", msg_p)
        self.assertIsNone(vision_tools.paddle_ocr_reader)

    @patch("tools.vision_tools.load_paddleocr")
    @patch("os.path.exists", return_value=True)
    def test_analyze_image_ocr_raw(self, mock_exists, mock_load):
        mock_reader = MagicMock()
        # Mock OCR output: [ [ [box], ("Hello World", 0.99) ] ]
        mock_reader.ocr.return_value = [[
            [[[10, 20], [100, 20], [100, 50], [10, 50]], ("Line 1", 0.98)],
            [[[10, 60], [100, 60], [100, 90], [10, 90]], ("Line 2", 0.95)],
        ]]
        vision_tools.paddle_ocr_reader = mock_reader

        with patch("PIL.Image.open") as mock_img:
            mock_img.return_value.size = (1920, 1080)
            res = analyze_image_ocr(image_path="dummy.png", task="<OCR_RAW>")

        self.assertIn("PaddleOCR v4 精準文字/代碼提取", res)
        self.assertIn("Line 1", res)
        self.assertIn("Line 2", res)

    @patch("tools.vision_tools.load_paddleocr")
    @patch("os.path.exists", return_value=True)
    def test_analyze_image_ocr_geometry(self, mock_exists, mock_load):
        mock_reader = MagicMock()
        mock_reader.ocr.return_value = [[
            [[[100, 200], [300, 200], [300, 250], [100, 250]], ("Submit Button", 0.99)],
        ]]
        vision_tools.paddle_ocr_reader = mock_reader

        with patch("PIL.Image.open") as mock_img:
            mock_img.return_value.size = (1000, 1000)
            res = analyze_image_ocr(image_path="dummy.png", task="<OCR_GEOMETRY>")

        self.assertIn("PaddleOCR v4 UI 幾何分析", res)
        self.assertIn("pixel_center", res)
        self.assertIn("Submit Button", res)

    def test_tool_docs_registered(self):
        doc_vis = get_tool_doc("analyze_image_visuals")
        self.assertIn("Florence-2", doc_vis)

        doc_ocr = get_tool_doc("analyze_image_ocr")
        self.assertIn("PaddleOCR v4", doc_ocr)

    def test_agent_worker_tool_execution(self):
        mock_cb = MagicMock()
        functions = {
            "analyze_image_visuals": MagicMock(return_value="[Florence result]"),
            "analyze_image_ocr": MagicMock(return_value="[OCR result]"),
            "unload_florence_model": MagicMock(return_value="[Florence unloaded]"),
            "unload_paddleocr_model": MagicMock(return_value="[OCR unloaded]"),
            "unload_all_vision_models": MagicMock(return_value="[All unloaded]"),
        }
        agent = AgentWorker(functions, event_callback=mock_cb, memory_path="test_temp_mem.json")
        try:
            # Test inline tool execution
            tool_call_str = '<|tool_call|>analyze_image_ocr("dummy.png", "<OCR_RAW>")<|tool_call|>'
            is_tool, combined_result, interleaved = agent._execute_tools(tool_call_str)
            self.assertTrue(is_tool)
            self.assertIn("[OCR result]", combined_result)

            # Test unload tool call
            unload_call_str = '<|tool_call|>unload_all_vision_models()<|tool_call|>'
            is_tool2, combined_result2, _ = agent._execute_tools(unload_call_str)
            self.assertTrue(is_tool2)
            self.assertIn("[All unloaded]", combined_result2)
        finally:
            if os.path.exists("test_temp_mem.json"):
                os.remove("test_temp_mem.json")


if __name__ == "__main__":
    unittest.main()
