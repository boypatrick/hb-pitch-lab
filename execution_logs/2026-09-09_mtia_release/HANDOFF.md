# MTIA-like 第一階段交付紀錄

交付整理日期：2026-09-10 Asia/Taipei。run IDs 與工具日誌使用 UTC；目錄保留 2026-09-09 的執行日期。

已完成可執行 INT8/INT32 PE/scratch/ME-NMC、2D/coarse/local 三切割、完整網格最佳化、對應 RTL、逐 cycle replay、generic synthesis、操作手冊、固定日誌與負向驗收。這一階段的軟體／RTL 交付已收尾；商用架構代表性與製程／thermal 校準尚未完成。

## 執行與驗收

| 流程 | run ID | 原始 full run | 結果 |
|---|---|---|---|
| MTIA 全網格 | `20260909T145004Z-63f950f4ecf0` | `runs/mtia_release_20260909` | M01–M06 全 PASS；verify exit 0 |
| 原有 module 回歸 | `20260909T145021Z-03d112c6b44a` | `runs/ppa_mtia_regression_20260909` | Q01–Q09 全 PASS；verify exit 0 |
| 無可行解負向案例 | `20260909T150143Z-9efa0dc3d563` | `runs/mtia_no_feasible_20260909` | 按預期 M02 FAIL、M03–M06 NOT_RUN；run/verify 均 exit 1 |

full run 路徑相對 repository 根目錄。本稽核包只保存精簡證據，不能當 full run 執行 verify。原始 M run 約 180 MB、Q run 約 35 MB，留在本機 ignored `runs/`。

- Python：63 tests PASS，包含 18 項新增 MTIA tests；參數變化／kernel tests 內含 18 次 RTL replay，另有三切法的 occupied-slot 背壓仲裁 replay。
- M03：13 個候選中 10 個幾何可行 × 5 workloads = 50 組 frozen wrapper/RTL 逐拍比對 PASS。
- M04：10 組 synthesis PASS；每組 16 multipliers、10,240 logical memory bits，沒有 latch。generic cells 因切法／宽度不同為 19,032–29,818，memories 保留，並非 foundry cell area。
- Q06/Q07：原有 23 組 module RTL simulations、四個 top elaboration/structure checks 與 system generic synthesis PASS。
- M01/M02/M05/M06 及 Q01–Q09 詳項見各自 `QC_REPORT.md`、`run.json`；原始 source/runtime/artifact hashes 皆保留。

[verification_receipts.json](verification_receipts.json) 保存實際 argv、exit code、stdout/stderr、UTC：合法 local-cut export 成功；同目錄再次 export 被拒絕；完整 run 的獨立 byte copy 修改 `mtia_pe.sv` 後 verify 被拒絕；兩個未修改原始 run 再次 verify 成功。複本未使用 hard links，已隨 temporary directory 清除。無可行解案例及固定限制保存在 [no_feasible_audit](no_feasible_audit/failure_receipt.json)。

打包時曾把原有 Q 的輸入目錄誤指為 `inputs/`；複製程序失敗後改用其實際 `search/inputs/` 完成稽核包。這是包裝路徑更正，沒有修改任何原始驗收 run 或工具结果。

## 輸入、搜尋與有效選點

MTIA 使用 [設計](../../examples/mtia.json)、[policy](../../examples/mtia_policy.json)、[synthetic costs](../../examples/mtia_costs_synthetic.json)；凍結快照在 `mtia/inputs/`。PES=2、LANES=8、scratch rows/shared entries=64、clock target=1 GHz。pitch={8,4,2} µm、local width={16,64,128} bits、coarse=64 bits、STAGES=1。

Policy 為 lexicographic：依序 latency/energy/area 最小化，scale=0.001 ms/0.001 mJ/0.01 mm²、weight 均 1；area≤0.1 mm²、steady Tmax≤85°C，最後同分偏好較大 pitch。raw/unique=13/13、geometry feasible=10、eligible=10、Pareto=1。完整結果見 [evaluation.json](mtia/search/evaluation.json)。

所選 `83955264838cf9517b7bd7b068a2368e7b5b9c5db082d4a5f4ff48134287dd80` 為理想直連 **2D baseline**，不是 SoIC 選點。所選有效 suite metrics：

| metric | synthetic 值 |
|---|---:|
| area | 0.004448 mm² |
| mean power | 0.01860422073 W |
| suite latency | 0.018575 ms = 18,575 cycles @ target 1 GHz |
| suite energy | 0.0003455734 mJ |
| max per-workload steady cell Tmax | 40.38967352°C |
| WNS | null，沒有 STA |

原有 Q 回歸使用 `examples/modules.json`、`examples/optimization_ppa.json`、該設計的 environment 與 `examples/costs_synthetic.json`，四份快照在 `legacy_q/search/inputs/`。weighted_sum 的 area/power/latency 權重為 0.3/0.3/0.4、scale=0.03 mm²/0.3 W/0.04 ms；限制 area≤0.1、latency≤0.04 ms、Tmax≤85°C、SRAM≥1024/RF≥256/FIFO≥32 bytes per tile。raw/unique=18/18、eligible=8、Pareto=3。

Q 選點 `72226b2baaccf4a9eb49fb125abc936670159da7617b2a642e1cd094d091cdbc`：area=0.03174112 mm²、power=0.2422049450 W、latency=0.031262 ms、energy=0.007571810992 mJ、Tmax=40.06931722°C、pitch=8 µm、WNS=null。其 scope 是原有 module benchmark，不能與 MTIA 數字當同一工作負載比較。[optimization.json](legacy_q/search/optimization.json) 保留完整策略與 reasons。

## HB pitch 的收益與反例

只在 local-scratch 切法內，依每個 pitch 幾何可行的最低 cycles 寬度比較；這不是全域 PPA policy 的選點：

| Case | 8 µm / 16b | 4 µm / 64b | 2 µm / 128b | 8→2 µm latency 下降 |
|---|---:|---:|---:|---:|
| 局部供料 | 322 cycles | 226 | 210 | 34.7826% |
| HBM 受限 | 10267 | 10171 | 10155 | 1.0909% |
| NIC 受限 | 8234 | 8234 | 8234 | 0% |

同寬度跨 pitch 的 cycles 完全相同；固定 conductance 的 thermal 也完全相同。coarse 64b 在三個 pitch 皆放得下，因此縮 pitch 沒有帶來邏輯執行收益。2D 對應三個案例為 91/10036/8234 cycles；此 baseline 沒有平面 routing extraction。

依公式 `ceil(2AW/8)+ceil(16×LANES/B)+2×STAGES+4`，16/64/128-bit 每次 vector iteration 預測 16/10/9 cycles；實際 event trace 的每 PE 每 command 內間距逐筆相符。每次 local_supply 都完成 320 HBM bytes、512 scratch-read bytes、4928 HB bits、512 PE ops、16 NMC adds。[numerical_checks.json](numerical_checks.json) 記錄手算公式、逐筆間距與固定寬度溫度控制。

此 synthetic cost 下，local_supply 16→128b 同時造成 energy −22.6896%、area +8.7126%、mean power +18.5426%，cell Tmax 從 40.255752°C 變為 40.309230°C。不能宣稱 pitch 縮小必然降溫；這只是固定 G、未校準成本的運算結果，並非晶片預測。

## 可用 RTL 與操作入口

完整手冊：[MTIA_OPERATIONS.md](../../MTIA_OPERATIONS.md)。從 JSON 設計與 policy 開始，Python 可直接完成 `run → verify → export`，不需要 AI 重新 assembly。

全域所選 RTL 在 `runs/mtia_release_20260909/search/selected_rtl/`。另匯出的可行研究點 `ead2debf458c42874a1a969f2e90089726a69eaa34a094e9c4eba76cb7dd7d53` 是 local-scratch 2 µm/128b；在 `runs/mtia_local_export_20260909/`，稽核包亦保留小型完整 [local_cut_rtl](local_cut_rtl/manifest.json)。包括 5 個源 RTL、固定 wrapper、files.f、clock.sdc、manifest、optimization binding。保留兩個選點是讓全域 policy 結果與局部切割研究都可檢查。

placement intent 為 PE 在靠散熱的 tier 0、scratch/shared/ME-NMC 在 tier 1；尚未生成兩顆 die 的分離 netlists，clock.sdc 未含跨 die I/O constraints。接 ASIC flow 仍須綁 2R1W SRAM macro/可行替代實作、Liberty、HB RC、PDN/clock/floorplan 及 STA/APR。

## 代表性與下一步

R01/R06 PARTIAL；R02/R03 僅對支持的 integer kernel、cycle model vs RTL PASS；R04/R05 NOT_CALIBRATED，整體 EXPLORATORY。參見 [representation.json](mtia/representation.json)。沒有 RISC-V/完整 MTIA ISA、FP8/BF16、完整 SFU、SIMT、NoC/RDMA、HBM/NIC/package power 或 foundry/FEM 校準。沒有由 generic synthesis 宣稱實際 ASIC 頻率、最佳 SoIC pitch 或 junction Tmax。

建議下一步先用少量 module synthesis／SRAM macro／局部 APR 點替换 synthetic 成本，並以固定功率圖校準兩層 thermal network；架構擴充按 roadmap 依序做 TPU training/inference，再做 SIMT GPU。較小 pitch 的必要性，最後應以各瓶頸下的可辨識收益與誤差範圍判斷。
