# HB Pitch Lab：最佳化與驗收操作手冊

版本：0.3，2026-09-09。適用於人類操作者與其他 AI agent。此文件中的命令可直接在 repository 根目錄執行。

## 1. 功能與完成定義

本工具以有限參數網格搜尋 module benchmark 的 PPA。使用者指定目標、上下限、成本模型與搜尋範圍；Python 完整枚舉、計算 Pareto 集合、選定配置，再產生相同參數的 RTL。

**這不是完整可程式化 GPU，也不是 APR／SoIC signoff。** 目前只有明示的 FIFO/HB stream 接線，未實作 kernel scheduler、SIMT instruction execution、完整 NoC、foundry SRAM macro 或 PHY。既有 RTL 功能與限制見 [MODULE_RTL.md](MODULE_RTL.md)。

任務「完成」必須同時滿足：

1. `quality_check.py run` exit code 為 0。
2. `run.json` 的 `status` 為 `PASS`，Q01–Q09 每一項均為 `PASS`。
3. `quality_check.py verify --run ...` exit code 為 0。
4. 選定 point ID、RTL manifest、RTL 模擬及合成報告一致。
5. 明確報告成本資料等級與模型限制。`synthetic` 結果不可改稱實際製程 PPA。

只執行 `optimize.py`、只有 RTL 可解析、只有某一個 test 印出 PASS，都不構成完整驗收。無可行解是有效的研究結果，但不是「已產生通過驗收的最佳 RTL」。

## 2. 環境準備

需求：Python 3.9+、`requirements.txt` 中的 numpy/scipy/matplotlib、Icarus Verilog 與 VVP、Yosys。

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 --version
iverilog -V
vvp -V
yosys -V
```

若 EDA 工具不在 PATH，可以設定 `IVERILOG`、`VVP`、`YOSYS` 指向真正的可執行檔；不要指向回傳固定成功碼的 stub。不要在這些變數內放 shell 命令或參數。工具需自行安裝；不由 requirements.txt 安裝。

此開發機另有 `.tooldeps/icarus-verilog/13.0`、`.tooldeps/yosys/0.68`，check scripts 會在沒有 PATH／環境變數指定時使用它們。這些 binary、dylib 路徑與快取未提交 Git，其他機器不可假設存在。已驗證開發版本為 Icarus 13.0、Yosys 0.68；每次正式執行仍記錄實際版本。

`run.json` 保存 Python/numpy/scipy 版本與執行來源 hash。浮點重算採嚴格一致檢查；更換 source 或數值套件版本後應建立新的 run，不能要求舊的 run 通過目前環境的 verify。不同 CPU／數值環境也可能需要重新產生結果。

## 3. 最短的完整執行方式

初次執行：

```sh
python3 quality_check.py run --design examples/modules.json --policy examples/optimization_ppa.json --out runs/ppa_001
python3 quality_check.py verify --run runs/ppa_001
```

必須檢查**兩個命令各自的 exit code**。第一個失敗時先處理失敗原因，不能用第二個的輸出覆蓋第一個的失敗。`runs/ppa_001` 必須不存在；重跑改成 `runs/ppa_002` 等新名稱。禁止刪除舊 evidence 以製造成功紀錄。

如果只想先探索、暫時不跑 EDA：

```sh
python3 optimize.py --design examples/modules.json --policy examples/optimization_ppa.json --out runs/search_001
```

這會產生搜尋結果及選定 RTL，但**沒有完整 QC PASS**。正式驗收仍要使用上面的 quality-check 命令，在新目錄重新執行。

## 4. 四份輸入資料

| 輸入 | 目前範例 | 職責 |
|---|---|---|
| 模組配置 | `examples/modules.json` | 模組、參數 sweep、bindings、接線、workload、tile 數與時脈 |
| 環境 | `examples/demo.json` | HB 幾何／能耗、熱網路、兩層功率空間權重；路徑由 design 的 `environment_file` 指定 |
| 最佳化策略 | `examples/optimization_ppa.json` | objectives、constraints、選解方式、搜尋上限、資料等級要求 |
| 成本資料 | `examples/costs_synthetic.json` | module area／額外 idle power，或逐點實測／EDA PPA table；路徑由 policy 的 `cost_model_file` 指定 |

環境路徑相對於 design 檔案；成本路徑相對於 policy 檔案。搬移設定檔時同步調整這些路徑。不要更改工具程式碼來改目標；一般操作只需要修改 JSON。

輸入會完整保存在每次 run 的 `search/inputs/`。記錄包含資料本身，不只是檔案路徑；若要 commit/push 這些資料，仍須遵守該次任務對資料分享的授權。

## 5. 指定要最佳化的項目

每個 objective 必須指定 `metric`、`direction`、`weight`、`scale`。weight 與 scale 必須為有限正數，不接受 0、負數、NaN、Infinity 或 boolean。

| metric | 單位／範圍 | 常用方向 |
|---|---|---|
| `area_mm2` | 兩層所有生成模組的 cell／macro area 合計；不是 die footprint | min |
| `power_w` | 兩層 benchmark 平均功率合計；未含外部 HBM stack／完整系統 | min |
| `latency_ms` | 該份 workload 的時間；解析 backend 為重疊模型加啟動項 | min |
| `energy_mj` | 相同 workload 的兩層能耗 | min |
| `throughput_tops` | workload operations／時間，不是 tokens/s | max |
| `steady_tmax_c` | 解析熱模型的穩態峰值溫度 | min／通常設上限 |
| `hb_site_budget_mm2` | 含 signal 配額的 bond-slot 面積預算；與 cell area 可能重疊 | min |
| `pitch_um` | 候選 pitch | 依研究問題；亦可作平手規則 |
| `timing_wns_ns` | point-table 提供的 setup WNS；解析 backend 為 null | max／通常要求 min=0 |
| `sram_bytes_per_tile` | 每 tile 所有 banked SRAM 的邏輯容量合計 | 通常設定 min |
| `rf_bytes_per_tile` | 每 tile 所有 RF 的邏輯容量合計 | 通常設定 min |
| `fifo_bytes_per_tile` | 每 tile 所有 stream FIFO 的邏輯容量合計 | 通常設定 min |

容量條件只是 aggregate capacity，不證明 workload mapping、bank conflicts 或每個 buffer 的存活資料都能容納。調整 DEPTH 等參數時，必須設定符合工作負載的搜尋下限／容量限制，不能把尚未建模的 buffer 命中率收益視為已知。

### 單一目標

將 `objectives` 換成以下內容，其他 policy 欄位保留：

```json
"objectives": [
  {"metric": "energy_mj", "direction": "min", "weight": 1, "scale": 0.01}
]
```

Power 優先可改 `metric` 為 `power_w`；Performance 優先可用 `latency_ms/min` 或 `throughput_tops/max`。如果追求低 power，也應限制 latency，避免接受效能過低的配置。

### 加權 PPA

範例 policy 採 area/power/latency 權重 0.3/0.3/0.4、scale 0.03 mm²/0.3 W/0.04 ms。scale 是固定正規化尺度，不是可行性門檻，也不是搜尋後的 min-max。若想將 area 上限設為 0.03 mm²，必須另外寫在 `constraints`。

### 依優先順序

設 `selection` 為 `lexicographic`，`objectives` 的順序就是優先順序。例如先滿足 constraints，再最小化 latency，再最小化 power，最後最小化 area。此模式的 weights 不影響選解；仍保留正數欄位與 score 以保持輸出格式一致。

### 限制條件

```json
"constraints": {
  "latency_ms": {"max": 0.04},
  "power_w": {"max": 0.5},
  "area_mm2": {"max": 0.1},
  "steady_tmax_c": {"max": 85},
  "sram_bytes_per_tile": {"min": 1024}
}
```

上下限均包含等號；可以同時指定 min/max。未知欄位、拼錯 metric、min > max 直接報錯。缺少必要 metric 的候選不會通過條件。例如解析成本沒有 WNS，指定 `timing_wns_ns.min=0` 會得到無可行解，不能偷偷將 null 當成 0。

## 6. 演算法與數學定義

令 X 為 module sweep × pitch × pad mode 的有限集合。固定 tile_count、clock_hz、workload、stack 與其他沒有 sweep 的欄位；本版不自動搜尋這些固定欄位，也不改 tier partition。需比較不同固定條件時，建立不同 design、分開執行。

先排除 HB/routing/endpoint 放不下的點，再計算 PPA、套用所有 constraints，得到可行集合 F。

對第 j 個目標，定義：

\[
z_j(x)=s_j f_j(x)/a_j,\qquad
s_j=+1\ (\mathrm{min}),\quad s_j=-1\ (\mathrm{max}),\qquad a_j>0.
\]

加權模式最小化：

\[
S(x)=\frac{\sum_j w_j z_j(x)}{\sum_j w_j},\quad w_j>0,\qquad
x^*=\arg\min_{x\in F}S(x).
\]

max 目標的 normalized value／score 可能為負數，這是正常現象。Lexicographic 模式直接依 z 向量做字典序最小化。

x 支配 y 的定義為：所有 j 都有 z_j(x) ≤ z_j(y)，且至少一項嚴格小於。Pareto 集合由所有未被支配的候選構成；相同目標向量的不同配置會全部保留。

由於所有權重為正，若某點被另一可行點支配，它的 weighted sum 不可能更好。因此 weighted／lexicographic 最小值應在 Pareto 集內，程式也會檢查此不變量。完整枚舉使最小值涵蓋所有 F，故 `OPTIMAL_ON_ENUMERATED_GRID` **只保證此網格、模型與 constraints 下的最佳值**，不保證連續空間、不同微架構或 silicon 的全域最佳值。

比較使用確定性的浮點值，沒有隱藏 epsilon 或 uncertainty margin。Weighted score 相同時，先比較 objective 向量，再依 `tie_breakers`，最後依 point ID 排序。Lexicographic 的目標向量相同時亦依後兩項處理。範例 tie breaker 為較大 pitch；它是明示的選解偏好，不是良率或製程成熟度模型。

枚舉評估約 O(N)，Pareto 比較 O(N²K)。每次最多允許 policy 的 `max_candidates`，其上限為 4096；底層另限制 module 參數組合最多 2048 組、pitch × pad mode 最多 100 組。超限會停止，不會偷偷抽樣或聲稱隨機搜尋結果為全域最佳。相同解析參數／physical 組合去重，報告同時列 raw grid count 與 unique count。

### 手算驗證例

兩個要最小化的目標 A=(1,4)、B=(2,2)、C=(4,1)、D=(3,3)，等權且 scale=1：score 分別為 2.5、2、2.5、3。D 被 B 支配，Pareto 為 {A,B,C}，weighted winner 為 B；若優先最小化第一個目標，winner 為 A。此案例由 unit test 獨立檢查。

## 7. 面積／功耗模型與資料來源

### resource_estimate：用於探索與示例

每一類已登錄模組都有 `area_um2` 與 `extra_idle_w` 係數，對特徵 `[1, memory_bits, state_bits, macs_per_cycle]` 做線性加總。

\[
A_{modules}[\mathrm{mm}^2]=10^{-6}T\sum_m\sum_k c^A_{mk}n_{mk},\qquad
P_{extra,tier}=T\sum_{m\in tier}\sum_k c^P_{mk}n_{mk}.
\]

extra idle power 加到原本該層的 background power，再重算能耗與溫度；係數只能代表原 background 尚未包含的部分，避免重複計算。MAC 的 state_bits 已含 accumulator/result registers；設定 per-MAC area 時也要避免重複算相同暫存器。

`quality` 只能為 `synthetic` 或 `estimated`。範例所有係數均為假設；不是依 node 大小就能得到準確 area。該模型未包含路由擁塞、clock tree、PDN、溫度相關 leakage 或 buffer 命中率，且固定 die footprint 不會因 area 變小而自動縮小。

### point_table：使用逐點 PPA

先用相同 source/design/environment 跑 `module_flow.py evaluate` 取得完整 point IDs，再以你的 EDA／量測 flow 取得相同 workload、clock、corner 與面積／功率範圍的資料。每個幾何可行點都必須有 row；漏一個即停止，沒有解析 fallback。

```json
{
  "schema_version": 1,
  "mode": "point_table",
  "quality": "reported",
  "provenance": "填寫資料取得方式、版本與報告位置",
  "context": {
    "process": "填寫製程與 library",
    "corner": "填寫 PVT corner",
    "voltage_v": 0.8,
    "temperature_c": 40,
    "flow": "填寫工具版本與 flow revision"
  },
  "entries": [
    {
      "point_id": "替換為實際完整的64字元point-ID",
      "area_mm2": 0.1,
      "latency_ms": 0.02,
      "top_power_w": 1.0,
      "bottom_power_w": 2.0,
      "timing_wns_ns": 0.1,
      "source": "填寫此點的真實報告位置"
    }
  ]
}
```

以上數值只是格式例，不能當作量測。`reported` 是來源方宣告，程式不會自動驗證報告真偽。可以用 `synthetic` point_table 測試匯入流程。

若要強制使用 reported PPA，policy 設 `quality_requirement="reported_ppa"`，並加入 `timing_wns_ns.min >= 0`。這只檢查提供的 setup WNS，未驗證 hold、其他 corners、IR、DRC 或功耗 activity 是否正確。只提供 target clock 不等同通過 STA；reported latency 應是相同 workload 的執行時間，不是 critical-path delay。

Point-table 能耗與吞吐重算：

\[
E[\mathrm{mJ}]=(P_{top}+P_{bottom})[\mathrm W]\,t[\mathrm{ms}],\quad
Q[\mathrm{TOP/s}]=N_{ops}/(t[\mathrm{ms}]\,10^9).
\]

例：3 W、0.02 ms、1,000,000 ops，得 E=0.06 mJ、Q=0.05 TOP/s；unit test 已核對。熱模型用所提供兩層功率重新求解 Gθ=P，**不把 point-table 標籤擴張成已校準 thermal**。

## 8. 輸出與有效指標的位置

| 位置，相對於 run 目錄 | 內容 |
|---|---|
| `search/inputs/*.json` | design/environment/policy/costs 的凍結快照 |
| `search/evaluation/evaluation.json` | 原始 module 評估；完整參數與 point ID |
| `search/optimization.json` | 有效 PPA、每點排除原因、score、Pareto、排序、selected ID、來源 hashes |
| `search/OPTIMIZATION.md` | 可讀的候選表 |
| `search/selected_rtl/` | 選定 RTL、wrappers、tops、SDC 與 manifest |
| `search/selected_rtl/optimization_binding.json` | **本次最佳化使用的 effective_metrics** 與其 point/cost/result hashes |
| `rtl/validation.json` | 標準測試＋每個選定模組參數的 scoreboard、四個 tops elaboration |
| `synthesis/synthesis_validation.json` | 四個 tops 結構檢查、generic synthesis、MAC／memory 資源核對 |
| `logs/`、`rtl/*.log`、`synthesis/*.log` | 命令、測試、工具輸出 |
| `events.jsonl` | 固定 Q01–Q09 的 START/PASS/FAIL 事件日誌 |
| `QC_REPORT.md` | 驗收摘要 |
| `run.json` | 最終 PASS/FAIL、checks、git/source/runtime、所有 evidence 檔案 hashes |

注意：`selected_rtl/manifest.json` 的 `evaluation_metrics` 保留原始解析 base model。應使用 `optimization_binding.json.effective_metrics` 或 `optimization.json` 讀取本次成本 adapter 的有效 PPA，不能混用兩組功率／溫度。

HB slot area 與 module cell/macro area 可能位於相同 footprint，**不能相加宣稱 total die area**。固定 Cu fill 下熱阻不隨 pitch 改變是均質化模型的假設，不能據此否定微觀 spreading 的 pitch 效應。

## 9. 固定 quality checks

| ID | 必須通過的檢查 | 失敗代表 |
|---|---|---|
| Q01 | schema、來源、成本等級、參數範圍與搜尋上限 | 設定不能正確解讀或超出支援範圍 |
| Q02 | 全部 Python unit tests | 模型、最佳化或流程回歸失敗 |
| Q03 | 完整網格評估與可行解選擇 | 沒有可行解／資料缺漏／模型錯誤 |
| Q04 | 全部候選重新計算、排序與選解重現，輸入快照一致 | stale、漏點、內容修改或非確定性 |
| Q05 | manifest、files.f、每個 RTL 檔案 hash、selected ID | 匯出內容不一致 |
| Q06 | 所有標準 scoreboard＋每個 selected module 的實際參數；四個 tops 展開 | 功能錯誤、工具缺失或驗證覆蓋不完整 |
| Q07 | Yosys 四個 top 檢查、system generic synthesis、MAC/memory 數量核對、無意外 latch | 電路結構／資源不一致 |
| Q08 | 所選 constraints/Pareto、所有可行模型點的能量與熱守恆 | 選解不合法或數值錯誤 |
| Q09 | 來源在執行期間未變、必要 evidence 完整、最終 RTL/PPA binding 一致 | 任務期間改動程式或交付不完整 |

熱殘差上限為 `1e-8 × max(1, power_w)` W，同時检查 nodal residual 與整體熱平衡。能量恆等式容許 `1e-10 × max(1, energy_mj)` mJ。這些是數值一致性檢查，不是模型準確度誤差棒。

目前標準 RTL regression 有 17 組，另外對每個選定模組加一組對應參數測試；六個模組的範例總計 23 組。記憶體選定參數測試涵蓋起始／中間／末位址、bank/lane isolation 與可編碼的越界位址；不是窮舉全部資料。MAC／stream 以確定的模擬器亂數序列測試資料、signed arithmetic、wrap、排序與背壓；不是形式證明。

Full QC 不提供 skip tests、skip synthesis 或「缺工具仍 PASS」選項。單一外部檢查預設 timeout 300 秒，可用 `--timeout-seconds 600` 等調整（1–3600）。Timeout 一樣是失敗，必須評估是否縮小配置或給足資源後另開 run。

## 10. 固定執行日誌與證據保存

每次 full-QC 會自動附加一筆到 repository 的 `execution_logs/history.jsonl`。欄位固定包含 schema_version、UTC、run ID、PASS/FAIL、selected ID、source hash、run directory、run.json hash、Q01–Q09 狀態。

每次 run 有獨立 `events.jsonl`：schema_version、run_id、sequence、utc、check_id、status、detail。成功時依序有 Q01 START/PASS 到 Q09 START/PASS 共 18 筆。失敗時記錄該階段 FAIL，剩餘 checks 在 run.json 中為 NOT_RUN。**不得刪除失败紀錄、重寫 PASS、手動修改 hashes，或把 NOT_RUN 改成 PASS。**

日誌採 append、fsync，Unix 主機加 advisory lock，避免多個執行者交錯寫入全域 history。每個 run 目錄必須唯一；不支持在同一目錄並行執行／resume。若程序被 SIGKILL 或主機斷電，可能留下 RUNNING 而没有最後一筆 history；這種情況不算成功，应保留現場並在新目錄重跑。

`verify` 核對完整檔案 hashes、事件順序、來源／runtime、重算結果與候選 ID。雜湊提供一致性追蹤，不是不可竄改簽章；完整歷史仍需 Git／備份等保存。

`runs/` 的大型中間檔預設不提交 Git。正式交付應保留完整 run 目錄供重查，並將 `run.json`、`events.jsonl`、`QC_REPORT.md`、optimization.json、selected manifest/binding、工具摘要及四份輸入快照複製到 `execution_logs/` 下的唯一 archive 目錄後提交。這是精簡稽核包，未包含所有大型 netlist／log；不能對精簡包直接呼叫 full `verify`，應對原始 run 目錄驗證，或依輸入重新執行。

## 11. 失敗處理

| 現象 | 正確處理 |
|---|---|
| 無可行解 | 查看 optimization.json 的 reasons；提出 constraints／架構變更方案，保留原限制與失敗日誌，不自動放寬 |
| 需要 WNS 但資料為 null | 提供 point-table STA 資料；不要補假 0 |
| 缺少 point-table row | 完成所有幾何可行點的資料，或明確縮小新的搜尋網格 |
| 工具找不到／不能執行 | 安裝合法工具、修正 PATH／工具環境變數，再建立新 run |
| generic SRAM 展成大量 FF 導致超時 | 使用適當資源或先縮小測試；真實 PPA 應另外綁 SRAM macro，不能拿此 FF 面積代替 |
| hash／replay mismatch | 检查 source、參數、環境、套件版本；重新 evaluate/QC，不更新舊 hash 來消除錯誤 |
| RTL test／synthesis failure | 修正 implementation 或支援範圍，加入有意義的回歸測試，更新 roadmap，重新完整驗收 |

`optimize.py` 成功為 exit 0、無可行解為 exit 2、設定／執行錯誤為 exit 1。`quality_check.py run/verify` 只有完整成功為 0，其餘為非 0。

## 12. 其他 AI agent 的交付格式

開始先讀 [AGENTS.md](AGENTS.md)、本手冊與 ROADMAP.md。不要因函式庫裡有 MAC/RF 就將輸出稱為完整 GPU。不要增加任務外的雲端部署、GitHub 分享或排程；commit/push 依使用者當次授權執行。

完成回報至少列出：

- run ID、原始 run 路徑與精簡稽核包路徑。
- objectives、constraints、cost quality/provenance。
- raw／unique／eligible／Pareto 數量與 selected point ID。
- 所選 area/power/latency/energy/temperature 與有效資料來源。
- Q01–Q09 結果、Python tests／RTL cases／synthesis 結果。
- 完整 `verify` 是否成功；若有 commit/push，列 commit 與 remote branch。
- 尚未覆蓋的 workload、physical timing、thermal 校準或其他限制。

任何重大功能或驗證範圍更動都要同步 ROADMAP.md。此最佳化與固定驗收流程的交付完成，不代表 roadmap 中完整 GPU、製程校準與 thermal signoff 項目已完成。
