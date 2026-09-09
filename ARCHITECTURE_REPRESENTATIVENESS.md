# 架構代表性與 2-tier HB 切割研究

查核日期：2026-09-09。本文保留原廠來源與研究切割設計。後續已實作第一階段 MTIA-like INT8/INT32 PE/scratch/ME-NMC 子系統，見 [MTIA 操作手冊](MTIA_OPERATIONS.md)；未完成原廠 ISA、TPU/SIMT、PPA holdout 或 thermal 校準。

## 1. 現況與可聲稱的範圍

原有六類 RTL 是 module benchmarks。`int_mac_array` 是 signed integer outer-product MAC；不是 TPU systolic pipeline，也沒有 GPU 的 SIMT、warp scheduler、scoreboard 或 tensor instruction。原有 assembly 除 FIFO/HB stream 之外未接通 kernel；新的 `mtia_*.sv` 已獨立接通整數 kernel、scratch 和 collective，並保留 2D/coarse/local 三切法。Q01–Q09 仍驗證原有軟體與模組，新 M01–M06 驗證有界架構模型對 RTL 的一致性；兩者都不能單獨證明對商用產品的準確度。

現有實作尚未建立「商用架構特徵 → workload mapping → 活動量 → module 成本 → 空間熱模型」的校準鏈。因此，應稱為 HB pitch 評估框架原型，不能稱為真實 GPU 的 PPA 預測器。公開架構圖也不提供完整 RTL、foundry memory compiler、floorplan、RC 與 activity；增加圖中同名方塊不會自動補齊這些資料。

研究目標是保留影響 HB 切割結論的瓶頸與物理量，建立有適用範圍的架構族模型；不是宣稱重製原廠晶片。

## 2. 原廠公開參照與日期

以下是本次實際查閱的資料。公開事實與第 3 節提出的切割方案必須分開使用。

| 參照 | 可確認的架構特徵 | 對評估器的要求 |
|---|---|---|
| NVIDIA Rubin，官方技術文章 2026-07-21 | SM/Tensor Core、L2、TMA、HBM4、NVLink，以及 attention 的 sparse metadata、softmax 與 kernel 依賴 | 不能只測 dense GEMM；須量化資料搬移、非矩陣算子及依賴延遲 |
| Google TPU 8t / 8i，官方技術文章 2026-04-22 | 8t 分開 MXU/VPU/SparseCore；8i 強調 SRAM 與 CAE collective engine | 訓練與推論使用不同映射；分開 irregular memory 與 reduction 流量 |
| Meta MTIA 300，官方文章 2026-08-24 | 12×6 PE grid、16 message engines、near-memory reduction、兩個 NIC chiplets | 將 collective offload 與 compute grid 各自建模，保留與 HBM/cache 的位置關係 |
| Meta MTIA 300/400/450/500，官方 roadmap 2026-03-11 | PE 的 vector/DPE/SFU/reduction/DMA/local scratch；後續世代擴充 GenAI、低精度與 HBM | 分開 PE 局部流量、chiplet 流量及 NIC 流量，不能一律歸成 HB bytes |
| AMD MI300，CDNA 3 原廠白皮書及架構文件 | 上層 compute XCD、下層 I/O die 與 memory-side infrastructure；真實 3D chiplet 實例 | 提供 coarse compute-on-I/O 對照；不能假定其產品數據可推導更細 pitch 的增益 |

來源：

- [NVIDIA Rubin 技術文章](https://developer.nvidia.com/blog/inside-nvidia-rubin-gpu-architecture-powering-the-era-of-agentic-ai/)
- [Google TPU 8t / 8i 技術文章](https://cloud.google.com/blog/products/compute/tpu-8t-and-tpu-8i-technical-deep-dive)
- [Meta MTIA 300，2026-08-24](https://engineering.fb.com/2026/08/24/networking-traffic/mtia-300-meta-training-chip-built-in-nics/)
- [Meta 四代 MTIA roadmap，2026-03-11](https://ai.meta.com/blog/meta-mtia-scale-ai-chips-for-billions/)
- [AMD CDNA 3 白皮書，Figure 1](https://www.amd.com/content/dam/amd/en/documents/instinct-tech-docs/white-papers/amd-cdna-3-white-paper.pdf)
- [AMD MI300 microarchitecture](https://instinct.docs.amd.com/develop/gpu-arch/mi300.html)
- [AMD CDNA 技術頁：3D hybrid bonding](https://www.amd.com/en/technologies/cdna.html)

以 2026-09-09 為基準，近一個月指約 2026-08-09 至 2026-09-09；MTIA 300 的 8 月文章在此區間，3 月 roadmap 則不在。8 月文章是新公開說明，不等同該晶片首次發表。

[Hot Chips 2026 官方議程](https://hotchips.org/) 確認 8 月 24 日的 Rubin/MI400，以及 8 月 25 日的 Meta「From Recommendation to Dual-Mandate with GenAI」與第八代 TPU 報告。網站列出註冊後的投影片／影片存取；本次沒有取得完整會議投影片，不能聲稱已逐頁驗證 MTIA 400 的會議內容。TPU 的 3D torus 指多晶片網路拓樸，不是 3D IC。

## 3. 供比較的 2-tier 切割方案

除 MI300 公開的功能分層參照外，以下都是本研究提出的候選，並非原廠 SoIC floorplan。統一假設上方為主要 cooling boundary；實際 face-to-face/face-to-back、active layer、BEOL/TSV、供電與散熱須以封裝資料替換。HBM stacks 位於堆疊之外的封裝側，不能把其發熱省略於最後的 package thermal model。

### A. SIMT + tensor GPU，Rubin 類

- 保守切法：Tier 0 保留完整 SM 的 scheduler、RF、ALU、Tensor Core、L1/shared/TMEM 等緊耦合路徑；Tier 1 放 L2 banks、NoC 與 memory-side logic。跨 HB 為 cache-line/request/response 流量。
- 細切法：Tier 0 保留 scheduler、RF、執行單元與必要 accumulator；Tier 1 放 selected shared/operand SRAM banks，依 SM 分散垂直 ports。RF 不在第一輪拆開。TMEM 的操作數／累積角色須依具體指令契約，不能整塊不分用途搬移。
- pitch 可能有用之處：每個 SM 下方小面積內需要寬而多的局部介面，且 bank/endpoint 能提供足夠頻寬。只增加總 bond 數、不增加實際可用 ports 不會改善吞吐。
- 主要風險：shared-memory latency、bank conflicts、barrier 往返、TMA 與 tensor pipeline 背壓；細切引入的一拍不能用總平均頻寬掩蓋。
- thermal：高活動 SM 靠近散熱端是一個起始方案，仍需檢查上層高功率密度、下層 SRAM leakage 與熱點重疊。

### B. Dense training / TPU 8t 類

- 保守切法：MXU、accumulator、VPU、必要 staging 及 SparseCore 執行部分保留在 Tier 0；較大 VMEM/banked SRAM、memory fabric 放 Tier 1。
- 細切法：依 MXU tile 在 Tier 1 配置獨立 operand SRAM bank，跨 HB 供應寬資料。局部 accumulator 與 PE 內 recurrence 留在同層；SparseCore 的 irregular 流量另算。
- pitch 可能有用之處：降低供料端序列化與長水平線，允許更多並行 bank ports；已充分重用且 compute-bound 的大 GEMM 可能早已飽和。
- 主要風險：不要先把 systolic array 沿 PE 中間切半；operand/partial-sum 每拍跨層可能破壞時序與 pipeline。拆分 SRAM 也會增加 periphery、clock 與控制成本。
- thermal：比較陣列正下方集中 SRAM 與 bank 分散／錯位配置，保持相同工作量與散熱邊界。

### C. SRAM / collective 強化的 inference，TPU 8i 類

- 保守切法：Tensor/VPU/局部 accumulator 在 Tier 0；較大 SRAM 與 CAE-like reduction/synchronization engine 在 Tier 1。這是研究選擇，非 Google 公布的層位。
- 細切法：依 compute tile 提供多個分散 KV/activation SRAM banks；reduction engine 靠近其資料，避免為了匯總把全量資料重複搬回上層。
- pitch 可能有用之處：低 batch decode 的局部 SRAM 存取、並行 bank 連接；MoE/collective 的控制延遲可能比 byte throughput 更關鍵。
- 主要風險：工作集放不進 SRAM、HBM 或外部 ICI 飽和時，更密 HB 不會解決主瓶頸。CAE 流量不能和 tensor operands 混成單一利用率。
- thermal：下層 SRAM 不是零功率；高存取率與 reduction engine 可形成下層熱點，且 leakage 需隨溫度回授。

### D. PE grid + collective offload，MTIA 類

- 保守切法：Tier 0 保留完整 PE（vector、DPE、SFU、local scratch、DMA）；Tier 1 放共享 banks、message-engine/NMC 與 memory fabric。NIC chiplets 保留在封裝側，電氣連接仍须經相應 interface。
- 細切法：Tier 0 保留 vector/DPE/SFU 與 PE 內 reduction recurrence；Tier 1 依 PE 分配 local scratch banks，DMA endpoint 按延遲安排；ME/NMC 靠近共享記憶體／HBM 入口。
- pitch 可能有用之處：PE ↔ scratch 的分散連線、多個 PE 同時供料；細 pitch 讓靠近資料的 reduction 更容易組合，但必須建模實際資料省流量。
- 主要風險：如果主瓶頸是 NIC、HBM random access 或小訊息排程，增大 HB payload 並無直接改善；將 ME/NMC 拉離記憶體可能使 collective 多次跨層。
- thermal：DPE、SFU 與 NMC 的 activity 不同且可同時運作；需要 joint trace，不能以固定比例拆總 TDP。

### E. Compute-on-I/O 的真實 3D 參照，MI300 類

- 公開功能分層：上層 XCD 保留 compute 與較近端 cache，下層 I/O dies 承擔 memory-side infrastructure；HBM 在封裝側。
- 研究延伸：在相同粗切法下先固定 bus width，找密度飽和對照；再研究更細的 cache-bank/local-port 切法。後者不是 MI300 已公開的實作。
- 目的：防止只選對細 pitch 有利的架構。即使產品已使用 3D hybrid bonding，也不能據此斷言下一代縮 pitch 一定提高效能或降溫。

## 4. 代表性的可驗證定義

### 需要接通的最小運作單元

從可跑 kernel 的 tile/cluster 開始，不必先重製整顆 GPU：dispatcher/scoreboard → banked memory/RF → matrix/vector/SFU → reduction/writeback，加入真實 dataflow、位址、背壓、barrier 與 DMA/NoC endpoints。浮點與 microscaling 必須實作 format、rounding、accumulation 和 exceptional-value 契約，不能用縮小整數 DATA_W 代替。

跨層協定至少記錄 payload/control、方向、burst、multicast、同步頻率、critical dependency、outstanding transactions 與可接受 latency。每個切割必須有對應 evaluation adapter 與產生 RTL 的合法性契約。目前已支援 MTIA-like 有界子系統的 coarse/local scratch 切法及 2D；其單 outstanding、同時脈協定見操作手冊，其他架構與完整協定仍待擴充。

### Workload 與觀測量

| workload | 必須保留／量測的特性 |
|---|---|
| 大小不同的 GEMM、attention prefill | tensor utilization、operand reuse、softmax/reduction、非整齊尺寸與 pipeline 空泡 |
| 低 batch / 長 context decode | KV residency、HBM/SRAM bytes、dependency latency、token critical path |
| MoE | expert skew、token dispatch/gather、突發與不均勻網路負載 |
| embedding / recommendation | gather/scatter、bank conflicts、irregular access、cache 命中與 miss |
| compute 與 AllReduce/AllToAll 重疊 | message rate、ME/NMC utilization、NIC/HBM 爭用與 collective stall |

每次保留 per-module/per-action counts、每個 HB cut 的雙向 bytes/time trace、bank/queue occupancy、stall 原因、結果 correctness 與具有座標的 power trace。不能把未完成的 operations 當成節能。

### 縮小模型時的相似性

定義 sustained compute capacity C [ops/s]、各層可用頻寬 B_l [bytes/s]，以及 workload 在該層的 arithmetic intensity I_l [ops/byte]：

\[
\rho_l=\frac{C}{B_l I_l},\qquad l\in\{RF,SRAM,NoC,HB,HBM,NIC\}.
\]

這是無因次的供需比，使用同一 precision 與 operation 計數；rho 大於 1 表示該流量階層的供料低於此 compute capacity。它是檢查瓶頸的近似，不包含 dependency 或 conflict。

還要保留 working-set/buffer-capacity、bank concurrency、outstanding transactions、cross-tier round-trip/計算依賴間距，以及 hotspot 尺寸、熱擴散長度與時間尺度之比。只同比縮小 MAC 和 SRAM bit count 不保證上述相似性；小 tile 的局部結果不能直接線性外推全晶片 Tmax。

## 5. HB pitch 的手算與反例

令局部連接窗口 A 用 µm²、pitch p 用 µm，alpha 為扣掉 power/ground、clock/control/test、keepout 與 routing 限制後的 payload 配額：

\[
N_{payload}(p)\approx \left\lfloor\frac{\alpha A}{p^2}\right\rfloor,
\qquad B_{HB}\leq\min\left(\frac{N_{payload}f\eta}{8},B_{endpoint},B_{banks},B_{routing}\right).
\]

此處是一個 bond 承載一個並行 bit/cycle 的簡化介面；雙向連線要各自分配，serial signaling 必須換用對應 data rate。幾何容量不是可佈線保證。

**自訂數值例，不是廠商數據：** A = 0.04 mm² = 40,000 µm²、alpha = 0.4。8/4/2 µm 分別可容納約 250/1,000/4,000 個 payload sites。若要 1,024-bit 介面，所需 pitch 上界為 sqrt(16,000/1,024) = 3.953 µm；所以 4 µm 放不下而 2 µm 可放下。以 1 GHz、eta = 0.8，1,024-bit 理想有效頻寬為 102.4 GB/s。若只需 128 bits，8 µm 已放得下，縮到 2 µm 且保持同一介面不增加頻寬。

**熱反例：** 圓 pad 的 Cu 面積比為 phi = (pi/4)(d/p)^2。d/p = 0.5 時，不論 p 是 8/4/2 µm，phi 都是 pi/16 = 0.19635。在平行 Cu/oxide 均質模型下，單位面積垂直導熱係數 [W/(m² K)] 為：

\[
g=\frac{\phi k_{Cu}+(1-\phi)k_{oxide}}{t}.
\]

若材料、厚度與 d/p 固定，g 不因 pitch 改變。這不否定離散 pad spreading/界面熱阻的效應；該效應需要 unit-cell FEM 或量測校準。固定 d 而縮 p 會改變 Cu fill，應與固定 fill 的實驗分開；thermal-only pads 亦應列為對照。

實際溫度還受到功率 trace、功率密度與配置影響：低 swing/短線可能降功耗，增加利用率亦可能提高平均功耗。比較固定 useful throughput 的 power/temperature，以及固定 power/temperature limit 的 throughput，不能只用相同 target clock。

## 6. 代表性驗收設計與第一階段狀態

下列 R checks 與 Q01–Q09/M01–M06 分開。第一階段已將狀態寫入 `representation.json`：R01/R06 PARTIAL；R02/R03 僅對已支援整數 kernel 及模型對 RTL 一致性 PASS；R04/R05 NOT_CALIBRATED。未模擬的 bank conflict/NoC/precision 不在 R03 適用範圍，整體維持 EXPLORATORY，不把軟體 QC 成功擴張為產品代表性。

| ID | 完整代表性所需證據 | 失敗處理 |
|---|---|---|
| R01 architecture coverage | source/date/version → feature → module/adapter/parameter → tests；逐項列 omission | 缺關鍵 dataflow 或 unsupported precision 不得聲稱涵蓋該架構族 |
| R02 workload correctness | end-to-end kernel 結果、數值誤差契約、非法 mapping 拒絕 | 不將 stub/idle 或未完成工作計入能效 |
| R03 traffic / timing | cut bytes、cycles、stall、bank conflict 與 trace/cycle simulator 的獨立對照 | 頻寬或延遲偏差超過預先設定門檻則縮小適用範圍 |
| R04 PPA calibration | actual library/macro/corner/flow 的 module synthesis 與少量 APR；holdout 配置 | 禁止以同一批擬合資料冒充獨立驗證，保留 model error |
| R05 thermal calibration | unit-cell 與 stack 模型、材料/邊界、座標功率、穩態/暫態參照 | 沒有校準不能輸出產品絕對 Tmax 保證 |
| R06 decision robustness | 固定架構與每 pitch 重新最佳化、coarse/dense 對照、uncertainty sampling | 最佳點隨合理誤差反轉則回報範圍，不能宣稱唯一最佳 pitch |

誤差門檻要在校準前写入實驗 manifest，來源依研究需要而定。模型預期區分的 pitch 收益必須大於可辨識的誤差；例如僅相差 3% 而誤差約 ±10% 時，資料不足以排出可信優劣。

代表性日誌應保存 source snapshot/hash、architecture/workload/mapping、cut ID、precision、macro/library/RC versions、校準/holdout 樣本 ID、誤差、未涵蓋項與 R01–R06 狀態。第一階段另用 `execution_logs/mtia_history.jsonl` 與各 run 的 `representation.json`，保留原有 Q history 格式；尚無 macro/library/RC 及 holdout 資料，明確標示未校準。

## 7. 優先順序

第一步 **MTIA-like 可執行 PE tile + scratch banks + ME/NMC 簡化硬體模型** 已完成，包含 GEMM、embedding/vector 子集、並行 compute/collective 與局部供料/HBM/NIC 瓶頸對照；驗收證據見 [交付紀錄](execution_logs/2026-09-09_mtia_release/HANDOFF.md)。下一步先補這個子系統的 module/physical 校準；架構擴充順序仍是 TPU-like systolic tile 及 SRAM-rich inference，再到 SIMT/tensor GPU 的 scheduling 與 memory semantics。每一步按列明的適用範圍驗收，再擴大 RTL 數量。

保留 MI300-like coarse partition 對照、每種架構的 2D baseline，以及至少一種細粒度 local-memory partition。先用 module-level calibrated costs + trace/dependency simulation 掃描，針對轉折點前/附近/後選少量配置做 APR/FEM。最終回答應是各架構與 workload 下可辨識的 pitch 收益及飽和範圍，而非一個脫離架構的「最佳 pitch」。
