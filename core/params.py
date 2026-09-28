"""寸法・色の設定値と、その妥当性チェック。CLI とデスクトップアプリで共通。"""

from dataclasses import asdict, dataclass, field, fields

LEVELS = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]
LAYER_NAMES = ["white", "L1", "L2", "L3", "L4"]

# GitHub の現行ライトテーマ（2026-09 時点、--contribution-default-bgColor-0..4）
GITHUB_COLORS = ["#EFF2F5", "#ACEEBB", "#4AC26B", "#2DA44E", "#116329"]

# 層の表示色の初期値 = フィラメント A 案のメーカー公表色
DEFAULT_COLORS = {
    "white": "#FFFFFF",  # Bambu PLA マット アイボリーホワイト
    "L1": "#C2E189",     # Bambu PLA マット アップルグリーン
    "L2": "#61C680",     # Bambu PLA マット グラスグリーン
    "L3": "#00AE42",     # Bambu PLA ベーシック Bambuグリーン
    "L4": "#22624F",     # Polymaker パンクロマ Matte エメラルドグリーン
}


def _f(default, label, group, unit="mm", lo=0.0, hi=100.0, step=0.1):
    return field(default=default, metadata=dict(label=label, group=group, unit=unit, min=lo, max=hi, step=step))


@dataclass
class Params:
    cell: float = _f(3.0, "マスの大きさ", "サイズ", lo=1.0, hi=10.0)
    gap: float = _f(1.0, "マスの間隔（壁厚）", "サイズ", lo=0.4, hi=5.0)
    cell_r: float = _f(0.5, "マスの角丸", "サイズ", lo=0.0, hi=2.0, step=0.05)
    margin: float = _f(2.25, "余白", "サイズ", lo=0.5, hi=10.0)
    corner_r: float = _f(3.0, "外形の角丸", "サイズ", lo=0.0, hi=10.0, step=0.5)
    layer_t: float = _f(0.8, "白・中間層の厚さ", "積層", lo=0.4, hi=5.0)
    bottom_t: float = _f(1.2, "最下層の厚さ", "積層", lo=0.6, hi=5.0)
    clearance: float = _f(0.2, "すき間（片側）", "積層", lo=0.0, hi=0.5, step=0.05)
    pin_protrude: float = _f(1.0, "突起の飛び出し（ベースプレートの上面から）", "積層", lo=0.0, hi=3.0)
    pin_extra_deep: float = _f(0.2, "L3・L4の突起の補正（たわみ・収縮対策）", "積層", lo=0.0, hi=1.0, step=0.05)
    keep_empty_layers: bool = field(default=False, metadata=dict(
        label="空の層も作る（2枚の厚さをそろえる）", group="積層", unit=""))
    hole_d: float = _f(4.5, "穴の直径", "キーリング", lo=2.0, hi=10.0, step=0.5)
    hole_wall: float = _f(2.0, "穴の周りの肉厚", "キーリング", lo=1.0, hi=5.0, step=0.5)
    show_months: bool = field(default=True, metadata=dict(
        label="月のラベル（ベースプレート上部をくり抜き）", group="刻印", unit=""))
    month_label_h: float = _f(2.5, "月ラベルの高さ", "刻印", lo=1.0, hi=6.0, step=0.1)
    month_label_pad: float = _f(1.125, "月ラベル上下の余白", "刻印", lo=0.2, hi=3.0, step=0.025)
    back_text: str = field(default="", metadata=dict(label="刻印の文字（空欄＝ユーザー名）", group="刻印", unit=""))
    text_h: float = _f(8.0, "文字の高さ", "刻印", lo=2.0, hi=20.0, step=0.5)
    text_depth: float = _f(0.6, "刻印の深さ", "刻印", lo=0.2, hi=3.0)
    mark_depth: float = _f(0.5, "識別スリット（各層の裏、本数でレベルを表す）の深さ。0で無効", "刻印", lo=0.0, hi=1.0, step=0.05)
    mark_h: float = _f(2.5, "識別スリットの高さ", "刻印", lo=1.0, hi=6.0, step=0.1)
    mark_pad: float = _f(0.375, "識別スリット上下の余白", "刻印", lo=0.2, hi=3.0, step=0.025)
    mark_slit_w: float = _f(1.0, "識別スリット1本の幅", "刻印", lo=0.4, hi=3.0, step=0.1)
    mark_slit_gap: float = _f(1.0, "識別スリットどうしの間隔", "刻印", lo=0.4, hi=3.0, step=0.1)
    colors: dict = field(default_factory=lambda: dict(DEFAULT_COLORS), metadata=dict(label="層の色", group="色", unit=""))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        known = {f.name for f in fields(cls)}
        p = cls(**{k: v for k, v in d.items() if k in known})
        p.colors = {**DEFAULT_COLORS, **(p.colors or {})}
        return p


def field_specs():
    """GUI 用: 設定項目の一覧（名前・ラベル・グループ・単位・範囲・初期値）"""
    out = []
    for f in fields(Params):
        if f.name == "colors":
            continue
        default = f.default
        kind = "bool" if isinstance(default, bool) else "str" if isinstance(default, str) else "float"
        out.append(dict(name=f.name, kind=kind, default=default, **f.metadata))
    return out


def errors(p: Params):
    """生成できない組み合わせ"""
    errs = []
    if p.text_depth >= p.bottom_t:
        errs.append("刻印の深さは最下層の厚さより小さくしてください")
    if p.mark_depth >= min(p.layer_t, p.bottom_t):
        errs.append("識別スリットの深さは層の厚さより小さくしてください")
    if 2 * p.clearance >= p.cell:
        errs.append("すき間が大きすぎて突起が作れません")
    return errs


def warnings(p: Params, infos=()):
    """生成はできるが注意が必要な点。infos は build_plate が返す info のリスト"""
    w = []
    if p.gap < 0.8:
        w.append(f"マスの間の壁が {p.gap:.2f}mm です。0.8mm（ノズル2本分）以上を推奨します")
    if p.layer_t < 1.2:
        w.append(f"白・中間層が {p.layer_t:.1f}mm です。1.2mm 未満だと下の層の色が透けるおそれがあります")
    if p.clearance < 0.1 or p.clearance > 0.3:
        w.append(f"すき間 {p.clearance:.2f}mm は、はめ込みがきつすぎる／ゆるすぎるおそれがあります（0.1〜0.3mm 推奨）")
    for info in infos:
        th = info.get("text_h_actual")
        if th is not None and th < 3.0:
            w.append(f"{info['name']}: 刻印の文字が {th:.1f}mm に縮小されました。3mm 未満は潰れやすくなります")
    return w
