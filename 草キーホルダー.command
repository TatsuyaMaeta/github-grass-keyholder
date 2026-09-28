#!/bin/zsh
# ダブルクリックで GitHub草キーホルダー作成アプリを起動する
cd "$(dirname "$0")"
exec venv/bin/python -m app
