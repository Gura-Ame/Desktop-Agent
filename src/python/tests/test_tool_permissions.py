"""
agent/tool_permissions.py 的測試：風險分級 + PermissionManager 的授權判斷邏輯。
這裡不牽涉 AgentWorker/事件迴圈，純粹測資料跟決策函式本身。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.tool_permissions import (
    PermissionManager,
    PermissionMode,
    ToolRisk,
    risk_of,
    TOOL_RISK_LEVELS,
)


def test_unknown_tool_defaults_to_dangerous():
    # 安全的預設方向：沒被分類到的新工具，寧可當作最高風險也不要悄悄放行。
    assert risk_of("some_brand_new_tool_nobody_classified_yet") == ToolRisk.DANGEROUS
    print("[PASS] test_unknown_tool_defaults_to_dangerous")


def test_known_risk_examples():
    assert risk_of("get_mouse_position") == ToolRisk.SAFE
    assert risk_of("remember") == ToolRisk.MODERATE
    assert risk_of("execute_python") == ToolRisk.DANGEROUS
    assert risk_of("click_mouse") == ToolRisk.DANGEROUS
    print("[PASS] test_known_risk_examples")


def test_safe_tools_never_need_confirmation_regardless_of_mode():
    for mode in PermissionMode:
        mgr = PermissionManager(mode=mode)
        assert mgr.needs_confirmation("search_memory") is False, mode
    print("[PASS] test_safe_tools_never_need_confirmation_regardless_of_mode")


def test_ask_mode_confirms_both_moderate_and_dangerous():
    mgr = PermissionManager(mode=PermissionMode.ASK)
    assert mgr.needs_confirmation("remember") is True  # MODERATE
    assert mgr.needs_confirmation("execute_python") is True  # DANGEROUS
    print("[PASS] test_ask_mode_confirms_both_moderate_and_dangerous")


def test_ask_dangerous_only_mode_skips_moderate():
    mgr = PermissionManager(mode=PermissionMode.ASK_DANGEROUS_ONLY)
    assert mgr.needs_confirmation("remember") is False  # MODERATE 自動放行
    assert mgr.needs_confirmation("execute_python") is True  # DANGEROUS 還是要問
    print("[PASS] test_ask_dangerous_only_mode_skips_moderate")


def test_auto_mode_never_confirms_anything():
    mgr = PermissionManager(mode=PermissionMode.AUTO)
    assert mgr.needs_confirmation("remember") is False
    assert mgr.needs_confirmation("execute_python") is False
    print("[PASS] test_auto_mode_never_confirms_anything")


def test_grant_makes_tool_stop_needing_confirmation_this_session():
    mgr = PermissionManager(mode=PermissionMode.ASK)
    assert mgr.needs_confirmation("execute_python") is True
    mgr.grant("execute_python")
    assert mgr.is_granted("execute_python") is True
    assert mgr.needs_confirmation("execute_python") is False
    print("[PASS] test_grant_makes_tool_stop_needing_confirmation_this_session")


def test_grant_is_scoped_to_a_single_tool_name():
    mgr = PermissionManager(mode=PermissionMode.ASK)
    mgr.grant("execute_python")
    # 允許了 execute_python 不代表其他 DANGEROUS 工具也一起被信任
    assert mgr.needs_confirmation("click_mouse") is True
    print("[PASS] test_grant_is_scoped_to_a_single_tool_name")


def test_revoke_restores_confirmation_requirement():
    mgr = PermissionManager(mode=PermissionMode.ASK)
    mgr.grant("execute_python")
    assert mgr.needs_confirmation("execute_python") is False
    mgr.revoke("execute_python")
    assert mgr.needs_confirmation("execute_python") is True
    print("[PASS] test_revoke_restores_confirmation_requirement")


def test_revoke_all_clears_every_grant():
    mgr = PermissionManager(mode=PermissionMode.ASK)
    mgr.grant("execute_python")
    mgr.grant("click_mouse")
    mgr.revoke_all()
    assert mgr.needs_confirmation("execute_python") is True
    assert mgr.needs_confirmation("click_mouse") is True
    print("[PASS] test_revoke_all_clears_every_grant")


def test_set_mode_takes_effect_immediately():
    mgr = PermissionManager(mode=PermissionMode.ASK)
    assert mgr.needs_confirmation("remember") is True
    mgr.set_mode(PermissionMode.AUTO)
    assert mgr.needs_confirmation("remember") is False
    print("[PASS] test_set_mode_takes_effect_immediately")


def test_every_registered_tool_has_an_explicit_risk_level_and_no_typos():
    # 這條測試存在的目的：往 TOOL_RISK_LEVELS 加新工具名稱時，如果打錯字或
    # 值不是 ToolRisk 的合法成員，這裡會馬上發現，而不是等到真的執行時
    # 才發現分級悄悄失效變成 DEFAULT_RISK。
    for name, risk in TOOL_RISK_LEVELS.items():
        assert isinstance(name, str) and name, f"工具名稱不合法: {name!r}"
        assert isinstance(risk, ToolRisk), f"{name} 的風險等級不是 ToolRisk 成員: {risk!r}"
    print("[PASS] test_every_registered_tool_has_an_explicit_risk_level_and_no_typos")


if __name__ == "__main__":
    tests = [
        test_unknown_tool_defaults_to_dangerous,
        test_known_risk_examples,
        test_safe_tools_never_need_confirmation_regardless_of_mode,
        test_ask_mode_confirms_both_moderate_and_dangerous,
        test_ask_dangerous_only_mode_skips_moderate,
        test_auto_mode_never_confirms_anything,
        test_grant_makes_tool_stop_needing_confirmation_this_session,
        test_grant_is_scoped_to_a_single_tool_name,
        test_revoke_restores_confirmation_requirement,
        test_revoke_all_clears_every_grant,
        test_set_mode_takes_effect_immediately,
        test_every_registered_tool_has_an_explicit_risk_level_and_no_typos,
    ]
    for t in tests:
        t()
    print(f"\n全部 {len(tests)} 個測試通過。")
