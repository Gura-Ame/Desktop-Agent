"""
task_system.py 的單元測試。純 stdlib，不需要真的 LLM、不需要開 main.py。

執行方式：
    python tests/test_task_system.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from task_system import TaskEngine, TaskStatus, ExecutionMode  # noqa: E402


PLAN_DSL = """
- [ ] [TASK-1] 建立資料夾
  - 方法: execute_python 建立 docs 資料夾
  - 條件: docs 資料夾存在
  - 注意: 已存在就略過
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: NO
  - 信心值: 0.9
- [ ] [TASK-2] 刪除舊檔案
  - 方法: execute_python 刪除 temp.txt
  - 條件: temp.txt 不存在
  - 注意: 只能刪 temp.txt，不能刪別的
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: YES
  - 信心值: 0.7
"""

DECOMPOSE_DSL = """
- [ ] [TASK-1] 建立 docs 資料夾
  - 方法: os.makedirs('docs')
  - 條件: docs 資料夾存在
  - 注意: 已存在就略過
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: NO
  - 信心值: 0.9
- [ ] [TASK-2] 建立 images 資料夾
  - 方法: os.makedirs('images')
  - 條件: images 資料夾存在
  - 注意: 已存在就略過
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: NO
  - 信心值: 0.9
"""


def new_engine() -> TaskEngine:
    return TaskEngine(mode=ExecutionMode.STEP_BY_STEP)


def test_load_initial_plan_parses_all_fields():
    engine = new_engine()
    ok = engine.load_initial_plan(PLAN_DSL)
    assert ok is True
    assert len(engine.tasks) == 2

    t1, t2 = engine.tasks
    assert t1.id == "TASK-1"
    assert t1.method == "execute_python 建立 docs 資料夾"
    assert t1.need_confirm is False
    assert t1.need_decompose is False
    assert abs(t1.confidence - 0.9) < 1e-6

    assert t2.need_confirm is True, "TASK-2 標了需要確認: YES，應該解析成 True"
    print("[PASS] test_load_initial_plan_parses_all_fields")


def test_missing_confirm_field_defaults_to_true():
    dsl = """
- [ ] [TASK-1] 沒有標需要確認欄位的任務
  - 方法: 做點什麼
  - 條件: 做完了
  - 注意: 無
  - 深度思考: NO
  - 需要拆解: NO
  - 信心值: 0.8
"""
    engine = new_engine()
    assert engine.load_initial_plan(dsl) is True
    assert engine.tasks[0].need_confirm is True, "沒標明時應該保守預設為需要確認"
    print("[PASS] test_missing_confirm_field_defaults_to_true")


def test_get_next_pending_task_order():
    engine = new_engine()
    engine.load_initial_plan(PLAN_DSL)
    first = engine.get_next_pending_task()
    assert first.id == "TASK-1"

    first.status = TaskStatus.COMPLETED
    second = engine.get_next_pending_task()
    assert second.id == "TASK-2"
    print("[PASS] test_get_next_pending_task_order")


def test_apply_reflected_dsl_rejects_missing_completed_task():
    engine = new_engine()
    engine.load_initial_plan(PLAN_DSL)
    engine.tasks[0].status = TaskStatus.COMPLETED
    engine.tasks[0].result = "docs 已建立"

    # 模型輸出的新樹「忘記」把已完成的 TASK-1 包進去
    bad_reflect = """
- [ ] [TASK-2] 刪除舊檔案
  - 方法: execute_python 刪除 temp.txt
  - 條件: temp.txt 不存在
  - 注意: 只能刪 temp.txt
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: YES
  - 信心值: 0.7
"""
    ok, msg = engine.apply_reflected_dsl(bad_reflect)
    assert ok is False
    assert "TASK-1" in msg
    assert engine.tasks[0].status == TaskStatus.COMPLETED, "拒絕套用後，原本的完成狀態必須維持不變"
    print("[PASS] test_apply_reflected_dsl_rejects_missing_completed_task")


def test_apply_reflected_dsl_rejects_downgraded_completed_task():
    engine = new_engine()
    engine.load_initial_plan(PLAN_DSL)
    engine.tasks[0].status = TaskStatus.COMPLETED
    engine.tasks[0].result = "docs 已建立"

    # 模型把已完成的 TASK-1 又標回未完成
    bad_reflect = """
- [ ] [TASK-1] 建立資料夾
  - 方法: execute_python 建立 docs 資料夾
  - 條件: docs 資料夾存在
  - 注意: 已存在就略過
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: NO
  - 信心值: 0.9
- [ ] [TASK-2] 刪除舊檔案
  - 方法: execute_python 刪除 temp.txt
  - 條件: temp.txt 不存在
  - 注意: 只能刪 temp.txt
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: YES
  - 信心值: 0.7
"""
    ok, msg = engine.apply_reflected_dsl(bad_reflect)
    assert ok is False
    assert engine.tasks[0].status == TaskStatus.COMPLETED
    print("[PASS] test_apply_reflected_dsl_rejects_downgraded_completed_task")


def test_apply_reflected_dsl_accepts_valid_update_and_appends_new_task():
    engine = new_engine()
    engine.load_initial_plan(PLAN_DSL)
    engine.tasks[0].status = TaskStatus.COMPLETED
    engine.tasks[0].result = "docs 已建立"

    good_reflect = """
- [x] [TASK-1] 建立資料夾
  - 結果: docs 已建立
- [ ] [TASK-2] 刪除舊檔案
  - 方法: execute_python 刪除 temp.txt
  - 條件: temp.txt 不存在
  - 注意: 只能刪 temp.txt
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: YES
  - 信心值: 0.7
- [ ] [TASK-3] 新增的後續任務
  - 方法: execute_python 印出結果
  - 條件: 有印出結果
  - 注意: 無
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: NO
  - 信心值: 0.9
"""
    ok, msg = engine.apply_reflected_dsl(good_reflect)
    assert ok is True
    assert [t.id for t in engine.tasks] == ["TASK-1", "TASK-2", "TASK-3"]
    assert engine.tasks[0].status == TaskStatus.COMPLETED
    print("[PASS] test_apply_reflected_dsl_accepts_valid_update_and_appends_new_task")


def test_decompose_task_inserts_children_and_marks_container():
    engine = new_engine()
    engine.load_initial_plan(PLAN_DSL)

    ok, msg = engine.decompose_task("TASK-1", DECOMPOSE_DSL)
    assert ok is True

    ids = [t.id for t in engine.tasks]
    assert ids == ["TASK-1", "TASK-1.1", "TASK-1.2", "TASK-2"], f"實際順序: {ids}"

    parent = engine.tasks[0]
    assert parent.status == TaskStatus.DECOMPOSED
    assert parent.is_decomposed is True

    child1 = engine.tasks[1]
    assert child1.parent_id == "TASK-1"
    assert child1.status == TaskStatus.PENDING

    # DECOMPOSED 的容器任務不應該被 get_next_pending_task 選中，
    # 應該直接跳到它的第一個子任務
    next_task = engine.get_next_pending_task()
    assert next_task.id == "TASK-1.1"
    print("[PASS] test_decompose_task_inserts_children_and_marks_container")


def test_check_and_complete_parent_completes_when_all_children_done():
    engine = new_engine()
    engine.load_initial_plan(PLAN_DSL)
    engine.decompose_task("TASK-1", DECOMPOSE_DSL)

    child1, child2 = engine.tasks[1], engine.tasks[2]
    child1.status = TaskStatus.COMPLETED
    child1.result = "docs 完成"
    engine.check_and_complete_parent(child1.id)

    parent = engine.tasks[0]
    assert parent.status == TaskStatus.DECOMPOSED, "還有一個子任務沒完成，父任務不該提早完成"

    child2.status = TaskStatus.COMPLETED
    child2.result = "images 完成"
    engine.check_and_complete_parent(child2.id)

    assert parent.status == TaskStatus.COMPLETED, "兩個子任務都完成了，父任務應該自動完成"
    assert "docs 完成" in parent.result and "images 完成" in parent.result
    print("[PASS] test_check_and_complete_parent_completes_when_all_children_done")


def test_apply_reflected_dsl_protects_decomposed_container():
    engine = new_engine()
    engine.load_initial_plan(PLAN_DSL)
    engine.decompose_task("TASK-1", DECOMPOSE_DSL)

    # Reflect 拿到的樹是用 render_tree_markdown 渲染出來的文字（模擬「模型原封不動回傳」的情境）
    rendered = engine.render_tree_markdown()
    # 把標題那行去掉，因為那不是合法的 DSL 條目
    dsl_text = "\n".join(line for line in rendered.split("\n") if not line.startswith("###"))

    ok, msg = engine.apply_reflected_dsl(dsl_text)
    assert ok is True, f"合法的原樣回傳應該要能通過驗證，實際: {msg}"

    parent = engine.tasks[0]
    assert parent.status == TaskStatus.DECOMPOSED
    assert parent.is_decomposed is True
    assert engine.tasks[1].parent_id == "TASK-1", "子任務的 parent_id 這個內部關聯要保留下來"
    print("[PASS] test_apply_reflected_dsl_protects_decomposed_container")


def test_render_tree_markdown_indents_children():
    engine = new_engine()
    engine.load_initial_plan(PLAN_DSL)
    engine.decompose_task("TASK-1", DECOMPOSE_DSL)

    text = engine.render_tree_markdown()
    lines = text.split("\n")
    parent_line = next(l for l in lines if "[TASK-1]" in l and "▾" in l)
    child_line = next(l for l in lines if "[TASK-1.1]" in l)

    assert not parent_line.startswith("  -"), "頂層任務不應該有縮排"
    assert child_line.startswith("  -"), "子任務應該比父任務多縮排"
    print("[PASS] test_render_tree_markdown_indents_children")


def test_parses_alphanumeric_dotted_id():
    """code_impact.py 產生的影響檢查任務 id 長這樣：TASK-1.impact1，不是純數字的 TASK-1.1，
    要確定這種格式在渲染/重新解析的來回過程中不會被切斷。"""
    dsl = """
- [ ] [TASK-1.impact1] 檢查 sample.route_request 是否受影響
  - 方法: 讀取原始碼比對
  - 條件: 確認呼叫的地方仍然正確
  - 注意: 這是自動產生的任務
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: YES
  - 信心值: 0.7
"""
    engine = new_engine()
    ok = engine.load_initial_plan(dsl)
    assert ok is True
    assert engine.tasks[0].id == "TASK-1.impact1", f"實際: {engine.tasks[0].id}"
    assert engine.tasks[0].title == "檢查 sample.route_request 是否受影響"
    print("[PASS] test_parses_alphanumeric_dotted_id")


def test_title_starting_with_bracket_not_misparsed_as_id():
    """標題本身用中括號開頭（例如「[重要] 做某事」）不該被誤判成任務 id——
    id 的字元集合限制在英數字/底線/點/連字號，中文不會被當成 id。"""
    dsl = """
- [ ] [TASK-1] [重要] 做某事
  - 方法: 做某事的方法
  - 條件: 做完了
  - 注意: 無
  - 深度思考: NO
  - 需要拆解: NO
  - 需要確認: NO
  - 信心值: 0.9
"""
    engine = new_engine()
    ok = engine.load_initial_plan(dsl)
    assert ok is True
    assert engine.tasks[0].id == "TASK-1"
    assert engine.tasks[0].title == "[重要] 做某事", f"實際: {engine.tasks[0].title!r}"
    print("[PASS] test_title_starting_with_bracket_not_misparsed_as_id")


if __name__ == "__main__":
    tests = [
        test_load_initial_plan_parses_all_fields,
        test_missing_confirm_field_defaults_to_true,
        test_get_next_pending_task_order,
        test_apply_reflected_dsl_rejects_missing_completed_task,
        test_apply_reflected_dsl_rejects_downgraded_completed_task,
        test_apply_reflected_dsl_accepts_valid_update_and_appends_new_task,
        test_decompose_task_inserts_children_and_marks_container,
        test_check_and_complete_parent_completes_when_all_children_done,
        test_apply_reflected_dsl_protects_decomposed_container,
        test_render_tree_markdown_indents_children,
        test_parses_alphanumeric_dotted_id,
        test_title_starting_with_bracket_not_misparsed_as_id,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
