"""
LJ2-FG248040 PDA (Physical Device Address) 換算工具

換算公式是直接照抄 fw_src/PJ_FW/LJ2-FG248040/src/ncl_20/nand.c 裡
nand_info_init() 算出來的各欄位 shift/mask，以及 pda_assemble_xlc() /
pda2ch() / pda2ce() / pda2lun() / pda2die() / pda2plane() / pda2page() 這些函式的邏輯，
不是自己猜的公式。已經用實際 case (SN0026071W02WD, overview_with_page_type.png)
的 13 筆 ECC table 資料逐行核對過，LB / Die / Page / DU / Plane / PageType
和 PDA 都能對得上（例如 PDA=0x1b10063c <-> LB=433,Die=3,Page=3,DU=0,Plane=3）。

預設的 NAND geometry 是從這台機種的 log 讀出來的：
    CPU2: nand_info_init() - 831blocks*1344pages,
    CPU2: nand_info_init() - 8CH*2CE*2LUN*4PL,
若換一顆機種 geometry 不同，用 --channels/--ce/--lun/--planes/--pages/--blocks 覆蓋即可。

注意：
- "Die" = CH/CE/LUN 三個欄位合併後的 5-bit 組合值 (pda2die)，不是單一硬體編號。
- "PB" (Physical Block，overview 表格裡的欄位) 不在這個換算範圍內：
  它是 LB (PDA 裡的 block 欄位) 經過 defect table 對應到實體壞塊表之後的號碼，
  必須配合當顆 SSD 的 bad block table 才能算，光靠 PDA 公式換算不出來。
- ErrLDA 是 LBA (邏輯位址)，跟 PDA (實體位址) 是兩條不同的換算路徑，這支工具不處理。

用法範例：
    # decode: 從 PDA 反推各欄位
    python pda_calc_lj2_fg248040.py decode 0x1b10063c

    # encode: 從各欄位組出 PDA
    python pda_calc_lj2_fg248040.py encode --ch 3 --ce 0 --lun 0 --plane 3 --block 433 --page 3 --du 0
"""

import argparse
import dataclasses


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
    ce: int = 2          # nr_targets (CE)
    lun: int = 2          # nr_luns
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


def encode_pda(geo: NandGeometry, ch: int, ce: int, lun: int, plane: int, block: int, page: int, du: int = 0) -> int:
    """對應 pda_assemble_xlc()：把各欄位組回 32-bit PDA"""
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
    physical_block = block * geo.planes + plane  # PB = LB * planes + plane
    return {
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


def _build_geo_from_args(args) -> NandGeometry:
    return NandGeometry(
        channels=args.channels,
        ce=args.ce,
        lun=args.lun,
        planes=args.planes,
        pages=args.pages,
        blocks=args.blocks,
    )


def main():
    parser = argparse.ArgumentParser(description="LJ2-FG248040 PDA 換算工具")
    parser.add_argument("--channels", type=int, default=8)
    parser.add_argument("--ce", type=int, default=2)
    parser.add_argument("--lun", type=int, default=2)
    parser.add_argument("--planes", type=int, default=4)
    parser.add_argument("--pages", type=int, default=1344)
    parser.add_argument("--blocks", type=int, default=831)

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_decode = sub.add_parser("decode", help="從 PDA 反推各欄位")
    p_decode.add_argument("pda", help="PDA，可用 0x 開頭的十六進位或十進位")

    p_encode = sub.add_parser("encode", help="從各欄位組出 PDA")
    p_encode.add_argument("--ch", type=int, required=True)
    p_encode.add_argument("--ce", dest="ce_val", type=int, required=True)
    p_encode.add_argument("--lun", dest="lun_val", type=int, required=True)
    p_encode.add_argument("--plane", type=int, required=True)
    p_encode.add_argument("--block", type=int, required=True, help="LB，PDA 裡的 block 欄位")
    p_encode.add_argument("--page", type=int, required=True)
    p_encode.add_argument("--du", type=int, default=0)

    args = parser.parse_args()
    geo = _build_geo_from_args(args)

    if args.cmd == "decode":
        pda = int(args.pda, 0)
        for k, v in decode_pda(geo, pda).items():
            print(f"{k:12s}: {v}")
    elif args.cmd == "encode":
        pda = encode_pda(geo, args.ch, args.ce_val, args.lun_val, args.plane, args.block, args.page, args.du)
        print(f"PDA = 0x{pda:08x}")


if __name__ == "__main__":
    main()
