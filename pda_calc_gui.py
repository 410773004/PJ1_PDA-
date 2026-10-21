"""
LJ2-FG248040 PDA 換算工具 - GUI 版

換算公式跟 tools/pda_calc_lj2_fg248040.py（CLI 版）完全一樣，都是照抄
fw_src/PJ_FW/LJ2-FG248040/src/ncl_20/nand.c 的 nand_info_init() / pda_assemble_xlc() /
pda2ch() / pda2ce() / pda2lun() / pda2die() / pda2plane() / pda2page()。
這裡把邏輯直接內嵌（不用跨檔 import），是因為 PyInstaller --onefile 打包時
曾經漏掉同資料夾的 pda_calc_lj2_fg248040.py 模組，導致 exe 執行時
ModuleNotFoundError；內嵌成單一檔案可以徹底避開這個打包踩坑。
打包成 exe 用：
    .venv/Scripts/python -m PyInstaller --onefile --windowed --name PDA_Calc_LJ2 tools/pda_calc_gui.py
"""

import dataclasses
import tkinter as tk
from tkinter import ttk


def ctz(x: int) -> int:
    """count trailing zeros，對應 nand.c 用的 ctz()：算 shift 量要用"""
    if x <= 0:
        raise ValueError(f"ctz() 只吃正整數，收到 {x}")
    n = 0
    while (x & 1) == 0:
        x >>= 1
        n += 1
    return n


def next_pow2(x: int) -> int:
    """對應 nand.c 的 get_next_power_of_two()：欄位寬度是用「不小於 x 的最小 2 的次方」去推"""
    p = 1
    while p < x:
        p <<= 1
    return p


@dataclasses.dataclass
class NandGeometry:
    channels: int = 8   # CH
    ce: int = 1          # nr_targets (CE)
    lun: int = 1          # nr_luns
    planes: int = 4          # nr_planes
    pages: int = 1344       # nr_pages / block
    blocks: int = 831        # nr_blocks / lun


@dataclasses.dataclass
class PdaLayout:
    """對應 nand_info 裡跟 PDA 有關的 shift / mask，算法照抄 nand_info_init()"""
    du_shift: int
    plane_shift: int
    ch_shift: int
    ce_shift: int
    lun_shift: int
    page_shift: int
    block_shift: int
    page_mask: int
    block_mask: int
    lun_num_mask: int  # pda2die() 用的 (lun_num - 1)


def build_layout(geo: NandGeometry) -> PdaLayout:
    du_shift = 0
    # DU_CNT_PER_PAGE 固定是 4 (NAND_PAGE_SIZE 16KB / NAND_DU_SIZE 4KB)，見 eccu.h
    interleave_shift = ctz(4)
    plane_shift = interleave_shift
    ch_shift = plane_shift + ctz(geo.planes)
    ce_shift = ch_shift + ctz(geo.channels)
    lun_shift = ce_shift + ctz(geo.ce)

    lun_num = geo.channels * geo.ce * geo.lun
    interleave = lun_num * geo.planes
    page_shift = interleave_shift + ctz(interleave)

    page_width = ctz(next_pow2(geo.pages))
    page_mask = (1 << page_width) - 1
    block_shift = page_shift + page_width

    block_width = ctz(next_pow2(geo.blocks))
    block_mask = (1 << block_width) - 1

    return PdaLayout(
        du_shift=du_shift,
        plane_shift=plane_shift,
        ch_shift=ch_shift,
        ce_shift=ce_shift,
        lun_shift=lun_shift,
        page_shift=page_shift,
        block_shift=block_shift,
        page_mask=page_mask,
        block_mask=block_mask,
        lun_num_mask=lun_num - 1,
    )


def page_type(page: int) -> str:
    """XLC (TLC) page type，照抄 nand_tsb.c 的 get_xlc_page_type()：page % 3"""
    return ("Lower", "Middle", "Upper")[page % 3]


def die_to_chcelun(geo: NandGeometry, die: int) -> tuple:
    """die 編號拆回 (ch, ce, lun)：die 的排列是 ch 在低位、接著 ce、最後 lun，
    跟 PDA 裡 ch_shift < ce_shift < lun_shift 的順序一致 (pda2die 就是從 ch_shift 開始取)"""
    lun_num = geo.channels * geo.ce * geo.lun
    if not 0 <= die < lun_num:
        raise ValueError(f"die={die} 超出範圍 (0~{lun_num - 1})")
    ch_bits = ctz(geo.channels)
    ce_bits = ctz(geo.ce)
    ch = die & (geo.channels - 1)
    ce = (die >> ch_bits) & (geo.ce - 1)
    lun = die >> (ch_bits + ce_bits)
    return ch, ce, lun


def chcelun_to_die(geo: NandGeometry, ch: int, ce: int, lun: int) -> int:
    """(ch, ce, lun) 合併成 die 編號，是 die_to_chcelun 的反向"""
    ch_bits = ctz(geo.channels)
    ce_bits = ctz(geo.ce)
    return ch | (ce << ch_bits) | (lun << (ch_bits + ce_bits))


def check_fields(geo: NandGeometry, ch: int, ce: int, lun: int, plane: int, block: int, page: int, du: int) -> None:
    """欄位超出 geometry 時直接報錯，避免超界的值被 OR 進相鄰欄位而算出看似正常的錯誤 PDA"""
    limits = (
        ("ch", ch, geo.channels), ("ce", ce, geo.ce), ("lun", lun, geo.lun),
        ("plane", plane, geo.planes), ("block", block, geo.blocks),
        ("page", page, geo.pages), ("du", du, 4),
    )
    for name, val, upper in limits:
        if not 0 <= val < upper:
            raise ValueError(f"{name}={val} 超出範圍 (0~{upper - 1})")


def encode_pda(geo: NandGeometry, ch: int, ce: int, lun: int, plane: int, block: int, page: int, du: int = 0) -> int:
    """對應 pda_assemble_xlc()：把各欄位組回 32-bit PDA"""
    check_fields(geo, ch, ce, lun, plane, block, page, du)
    layout = build_layout(geo)
    return (
        (lun << layout.lun_shift)
        | (ce << layout.ce_shift)
        | (ch << layout.ch_shift)
        | (plane << layout.plane_shift)
        | (block << layout.block_shift)
        | (page << layout.page_shift)
        | (du << layout.du_shift)
    )


def decode_pda(geo: NandGeometry, pda: int) -> dict:
    """對應 pda2ch()/pda2ce()/pda2lun()/pda2die()/pda2plane()/pda2page() 這幾個函式"""
    layout = build_layout(geo)
    ch = (pda >> layout.ch_shift) & (geo.channels - 1)
    ce = (pda >> layout.ce_shift) & (geo.ce - 1)
    lun = (pda >> layout.lun_shift) & (geo.lun - 1)
    die = (pda >> layout.ch_shift) & layout.lun_num_mask  # pda2die()：CH/CE/LUN 合併的 5-bit 組合值
    plane = (pda >> layout.plane_shift) & (geo.planes - 1)
    block = (pda >> layout.block_shift) & layout.block_mask  # 這是 LB (PDA 裡的 block 欄位)，不是 PB
    page = (pda >> layout.page_shift) & layout.page_mask
    du = (pda >> layout.du_shift) & 3
    physical_block = block * geo.planes + plane  # PB = LB * planes + plane，跟 encode 端的雙向換算公式一致

    # 欄位值超出 geometry 代表這個 PDA 不屬於這個 geometry (或 PDA 本身有誤)，附上 warning 提醒
    warnings = []
    if page >= geo.pages:
        warnings.append(f"page {page} >= {geo.pages}")
    if block >= geo.blocks:
        warnings.append(f"block {block} >= {geo.blocks}")
    if pda >> (layout.block_shift + ctz(next_pow2(geo.blocks))):
        warnings.append("PDA 高位元有多餘的值")
    result = {
        "pda": f"0x{pda:08x}",
        "ch": ch,
        "ce": ce,
        "lun": lun,
        "die": die,
        "plane": plane,
        "block(LB)": block,
        "physical_block": physical_block,
        "page": page,
        "page_type": page_type(page),
        "du": du,
    }
    if warnings:
        result["warning"] = "; ".join(warnings) + " (geometry 可能不符)"
    return result


DEFAULT_GEO = NandGeometry()  # 8CH*1CE*1LUN*4PL, 831blocks*1344pages


class PdaCalcApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=12)
        self.pack(fill="both", expand=True)
        self._build_geo_section()
        self._build_decode_section()
        self._build_encode_section()
        # 初始化 PB 與 Die 欄位 (它們是由其他欄位推出來的)
        self._on_lb_plane_changed()
        self._on_chcelun_changed()
        self._do_decode()
        self._do_encode()

    # ── NAND geometry（預設 8CH*1CE*1LUN*4PL，換機種可以自己改）──────────────
    def _build_geo_section(self):
        box = ttk.LabelFrame(self, text="NAND geometry（預設值：8CH*1CE*1LUN*4PL, 831blocks*1344pages，換機種請自行修改）")
        box.pack(fill="x", pady=(0, 8))

        self.geo_vars = {
            "channels": tk.StringVar(value=str(DEFAULT_GEO.channels)),
            "ce": tk.StringVar(value=str(DEFAULT_GEO.ce)),
            "lun": tk.StringVar(value=str(DEFAULT_GEO.lun)),
            "planes": tk.StringVar(value=str(DEFAULT_GEO.planes)),
            "pages": tk.StringVar(value=str(DEFAULT_GEO.pages)),
            "blocks": tk.StringVar(value=str(DEFAULT_GEO.blocks)),
        }
        labels = {
            "channels": "CH", "ce": "CE", "lun": "LUN",
            "planes": "Plane", "pages": "Pages/blk", "blocks": "Blocks",
        }
        for i, key in enumerate(["channels", "ce", "lun", "planes", "pages", "blocks"]):
            ttk.Label(box, text=labels[key]).grid(row=0, column=i * 2, padx=(4, 2), pady=4, sticky="e")
            ttk.Entry(box, width=6, textvariable=self.geo_vars[key]).grid(row=0, column=i * 2 + 1, padx=(0, 4), pady=4)

        # geometry 改了會影響 decode/encode 的 shift 換算，所以也要跟著即時重算。
        # decode/encode 區塊此時還沒建立，但 trace 只有在使用者真的改值時才會觸發，
        # 屆時 self._do_decode / self._do_encode 用到的元件早就都存在了。
        # PB 與 Die 的換算也跟 geometry 有關 (PB = LB*planes + plane；die 的位元寬度取決於 CH/CE 數)，
        # 所以 geometry 改了也要重算這兩個欄位。
        for var in self.geo_vars.values():
            var.trace_add("write", lambda *_a: (self._on_lb_plane_changed(), self._on_chcelun_changed(),
                                                 self._do_decode(), self._do_encode()))

    def _current_geo(self) -> NandGeometry:
        try:
            return NandGeometry(**{k: int(v.get(), 0) for k, v in self.geo_vars.items()})
        except ValueError:
            raise ValueError("geometry 欄位要填數字")

    # ── decode：PDA -> 各欄位 ───────────────────────────────────────────
    def _build_decode_section(self):
        box = ttk.LabelFrame(self, text="Decode：PDA → 各欄位")
        box.pack(fill="x", pady=(0, 8))

        row = ttk.Frame(box)
        row.pack(fill="x", padx=4, pady=4)
        ttk.Label(row, text="PDA (0x開頭)：").pack(side="left")
        self.decode_pda_var = tk.StringVar(value="0x02dc018c")
        entry = ttk.Entry(row, width=20, textvariable=self.decode_pda_var)
        entry.pack(side="left", padx=(2, 8))
        ttk.Button(row, text="複製結果", command=self._copy_decode_result).pack(side="left", padx=(8, 0))

        # 用唯讀 Text（而非 Label）顯示結果，因為 Label 的文字沒辦法用滑鼠選取複製；
        # Text 可以選取，同時搭配上面的「複製結果」按鈕直接複製整段內容到剪貼簿。
        self.decode_result_text = tk.Text(box, height=2, font=("Consolas", 10), wrap="word")
        self.decode_result_text.pack(fill="x", padx=8, pady=(0, 8))
        self.decode_result_text.configure(state="disabled")

        # 即時換算：PDA 輸入框或上方 geometry 欄位一有變動就自動重算，
        # 不用再按按鈕。打字打到一半（值還不合法）時直接跳過、不彈錯誤視窗。
        self.decode_pda_var.trace_add("write", lambda *_a: self._do_decode())

    def _copy_decode_result(self):
        text = self.decode_result_text.get("1.0", "end-1c")
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _do_decode(self):
        try:
            geo = self._current_geo()
            pda = int(self.decode_pda_var.get().strip(), 0)
            fields = decode_pda(geo, pda)
        except ValueError:
            return
        text = "  ".join(f"{k}={v}" for k, v in fields.items() if k != "pda")
        result = f"{fields['pda']}\n{text}"
        self.decode_result_text.configure(state="normal")
        self.decode_result_text.delete("1.0", "end")
        self.decode_result_text.insert("1.0", result)
        self.decode_result_text.configure(state="disabled")

    # ── encode：各欄位 -> PDA ───────────────────────────────────────────
    def _build_encode_section(self):
        box = ttk.LabelFrame(self, text="Encode：各欄位 → PDA")
        box.pack(fill="x")

        self.encode_vars = {
            "die": tk.StringVar(value="0"),
            "ch": tk.StringVar(value="0"),
            "ce": tk.StringVar(value="0"),
            "lun": tk.StringVar(value="0"),
            "plane": tk.StringVar(value="3"),
            "block": tk.StringVar(value="183"),
            "pb": tk.StringVar(value="735"),
            "page": tk.StringVar(value="3"),
            "du": tk.StringVar(value="0"),
        }
        labels = {
            "die": "Die", "ch": "CH", "ce": "CE", "lun": "LUN", "plane": "Plane",
            "block": "Block(LB)", "pb": "PB", "page": "Page", "du": "DU",
        }
        row = ttk.Frame(box)
        row.pack(fill="x", padx=4, pady=4)
        for i, key in enumerate(["die", "ch", "ce", "lun", "plane", "block", "pb", "page", "du"]):
            ttk.Label(row, text=labels[key]).grid(row=0, column=i * 2, padx=(4, 2), sticky="e")
            if key == "pb":
                # PB 常常需要一格一格微調著找對應的 LB/Plane，用 Spinbox 給上下箭頭比手動打字方便。
                # to 給一個夠大的上限（實際換算不會受它限制，超界只是箭頭按不上去而已）。
                e = ttk.Spinbox(row, width=6, from_=0, to=999999, textvariable=self.encode_vars[key])
            else:
                e = ttk.Entry(row, width=6, textvariable=self.encode_vars[key])
            e.grid(row=0, column=i * 2 + 1, padx=(0, 4))

        btn_row = ttk.Frame(box)
        btn_row.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(btn_row, text="複製結果", command=self._copy_encode_result).pack(side="left")

        # 跟 decode 結果一樣，改用唯讀 Entry 取代 Label，讓結果可以被選取/複製。
        self.encode_result = tk.StringVar(value="")
        result_entry = ttk.Entry(box, textvariable=self.encode_result, font=("Consolas", 11, "bold"), state="readonly")
        result_entry.pack(fill="x", padx=8, pady=(0, 8))
        self.encode_result_entry = result_entry

        # LB/Plane 跟 PB 是同一個東西的兩種表示法（PB = LB*planes + plane），
        # 用 trace 做雙向連動：改 LB 或 Plane 就自動算出 PB，改 PB 就自動反推 LB/Plane。
        # 用 _encode_sync_lock 擋住 set() 觸發的 trace，避免互相觸發變成無窮迴圈。
        self._encode_sync_lock = False
        self.encode_vars["block"].trace_add("write", self._on_lb_plane_changed)
        self.encode_vars["plane"].trace_add("write", self._on_lb_plane_changed)
        self.encode_vars["pb"].trace_add("write", self._on_pb_changed)

        # Die 跟 CH/CE/LUN 也是同一件事的兩種表示法 (die = ch | ce<<.. | lun<<..)，同樣雙向連動、共用同一把鎖。
        for key in ("ch", "ce", "lun"):
            self.encode_vars[key].trace_add("write", self._on_chcelun_changed)
        self.encode_vars["die"].trace_add("write", self._on_die_changed)

        # 即時換算：任何欄位一改就自動重算 PDA，不用再按按鈕。
        for key, var in self.encode_vars.items():
            var.trace_add("write", lambda *_a: self._do_encode())

    def _copy_encode_result(self):
        text = self.encode_result.get()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _on_lb_plane_changed(self, *_args):
        if self._encode_sync_lock:
            return
        try:
            geo = self._current_geo()
            block = int(self.encode_vars["block"].get(), 0)
            plane = int(self.encode_vars["plane"].get(), 0)
            pb = block * geo.planes + plane
        except (ValueError, ZeroDivisionError):
            return
        self._encode_sync_lock = True
        try:
            self.encode_vars["pb"].set(str(pb))
        finally:
            self._encode_sync_lock = False

    def _on_pb_changed(self, *_args):
        if self._encode_sync_lock:
            return
        try:
            geo = self._current_geo()
            pb = int(self.encode_vars["pb"].get(), 0)
            block, plane = divmod(pb, geo.planes)
        except (ValueError, ZeroDivisionError):
            return
        self._encode_sync_lock = True
        try:
            self.encode_vars["block"].set(str(block))
            self.encode_vars["plane"].set(str(plane))
        finally:
            self._encode_sync_lock = False

    def _on_chcelun_changed(self, *_args):
        if self._encode_sync_lock:
            return
        try:
            geo = self._current_geo()
            ch, ce, lun = (int(self.encode_vars[k].get(), 0) for k in ("ch", "ce", "lun"))
            # 超界的 ch/ce/lun 不能拿來合成 die，否則位元會互相蓋到
            if not (0 <= ch < geo.channels and 0 <= ce < geo.ce and 0 <= lun < geo.lun):
                return
            die = chcelun_to_die(geo, ch, ce, lun)
        except ValueError:
            return
        self._encode_sync_lock = True
        try:
            self.encode_vars["die"].set(str(die))
        finally:
            self._encode_sync_lock = False

    def _on_die_changed(self, *_args):
        if self._encode_sync_lock:
            return
        try:
            geo = self._current_geo()
            ch, ce, lun = die_to_chcelun(geo, int(self.encode_vars["die"].get(), 0))
        except ValueError:
            return
        self._encode_sync_lock = True
        try:
            self.encode_vars["ch"].set(str(ch))
            self.encode_vars["ce"].set(str(ce))
            self.encode_vars["lun"].set(str(lun))
        finally:
            self._encode_sync_lock = False

    def _do_encode(self):
        try:
            geo = self._current_geo()
            v = {k: int(var.get(), 0) for k, var in self.encode_vars.items() if k not in ("pb", "die")}
            pda = encode_pda(geo, v["ch"], v["ce"], v["lun"], v["plane"], v["block"], v["page"], v["du"])
        except ValueError as e:
            # 欄位超界要讓使用者看得到原因，不能只是靜默不更新 (否則會誤以為還是舊結果)
            self.encode_result_entry.configure(state="normal")
            self.encode_result.set(f"錯誤：{e}")
            self.encode_result_entry.configure(state="readonly")
            return
        self.encode_result.set(f"PDA = 0x{pda:08x}")


def main():
    root = tk.Tk()
    root.title("LJ2-FG248040 PDA 換算工具")
    root.resizable(False, False)
    PdaCalcApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
