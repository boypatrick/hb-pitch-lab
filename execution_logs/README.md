# 固定 quality-check 執行紀錄

`history.jsonl` 由 `quality_check.py run` 自動附加，每次 full-QC 一筆。保留原始 PASS／FAIL，不刪除失敗紀錄。詳細格式、驗收門檻與備份規則見 [操作手冊](../OPERATIONS_MANUAL.md)。

| 欄位 | 定義 |
|---|---|
| schema_version | 目前為 1 |
| utc／run_id | UTC 時間與唯一執行 ID |
| status | full-QC 的 PASS 或 FAIL |
| selected_point_id | 選定候選；無可行解／尚未選點時為 null |
| source_sha256 | 當次 Python、RTL、測試來源內容的 hash |
| run_directory | 相對於 repository 的原始 evidence 目錄 |
| run_json_sha256 | 完成時 run.json 的 SHA256 |
| checks | 固定 Q01–Q09 的 PASS／FAIL／NOT_RUN |

## 2026-09-09 發行驗收

精簡稽核包：[2026-09-09_ppa_release](2026-09-09_ppa_release/)。原始完整 run 在 `runs/ppa_release_20260909`，未提交大型 netlist／tool logs。稽核包不能直接代替原始 run 執行 full `verify`；其他機器應按保存的 inputs 與手冊重新執行。

- [成功紀錄](2026-09-09_ppa_release/success/QC_REPORT.md)：Q01–Q09 全 PASS；45 項 Python tests、23 組 RTL simulations、四個 tops elaboration／Yosys 結構檢查與 system generic synthesis。
- [獨立重驗收據](2026-09-09_ppa_release/verification_receipt.json)：原始完整 evidence hashes、source/runtime、重算結果與候選 ID 驗證成功。
- [最佳化結果](2026-09-09_ppa_release/success/search/OPTIMIZATION.md)：18 個候選，8 個滿足 constraints，3 個 Pareto 候選；依明示平手規則選 8 µm pitch。
- [所選 RTL](2026-09-09_ppa_release/success/search/selected_rtl/README.md)：2 tiles、8×4 integer MAC／tile、64-bit HB pipeline、2 stages；64 個乘法器、20,992 memory bits 與模型一致。
- [預期失敗案例](2026-09-09_ppa_release/expected_no_feasible_failure/QC_REPORT.md)：極小 area 上限使 Q03 FAIL、exit 1、後續 NOT_RUN，沒有產生 RTL；這是負向測試成功，原始 full-QC 狀態仍保留 FAIL。
- [檔案修改偵測](2026-09-09_ppa_release/tamper_detection.json)：在完整 run 的副本修改 optimization.json 後，verify 正確拒絕；原始 evidence 未更動。

所選 synthetic 模型結果約為：module area 0.03174112 mm²、power 0.242204945 W、latency 0.031262 ms、energy 0.007571811 mJ、steady Tmax 40.069317 °C。這些是為測試演算法而提供的假設資料，**不是實際 ASIC／SoIC PPA 或最佳製程 pitch 結論**。

日誌使用 UTC，因此本地台灣日期 2026-09-09 的執行 ID 可能以 `20260908T...Z` 開頭。開發過程的較早 PASS 記錄屬於其各自 source hash，不表示可直接在新版 source 上通過 verify。
