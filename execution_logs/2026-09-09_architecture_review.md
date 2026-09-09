# Architecture review evidence — 2026-09-09

本次變更為 `ARCHITECTURE_REPRESENTATIVENESS.md` 與 roadmap 研究設計，另製作五種架構、各兩種切割的互動概念圖。沒有增加可執行架構 adapter 或新 RTL；R01–R06 尚未實作／未驗收。

## 研究與圖面檢查

- 查閱 NVIDIA、Google、Meta、AMD 原廠文章／白皮書與 Hot Chips 官方議程；來源與 publication dates 保存在研究文件。
- 沒有取得 Hot Chips 2026 完整註冊投影片；議程確認與原廠公開技術資料分開陳述。
- 自訂手算的 Python 核對：8/4/2 µm 的 payload sites 為 250/1000/4000；1024-bit 需求的 pitch 上界 3.9528470752 µm；1 GHz、80% efficiency 的有效頻寬 102.4 GB/s；固定 d/p=0.5 的 Cu fill 均為 0.19634954085。
- 互動圖十組 architecture/cut 狀態正常更新；窄版 328 px 實際圖寬的 SVG 文字沒有超出圖面。淺／深色在 360 px 與桌面 736 px 圖寬附近目視檢查，瀏覽器沒有 error/warn。這是呈現檢查，不是科學代表性驗收。

## 既有框架回歸

Run ID：`20260909T120907Z-ff14123b5172`。

原始 run：[architecture_review_20260909](../runs/architecture_review_20260909/QC_REPORT.md)。

執行：

```sh
python3 quality_check.py run --design examples/modules.json --policy examples/optimization_ppa.json --out runs/architecture_review_20260909
python3 quality_check.py verify --run runs/architecture_review_20260909
```

兩個命令各自 exit 0。Q01/Q02/Q03/Q04/Q05/Q06/Q07/Q08/Q09 全部 PASS；獨立 verify 回傳 `VERIFIED PASS`。檢查包含既有 45 項 Python tests、23 組 RTL simulations、四個 top 的結構檢查與 generic synthesis。詳細 evidence 在原始 run，固定事件與摘要自動寫入該 run 的 `events.jsonl` 及 `execution_logs/history.jsonl`；未手改這些日誌。

輸入為 `examples/modules.json`、`examples/demo.json`、`examples/optimization_ppa.json`、`examples/costs_synthetic.json`。成本來源仍為 **synthetic**，不包含新查閱產品的量測數據。

目標：最小化 area/power/latency，權重 0.3/0.3/0.4，normalization scale 為 0.03 mm²/0.3 W/0.04 ms。限制：area ≤0.1 mm²、latency ≤0.04 ms、Tmax ≤85°C，每 tile SRAM/RF/FIFO 至少 1024/256/32 bytes；平手取較大 pitch。

候選：raw 18、unique 18、eligible 8、Pareto 3。

Selected point ID：`72226b2baaccf4a9eb49fb125abc936670159da7617b2a642e1cd094d091cdbc`。

本次既有示例 effective metrics：

| 指標 | 數值 |
|---|---:|
| summed module area | 0.03174112 mm² |
| average power | 0.242204945 W |
| model workload latency | 0.031262 ms |
| energy | 0.007571811 mJ |
| model steady Tmax | 40.069317°C |
| selected pitch | 8 µm |
| timing WNS | null（沒有 STA） |

這些數字僅證明原範例仍可重現，不能當成 MTIA/Rubin/TPU/MI300 的 PPA，亦不能證明 8 µm 是產品最佳 pitch。本次沒有架構代表性 PASS、physical timing closure 或 thermal signoff。
