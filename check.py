#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dist/ に出力された HTML を検証する。

  python3 build.py && python3 check.py

チェック内容:
  1. HTML のタグが正しく閉じられているか
  2. サイト内リンクの参照先ファイルとアンカーが存在するか
  3. 検索インデックスのアンカーが実在するか
  4. 必須ファイルが揃っているか

問題があれば終了コード 1 を返す。
"""

from __future__ import annotations

import json
import sys
from html.parser import HTMLParser
from pathlib import Path

DIST = Path(__file__).resolve().parent / "dist"

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "source", "track", "wbr",
}

problems: list[str] = []


class TagBalance(HTMLParser):
    """開始タグと終了タグの対応を確認する。"""

    def __init__(self, filename: str):
        super().__init__(convert_charrefs=True)
        self.filename = filename
        self.stack: list[tuple[str, tuple[int, int]]] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID_TAGS:
            self.stack.append((tag, self.getpos()))

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if not self.stack:
            problems.append(f"{self.filename}: 対応する開始タグのない </{tag}> {self.getpos()}")
            return
        if self.stack[-1][0] != tag:
            open_tag, pos = self.stack[-1]
            problems.append(
                f"{self.filename}: <{open_tag}> {pos} を </{tag}> {self.getpos()} で閉じています"
            )
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    return
            return
        self.stack.pop()


class Refs(HTMLParser):
    """id 属性・リンク先・読み込むファイルを集める。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.assets: list[str] = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get("id"):
            self.ids.add(d["id"])
        if tag == "a" and d.get("href"):
            self.links.append(d["href"])
        # favicon・CSS・JS などの参照先が実在するか確かめる
        if tag == "link" and d.get("href"):
            self.assets.append(d["href"])
        if tag in ("script", "img", "source") and d.get("src"):
            self.assets.append(d["src"])


def main() -> int:
    if not DIST.is_dir():
        print("エラー: dist/ がありません。先に python3 build.py を実行してください。")
        return 1

    pages = {f.name: f.read_text(encoding="utf-8") for f in sorted(DIST.glob("*.html"))}
    if not pages:
        problems.append("dist/ に HTML がありません")

    for required in ("index.html", "search.json", "assets/style.css", "assets/app.js"):
        if not (DIST / required).exists():
            problems.append(f"必須ファイルがありません: {required}")

    ids: dict[str, set[str]] = {}
    links: dict[str, list[str]] = {}

    for name, src in pages.items():
        balance = TagBalance(name)
        balance.feed(src)
        if balance.stack:
            leftover = ", ".join(f"<{t}>" for t, _ in balance.stack)
            problems.append(f"{name}: 閉じられていないタグ: {leftover}")

        refs = Refs()
        refs.feed(src)
        ids[name] = refs.ids
        links[name] = refs.links

        for asset in refs.assets:
            if asset.startswith(("http://", "https://", "data:", "//")):
                continue
            if not (DIST / asset.split("?")[0]).exists():
                problems.append(f"{name}: 参照先のファイルがありません → {asset}")

    external = ("http://", "https://", "mailto:", "tel:", "data:")
    for name, hrefs in links.items():
        for href in hrefs:
            if href.startswith(external):
                continue
            target, _, fragment = href.partition("#")
            target = target or name
            if target not in pages:
                problems.append(f"{name}: リンク先のページがありません → {href}")
            elif fragment and fragment not in ids[target]:
                problems.append(f"{name}: リンク先のアンカーがありません → {href}")

    index_path = DIST / "search.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        if not index:
            problems.append("search.json が空です")
        for entry in index:
            if entry["u"] not in pages:
                problems.append(f"search.json: 存在しないページ {entry['u']}")
            elif entry["a"] not in ids[entry["u"]]:
                problems.append(f"search.json: 存在しないアンカー {entry['u']}#{entry['a']}")

    total_links = sum(len(v) for v in links.values())
    print(f"ページ {len(pages)} 件 / サイト内リンク {total_links} 本を検証しました")

    if problems:
        print(f"\n✗ {len(problems)} 件の問題が見つかりました:")
        for p in problems:
            print("  -", p)
        return 1

    print("✓ 問題はありませんでした")
    return 0


if __name__ == "__main__":
    sys.exit(main())
