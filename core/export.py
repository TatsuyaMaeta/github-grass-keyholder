"""STL / 3MF / プレビュー画像 / 仕様テキストの書き出し。"""

import json
import math
import xml.sax.saxutils as xmlesc
import zipfile
from pathlib import Path

import numpy as np
from manifold3d import Manifold

from .params import LAYER_NAMES, Params


def mesh_arrays(m: Manifold):
    mesh = m.to_mesh()
    return np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts)


def write_stl(path, m):
    v, t = mesh_arrays(m)
    tri = v[t]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    rec = np.zeros(len(t), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, tri
    with open(path, "wb") as f:
        f.write(b"grass keychain".ljust(80, b"\0"))
        f.write(np.uint32(len(t)).tobytes())
        f.write(rec.tobytes())


def write_layer_stls(outdir, prefix, plate):
    """層ごとの STL（印刷向き: 各層の底面を z=0 に、突起は上向き）。n は上から重ねる順番"""
    paths = []
    for n, (name, m) in enumerate(plate.layers.items(), 1):
        path = Path(outdir) / f"{prefix}_{plate.name}_{n}_{name}.stl"
        write_stl(path, m.translate((0, 0, -plate.info["z0"][name])))
        paths.append(path)
    return paths


def write_3mf(path, plates, colors):
    """組み立て状態の確認用。1 プレート = 層ごとのパーツ（components）を持つ 1 オブジェクト"""
    res = ['<basematerials id="1">'] + [
        f'<base name="{n}" displaycolor="{colors[n]}FF"/>' for n in LAYER_NAMES] + ["</basematerials>"]
    build, oid, dy = [], 2, 0.0
    for plate in plates:
        comps = []
        for part, m in plate.layers.items():
            v, t = mesh_arrays(m)
            vs = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in v)
            ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in t)
            res.append(f'<object id="{oid}" type="model" name="{xmlesc.escape(f"{plate.name}_{part}")}" '
                       f'pid="1" pindex="{LAYER_NAMES.index(part)}"><mesh><vertices>{vs}</vertices>'
                       f'<triangles>{ts}</triangles></mesh></object>')
            comps.append(f'<component objectid="{oid}"/>')
            oid += 1
        res.append(f'<object id="{oid}" type="model" name="{plate.name}"><components>{"".join(comps)}</components></object>')
        build.append(f'<item objectid="{oid}" transform="1 0 0 0 1 0 0 0 1 0 {dy:.3f} 0"/>')
        dy += plate.info["plate_h"] + 5
        oid += 1
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources>{"".join(res)}</resources><build>{"".join(build)}</build></model>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                   '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
                   'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", model)


def write_preview(path, plate, colors):
    """組み立て後の表面・裏面・断面と、各層を上から見た図"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MplPath

    layers, info, pname = plate.layers, plate.info, plate.name

    def draw(ax, cs, color, flip=False):
        polys = [q * (-1, 1) if flip else q for q in cs.to_polygons()]
        if polys:  # 穴を抜くため複合パスとして描く
            cpath = MplPath.make_compound_path(*[MplPath(np.vstack([q, q[:1]]), closed=True) for q in polys])
            ax.add_patch(PathPatch(cpath, fc=color, ec="#777", lw=0.3))

    def finish(ax, title):
        ax.autoscale_view()
        ax.set_aspect("equal")
        ax.set_facecolor("#555")
        ax.set_title(title, fontname="Hiragino Sans", fontsize=9)
        ax.set_xticks([]), ax.set_yticks([])

    names = list(layers)
    nrows = 2 + math.ceil(len(names) / 2)
    fig, axes = plt.subplots(nrows, 2, figsize=(12, 1.9 * nrows),
                             gridspec_kw={"height_ratios": [3, 1.2] + [3] * (nrows - 2)})
    ax_top, ax_back = axes[0]

    # 表面: 下の層から順に、各層の上端を描く
    for name in reversed(names):
        m = layers[name]
        draw(ax_top, m.slice(m.bounding_box()[5] - 0.01), colors[name])
    finish(ax_top, f"{pname} 組み立て後の表面")
    draw(ax_back, layers[names[-1]].slice(0.005), colors[names[-1]], flip=True)
    finish(ax_back, f"{pname} 裏面（{names[-1]}）")

    # 断面: 草の多い行で切る（Y 軸まわりに倒して XZ 平面を見る）。草のある範囲を拡大表示
    ax_sec = axes[1][0]
    sy, (sx0, sx1) = info["section_y"], info["section_x"]
    for name in names:
        # X 軸まわりに +90° 回すと元の Y が Z に、元の Z が -Y になる
        draw(ax_sec, layers[name].rotate((90, 0, 0)).slice(sy).mirror((0, 1)), colors[name])
    finish(ax_sec, f"{pname} 断面（草の多い行、実寸比）")
    ax_sec.set_xlim(sx0 - 1, min(sx1, sx0 + 45) + 1)
    axes[1][1].axis("off")

    # 各層（印刷する面を上から見た図）
    for i, name in enumerate(names):
        ax = axes[2 + i // 2][i % 2]
        m = layers[name]
        draw(ax, m.slice(info["z0"][name] + info["t"][name] - 0.01), colors[name])
        pin_part = m.slice(m.bounding_box()[5] - 0.01)
        if name != "white":
            draw(ax, pin_part, colors[name])
            for q in pin_part.to_polygons():
                ax.plot(*np.vstack([q, q[:1]]).T, color="k", lw=0.4)
        finish(ax, f"{i + 1}. {name}" + ("（突起を黒線で表示）" if name != "white" else ""))
    for j in range(len(names), 2 * (nrows - 2)):
        axes[2 + j // 2][j % 2].axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_spec(path, plates, p: Params, user=""):
    lines = [f"GitHub草キーホルダー 生成時の設定（{user}）", ""]
    for plate in plates:
        i = plate.info
        lines.append(f"{plate.name}: {plate.period[0]} 〜 {plate.period[1]}  外形 {i['plate_w']:.1f} x {i['plate_h']:.1f} mm, "
                     f"厚さ {i['thickness']:.1f} mm（突起込み {i['total']:.1f} mm）, 層: {' → '.join(plate.layers)}")
    lines += ["", "設定値:", json.dumps(p.to_dict(), ensure_ascii=False, indent=2)]
    Path(path).write_text("\n".join(lines) + "\n")


def export_keychain(plates, outdir, prefix, p: Params, weeks=None, preview=True):
    """一式を書き出して、書いたファイルのパスを返す"""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    if weeks is not None:
        path = outdir / f"{prefix}_contributions.json"
        path.write_text(json.dumps(weeks, indent=1))
        paths.append(path)
    for plate in plates:
        paths += write_layer_stls(outdir, prefix, plate)
        if preview:
            path = outdir / f"{prefix}_{plate.name}_preview.png"
            write_preview(path, plate, p.colors)
            paths.append(path)
    path = outdir / f"{prefix}_keychain.3mf"
    write_3mf(path, plates, p.colors)
    paths.append(path)
    path = outdir / f"{prefix}_spec.txt"
    write_spec(path, plates, p, prefix)
    paths.append(path)
    return paths


def export_test_coupons(coupons, outdir, prefix="test"):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for plate in coupons:
        paths += write_layer_stls(outdir, prefix, plate)
    return paths
