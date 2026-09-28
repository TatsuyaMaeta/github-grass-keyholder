"""積層タグの形状生成。

1 枚は単色パーツを重ねてはめ込む積層構造（上から 白 → L1 → L2 → L3 → L4）:
  白     全マス（L0 以外）がくり抜き
  Ln     Ln のマスが突起（上の層を貫通して白の上面から飛び出す）、Ln+1 以降のマスはくり抜き
  最下層 裏面に刻印
L0（草のない日）は白のまま。マスが 1 つもないレベルの層は、keep_empty_layers でなければ作らない。
"""

import math
from dataclasses import dataclass

import numpy as np
from manifold3d import CrossSection, FillRule, JoinType, Manifold

from .params import LEVELS, Params

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class Plate:
    name: str
    layers: dict  # {層名: Manifold}（上から順、組み立て位置。最下面が z=0）
    info: dict
    period: tuple = ("", "")  # (最初の日, 最後の日)


def rounded_rect(w, h, r, segs=48):
    return (CrossSection.square((w - 2 * r, h - 2 * r)).translate((r, r))
            .offset(r, JoinType.Round, circular_segments=segs))


def text_section(text, height):
    """文字列をアウトライン化し、高さ height(mm) に揃えた CrossSection を返す"""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath

    path = TextPath((0, 0), text, size=10, prop=FontProperties(family="DejaVu Sans", weight="bold"))
    polys = [np.asarray(p, dtype=float) for p in path.to_polygons() if len(p) >= 3]
    cs = CrossSection(polys, FillRule.EvenOdd)
    (x0, y0), (x1, y1) = np.array(cs.bounds()[:2]), np.array(cs.bounds()[2:])
    return cs.translate((-x0, -y0)).scale((height / (y1 - y0),) * 2)


def month_label_cols(half):
    """半年分のweeksから、新しい月が始まる列 → 月の略称(英語3文字)"""
    seen, labels = set(), {}
    for col, week in enumerate(half):
        months_this_week = sorted({d["date"][:7] for d in week["contributionDays"]})
        new_months = [m for m in months_this_week if m not in seen]
        seen.update(months_this_week)
        if new_months:
            labels[col] = MONTH_ABBR[int(new_months[0].split("-")[1]) - 1]
    return labels


def text_section_filled(text, height):
    """文字列をアウトライン化し、文字の内側の穴（e・o・aなど）も塗りつぶして返す。
    くり抜き（貫通穴）にすると内側の穴の部分が孤立して抜け落ちるため、月ラベルの貫通穴に使う"""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath

    path = TextPath((0, 0), text, size=10, prop=FontProperties(family="DejaVu Sans", weight="bold"))
    polys = []
    for poly in path.to_polygons():
        if len(poly) < 3:
            continue
        area = np.sum(poly[:, 0] * np.roll(poly[:, 1], -1) - np.roll(poly[:, 0], -1) * poly[:, 1])
        polys.append(poly if area > 0 else poly[::-1])  # 向きを揃えて内側の穴も塗りつぶす
    cs = CrossSection(polys, FillRule.Positive)
    (x0, y0), (x1, y1) = np.array(cs.bounds()[:2]), np.array(cs.bounds()[2:])
    return cs.translate((-x0, -y0)).scale((height / (y1 - y0),) * 2)


def weeks_to_cells(weeks):
    """週データ → [(列, 行, レベル)]。行 0 が最下段（土曜）、6 が最上段（日曜）"""
    return [(col, 6 - d["weekday"], LEVELS.index(d["contributionLevel"]))
            for col, week in enumerate(weeks) for d in week["contributionDays"]]


def build_plate(cells, cols, rows, p: Params, back_text="", with_ring=True, name="", month_labels=None):
    """1 枚分の層を作る。グリッド左下が原点"""
    cell, c = p.cell, p.clearance
    pitch = cell + p.gap
    grid_w = cols * pitch - p.gap
    grid_h = rows * pitch - p.gap

    # 外形: 左側にキーリング用のタブ。月のラベル（上）・組み立て順マーク（下）を入れる帯だけ、
    # ラベル／マークが収まる幅を確保する
    tab = p.hole_d + 2 * p.hole_wall if with_ring else 0.0
    top_margin = p.month_label_h + 2 * p.month_label_pad if p.show_months and month_labels else p.margin
    bottom_margin = p.mark_h + 2 * p.mark_pad if p.mark_depth > 0 else p.margin
    x0 = -p.margin - tab
    plate_w = tab + grid_w + 2 * p.margin
    plate_h = grid_h + bottom_margin + top_margin
    corner = min(p.corner_r, plate_w / 2 - 0.01, plate_h / 2 - 0.01)
    plate = rounded_rect(plate_w, plate_h, corner).translate((x0, -bottom_margin))
    if with_ring:
        plate -= CrossSection.circle(p.hole_d / 2, 64).translate((x0 + p.hole_wall + p.hole_d / 2, grid_h / 2))

    # マスの位置をレベルごとに集める。穴はマスそのもの、突起は片側 clearance だけ小さくする
    r = min(p.cell_r, cell / 2 - 0.01)
    hole_polys = rounded_rect(cell, cell, r, 16).to_polygons()
    pin_polys = rounded_rect(cell - 2 * c, cell - 2 * c, max(r - c, 0.01), 16).translate((c, c)).to_polygons()
    holes = {lv: [] for lv in range(1, 5)}
    pins = {lv: [] for lv in range(1, 5)}
    for col, row, lv in cells:
        if lv == 0:
            continue
        o = (col * pitch, row * pitch)
        holes[lv].extend(q + o for q in hole_polys)
        pins[lv].extend(q + o for q in pin_polys)

    # 層の並び（上から）と厚さ。最下層だけ刻印分厚くする
    levels = [lv for lv in range(1, 5) if pins[lv] or p.keep_empty_layers]
    names = ["white"] + [f"L{lv}" for lv in levels]
    thick = [p.layer_t] * (len(names) - 1) + [p.bottom_t]
    z0 = {}
    z = 0.0
    for lname, t in reversed(list(zip(names, thick))):
        z0[lname] = z
        z += t
    top = z  # 白（ベースプレート）の上面

    def pin_top_for(lv):
        # L3・L4 は根元が長くたわみ・収縮しやすいので、飛び出し量を少し多めにとる
        return top + p.pin_protrude + (p.pin_extra_deep if lv >= 3 else 0.0)

    layers = {}
    for i, lname in enumerate(names):
        body = plate
        for lv in levels[i:]:  # この層より下の層が持つ突起 → この層では穴
            if holes[lv]:
                body -= CrossSection(holes[lv])
        solid = body.extrude(thick[i]).translate((0, 0, z0[lname]))
        if lname != "white" and pins[int(lname[1:])]:
            lv = int(lname[1:])
            layer_top = z0[lname] + thick[i]
            solid += CrossSection(pins[lv]).extrude(pin_top_for(lv) - layer_top).translate((0, 0, layer_top))
        layers[lname] = solid

    # 各層の裏に組み立て順のマーク（例: 2番目に重ねる L1 なら "2L1"）を刻印。5層あると組み立て順がわからなくなるため
    if p.mark_depth > 0:
        for i, lname in enumerate(names):
            label = f"{i + 1}{'W' if lname == 'white' else lname}"
            mk = text_section(label, p.mark_h)  # 原点合わせ済み: (0,0)〜(幅, mark_h)
            mk_w = mk.bounds()[2]
            mk = mk.translate((0, -bottom_margin + p.mark_pad))  # マージン帯の中で上下均等に余白を取る
            mk = mk.mirror((1, 0)).translate((2.0 + mk_w, 0))  # 裏から見て読めるよう左右反転
            layers[lname] -= mk.extrude(p.mark_depth + 0.01).translate((0, 0, z0[lname] - 0.01))

    # 月が変わる列の上に月名をくり抜く（白の天板のみ、上の余白帯）
    if p.show_months and month_labels:
        white_thick = thick[names.index("white")]
        for col, label in month_labels.items():
            if col >= cols:
                continue
            lb = text_section_filled(label, p.month_label_h)
            lb = lb.translate((col * pitch, grid_h + p.month_label_pad))
            layers["white"] -= lb.extrude(white_thick + 0.02).translate((0, 0, z0["white"] - 0.01))

    # 最下層の裏面に刻印（裏から見て読めるよう左右反転）
    text_h_actual = None
    if back_text:
        txt = text_section(back_text, p.text_h)
        (tx0, _), (tx1, ty1) = txt.bounds()[:2], txt.bounds()[2:]
        if tx1 - tx0 > grid_w:  # 長い文字列は幅に合わせて縮小
            txt = txt.scale((grid_w / (tx1 - tx0),) * 2)
            (tx0, _), (tx1, ty1) = txt.bounds()[:2], txt.bounds()[2:]
        if ty1 > grid_h:
            txt = txt.scale((grid_h / ty1,) * 2)
            (tx0, _), (tx1, ty1) = txt.bounds()[:2], txt.bounds()[2:]
        text_h_actual = ty1
        txt = txt.translate(((grid_w - tx1) / 2, (grid_h - ty1) / 2)).mirror((1, 0)).translate((grid_w, 0))
        layers[names[-1]] -= txt.extrude(p.text_depth + 0.01).translate((0, 0, -0.01))

    # プレビュー用: 草が最も多い行の中心 Y と、その行で草のある X 範囲
    by_row = {}
    for col, row, lv in cells:
        if lv:
            by_row.setdefault(row, []).append(col * pitch)
    srow = max(by_row, key=lambda k: len(by_row[k])) if by_row else rows // 2
    xs = by_row.get(srow, [0.0])
    total = max((pin_top_for(lv) for lv in levels), default=top)
    info = dict(name=name, pitch=pitch, plate_w=plate_w, plate_h=plate_h, thickness=top, total=total, z0=z0,
                t=dict(zip(names, thick)), text_h_actual=text_h_actual,
                section_y=srow * pitch + cell / 2, section_x=(min(xs), max(xs) + cell),
                counts={f"L{lv}": len(pins[lv]) // max(len(pin_polys), 1) for lv in range(1, 5)})
    return layers, info


def split_halves(weeks):
    cols = math.ceil(len(weeks) / 2)
    return [weeks[:cols], weeks[cols:]], cols


def build_keychain(weeks, p: Params, user=""):
    """直近 1 年分を半年ずつ 2 枚にする"""
    halves, cols = split_halves(weeks)
    plates = []
    for i, half in enumerate(halves, 1):
        name = f"plate{i}"
        days = [d["date"] for w in half for d in w["contributionDays"]]
        layers, info = build_plate(weeks_to_cells(half), cols, 7, p, back_text=p.back_text or user, name=name,
                                   month_labels=month_label_cols(half))
        plates.append(Plate(name, layers, info, (days[0], days[-1]) if days else ("", "")))
    return plates


def build_test_coupons(p: Params, clearances=(0.1, 0.15, 0.2), size=3):
    """はめ込み確認用の小片: size×size マスの白＋L1 の 2 層。裏面にすき間の値を刻印"""
    cells = [(col, row, 1) for col in range(size) for row in range(size)]
    plates = []
    for c in clearances:
        q = Params.from_dict({**p.to_dict(), "clearance": c, "keep_empty_layers": False})
        name = f"fit_{c:.2f}".replace(".", "_")
        layers, info = build_plate(cells, size, size, q, back_text=f"{c:.2f}", with_ring=False, name=name)
        plates.append(Plate(name, layers, info))
    return plates
