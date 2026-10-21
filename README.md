# PDA_Calc_LJ2

LJ2 韌體的 PDA（Physical Device Address）換算工具：PDA ↔ CH / CE / LUN / Die / Plane / Block / Page / DU。
換算邏輯照抄韌體 `ncl_20/nand.c` 的 `nand_info_init()` 與 `pda2xxx()` 系列函式。

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `pda_calc_gui.py` | GUI 版（tkinter）。Decode / Encode 兩區即時換算，打包成 exe 的來源檔 |
| `pda_calc_lj2_fg248040.py` | CLI 版，`decode` / `encode` 兩個子指令，邏輯與 GUI 版相同 |
| `PDA_Calc_LJ2.exe` | 用 `build.bat` 打包好的 GUI 單檔執行檔，不用裝 Python 就能用 |
| `build.bat` | 打包腳本，從 `pda_calc_gui.py` 產生 `PDA_Calc_LJ2.exe` |
| `.gitignore` | 忽略 `build/`、`dist/`、`*.spec`、`__pycache__/` |

GUI 版把換算邏輯直接內嵌，沒有 import CLI 版。原因是 PyInstaller `--onefile` 曾漏打包同資料夾的模組，
導致 exe 執行時 `ModuleNotFoundError`。所以修改換算邏輯時，**兩支 `.py` 都要改**。

## 預設 geometry

預設為 `8CH × 1CE × 1LUN × 4PL`，`831 blocks × 1344 pages`。換機種時：

- GUI：直接改上方 geometry 欄位。
- CLI：加 `--channels / --ce / --lun / --planes / --pages / --blocks`，放在子指令前面。

PDA 欄位由低到高的排列為 `[DU][Plane][CH][CE][LUN][Page][Block]`，各欄位寬度由 geometry 推出。

## 用法

### GUI

執行 `PDA_Calc_LJ2.exe`（或 `python pda_calc_gui.py`）。

- **Decode**：輸入 PDA，即時顯示各欄位。欄位值超出 geometry 時會多一個 `warning`。
- **Encode**：填各欄位，即時算出 PDA。Die 與 CH/CE/LUN、PB 與 Block(LB)/Plane 彼此雙向連動；欄位超界時結果欄會顯示錯誤原因。

### CLI

```
# PDA -> 各欄位
python pda_calc_lj2_fg248040.py decode 0x02dc018c

# 各欄位 -> PDA
python pda_calc_lj2_fg248040.py encode --ch 0 --ce 0 --lun 0 --plane 3 --block 183 --page 3

# 用 die 代替 ch/ce/lun
python pda_calc_lj2_fg248040.py encode --die 0 --plane 3 --block 183 --page 3

# 其他 geometry（例如 8CH*2CE*2LUN）：選項放在 decode/encode 前面
python pda_calc_lj2_fg248040.py --ce 2 --lun 2 decode 0x1b10063c
```

## 名詞

- **Die**：CH、CE、LUN 合併後的編號（`pda2die`），由低到高為 `ch | ce<<.. | lun<<..`。8CH×1CE×1LUN 時 die 就等於 CH 號。
- **Block(LB)**：PDA 裡的 block 欄位。
- **PB**：`LB × planes + plane`。
- **Page type**：`page % 3`（Lower / Middle / Upper），對應 `get_xlc_page_type()`。

## 打包

需要 Python 與 PyInstaller（`pip install pyinstaller`）。

```
build.bat
```

等同於：

```
python -m PyInstaller --noconfirm --onefile --windowed --name PDA_Calc_LJ2 ^
    --distpath . --workpath build --specpath build pda_calc_gui.py
```

產出 `PDA_Calc_LJ2.exe` 在專案根目錄（會覆蓋舊檔），PyInstaller 的暫存檔與 spec 放在 `build/`。
打包前請先關閉正在執行的 `PDA_Calc_LJ2.exe`，否則檔案被佔用會覆蓋失敗。
