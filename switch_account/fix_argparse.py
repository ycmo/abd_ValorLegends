import sys
from pathlib import Path

sa_file = Path("E:/antigravity/adb_vl/switch_account/switch_account.py")
sa_content = sa_file.read_text(encoding="utf-8")

sa_target7 = """    parser.add_argument("account", choices=list(ACCOUNTS.keys()) + ["toggle"], help="要切換的帳號 (google, 14, tiger, toggle)")
    args = parser.parse_args()

    switch_account(args.account)"""
    
sa_replace7 = """    parser.add_argument("account", choices=list(ACCOUNTS.keys()) + ["toggle"], help="要切換的帳號 (google, 14, tiger, toggle)")
    parser.add_argument("--debug", action="store_true", help="開啟 Debug 模式")
    args = parser.parse_args()

    switch_account(args.account, debug_mode=args.debug)"""

if sa_target7 in sa_content:
    sa_content = sa_content.replace(sa_target7, sa_replace7)
    sa_file.write_text(sa_content, encoding="utf-8")
    print("Fixed argparse")
else:
    print("Could not find target string!")
