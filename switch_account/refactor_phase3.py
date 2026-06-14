import sys
from pathlib import Path

target_file = Path("E:/antigravity/adb_vl/switch_account/switch_account.py")
content = target_file.read_text(encoding="utf-8")

# 1. Add TOGGLE_MAP below ACCOUNTS = load_accounts()
content = content.replace("ACCOUNTS = load_accounts()\n", 'ACCOUNTS = load_accounts()\n\nTOGGLE_MAP = {"311": "em3", "em3": "311", "14": "tiger", "tiger": "14"}\n')

# 2. Add resolve_next_target and update resolve_toggle_target
old_resolve_toggle = """def resolve_toggle_target(current_acc_name: str) -> str:
    if current_acc_name == "311":
        return "em3"
    elif current_acc_name == "em3":
        return "311"
    elif current_acc_name == "14":
        return "tiger"
    elif current_acc_name == "tiger":
        return "14"
    else:
        print("錯誤：無法辨識當前帳號，無法執行 Toggle 模式！")
        return None"""

new_resolvers = """def resolve_next_target(current_acc_name: str) -> str:
    if not current_acc_name:
        return None
    acc_list = list(ACCOUNTS.keys())
    if current_acc_name not in acc_list:
        return None
    current_idx = acc_list.index(current_acc_name)
    next_idx = (current_idx + 1) % len(acc_list)
    return acc_list[next_idx]

def resolve_toggle_target(current_acc_name: str) -> str:
    return TOGGLE_MAP.get(current_acc_name)"""

content = content.replace(old_resolve_toggle, new_resolvers)

# 3. Update the early checks and macro logic in switch_account
start_idx = content.find("def switch_account")
end_idx = content.find("if __name__ ==")
body = content[start_idx:end_idx]

old_early_check = """def switch_account(account_name: str, debug_mode: bool = False) -> bool:
    if account_name != "toggle" and account_name not in ACCOUNTS:
        print(f"錯誤：找不到帳號 '{account_name}'。支援的帳號有：{', '.join(list(ACCOUNTS.keys()) + ['toggle'])}")
        return False

    if account_name != "toggle":
        account_info = ACCOUNTS[account_name]"""

new_early_check = """def switch_account(account_name: str, debug_mode: bool = False) -> bool:
    MACRO_RESOLVERS = {
        "toggle": resolve_toggle_target,
        "next": resolve_next_target,
    }

    if account_name not in MACRO_RESOLVERS and account_name not in ACCOUNTS:
        print(f"錯誤：找不到帳號 '{account_name}'。支援的帳號有：{', '.join(list(ACCOUNTS.keys()) + list(MACRO_RESOLVERS.keys()))}")
        return False"""

body = body.replace(old_early_check, new_early_check)

old_macro_logic = """    if account_name == "toggle":
        target = resolve_toggle_target(current_acc_name)
        if not target:
            return False
        account_name = target
        print(f"🔄 觸發 Toggle 模式：決定目標帳號為 '{account_name}'")
        if account_name not in ACCOUNTS:
            print(f"錯誤：Toggle 目標帳號 '{account_name}' 不存在於設定檔！")
            return False"""

new_macro_logic = """    if account_name in MACRO_RESOLVERS:
        target = MACRO_RESOLVERS[account_name](current_acc_name)
        if not target:
            print(f"錯誤：無法解析 {account_name} 模式下的目標帳號！(可能無法辨識當前畫面)")
            return False
        print(f"🔄 觸發 {account_name} 模式：動態推導目標帳號為 '{target}'")
        account_name = target"""

body = body.replace(old_macro_logic, new_macro_logic)

content = content[:start_idx] + body + content[end_idx:]

# Update the argparse choices
old_argparse = """    parser.add_argument("account", choices=list(ACCOUNTS.keys()) + ["toggle"], help="要切換的帳號 (google, 14, tiger, toggle)")"""
new_argparse = """    parser.add_argument("account", choices=list(ACCOUNTS.keys()) + ["toggle", "next"], help="要切換的帳號 (對應設定檔名稱, toggle, 或 next)")"""

content = content.replace(old_argparse, new_argparse)

target_file.write_text(content, encoding="utf-8")
print("Refactoring Phase 3 complete.")
