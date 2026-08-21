import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from test_agent_core_escalation import (
    test_reasoning_escalates_to_planning_with_decompose_and_smart_confirm,
    test_truncated_without_conclusion_auto_escalates_to_planning,
    test_truncated_but_has_tool_call_does_not_force_escalate,
    test_repeating_without_progress_auto_escalates_to_planning,
    test_short_similar_replies_not_falsely_flagged
)
from test_agent_core_retries import (
    test_reasoning_does_not_escalate_reuses_first_call,
    test_ask_user_triggered_after_max_retries
)

if __name__ == "__main__":
    tests = [
        test_reasoning_escalates_to_planning_with_decompose_and_smart_confirm,
        test_truncated_without_conclusion_auto_escalates_to_planning,
        test_truncated_but_has_tool_call_does_not_force_escalate,
        test_repeating_without_progress_auto_escalates_to_planning,
        test_short_similar_replies_not_falsely_flagged,
        test_reasoning_does_not_escalate_reuses_first_call,
        test_ask_user_triggered_after_max_retries,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
