# Vision Platform

Vision Platform 的目標是把專案內分散的截圖、template、candidate crop、人工標註圖、debug overlay、review 圖片與模型輸出整理成可追溯的視覺資料資產。

目前核心決策：

- `vision_assets` 是共用資產層，負責圖片盤點、identity、content hash、來源追蹤、重複圖片追蹤與人工 review 基礎。
- `ads` 與 `game` 是兩個獨立 vision domain。
- ads 與 game 可以共用 inventory 工具與 `content_id`，但不共用 production detector/classifier checkpoint。
- ads 與 game 的 review、dataset、detector、classifier、評估報告、模型版本、production checkpoint 與 runtime 設定必須分開管理。

規劃中的邏輯結構：

```text
vision_platform/
├─ vision_assets/
│  ├─ tools/
│  ├─ inventory/
│  ├─ review/
│  └─ reports/
│
├─ ads/
│  ├─ detector/
│  ├─ classifiers/
│  ├─ datasets/
│  ├─ config/
│  └─ reports/
│
└─ game/
   ├─ detector/
   ├─ classifiers/
   ├─ datasets/
   ├─ config/
   └─ reports/
```

目前不先建立大量空目錄。目錄設計要保持淺層、命名直接，方便用 Windows 檔案總管操作。

## Vision Domains

`vision_domain` 允許值：

- `ads`: 廣告播放、廣告結束、close、skip、claim、continue、廣告 runtime collection 與廣告 debug 圖片。
- `game`: 遊戲主畫面、任務、活動、商店、帳號切換、popup、遊戲按鈕與其他遊戲內 UI。
- `shared`: 經確認可以供兩個領域共同使用的通用資產。
- `unknown`: 目前無法可靠判斷。

第一版 inventory 只依來源路徑保守判斷：

- `ads/`, `ads2/`, `close_x_classifier/` → `ads`
- `AwayFromKeyboard/`, `switch_account/`, `call_of_the_gale/`, `magic_shop/`, `arcane_forge/`, `Screw/`, `tasks/`, `assets/tasks/` → `game`
- `manual_screenshots/` → 依子路徑粗分；明確廣告相關路徑歸 `ads`，其餘多數歸 `game`
- `assets/shared/`, `log/` → 無法可靠判斷時維持 `unknown`

`close_x_classifier/` 目前定位為 ads domain 的第二層 specialist classifier，服務廣告 close/X 偵測。未來如果 game 也需要 popup close classifier，應建立獨立的 `game_classifier_popup_close`，不要直接把廣告 close classifier 當作同一個 production model。

## Runtime Architecture

ads 與 game 都採用相同責任分層，但模型與設定分開：

```text
完整 screenshot
        ↓
Detector / Proposal Layer
        ↓
候選 bbox
        ↓
Specialist Classifier Layer
        ↓
Resolver
        ↓
操作與結果驗證
```

Ads：

```text
ads proposal sources / detector
        ↓
ads specialist classifiers
        ↓
ads resolver
```

Game：

```text
game proposal sources / detector
        ↓
game specialist classifiers
        ↓
game resolver
```

## Proposal Sources

第一層責任是從完整畫面找出值得進一步判斷的候選區域。第一層不限定是神經網路 detector。

以下都視為 proposal source：

- learned detector
- template matching
- glyph matching
- geometry scan
- 固定 ROI
- OCR region proposal
- 既有規則

目前 ads 系統已存在的 template、glyph、geometry X scan 都可以繼續保留，作為 ads 第一層 proposal source。未來加入 learned detector 時，不需要移除穩定的 template 能力。

第一層輸出至少應保留：

```text
bbox
proposal_score
proposal_source
proposal_type
model_or_rule_version
```

## Specialist Classifiers

第二層接收第一層產生的 candidate patch，判斷候選是否屬於特定目標。

初期優先使用多個範圍狹窄的 binary classifier，而不是立即建立大型通用 multi-class classifier。

ads 可能包含：

```text
ads_classifier_close
ads_classifier_skip
ads_classifier_claim
ads_classifier_continue
```

game 可能包含：

```text
game_classifier_task_button
game_classifier_claim_button
game_classifier_back_button
game_classifier_popup_close
game_classifier_scene_state
```

每個 classifier 都應能獨立增加資料、訓練、評估、調整 threshold、發布與停用。

## Datasets

Detector dataset 與 classifier dataset 必須分開管理。

```text
vision_platform/ads/datasets/
├─ detector/
└─ classifiers/

vision_platform/game/datasets/
├─ detector/
└─ classifiers/
```

Detector dataset 主要包含完整 screenshot、bbox annotation、proposal class、來源 session。

Classifier dataset 主要包含 candidate crop、positive/negative label、來源 screenshot、來源 bbox、proposal source、目標 classifier task。

未來任何 classifier crop 都必須能追溯到：

```text
parent_instance_id
parent_content_id
source_bbox
proposal_source
proposal_version
vision_domain
classifier_task
```

## Review Flow

後續人工 review 不使用單一混合 inbox。規劃為：

```text
vision_platform/vision_assets/review/
├─ ads/
├─ game/
└─ domain_triage/
```

ads 與 game 各自維持淺層分類：

```text
ads/
├─ inbox/
├─ clean_fullscreen/
├─ annotated_fullscreen/
├─ crop/
├─ sheet/
├─ template/
├─ ignore/
└─ uncertain/
```

```text
game/
├─ inbox/
├─ clean_fullscreen/
├─ annotated_fullscreen/
├─ crop/
├─ sheet/
├─ template/
├─ ignore/
└─ uncertain/
```

`domain_triage/` 只處理目前無法可靠判斷屬於 ads 或 game 的圖片：

```text
domain_triage/
├─ inbox/
├─ ads/
├─ game/
├─ shared/
└─ unknown/
```

不要把 `manual_screenshots/` 的全部圖片直接放入同一個正式 review inbox。應先依 `vision_domain` 分流；無法判斷的才進 domain triage。

## Resolver

Runtime 決策仍需要非模型的 resolver：

```text
proposal/detector 找候選
→ specialist classifier 判斷
→ resolver 決定是否操作
→ 點擊
→ fresh screenshot
→ 驗證畫面是否改變
```

Resolver 依據 domain、scene profile、classifier threshold、操作優先度、候選位置、runtime state 與點擊後畫面變化做決策。不同 classifier 的原始分數不應直接互相比大小，除非未來完成明確校準。

未來 API 應明確指定 domain：

```python
vision.find(image=screenshot, domain="ads", target="close")
vision.find(image=screenshot, domain="game", target="task_button")
```

domain 不應完全依靠模型自行猜測。呼叫端或已確認的 runtime state 應明確提供 domain 與 scene profile。

## Model Versioning

模型名稱至少包含：

```text
domain
layer
task
```

例如：

```text
ads_detector_actionable_ui
ads_classifier_close
ads_classifier_skip

game_detector_interactive_ui
game_classifier_task_button
game_classifier_popup_close
```

任何模型版本資料至少記錄：

```text
vision_domain
model_layer
task_name
dataset_version
model_version
checkpoint_path
metrics
created_at
production_status
```
