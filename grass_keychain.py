#!/usr/bin/env python3
"""GitHub のコントリビューション（草）を半年ずつ 2 枚の積層キーホルダーにする（CLI 版）。

出力 (out/ 以下):
  <user>_plate{1,2}_{n}_<層>.stl  層ごとの STL（印刷向きのまま。n は上から重ねる順番）
  <user>_keychain.3mf        組み立て状態の確認用（層ごとに色付きパーツ）
  <user>_plate{1,2}_preview.png  組み立て後の表面・裏面・断面、各層のプレビュー
  <user>_spec.txt            生成時の設定
  <user>_contributions.json  取得した生データ

使い方:
  venv/bin/python grass_keychain.py <github_user>
  venv/bin/python grass_keychain.py <github_user> --demo     # API を使わずランダムデータで試す
  venv/bin/python grass_keychain.py <github_user> --test-coupons  # はめ込み確認用のテスト片だけを作る
トークンは環境変数 GITHUB_TOKEN → `gh auth token` → キーチェーン（アプリで保存したもの）の順に探す。
デスクトップアプリ版は `venv/bin/python -m app`。
"""

import argparse
import json
from pathlib import Path

from core import params as P
from core.export import export_keychain, export_test_coupons
from core.fetch import FetchError, demo_weeks, fetch_weeks, parse_weeks_json
from core.geometry import build_keychain, build_test_coupons


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("user", help="GitHub ユーザー名")
    ap.add_argument("--demo", action="store_true", help="API を使わずランダムデータで生成")
    ap.add_argument("--json", type=Path, help="保存済みの contributions.json を使う")
    ap.add_argument("--start-date", type=str, default=None,
                    help="データの開始週（日曜、YYYY-MM-DD）。省略時は取得した日を基準にした直近54週")
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--test-coupons", action="store_true", help="すき間 0.1/0.15/0.2mm のテスト片だけを作る")
    for spec in P.field_specs():
        opt = "--" + spec["name"].replace("_", "-")
        help_ = f"{spec['label']} {spec['unit']}（既定 {spec['default']}）"
        if spec["kind"] == "bool":
            ap.add_argument(opt, action=argparse.BooleanOptionalAction, default=spec["default"], help=spec["label"])
        else:
            ap.add_argument(opt, type=float if spec["kind"] == "float" else str, default=spec["default"], help=help_)
    args = ap.parse_args()
    p = P.Params.from_dict(vars(args))

    errs = P.errors(p)
    if errs:
        raise SystemExit("\n".join(errs))

    if args.test_coupons:
        paths = export_test_coupons(build_test_coupons(p), args.out)
        print("\n".join(str(x) for x in paths))
        return

    try:
        if args.json:
            weeks = parse_weeks_json(json.loads(args.json.read_text()))
        elif args.demo:
            weeks = demo_weeks(start_date=args.start_date)
        else:
            weeks = fetch_weeks(args.user, start_date=args.start_date)
    except FetchError as e:
        raise SystemExit(str(e))

    plates = build_keychain(weeks, p, user=args.user)
    for plate in plates:
        i = plate.info
        print(f"{plate.name}: {plate.period[0]} 〜 {plate.period[1]}  外形 {i['plate_w']:.1f} x {i['plate_h']:.1f} mm, "
              f"厚さ {i['thickness']:.1f} mm（突起込み {i['total']:.1f} mm）, 層: {' → '.join(plate.layers)}")
    for w in P.warnings(p, [pl.info for pl in plates]):
        print(f"  注意: {w}")
    export_keychain(plates, args.out, args.user, p, weeks=weeks)
    print(f"出力先: {args.out.resolve()}")


if __name__ == "__main__":
    main()
