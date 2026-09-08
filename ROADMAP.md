# HB pitch 研究 roadmap

更新：2026-09-08。研究主線為 HB pitch × 架構切割粒度的 module-level 探索。依新需求加入「評估參數與 RTL 共用規格 → 凍結候選 → 匯出實作」，先完成六類數位模組；完整 AI GPU 為後續擴充。

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

## v0.3：架構與技術資料校準

- [ ] 確定要評估的 pitch 範圍、stack、node 與 cooling envelope。
- [ ] 接 AccelForge／HWComponents（先驗證版本 API 與假設）；不要重寫 mapper。
- [ ] 匯入 SRAM macro 成本、HB RC／energy、接收發送端與可路由連接密度。
- [ ] 按 module type／parameters／RTL hash 與 node／corner／flow 匯入合成／APR 的 area、delay、energy/action、leakage；擬合有效範圍內的成本。
- [ ] 分離 HBM、NoC、SRAM、HB bytes，加入 bank conflicts、RF dependency 與 buffering。
- [ ] 保存 per-parameter provenance、有效範圍、uncertainty 與校準／驗證樣本分割。

## v0.4：熱與實體交叉驗證

- [ ] 以 FEM／量測 unit cell 驗證固定 Cu 比例下的 pitch/spreading 效應。
- [ ] 加入空間材料圖、實際 active-layer 位置、TSV／BEOL／TIM 與 package。
- [ ] 匯入動態 module power trace，加入溫度相關 leakage 與節流閉迴路。
- [ ] 選轉折點前／附近／後的 module 配置跑局部 APR；量測 timing／routing／clock／IR。
- [ ] 保留固定架構與各 pitch 重新最佳化兩組結果，生成含不確定度的 Pareto 圖。

## 研究結論的門檻

未經上述交叉驗證，不宣稱「最佳 pitch」、實際 SoIC 的 PPA／温度或 foundry 製程可製造性。最終輸出應指出哪些架構受 pitch 限制、收益飽和範圍，以及 SRAM／layout／thermal pad 等替代方案是否可取得相近收益。
