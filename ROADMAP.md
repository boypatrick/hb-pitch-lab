# HB pitch 研究 roadmap

更新：2026-09-09。研究主線為 HB pitch × 架構切割粒度的 module-level 探索。已完成參數化六類 RTL、可設定 PPA 目標的最佳化與固定驗收／日誌；完整 AI GPU 為後續擴充。

## v0.1：可檢查的解析原型

- [x] 輸入模型／假設來源、pitch 清單與三種 traffic proxies。
- [x] 分開固定資料寬度、可變資料寬度；加入幾何、routing 與端點上限。
- [x] 分開固定 Cu 比例與固定 pad 直徑。
- [x] 實作兩層空間熱網路、穩態／固定功率暫態、守恆殘差。
- [x] JSON／CSV／圖表、輸入與程式雜湊、解析與物理不變量測試。
- [x] 文檔明示所有示例是假設，未做 foundry／APR／FEM 校準。

## v0.2：參數與 RTL 的可追溯對應

- [x] 六類參數化 RTL：integer MAC array、banked SRAM、RF、FIFO、HB digital pipeline、RR arbiter。
- [x] 共用參數範圍／ports／資源公式、Cartesian sweep、參數 bindings、明示 stream 接線。
- [x] 由實作參數導出 compute／SRAM／HB 上限；限制目前可支持的熱模型分割。
- [x] 18 個候選示例、16 個幾何可行；由 point ID 匯出固定 wrapper、tile／system／tier views、SDC、manifest。
- [x] 25 項 Python 測試、17 組 RTL 功能模擬及四個 generated tops elaboration。
- [x] Yosys 四個 top 結構檢查與 system generic synthesis；交叉確認 64 個乘法器、21,504 memory bits；未做製程 mapping／timing closure。
- [x] 防止 stale／篡改結果、HB 不可行、介面不匹配與不存在的 RTL 型別被匯出。
- [ ] 增加真正接通 SRAM/RF → tensor 的 dispatcher、dataflow controller 與 scoreboard。
- [ ] 加入 FP8/BF16/FP16 arithmetic、格式正確性驗證與相應成本模型。
- [ ] 加入 NoC router／跨時脈 adapter、foundry SRAM macro adapter。

## v0.3：最佳化、品質驗收與 agent 操作交付

- [x] 完整枚舉有限網格、硬限制、Pareto 集合、weighted-sum／lexicographic／單目標選解；超出搜尋上限拒絕執行。
- [x] PPA／energy／thermal／容量目標與限制；未知欄位、缺失 timing、無可行解不會被忽略。
- [x] 分離 module area 與 HB slot area；resource estimate 明示 synthetic/estimated，逐點 PPA 支持完整 reported table 與 WNS 門檻。
- [x] 固定 Q01–Q09：輸入、Python regression、完整搜尋、重現、RTL hashes、選定參數功能模擬、generic synthesis、物理一致性、交付完整性。
- [x] 每次 full-QC 的 append-only JSONL history／events、PASS/FAIL/NOT_RUN、source/runtime/artifact hashes 與 verify 命令。
- [x] 完整操作手冊、數學定義／手算案例、失敗處理、AGENTS.md 執行契約。
- [x] 選定模組的實際參數加入 RTL scoreboard；支援較深 FIFO 的 fill／full-replace／drain 驗證。
- [x] 發行驗收：45 項 Python tests、23 組 RTL simulations、四個 top 結構檢查與 generic synthesis；九項 QC、獨立 verify、無可行解與 artifact 修改偵測均完成，稽核紀錄存於 execution_logs。
- [ ] 使用真實製程 module/PPA 樣本替換 synthetic coefficients，確認 cost scope 與有效範圍。
- [ ] 多 workload／工作負載映射可行性、每 bank 容量／衝突與 uncertainty-aware robust optimization。
- [ ] 經校準的 clock/tile-count 聯合搜尋、大規模搜尋加速與微架構切割擴充。

## v0.4：架構與技術資料校準

- [ ] 確定要評估的 pitch 範圍、stack、node 與 cooling envelope。
- [ ] 接 AccelForge／HWComponents（先驗證版本 API 與假設）；不要重寫 mapper。
- [ ] 匯入 SRAM macro 成本、HB RC／energy、接收發送端與可路由連接密度。
- [ ] 逐點 PPA 匯入已於 v0.3 完成；後續按 module type／parameters／RTL hash 與 node／corner／flow 建立 action-level 成本擬合與有效範圍。
- [ ] 分離 HBM、NoC、SRAM、HB bytes，加入 bank conflicts、RF dependency 與 buffering。
- [ ] 保存 per-parameter provenance、有效範圍、uncertainty 與校準／驗證樣本分割。

## v0.5：熱與實體交叉驗證

- [ ] 以 FEM／量測 unit cell 驗證固定 Cu 比例下的 pitch/spreading 效應。
- [ ] 加入空間材料圖、實際 active-layer 位置、TSV／BEOL／TIM 與 package。
- [ ] 匯入動態 module power trace，加入溫度相關 leakage 與節流閉迴路。
- [ ] 選轉折點前／附近／後的 module 配置跑局部 APR；量測 timing／routing／clock／IR。
- [ ] 保留固定架構與各 pitch 重新最佳化兩組結果，生成含不確定度的 Pareto 圖。

## 研究結論的門檻

未經上述交叉驗證，不宣稱「最佳 pitch」、實際 SoIC 的 PPA／温度或 foundry 製程可製造性。最終輸出應指出哪些架構受 pitch 限制、收益飽和範圍，以及 SRAM／layout／thermal pad 等替代方案是否可取得相近收益。
