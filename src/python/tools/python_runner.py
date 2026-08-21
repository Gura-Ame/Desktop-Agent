import io
import math
import contextlib

def execute_python(code: str) -> str:
    buffer = io.StringIO()

    # 1. 優先嘗試當成單一運算式 (Expression) 求值 (Evaluation)
    try:
        res = eval(code, {"math": math, "__builtins__": __builtins__})
        if res is not None:
            return str(res)
    except Exception:
        pass

    # 2. 失敗則作為程式敘述 (Statement) 執行並擷取 print 輸出
    try:
        with contextlib.redirect_stdout(buffer):
            exec(code, {"math": math, "__builtins__": __builtins__})
        output = buffer.getvalue().strip()
        return output if output else "成功（無輸出）"
    except Exception as e:
        return f"執行失敗: {e}"
