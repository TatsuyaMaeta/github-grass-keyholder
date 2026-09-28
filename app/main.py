"""デスクトップアプリ版。pywebview のウィンドウに web/ の画面を表示し、生成処理は core を呼ぶ。

起動: venv/bin/python -m app
"""

import base64
import json
import os
import subprocess
import threading
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 生成処理は別スレッドで動くので GUI バックエンドを使わない

import numpy as np
import webview

from core import params as P
from core.export import export_keychain, export_test_coupons, mesh_arrays
from core.fetch import (FetchError, delete_keychain_token, demo_weeks, fetch_weeks, get_token,
                        parse_weeks_json, save_keychain_token)
from core.geometry import build_keychain, build_test_coupons, split_halves, weeks_to_cells

WEB_DIR = Path(__file__).resolve().parent / "web"
PROJECT_DIR = Path(__file__).resolve().parent.parent
SLICER_APPS = ["/Applications/BambuStudio.app", "/Applications/Bambu Studio.app",
               "/Applications/OrcaSlicer.app", "/Applications/Original Prusa Drivers/PrusaSlicer.app"]


def _b64(arr, dtype):
    return base64.b64encode(np.ascontiguousarray(arr, dtype=dtype).tobytes()).decode()


def _ok(**data):
    return {"ok": True, **data}


def _err(msg):
    return {"ok": False, "error": msg}


class Api:
    """画面（JavaScript）から window.pywebview.api.<名前>() で呼ばれるメソッド群。
    先頭が _ の属性は画面に公開されない"""

    def __init__(self):
        self._window = None
        self._lock = threading.Lock()
        self._weeks = None
        self._user = ""
        self._cache = {}  # 設定 JSON → plates（書き出し時に作り直さないため）
        self._last_dir = str(PROJECT_DIR / "out")

    # ------------------------------------------------------------ 初期表示

    def init(self):
        _, source = get_token()
        return _ok(fields=P.field_specs(), colors=P.DEFAULT_COLORS, github_colors=P.GITHUB_COLORS,
                   layer_names=P.LAYER_NAMES, token_source=source)

    # ------------------------------------------------------------ トークン

    def token_status(self):
        _, source = get_token()
        return _ok(token_source=source)

    def save_token(self, token):
        token = (token or "").strip()
        if not token:
            return _err("トークンが空です")
        save_keychain_token(token)
        return self.token_status()

    def delete_token(self):
        delete_keychain_token()
        return self.token_status()

    # ------------------------------------------------------------ データ

    def fetch(self, user, start_date=None):
        user = (user or "").strip()
        if not user:
            return _err("ユーザー名を入力してください")
        try:
            weeks = fetch_weeks(user, start_date=start_date or None)
        except FetchError as e:
            return _err(str(e))
        return self._set_weeks(weeks, user)

    def demo(self, user, start_date=None):
        return self._set_weeks(demo_weeks(start_date=start_date or None), (user or "").strip() or "demo")

    def load_json(self, user):
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, directory=self._last_dir,
                                                file_types=("JSON (*.json)",))
        if not paths:
            return _ok(cancelled=True)
        path = Path(paths[0])
        try:
            weeks = parse_weeks_json(json.loads(path.read_text()))
        except (OSError, ValueError, FetchError) as e:
            return _err(f"読み込めません: {e}")
        name = (user or "").strip() or path.name.removesuffix("_contributions.json")
        return self._set_weeks(weeks, name)

    def _set_weeks(self, weeks, user):
        self._weeks, self._user = weeks, user
        self._cache.clear()
        halves, cols = split_halves(weeks)
        grids = []
        for half in halves:
            grid = [[None] * cols for _ in range(7)]  # grid[行(0=日曜)][列] = レベル
            for col, row, lv in weeks_to_cells(half):
                grid[6 - row][col] = lv
            days = [d["date"] for w in half for d in w["contributionDays"]]
            grids.append(dict(grid=grid, period=[days[0], days[-1]] if days else ["", ""]))
        total = sum(d["contributionCount"] for w in weeks for d in w["contributionDays"])
        return _ok(user=user, total=total, halves=grids)

    # ------------------------------------------------------------ 生成

    def _plates(self, p):
        key = json.dumps(p.to_dict(), sort_keys=True)
        with self._lock:
            if key not in self._cache:
                self._cache.clear()
                self._cache[key] = build_keychain(self._weeks, p, user=self._user)
            return self._cache[key]

    def generate(self, params):
        if self._weeks is None:
            return _err("先にデータを取得してください")
        p = P.Params.from_dict(params)
        errs = P.errors(p)
        if errs:
            return _err("\n".join(errs))
        try:
            plates = self._plates(p)
        except Exception as e:  # 形状演算の失敗は画面に出す
            return _err(f"生成に失敗しました: {e}")
        out = []
        for plate in plates:
            layers = []
            for name, m in plate.layers.items():
                v, t = mesh_arrays(m)
                layers.append(dict(name=name, z0=plate.info["z0"][name], t=plate.info["t"][name],
                                   positions=_b64(v, "<f4"), indices=_b64(t, "<u4")))
            info = {k: plate.info[k] for k in ("plate_w", "plate_h", "thickness", "total", "text_h_actual", "counts")}
            out.append(dict(name=plate.name, period=list(plate.period), info=info, layers=layers))
        return _ok(plates=out, warnings=P.warnings(p, [pl.info for pl in plates]))

    # ------------------------------------------------------------ 書き出し

    def _ask_folder(self):
        paths = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=self._last_dir)
        if not paths:
            return None
        self._last_dir = paths[0] if isinstance(paths, (list, tuple)) else paths
        return self._last_dir

    def export(self, params):
        if self._weeks is None:
            return _err("先にデータを取得してください")
        p = P.Params.from_dict(params)
        if P.errors(p):
            return _err("\n".join(P.errors(p)))
        outdir = self._ask_folder()
        if not outdir:
            return _ok(cancelled=True)
        paths = export_keychain(self._plates(p), outdir, self._user, p, weeks=self._weeks)
        return _ok(dir=outdir, files=[x.name for x in paths],
                   threemf=str(next(x for x in paths if x.suffix == ".3mf")))

    def export_test_coupons(self, params):
        p = P.Params.from_dict(params)
        outdir = self._ask_folder()
        if not outdir:
            return _ok(cancelled=True)
        with self._lock:
            paths = export_test_coupons(build_test_coupons(p), outdir)
        return _ok(dir=outdir, files=[x.name for x in paths])

    def open_folder(self, path):
        subprocess.run(["open", path])
        return _ok()

    def open_in_slicer(self, path):
        app = next((a for a in SLICER_APPS if os.path.exists(a)), None)
        subprocess.run(["open", "-a", app, path] if app else ["open", path])
        return _ok(app=Path(app).stem if app else "既定のアプリ")

    # ------------------------------------------------------------ プリセット

    def save_preset(self, params):
        path = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=self._last_dir,
                                               save_filename="preset.json")
        if not path:
            return _ok(cancelled=True)
        path = path[0] if isinstance(path, (list, tuple)) else path
        Path(path).write_text(json.dumps(P.Params.from_dict(params).to_dict(), ensure_ascii=False, indent=2))
        return _ok(path=path)

    def load_preset(self):
        paths = self._window.create_file_dialog(webview.FileDialog.OPEN, directory=self._last_dir,
                                                file_types=("JSON (*.json)",))
        if not paths:
            return _ok(cancelled=True)
        try:
            p = P.Params.from_dict(json.loads(Path(paths[0]).read_text()))
        except (OSError, ValueError, TypeError) as e:
            return _err(f"読み込めません: {e}")
        return _ok(params=p.to_dict())


def main():
    api = Api()
    window = webview.create_window("GitHub草キーホルダー", str(WEB_DIR / "index.html"), js_api=api,
                                   width=1320, height=860, min_size=(1000, 640))
    api._window = window
    webview.start(http_server=True, debug=bool(os.environ.get("GRASS_DEBUG")))
    # 終了時の後片付けで manifold3d（nanobind）が無害なリーク警告を大量に出すので、そのまま終了する
    os._exit(0)


if __name__ == "__main__":
    main()
