import sys
from pathlib import Path

# 加入當下目錄與父目錄以利載入模組
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))
parent_dir = current_dir.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from router import RouteNavigator
import subprocess
import task_config

# 強制設定輸出為 UTF-8，以防在 Windows 終端機顯示中文出錯
sys.stdout.reconfigure(encoding='utf-8')

def main():
    # 支援從命令列接收引數當作 route_name，預設為「點金手」
    route_name = "點金手"
    if len(sys.argv) > 1:
        route_name = sys.argv[1]
        
    print(f"🚀 開始執行路由任務：{route_name}")
    print("-" * 40)
    
    try:
        navigator = RouteNavigator(route_name=route_name)
        print(f"[Router] 開始執行進場路由...")
        navigator.execute_route(phase="enter")
        print("-" * 40)
        print(f"✅ [成功] 路由任務 '{route_name}' 進場導航完畢！準備執行對應指令...")
        
        # 尋找對應指令並執行
        cmd_args = task_config.get_command_for_task(route_name)
        if cmd_args:
            project_root = current_dir.parent.parent
            python_exe = sys.executable
            
            full_cmd = [python_exe] + cmd_args
            print("\n" + "=" * 60)
            print("🛠️ [Debug] 若腳本卡住，可手動在終端機貼上以下指令重新執行：")
            print(f">>> {' '.join(full_cmd)}")
            print("=" * 60 + "\n")
            
            # 加上 try-except 捕捉 subprocess 可能的系統級崩潰
            script_failed = False
            try:
                result = subprocess.run(full_cmd, cwd=str(project_root))
                if result.returncode != 0:
                    print(f"⚠️ [警告] 外部指令執行結束，但回傳錯誤碼 (returncode={result.returncode})")
                    script_failed = True
                else:
                    print(f"✅ [成功] 外部腳本執行完畢！")
            except Exception as e:
                print(f"❌ [錯誤] 執行外部指令時發生崩潰: {e}")
                script_failed = True
                
            print(f"\n[Router] 外部腳本執行完畢，檢查是否有離場路由...")
            navigator.execute_route(phase="exit")
            print(f"✅ [成功] 離場路由執行完畢！")
            

            
            if script_failed:
                print("❌ [錯誤] 由於外部腳本執行失敗，結束路由任務並拋出錯誤碼以觸發 Fail-Fast。")
                sys.exit(1)
        else:
            print(f"⚠️ [提示] 找不到 '{route_name}' 對應的外部指令配置，不執行額外動作。")
            
    except ImportError as e:
        print(f"❌ [錯誤] 無法載入必要的模組 (ImportError): {e}")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"❌ [錯誤] 找不到目錄或檔案: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"❌ [錯誤] 圖片解析失敗: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ [錯誤] 發生未預期的例外狀況: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
