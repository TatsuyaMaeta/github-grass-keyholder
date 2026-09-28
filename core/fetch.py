"""GitHub のコントリビューション取得とトークン管理。"""

import datetime as dt
import json
import os
import random
import shutil
import subprocess
import urllib.error
import urllib.request

from .params import LEVELS

KEYCHAIN_SERVICE = "grass-keychain"
KEYCHAIN_ACCOUNT = "github-token"

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date weekday contributionCount contributionLevel } }
      }
    }
  }
}
"""

WEEKS_PER_PLATE = 27  # 1 枚あたりの週数（半年分）。取得する週数を固定し、取得タイミングで行数が変わらないようにする


class FetchError(Exception):
    pass


def _sunday_on_or_before(d):
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def _default_start(today):
    """既定の開始週: 直近54週（今週を含む）の最初の日曜"""
    return _sunday_on_or_before(today) - dt.timedelta(weeks=WEEKS_PER_PLATE * 2 - 1)


def _resolve_start(start_date, today):
    if not start_date:
        return _default_start(today)
    if isinstance(start_date, str):
        start_date = dt.date.fromisoformat(start_date)
    return _sunday_on_or_before(start_date)


# ---------------------------------------------------------------- トークン

def _gh_path():
    # .app から起動すると PATH に Homebrew が入らないので、よくある場所も探す
    return shutil.which("gh") or next(
        (p for p in ("/usr/local/bin/gh", "/opt/homebrew/bin/gh") if os.path.exists(p)), None)


def get_token():
    """(トークン, 取得元) を返す。環境変数 → gh CLI → キーチェーンの順。見つからなければ (None, None)"""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token, "環境変数 GITHUB_TOKEN"
    gh = _gh_path()
    if gh:
        try:
            token = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()
            if token:
                return token, "gh auth token"
        except (OSError, subprocess.CalledProcessError):
            pass
    token = keychain_token()
    if token:
        return token, "キーチェーン"
    return None, None


def keychain_token():
    import keyring
    try:
        return keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except Exception:
        return None


def save_keychain_token(token):
    import keyring
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, token)


def delete_keychain_token():
    import keyring
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except Exception:
        pass


# ---------------------------------------------------------------- 取得

def _fetch_range(user, token, frm, to):
    variables = {"login": user, "from": frm.isoformat() + "T00:00:00Z", "to": to.isoformat() + "T23:59:59Z"}
    body = json.dumps({"query": QUERY, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            data = json.load(res)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise FetchError("トークンが無効です（HTTP 401）。有効期限と権限を確認してください") from e
        raise FetchError(f"GitHub API エラー: HTTP {e.code}") from e
    except urllib.error.URLError as e:
        raise FetchError(f"GitHub に接続できません: {e.reason}") from e
    if data.get("errors"):
        raise FetchError(f"GitHub API エラー: {data['errors'][0].get('message', data['errors'])}")
    if not data["data"]["user"]:
        raise FetchError(f"ユーザー {user} が見つかりません")
    return data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]


def fetch_weeks(user, token=None, start_date=None):
    """開始週から plate 2 枚分（54 週＝27 週 × 2）を取得する。
    start_date を指定しないと、取得した日を基準にした直近54週になる（毎回同じ日に取得しないと結果がずれる）。
    1 回の取得範囲が API の1年制限を超えないよう、半年分ずつ2回に分けて取得する"""
    import truststore
    truststore.inject_into_ssl()  # macOS キーチェーンの証明書で検証する
    if token is None:
        token, _ = get_token()
    if not token:
        raise FetchError("GitHub のトークンが見つかりません。GITHUB_TOKEN を設定するか、`gh auth login` を実行してください")
    today = dt.date.today()
    start = _resolve_start(start_date, today)
    weeks = []
    for half in range(2):
        frm = start + dt.timedelta(weeks=WEEKS_PER_PLATE * half)
        if frm > today:
            break  # start_date が未来
        to = min(frm + dt.timedelta(days=WEEKS_PER_PLATE * 7 - 1), today)
        weeks += _fetch_range(user, token, frm, to)
    return weeks


def _find_weeks(node):
    """dict/listの中から weeks の配列（各要素が contributionDays を持つ）を再帰的に探す"""
    if isinstance(node, list):
        if node and isinstance(node[0], dict) and "contributionDays" in node[0]:
            return node
        return None
    if isinstance(node, dict):
        if isinstance(node.get("weeks"), list):
            return node["weeks"]
        for v in node.values():
            found = _find_weeks(v)
            if found is not None:
                return found
    return None


def parse_weeks_json(raw):
    """--json / JSONを読み込むで受け取ったデータをweeksの配列にする。
    このアプリが書き出したweeksの配列そのものでも、GitHubのGraphQL Explorerからコピーした
    生のレスポンス（{"data": {"viewer": {...}}} など）でも、どちらでも受け付ける"""
    weeks = _find_weeks(raw)
    if weeks is None:
        raise FetchError("JSONの中に weeks のデータが見つかりません")
    return weeks


def demo_weeks(seed=0, start_date=None):
    """API と同じ形のランダムデータ（開始週から54週、日曜始まりの週）"""
    rnd = random.Random(seed)
    today = dt.date.today()
    start = _resolve_start(start_date, today)
    end = min(start + dt.timedelta(weeks=WEEKS_PER_PLATE * 2) - dt.timedelta(days=1), today)
    weeks, day = [], start
    while day <= end:
        days = []
        for _ in range(7):
            if day <= end:
                lv = rnd.choices(range(5), weights=[55, 20, 12, 8, 5])[0]
                days.append({"date": day.isoformat(), "weekday": (day.weekday() + 1) % 7,
                             "contributionCount": lv * 3, "contributionLevel": LEVELS[lv]})
            day += dt.timedelta(days=1)
        weeks.append({"contributionDays": days})
    return weeks
