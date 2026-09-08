# HB Pitch Lab 0.3

可執行的 **pre-RTL、module-level HB pitch 研究原型**。輸入 JSON，輸出頻寬／延遲／能耗／介面面積預算、兩層溫度與圖表。0.2 新增六類參數化 RTL，能由選定的評估結果匯出固定配置；尚未實作完整 GPU。

新功能入口：[參數評估與 RTL 匯出流程](MODULE_RTL.md)。設定在 `examples/modules.json`，結果示例在 `results/module_demo`，固定配置 RTL 在 `results/generated_v02`。以下原有 `run.py` 流程仍是沒有對應 RTL 的 traffic proxy；必須使用 `module_flow.py` 才能匯出實作。

**0.3 新增可設定目標／限制的完整枚舉 PPA 最佳化、Pareto 集合、逐點 PPA 匯入、九項固定驗收與執行日誌。** 詳細步驟、演算法推導、成本資料格式與失敗處理見 [完整操作手冊](OPERATIONS_MANUAL.md)；其他 AI agent 先讀 [AGENTS.md](AGENTS.md)。

完整執行與驗收（使用未存在的 output 目錄）：

```sh
python3 quality_check.py run --design examples/modules.json --policy examples/optimization_ppa.json --out runs/ppa_001
python3 quality_check.py verify --run runs/ppa_001
```

範例成本是 synthetic。每次 full-QC 都會附加 `execution_logs/history.jsonl`，PASS 必須包含 Q01–Q09 全部通過；沒有跳過工具仍宣告完成的模式。`runs/` 與大型 netlists 不提交 Git，正式執行摘要存入 `execution_logs/`。

**這是未校準的解析模型，不是 SoIC PPA 預測器、signoff 工具或已整合 AccelForge 的完整模擬器。示例中所有物理、電性與工作負載資料都是假設。**

## 執行

在本目錄執行（Python 3.9+）：

```sh
python3 run.py --config examples/demo.json --out results/demo
python3 -m unittest discover -s tests -v
```

依賴 numpy、scipy、matplotlib；目前工作環境已有安裝。其他環境可在自己的 virtual environment 安裝 requirements.txt。

輸出：`results.json`、`sweep.csv`、`thermal_control.csv`、`fixed_power_transient.csv`、圖表與 `REPORT.md`。包含輸入快照、輸入 SHA256、引擎 SHA256；以相同參數重跑可追蹤比較。

## 目前實作

- 任意 pitch 清單；固定 Cu fill 或固定 pad diameter。
- 固定連線寬度：不夠放時標記 infeasible，不能偷偷改成 serialization。
- 寬度掃描：在 HB 幾何、routing 與 endpoint 上限內增加平行資料線。**不是 architecture optimizer。**
- Compute、HB、SRAM、NoC、外部記憶體的完全重疊延遲下界。
- 可替換的 compute、memory、link energy 與 lane clock／面積成本。
- 空間上 2 × n × n 的線性有限體積熱網路；穩態與 backward-Euler 暫態。
- 固定功率／固定位置的熱控制實驗，與工作負載導致的功率變化分離。
- HB 熱阻與 energy/bit 可匯入 pitch lookup；超出資料範圍拒絕外插。

三個示例是 `coarse_tile_L2`、`bank_to_tensor`、`RF_lane_traffic_proxy`。它們只有流量／容量／成本參數不同；並非實作了三種微架構。RF proxy 不模擬 scoreboard、回授延遲、RF ports 或 bank conflict。

## 方程與單位

幾何連接容量：

`N = floor(floor(window_mm2 * 1e6 / pitch_um²) * signal_fraction)`

這是局部連接區的幾何上界，不是全晶片 pin-access/DRC 結果。`signal_fraction` 是 P/G、clock、test 等預留之後的資料線配額，和熱模型的 Cu 比例互相獨立。

`B_HB [GB/s] = lanes_per_tile * tile_count * lane_rate_Gbps * payload_efficiency / 8`

HB read/write 共用此聚合資料預算；若有獨立雙向通道，需先各自建模，不能把此值當 full-duplex 每方向頻寬。

`latency = max(work_ops/peak_ops_s, HB_bytes/B_HB, HB_bytes/B_SRAM, HB_bytes/B_NoC, external_bytes/B_external)`

完全重疊、忽略排隊與填充，故為樂觀下界。SRAM 與 NoC 流量暫與 HB bytes 相同。外部記憶體只做時間上界，本版 energy 範圍是兩層 dies 的合成 proxy，未獨立加入 HBM stack 能耗。

`energy = compute_actions * E_compute + HB_bytes * E_memory + HB_bits * E_link + runtime * (background_power + lane_clock_power)`

背景功率是使用者提供的固定開銷，應包含所需的 idle/control/leakage 成分；不隨溫度更新。端點功耗各一半放到兩層。link energy 預設固定，**沒有硬編碼 pitch 縮小就自動省電**。

`Cu fill = pattern_coverage * pi/4 * (pad_diameter/pitch)²`

`R_interface'' = 1 / (Cu_fill/R_Cu_path'' + (1-Cu_fill)/R_dielectric_path'')`

兩個路徑的 R'' 都為 m² K/W，應含各自的材料厚度與接觸熱阻。`pattern_coverage_fraction` 是整個熱介面的 pattern 覆蓋比例；未分配到 signal 的 Cu 可能屬於 P/G 或 dummy pads。此項需以真實版圖校準，不能從訊號數推算。

固定 Cu 比例時此均質化模型會得到相同熱阻。這是模型假設的結果，**無法測出等 Cu 比例下微觀 pitch/spreading 的收益**；必須匯入 FEM／量測的 R'' 才能研究該效應。

熱網路解：`G θ = P`，暫態解 `(C/dt + G) θ_next = P + C/dt θ_previous`。

節點在每層薄矽片中面；含水平導熱、垂直半層矽熱阻、無熱容量的 HB 介面。上下表面可接固定溫度 reservoir，側面絕熱；上方邊界 R'' 為 TIM／封装／冷卻系統的有效熱阻參數，不是已建立實體冷板模型。默認下方絕熱。

晶片總 footprint 固定。`hb_site_budget_mm2` 為保留比例後的 bond slot 配置預算，`endpoint_cell_area_mm2` 是端點 cell 成本，兩者都可能位於 die footprint 內；**不能相加當成 die 面積，也不能由它們宣稱晶片面積縮小。**

## 校準資料入口

HB 設定可加：

```json
{
  "interface_r_lookup": {
    "constant_fill": {"1.0": 1e-6, "4.0": 1.2e-6}
  },
  "link_energy_lookup_pj_bit": {"1.0": 0.2, "4.0": 0.3}
}
```

以上仍只是語法示例。thermal lookup 按 pad mode 分組；energy lookup 是跨 pad mode 共用的總能耗查表，若兩種 pad mode 的電性不同，請分開配置檔／分開執行。線性內插而不外插。`provenance` 必填；資料來源、製程、工作點與有效範圍應填入並保存。

## 驗證與限制

測試覆蓋單柱解析解、非均勻功率能量守恆、零功率、均勻負載網格細化、暫態能量守恆與收斂、幾何 scaling、非法參數、lane 可行性、頻寬飽和、固定介面不會自動加速、校準範圍及雙面冷卻。

這些是數值／程式驗證，**不是 FEM、APR 或 silicon accuracy 驗證**。本版未包含 RC timing、bank conflict、完整 dataflow mapping、微觀 Cu spreading、PDN/IR drop、熱相關 leakage、熱節流、製程統計／良率、finest-pitch manufacturability。也沒有安裝或整合下面的新工具。

## 更新的相關工具（查閱日期：2026-09-08）

- [AccelForge](https://github.com/Accelergy-Project/accelforge)：Python tensor-accelerator modeling、fusion-aware mapping、heterogeneous compute、HWComponents 元件模型。其[假設文件](https://accelergy-project.github.io/accelforge/guide/modeling/assumptions.html)仍包含完全重疊與固定 action cost；不能把 mapper optimality 當成物理硬體最佳解。
- [Cool-3D](https://github.com/iCAS-SJTU/Cool-3D)：2025 JETCAS，已公開，整合 gem5／McPAT／CACTI／HotSpot 與微流道冷卻，提供 pre-RTL stack/thermal 探索。不是專用 HB pitch 電性模型。
- [Open3DBench](https://github.com/lamda-bbo/Open3DBench)：2025 工作，目前 README v1.1，MoL／LoL 後端比較；NanGate45_3D 雙金屬堆疊為評估環境，不是 SoIC PDK。
- [Open3DFlow](https://github.com/b224hisl/Open3DFlow)：3D RTL-to-GDS flow；README 說明 3.0 部分因 NDA 尚待匿名化公開。
- [NanoIC D2W HB PDK](https://www.imec-int.com/en/press/nanoic-opens-access-first-ever-fine-pitch-rdl-and-d2w-hybrid-bonding-interconnect-pdks)：2026-03-02 公布 exploratory/pathfinding PDK，初版提供 layout／routing／DRC。需查核存取條件及可用模型；不能假設包含完整 thermal/RC/signoff，也不等同 TSMC SoIC 製程。

建議方向：讓本工具負責 pitch、幾何、物理模型與掃描；使用 AccelForge 供應 workload/mapping/action counts，以 Cool-3D 或 FEM 校準熱網路，再以少數 Open3DBench／商用 APR 點驗證路由與時序。
