# tests_v2/ — src_v2 的獨立測試目錄
#
# 原則：
#   - 所有測試使用 unittest + unittest.mock
#   - 不呼叫真實 ADB / OpenCV / 外部 API
#   - 與 tests/ 完全獨立，不互相干擾
#
# 執行方式：
#   python -m pytest tests_v2/ -v
