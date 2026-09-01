"""
從模型輸出裡解析 <|tool_call|>...<|tool_call|> 標記、執行對應的函式、
懶加載工具文件。

從 agent_llm_client.py 拆出來——這部分是「模型說要用工具之後，接下來怎麼辦」，
跟怎麼呼叫 LLM API 本身是不同層次的事。
"""
import ast
import re
from typing import TYPE_CHECKING
from agent.tool_docs import TOOL_DOCS, get_tool_doc

if TYPE_CHECKING:
    from agent.agent_protocol import AgentWorkerBase as _Base
else:
    _Base = object


class AgentToolExecutionMixin(_Base):
    """提供 AgentWorker 解析/執行 <|tool_call|> 標記與工具文件懶加載。"""

    def read_tool_doc(self, name: str) -> str:
        """讓模型在真的呼叫某個工具之前，可以主動先查它的詳細用法。
        呼叫過一次之後，_execute_tools 就不會在該工具第一次實際執行時再重複贈送同一份文件。
        """
        self._doc_shown_tools.add(name)
        return get_tool_doc(name)

    def _execute_tools(self, content: str):
        pattern = r'<\|tool_call\|>(\w+)\(([\s\S]*?)\)\s*</?\|?tool_call\|?>'
        matches = list(re.finditer(pattern, content))
        if not matches:
            return False, content, content

        combined_parts = []

        def _execute_and_format(match):
            func_name, args_str = match.group(1), match.group(2)
            # 懶加載文件：這個工具有額外的詳細用法規則、而且這是本次對話第一次真的呼叫它，
            # 就自動把說明書夾帶進「回饋給模型」的那份結果裡——不管模型有沒有先自己查過，
            # 都保證它在第一次用之前一定看得到規則，避免因為不知道格式而白白失敗一次。
            # 這份文件只塞進模型看到的 combined_result，不混進使用者在聊天視窗看到的
            # interleaved_content，不然每個工具第一次用都會在畫面上炸出一大段說明書。
            doc_prefix = ""
            if func_name in TOOL_DOCS and func_name not in self._doc_shown_tools:
                self._doc_shown_tools.add(func_name)
                doc_prefix = f"[系統：這是你本次對話第一次呼叫 {func_name}，以下是完整使用說明]\n{TOOL_DOCS[func_name]}\n\n[執行結果]\n"

            if func_name in self.available_functions:
                try:
                    args, kwargs = self._parse_tool_arguments(func_name, args_str)
                    res = self.available_functions[func_name](*args, **kwargs)
                    disp_text = f"[{func_name}]: {res}"
                    tag = "tool_result"
                except Exception as e:
                    disp_text = f"[{func_name} 錯誤]: {e}"
                    tag = "tool_error"
            else:
                disp_text = f"未找到函式 '{func_name}'"
                tag = "tool_error"

            combined_parts.append(f"{doc_prefix}{disp_text}")
            return disp_text, tag

        def _replace(match):
            disp_text, tag = _execute_and_format(match)
            return f"{match.group(0)}\n<{tag}>\n{disp_text}\n</{tag}>\n"

        interleaved_content = re.sub(pattern, _replace, content)
        combined_result = "\n".join(combined_parts)
        return True, combined_result, interleaved_content

    def _parse_tool_arguments(self, func_name: str, args_str: str):
        args_str = args_str.strip()
        if not args_str:
            return [], {}

        if func_name == "execute_python":
            # 優先用 ast.literal_eval 把 args_str 當成一個 Python 字串字面值來解析。
            # 這是唯一不會破壞非 ASCII 字元的做法——全程都是 Python str 在處理，
            # 沒有經過任何 bytes 編碼/解碼的轉換，模型如果照 Python 語法正確跳脫，
            # 這裡解析出來的中文字元完全不會被動到。
            try:
                parsed = ast.literal_eval(args_str)
                if isinstance(parsed, str):
                    return [parsed], {}
            except Exception:
                pass

            # ast.literal_eval 解析失敗（例如模型寫出來的字串裡有沒跳脫好的實際換行），
            # 退而求其次：只手動剝掉最外層引號，並且只替換「常見的跳脫序列本身」
            # （\n \t \" \' \\），不對整個字串做 unicode_escape 解碼——
            # 那個做法會把 UTF-8 編碼的中文字元誤判成 Latin-1 字元，變成亂碼，
            # 這正是之前「人生的意義」被印成亂碼的原因。
            code_str = args_str
            for q in ('"""', "'''", '"', "'"):
                if code_str.startswith(q) and code_str.endswith(q) and len(code_str) >= len(q) * 2:
                    code_str = code_str[len(q):-len(q)]
                    break
            code_str = (
                code_str.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\\'", "'")
                .replace("\\\\", "\\")
            )
            return [code_str], {}

        try:
            expr = ast.parse(f"dummy({args_str})", mode="eval")
            if isinstance(expr.body, ast.Call):
                args = [ast.literal_eval(a) for a in expr.body.args]
                kwargs = {str(kw.arg): ast.literal_eval(kw.value) for kw in expr.body.keywords if kw.arg is not None}
                return args, kwargs
        except Exception:
            pass

        return [], {}
