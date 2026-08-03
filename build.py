#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
未来国会2026 テキストブック — 静的サイトジェネレータ

content/*.md を読み込み、dist/ に静的 HTML を書き出す。
Python 3 の標準ライブラリのみで動作する（追加インストール不要）。

    python3 build.py

出力された dist/ をそのまま GitHub Pages に配信する。
"""

from __future__ import annotations

import html
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
ASSETS = ROOT / "assets"
DIST = ROOT / "dist"

SITE_TITLE = "未来国会2026 テキストブック"
SITE_TAGLINE = "若者のための国家デザインコンテスト"
SITE_DESC = (
    "NPO法人ドットジェイピー「未来国会2026」の国家デザイン テキストブックを、"
    "Webで読みやすく再構成したものです。"
)

# accent は章ごとのテーマ色（style.css の body[data-accent=...] に対応）。
# 【主要】ワークのオレンジと衝突しないよう、章の色にオレンジは使わない。
PAGES: list[dict] = [
    dict(slug="index", nav="ホーム", file="index.md", group="", accent="brand", home=True),
    dict(slug="intro", nav="はじめに", file="intro.md",
         group="コンテストを知る", accent="slate"),
    dict(slug="rules", nav="大会とルール", file="rules.md",
         group="コンテストを知る", accent="slate"),
    dict(slug="schedule", nav="スケジュールと提出物", file="schedule.md",
         group="コンテストを知る", accent="slate"),
    dict(slug="vision", nav="第1章　ビジョン", file="vision.md",
         group="テキスト本編", accent="blue", chapter="1", chapter_title="ビジョン",
         chapter_q="30年後、あなたが最も見たい未来はどんな景色か。"),
    dict(slug="issues", nav="第2章　社会課題と解決", file="issues.md",
         group="テキスト本編", accent="teal", chapter="2", chapter_title="社会課題と解決",
         chapter_q="理想と現実の差を、どんな打ち手で埋めるのか。"),
    dict(slug="budget", nav="第3章　予算", file="budget.md",
         group="テキスト本編", accent="violet", chapter="3", chapter_title="予算",
         chapter_q="限られたお金の配分に、あなたの本音はどう表れるか。"),
    dict(slug="presentation", nav="第4章　プレゼンテーション", file="presentation.md",
         group="テキスト本編", accent="rose", chapter="4", chapter_title="プレゼンテーション",
         nav_short="第4章　プレゼン",
         chapter_q="その未来を、どう語れば聞き手の心が動くのか。"),
    dict(slug="works", nav="ワーク一覧", file="works.md", group="資料", accent="brand"),
    dict(slug="glossary", nav="巻末資料　用語の説明", file="glossary.md",
         group="資料", accent="slate"),
]

# 章スラッグ → 短縮ラベル（ワーク一覧などで使う）
CHAPTER_LABEL = {
    "vision": "第1章 ビジョン",
    "issues": "第2章 社会課題と解決",
    "budget": "第3章 予算",
    "presentation": "第4章 プレゼン",
}

# 日本語の読む速さの目安（1分あたりの文字数）
CHARS_PER_MINUTE = 520


# --------------------------------------------------------------------------
# データ構造
# --------------------------------------------------------------------------

@dataclass
class Work:
    """テキストブック中の「ワーク」1件。"""
    wid: str            # "1-1"
    kind: str           # "main" | "sub"
    title: str
    page: str           # ページ slug
    anchor: str
    plansheet: bool = False


@dataclass
class Heading:
    level: int
    text: str
    anchor: str


@dataclass
class Page:
    slug: str
    nav_title: str
    group: str
    nav_short: str = ""
    home: bool = False
    accent: str = "brand"
    chapter: str = ""
    chapter_title: str = ""
    chapter_q: str = ""
    title: str = ""
    lead: str = ""
    body: str = ""
    minutes: int = 0
    headings: list[Heading] = field(default_factory=list)
    search: list[dict] = field(default_factory=list)


WORKS: list[Work] = []

# content 側で :::worklist / :::chapters と書いた位置に差し込むための目印
WORKLIST_TOKEN = "<!--WORKLIST-->"
CHAPTERS_TOKEN = "<!--CHAPTERS-->"


# --------------------------------------------------------------------------
# インライン記法
# --------------------------------------------------------------------------

_CODE_TOKEN = "\x00C{}\x00"


def inline(text: str) -> str:
    """インライン記法を HTML に変換する。"""
    codes: list[str] = []

    def stash_code(m: re.Match) -> str:
        codes.append(html.escape(m.group(1), quote=False))
        return _CODE_TOKEN.format(len(codes) - 1)

    text = re.sub(r"`([^`]+)`", stash_code, text)
    text = html.escape(text, quote=False)

    # [表示テキスト](URL)
    def link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        external = url.startswith(("http://", "https://", "mailto:"))
        attrs = ' target="_blank" rel="noopener noreferrer"' if external else ""
        cls = ' class="ext"' if external else ""
        return f'<a href="{html.escape(url, quote=True)}"{cls}{attrs}>{label}</a>'

    text = re.sub(r"\[([^\]\[]+)\]\(([^)\s]+)\)", link, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"==([^=]+)==", r"<mark>\1</mark>", text)
    text = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", text)

    for i, code in enumerate(codes):
        text = text.replace(_CODE_TOKEN.format(i), f"<code>{code}</code>")
    return text


# --------------------------------------------------------------------------
# ブロック記法
# --------------------------------------------------------------------------

FENCE_RE = re.compile(r"^:::(\w+)\s*(.*)$")
ATTR_RE = re.compile(r'(\w+)(?:=(?:"([^"]*)"|(\S+)))?')
HEADING_RE = re.compile(r"^(#{1,4})\s+(.*?)\s*(?:\{#([\w.-]+)\})?\s*$")
ULI_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")
OLI_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")


def parse_attrs(raw: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for m in ATTR_RE.finditer(raw):
        key = m.group(1)
        val = m.group(2) if m.group(2) is not None else m.group(3)
        attrs[key] = val if val is not None else "true"
    return attrs


def slugify(text: str, fallback: str) -> str:
    """見出しから anchor を作る。先頭の節番号を優先的に使う。"""
    m = re.match(r"^\s*(\d+(?:\.\d+)*)\.?\s", text)
    if m:
        return "s" + m.group(1).replace(".", "-")
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    if ascii_part and len(ascii_part) >= 3:
        return ascii_part[:48]
    return fallback


class Parser:
    def __init__(self, page_slug: str):
        self.page_slug = page_slug
        self.headings: list[Heading] = []
        self.search: list[dict] = []
        self._anchor_n = 0
        self._current_section = ""
        self._current_anchor = ""
        self._buffer: list[str] = []

    # -- 検索インデックス -------------------------------------------------
    def _flush_search(self) -> None:
        if not self._current_section:
            self._buffer = []
            return
        text = " ".join(self._buffer).strip()
        self.search.append({
            "s": self._current_section,
            "a": self._current_anchor,
            "t": text[:1200],
        })
        self._buffer = []

    def _collect(self, raw_text: str) -> None:
        cleaned = re.sub(r"[`*=~\[\]()#|>-]", " ", raw_text)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            self._buffer.append(cleaned)

    def next_anchor(self) -> str:
        self._anchor_n += 1
        return f"sec-{self._anchor_n}"

    # -- 本体 --------------------------------------------------------------
    def parse(self, lines: list[str], top: bool = True) -> str:
        out: list[str] = []
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]

            if not line.strip():
                i += 1
                continue

            # --- フェンス付きブロック ---
            m = FENCE_RE.match(line)
            if m:
                name, attr_raw = m.group(1), m.group(2)
                depth = 1
                j = i + 1
                inner: list[str] = []
                while j < n:
                    if FENCE_RE.match(lines[j]):
                        depth += 1
                    elif lines[j].strip() == ":::":
                        depth -= 1
                        if depth == 0:
                            break
                    inner.append(lines[j])
                    j += 1
                out.append(self.render_block(name, parse_attrs(attr_raw), inner))
                i = j + 1
                continue

            # --- 見出し ---
            m = HEADING_RE.match(line)
            if m:
                level = len(m.group(1))
                text = m.group(2)
                anchor = m.group(3) or slugify(text, self.next_anchor())
                if top and level in (2, 3):
                    self._flush_search()
                    self._current_section = re.sub(r"\s+", " ", text).strip()
                    self._current_anchor = anchor
                    self.headings.append(Heading(level, text, anchor))
                self._collect(text)
                out.append(self.render_heading(level, text, anchor, top))
                i += 1
                continue

            # --- 水平線 ---
            if re.match(r"^-{3,}$", line.strip()):
                out.append('<hr class="rule">')
                i += 1
                continue

            # --- テーブル ---
            if line.lstrip().startswith("|") and i + 1 < n and re.match(
                r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]
            ):
                block: list[str] = []
                while i < n and lines[i].lstrip().startswith("|"):
                    block.append(lines[i])
                    i += 1
                out.append(self.render_table(block))
                continue

            # --- 引用 ---
            if line.lstrip().startswith("> "):
                block = []
                while i < n and lines[i].lstrip().startswith(">"):
                    block.append(re.sub(r"^\s*>\s?", "", lines[i]))
                    i += 1
                self._collect(" ".join(block))
                out.append(
                    "<blockquote>" + self.parse(block, top=False) + "</blockquote>"
                )
                continue

            # --- リスト ---
            if ULI_RE.match(line) or OLI_RE.match(line):
                block = []
                while i < n and (
                    ULI_RE.match(lines[i]) or OLI_RE.match(lines[i])
                    or (lines[i].startswith("  ") and lines[i].strip())
                ):
                    block.append(lines[i])
                    i += 1
                out.append(self.render_list(block))
                continue

            # --- 段落 ---
            # 先頭1行は必ず消費する（どの分岐にも当てはまらない行で止まらないように）
            para: list[str] = [lines[i].strip()]
            i += 1
            while i < n and lines[i].strip() and not FENCE_RE.match(lines[i]) \
                    and not HEADING_RE.match(lines[i]) \
                    and not lines[i].lstrip().startswith(("|", ">")) \
                    and not ULI_RE.match(lines[i]) and not OLI_RE.match(lines[i]) \
                    and not re.match(r"^-{3,}$", lines[i].strip()):
                para.append(lines[i].strip())
                i += 1
            text = " ".join(para)
            self._collect(text)
            out.append(f"<p>{inline(text)}</p>")

        if top:
            self._flush_search()
        return "\n".join(out)

    # -- 個別レンダラ ------------------------------------------------------
    def render_heading(self, level: int, text: str, anchor: str, top: bool) -> str:
        content = inline(text)
        if top and level == 2:
            num = ""
            m = re.match(r"^\s*(\d+(?:\.\d+)*)\.?\s+(.*)$", text)
            if m:
                num = f'<span class="h2-num">{html.escape(m.group(1))}</span>'
                content = inline(m.group(2))
            return (
                f'<h2 id="{anchor}" class="h2">{num}'
                f'<span class="h2-text">{content}</span>'
                f'<a class="anchor" href="#{anchor}" aria-label="このセクションへのリンク">#</a></h2>'
            )
        if top and level == 3:
            return (
                f'<h3 id="{anchor}">{content}'
                f'<a class="anchor" href="#{anchor}" aria-label="この項目へのリンク">#</a></h3>'
            )
        tag = f"h{min(level, 6)}"
        return f"<{tag}>{content}</{tag}>"

    def render_table(self, block: list[str]) -> str:
        def cells(row: str) -> list[str]:
            row = row.strip()
            if row.startswith("|"):
                row = row[1:]
            if row.endswith("|"):
                row = row[:-1]
            return [c.strip() for c in row.split("|")]

        header = cells(block[0])
        aligns = []
        for spec in cells(block[1]):
            if spec.startswith(":") and spec.endswith(":"):
                aligns.append("center")
            elif spec.endswith(":"):
                aligns.append("right")
            else:
                aligns.append("left")
        rows = [cells(r) for r in block[2:]]

        self._collect(" ".join(header))
        for r in rows:
            self._collect(" ".join(r))

        head_html = "".join(
            f'<th style="text-align:{aligns[k] if k < len(aligns) else "left"}">'
            f"{inline(c)}</th>"
            for k, c in enumerate(header)
        )
        body_html = ""
        for r in rows:
            tds = "".join(
                f'<td style="text-align:{aligns[k] if k < len(aligns) else "left"}" '
                f'data-label="{html.escape(header[k] if k < len(header) else "", quote=True)}">'
                f"{inline(c)}</td>"
                for k, c in enumerate(r)
            )
            body_html += f"<tr>{tds}</tr>"
        # 列数を CSS 変数で渡し、狭い画面での見せ方を切り替えられるようにする
        return (
            f'<div class="table-wrap" data-cols="{len(header)}" '
            f'style="--cols:{len(header)}"><table><thead><tr>'
            f"{head_html}</tr></thead><tbody>{body_html}</tbody></table></div>"
        )

    def render_list(self, block: list[str]) -> str:
        """インデント（2スペース）でネストするリストを組み立てる。"""
        items: list[tuple[int, str, list[str]]] = []  # (indent, marker, lines)
        for raw in block:
            m = ULI_RE.match(raw)
            if m:
                items.append((len(m.group(1)), "ul", [m.group(2)]))
                continue
            m = OLI_RE.match(raw)
            if m:
                items.append((len(m.group(1)), "ol", [m.group(2)]))
                continue
            if items:  # 継続行
                items[-1][2].append(raw.strip())

        def build(idx: int, indent: int) -> tuple[str, int]:
            """indent 以上の項目を、同種マーカーごとのリストに束ねて返す。"""
            lists: list[str] = []
            while idx < len(items) and items[idx][0] >= indent:
                tag = items[idx][1]
                parts: list[str] = []
                while idx < len(items) and items[idx][0] >= indent:
                    cur_indent, cur_tag, cur_lines = items[idx]
                    if cur_indent > indent:
                        child, idx = build(idx, cur_indent)
                        if not parts:
                            parts.append("<li>")
                        parts[-1] += child
                        continue
                    if cur_tag != tag:
                        break  # ul → ol の切り替わり。兄弟リストとして開き直す
                    text = " ".join(cur_lines)
                    self._collect(text)
                    parts.append(f"<li>{inline(text)}")
                    idx += 1
                closed = "".join(p + "</li>" for p in parts)
                lists.append(f"<{tag}>{closed}</{tag}>")
            return "".join(lists), idx

        if not items:
            return ""
        html_out, _ = build(0, items[0][0])
        return html_out

    def render_block(self, name: str, attrs: dict[str, str], inner: list[str]) -> str:
        method = getattr(self, f"blk_{name}", None)
        if method is None:
            return self.parse(inner, top=False)
        return method(attrs, inner)

    # -- ブロック: ワークカード -------------------------------------------
    def blk_work(self, attrs: dict[str, str], inner: list[str]) -> str:
        wid = attrs.get("id", "")
        kind = attrs.get("kind", "sub")
        title = attrs.get("title", "")
        plansheet = attrs.get("plansheet") == "true"
        anchor = f"work-{wid}" if wid else self.next_anchor()

        WORKS.append(Work(wid, kind, title, self.page_slug, anchor, plansheet))
        self._collect(f"ワーク{wid} {title}")

        badge = "【主要】ワーク" if kind == "main" else "［補助］ワーク"
        body = self.parse(inner, top=False)
        ps = (
            '<p class="work-plansheet">ここまでできたらプランシートへ転記しましょう</p>'
            if plansheet else ""
        )
        return f"""<section class="work work--{kind}" id="{anchor}">
  <header class="work-head">
    <label class="work-check">
      <input type="checkbox" class="work-toggle" data-work="{html.escape(wid, quote=True)}"
             aria-label="ワーク{html.escape(wid, quote=True)}を完了にする">
      <span class="work-check-box" aria-hidden="true"></span>
    </label>
    <div class="work-headtext">
      <p class="work-badge">{badge} <span class="work-id">{html.escape(wid)}</span></p>
      <h4 class="work-title">{inline(title)}</h4>
    </div>
    <a class="anchor work-anchor" href="#{anchor}" aria-label="このワークへのリンク">#</a>
  </header>
  <div class="work-body">{body}{ps}</div>
</section>"""

    # -- ブロック: 補足・コラム -------------------------------------------
    def blk_note(self, attrs: dict[str, str], inner: list[str]) -> str:
        kind = attrs.get("kind", "info")
        title = attrs.get("title", "")
        icons = {
            "info": "i", "tip": "＊", "warn": "!", "column": "＋",
            "example": "例", "source": "出典",
        }
        icon = icons.get(kind, "i")
        head = (
            f'<p class="note-title"><span class="note-icon" aria-hidden="true">{icon}</span>'
            f"{inline(title)}</p>" if title else ""
        )
        if title:
            self._collect(title)
        return (
            f'<aside class="note note--{kind}">{head}'
            f'<div class="note-body">{self.parse(inner, top=False)}</div></aside>'
        )

    # -- ブロック: カードグリッド -----------------------------------------
    def blk_grid(self, attrs: dict[str, str], inner: list[str]) -> str:
        cols = attrs.get("cols", "3")
        cards = self._split_by_h3(inner)
        html_cards = []
        for title, body in cards:
            self._collect(title)
            html_cards.append(
                f'<article class="card"><h4 class="card-title">{inline(title)}</h4>'
                f'<div class="card-body">{self.parse(body, top=False)}</div></article>'
            )
        return f'<div class="grid grid--{cols}">{"".join(html_cards)}</div>'

    # -- ブロック: 手順 ----------------------------------------------------
    def blk_steps(self, attrs: dict[str, str], inner: list[str]) -> str:
        steps = self._split_by_h3(inner)
        items = []
        for k, (title, body) in enumerate(steps, start=1):
            self._collect(title)
            items.append(
                f'<li class="step"><span class="step-num" aria-hidden="true">{k}</span>'
                f'<div class="step-main"><p class="step-title">{inline(title)}</p>'
                f'{self.parse(body, top=False)}</div></li>'
            )
        return f'<ol class="steps">{"".join(items)}</ol>'

    # -- ブロック: タイムライン -------------------------------------------
    def blk_timeline(self, attrs: dict[str, str], inner: list[str]) -> str:
        entries = self._split_by_h3(inner)
        items = []
        for title, body in entries:
            self._collect(title)
            items.append(
                '<li class="tl-item"><div class="tl-marker" aria-hidden="true"></div>'
                f'<div class="tl-body"><p class="tl-when">{inline(title)}</p>'
                f'{self.parse(body, top=False)}</div></li>'
            )
        return f'<ol class="timeline">{"".join(items)}</ol>'

    # -- ブロック: フロー（矢印でつなぐ） ---------------------------------
    def blk_flow(self, attrs: dict[str, str], inner: list[str]) -> str:
        nodes = [ln.strip()[2:].strip() for ln in inner if ln.strip().startswith("- ")]
        for nd in nodes:
            self._collect(nd)
        parts = []
        for k, nd in enumerate(nodes):
            if k:
                parts.append('<li class="flow-arrow" aria-hidden="true"></li>')
            parts.append(f'<li class="flow-node">{inline(nd)}</li>')
        return f'<ul class="flow">{"".join(parts)}</ul>'

    # -- ブロック: ロジックツリー -----------------------------------------
    def blk_tree(self, attrs: dict[str, str], inner: list[str]) -> str:
        body = self.render_list([ln for ln in inner if ln.strip()])
        return f'<div class="tree">{body}</div>'

    # -- ブロック: 図版プレースホルダ -------------------------------------
    def blk_figure(self, attrs: dict[str, str], inner: list[str]) -> str:
        caption = attrs.get("caption", "")
        kind = attrs.get("kind", "")
        if caption:
            self._collect(caption)
        cap = f'<figcaption>{inline(caption)}</figcaption>' if caption else ""
        cls = "figure figure--missing" if kind == "missing" else "figure"
        return (
            f'<figure class="{cls}"><div class="figure-body">'
            f'{self.parse(inner, top=False)}</div>{cap}</figure>'
        )

    # -- ブロック: 数値ハイライト -----------------------------------------
    def blk_stats(self, attrs: dict[str, str], inner: list[str]) -> str:
        items = []
        for ln in inner:
            if not ln.strip().startswith("- "):
                continue
            raw = ln.strip()[2:]
            if "：" in raw:
                label, value = raw.split("：", 1)
            elif ":" in raw:
                label, value = raw.split(":", 1)
            else:
                label, value = raw, ""
            self._collect(raw)
            items.append(
                f'<div class="stat"><span class="stat-value">{inline(value.strip())}</span>'
                f'<span class="stat-label">{inline(label.strip())}</span></div>'
            )
        return f'<div class="stats">{"".join(items)}</div>'

    # -- ブロック: 引用（大きく見せる） -----------------------------------
    def blk_quote(self, attrs: dict[str, str], inner: list[str]) -> str:
        cite = attrs.get("cite", "")
        text = " ".join(ln.strip() for ln in inner if ln.strip())
        self._collect(text)
        footer = f'<footer class="pq-cite">{inline(cite)}</footer>' if cite else ""
        return (
            f'<blockquote class="pullquote"><span class="pq-mark" aria-hidden="true">"</span>'
            f'<p class="pq-text">{inline(text)}</p>{footer}</blockquote>'
        )

    # -- ブロック: 全ワークの一覧（全ページのパース後に差し込む） ---------
    def blk_worklist(self, attrs: dict[str, str], inner: list[str]) -> str:
        return WORKLIST_TOKEN

    # -- ブロック: トップページのヒーロー ---------------------------------
    def blk_hero(self, attrs: dict[str, str], inner: list[str]) -> str:
        kicker = attrs.get("kicker", "")
        title = attrs.get("title", "")
        tag = "h1" if attrs.get("h1") == "true" else "p"
        self._collect(f"{kicker} {title}")
        k = f'<p class="hero-kicker">{inline(kicker)}</p>' if kicker else ""
        t = f'<{tag} class="hero-title">{inline(title)}</{tag}>' if title else ""
        return (
            f'<section class="hero">{k}{t}'
            f"{self.parse(inner, top=False)}</section>"
        )

    # -- ブロック: 4つの章のカード（ビルド後に差し込む） ------------------
    def blk_chapters(self, attrs: dict[str, str], inner: list[str]) -> str:
        return CHAPTERS_TOKEN

    # -- ブロック: リンクカード -------------------------------------------
    def blk_linkcards(self, attrs: dict[str, str], inner: list[str]) -> str:
        cards: list[str] = []
        for ln in inner:
            if not ln.strip().startswith("- "):
                continue
            fields = [f.strip() for f in ln.strip()[2:].split("|")]
            m = re.match(r"^\[([^\]]+)\]\(([^)\s]+)\)$", fields[0])
            if not m:
                continue
            label, url = m.group(1), m.group(2)
            eyebrow = fields[1] if len(fields) > 1 else ""
            desc = fields[2] if len(fields) > 2 else ""
            self._collect(f"{label} {desc}")
            eb = f'<p class="linkcard-eyebrow">{inline(eyebrow)}</p>' if eyebrow else ""
            ds = f'<p class="linkcard-desc">{inline(desc)}</p>' if desc else ""
            cards.append(
                f'<a class="linkcard" href="{html.escape(url, quote=True)}">{eb}'
                f'<p class="linkcard-title">{inline(label)}</p>{ds}</a>'
            )
        return f'<div class="linkcards">{"".join(cards)}</div>'

    @staticmethod
    def _split_by_h3(lines: list[str]) -> list[tuple[str, list[str]]]:
        """### 見出しごとに (見出し, 本文行) に分割する。"""
        out: list[tuple[str, list[str]]] = []
        title: str | None = None
        buf: list[str] = []
        for ln in lines:
            m = re.match(r"^#{3,4}\s+(.*)$", ln)
            if m:
                if title is not None:
                    out.append((title, buf))
                title = m.group(1).strip()
                buf = []
            else:
                buf.append(ln)
        if title is not None:
            out.append((title, buf))
        elif buf:
            out.append(("", buf))
        return out


# --------------------------------------------------------------------------
# ページの読み込み
# --------------------------------------------------------------------------

def load_page(cfg: dict) -> Page:
    slug = cfg["slug"]
    src = (CONTENT / cfg["file"]).read_text(encoding="utf-8")
    page = Page(
        slug=slug,
        nav_title=cfg["nav"],
        nav_short=cfg.get("nav_short", cfg["nav"]),
        home=cfg.get("home", False),
        group=cfg["group"],
        accent=cfg.get("accent", "brand"),
        chapter=cfg.get("chapter", ""),
        chapter_title=cfg.get("chapter_title", ""),
        chapter_q=cfg.get("chapter_q", ""),
    )
    nav_title = cfg["nav"]

    lines = src.split("\n")
    # 1行目の "# タイトル"、続く "> リード文" を取り出す
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx < len(lines) and lines[idx].startswith("# "):
        page.title = lines[idx][2:].strip()
        idx += 1
    else:
        page.title = nav_title

    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    lead_lines: list[str] = []
    while idx < len(lines) and lines[idx].startswith("> "):
        lead_lines.append(lines[idx][2:].strip())
        idx += 1
    page.lead = " ".join(lead_lines)

    parser = Parser(slug)
    page.body = parser.parse(lines[idx:])
    page.headings = parser.headings
    page.search = parser.search

    # 読了時間の目安（タグを除いた本文の文字数から概算する）
    plain = re.sub(r"<[^>]+>", "", page.body)
    plain = re.sub(r"\s+", "", plain)
    page.minutes = max(1, round(len(plain) / CHARS_PER_MINUTE))
    return page


# --------------------------------------------------------------------------
# HTML 組み立て
# --------------------------------------------------------------------------

def render_nav(pages: list[Page], current: str) -> str:
    groups: list[tuple[str, list[Page]]] = []
    for p in pages:
        if not groups or groups[-1][0] != p.group:
            groups.append((p.group, []))
        groups[-1][1].append(p)

    out: list[str] = []
    for group_name, members in groups:
        if group_name:
            out.append(f'<p class="nav-group">{html.escape(group_name)}</p>')
        out.append('<ul class="nav-list">')
        for p in members:
            active = " aria-current=\"page\"" if p.slug == current else ""
            cls = "nav-link is-active" if p.slug == current else "nav-link"
            n_works = sum(1 for w in WORKS if w.page == p.slug)
            badge = (
                f'<span class="nav-count" data-page="{p.slug}" data-total="{n_works}">'
                f"0/{n_works}</span>" if n_works else ""
            )
            dot = f'<span class="nav-dot nav-dot--{p.accent}" aria-hidden="true"></span>'
            out.append(
                f'<li><a class="{cls}" href="{p.slug}.html"{active}>'
                f'{dot}<span class="nav-label">{html.escape(p.nav_short)}</span>'
                f"{badge}</a>"
            )
            if p.slug == current and p.headings:
                out.append('<ul class="nav-sub">')
                for h in p.headings:
                    if h.level != 2:
                        continue
                    out.append(
                        f'<li><a class="nav-sublink" href="#{h.anchor}">'
                        f"{html.escape(h.text)}</a></li>"
                    )
                out.append("</ul>")
            out.append("</li>")
        out.append("</ul>")
    return "\n".join(out)


def render_toc(page: Page) -> str:
    if len(page.headings) < 2:
        return ""
    items = []
    for h in page.headings:
        items.append(
            f'<li class="toc-l{h.level}"><a href="#{h.anchor}">'
            f"{html.escape(h.text)}</a></li>"
        )
    # details にしておくと、狭い画面では JS で閉じて場所を取らないようにできる
    return f"""<details class="toc" id="toc" open>
  <summary class="toc-title">このページの内容</summary>
  <ul class="toc-list">{"".join(items)}</ul>
</details>"""


def render_pager(pages: list[Page], idx: int) -> str:
    prev_p = pages[idx - 1] if idx > 0 else None
    next_p = pages[idx + 1] if idx < len(pages) - 1 else None
    parts = ['<nav class="pager" aria-label="ページ送り">']
    if prev_p:
        parts.append(
            f'<a class="pager-link pager-prev" href="{prev_p.slug}.html">'
            f'<span class="pager-dir">前のページ</span>'
            f'<span class="pager-title">{html.escape(prev_p.nav_title)}</span></a>'
        )
    else:
        parts.append("<span></span>")
    if next_p:
        parts.append(
            f'<a class="pager-link pager-next" href="{next_p.slug}.html">'
            f'<span class="pager-dir">次のページ</span>'
            f'<span class="pager-title">{html.escape(next_p.nav_title)}</span></a>'
        )
    else:
        parts.append("<span></span>")
    parts.append("</nav>")
    return "".join(parts)


SHELL = """<!DOCTYPE html>
<html lang="ja" data-page="{slug}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta name="robots" content="noindex, nofollow">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<!-- 表示をブロックしないようにフォントは後から適用する。届かない環境では端末のゴシック体になる -->
<link rel="stylesheet" media="print" onload="this.media='all';this.onload=null"
      href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&amp;family=Zen+Kaku+Gothic+New:wght@400;500;700;900&amp;display=swap">
<noscript><link rel="stylesheet"
      href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&amp;family=Zen+Kaku+Gothic+New:wght@400;500;700;900&amp;display=swap"></noscript>
<link rel="stylesheet" href="assets/style.css">
<link rel="icon" href="data:image/svg+xml,{favicon}">
<script>
  (function () {{
    try {{
      var t = localStorage.getItem('mk-theme');
      if (t === 'dark' || t === 'light') document.documentElement.dataset.theme = t;
    }} catch (e) {{}}
  }})();
</script>
</head>
<body data-worktotal="{worktotal}" data-accent="{accent}">
<a class="skip" href="#main">本文へスキップ</a>
<div class="progress" id="progress" aria-hidden="true"><span id="progress-bar"></span></div>

<header class="topbar">
  <button class="icon-btn menu-btn" id="menu-btn" aria-label="メニューを開く" aria-expanded="false" aria-controls="sidebar">
    <span class="menu-icon" aria-hidden="true"></span>
  </button>
  <a class="brand" href="index.html">
    <span class="brand-mark" aria-hidden="true">未</span>
    <span class="brand-text">
      <span class="brand-title">未来国会2026</span>
      <span class="brand-sub">テキストブック</span>
    </span>
  </a>
  <div class="topbar-actions">
    <button class="search-btn" id="search-btn" aria-label="サイト内を検索">
      <span class="search-btn-icon" aria-hidden="true"></span>
      <span class="search-btn-label">検索</span>
      <kbd class="search-btn-kbd">/</kbd>
    </button>
    <button class="icon-btn" id="theme-btn" aria-label="ダークモードを切り替える">
      <span class="theme-icon" aria-hidden="true"></span>
    </button>
  </div>
</header>

<div class="shell">
  <div class="scrim" id="scrim" hidden></div>
  <aside class="sidebar" id="sidebar" aria-label="目次">
    <nav class="nav">{nav}</nav>
    <div class="sidebar-foot">
      <p class="progress-card">
        <span class="progress-card-label">ワーク進捗</span>
        <span class="progress-card-value"><span id="work-done">0</span> / <span id="work-total">0</span></span>
        <span class="progress-track"><span class="progress-fill" id="work-fill"></span></span>
      </p>
      <p class="sidebar-note">チェックはこの端末のブラウザにのみ保存されます。</p>
    </div>
  </aside>

  <main class="main" id="main">
    <article class="doc">
{dochead}
      {toc}
      <div class="doc-body">
{body}
      </div>
      {pager}
    </article>
    <footer class="foot">
      <p>Copyright © Dot-jp, Nonprofit Organization — All Rights Reserved.</p>
      <p class="foot-note">本サイトは NPO法人ドットジェイピー「未来国会2026 テキストブック」を、
      参加者が読みやすいように Web 版として再構成した非公式の内部資料です。
      正本は配布された PDF です。</p>
    </footer>
  </main>
</div>

<div class="search-modal" id="search-modal" hidden>
  <div class="search-panel" role="dialog" aria-modal="true" aria-label="サイト内検索">
    <div class="search-inputwrap">
      <input type="search" id="search-input" class="search-input" placeholder="キーワードを入力（例: ロジックツリー）"
             autocomplete="off" spellcheck="false">
      <button class="search-close" id="search-close" aria-label="検索を閉じる">esc</button>
    </div>
    <div class="search-results" id="search-results"></div>
  </div>
</div>

<button class="totop" id="totop" aria-label="ページ先頭へ戻る" hidden></button>
<script>window.MK_WORKS = {worksmap};</script>
<script src="assets/app.js" defer></script>
</body>
</html>
"""

FAVICON = (
    "%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20viewBox='0%200%2064%2064'%3E"
    "%3Crect%20width='64'%20height='64'%20rx='14'%20fill='%23E8622C'/%3E"
    "%3Ctext%20x='32'%20y='45'%20font-size='38'%20text-anchor='middle'%20"
    "fill='white'%20font-family='sans-serif'%3E%E6%9C%AA%3C/text%3E%3C/svg%3E"
)


def render_meta(page: Page) -> str:
    """読了時間・ワーク数などの小さな指標。"""
    bits = [f'<span class="meta-item"><b>約{page.minutes}</b>分</span>']
    works = [w for w in WORKS if w.page == page.slug]
    if works:
        main_n = sum(1 for w in works if w.kind == "main")
        bits.append(f'<span class="meta-item">ワーク <b>{len(works)}</b></span>')
        bits.append(f'<span class="meta-item meta-item--main">うち主要 <b>{main_n}</b></span>')
    return f'<p class="doc-meta">{"".join(bits)}</p>'


def render_dochead(page: Page) -> str:
    """ページ冒頭。章のページは「扉」として大きく見せる。"""
    lead = f'<p class="doc-lead">{inline(page.lead)}</p>' if page.lead else ""

    if page.chapter:
        return f"""      <header class="opener">
        <div class="opener-num" aria-hidden="true">{html.escape(page.chapter)}</div>
        <div class="opener-main">
          <p class="opener-kicker">第 {html.escape(page.chapter)} 章</p>
          <h1 class="opener-title">{inline(page.chapter_title)}</h1>
          <p class="opener-q">{inline(page.chapter_q)}</p>
          {lead}
          {render_meta(page)}
        </div>
      </header>"""

    if page.home:
        # トップページは hero ブロック自体が h1 を持つので、見出し帯は出さない
        return ""

    eyebrow = ""
    if page.group:
        eyebrow = f'<p class="doc-eyebrow">{html.escape(page.group)}</p>'
    meta = render_meta(page)
    return f"""      <header class="doc-head">
        {eyebrow}
        <h1 class="doc-title">{inline(page.title)}</h1>
        {lead}
        {meta}
      </header>"""


def build_page(page: Page, pages: list[Page], idx: int, worksmap: str) -> str:
    title = SITE_TITLE if page.slug == "index" else f"{page.title}｜{SITE_TITLE}"
    desc = page.lead or SITE_DESC
    return SHELL.format(
        slug=page.slug,
        accent=page.accent,
        worktotal=len(WORKS),
        worksmap=worksmap,
        title=html.escape(title, quote=True),
        desc=html.escape(re.sub(r"<[^>]+>", "", desc)[:160], quote=True),
        favicon=FAVICON,
        nav=render_nav(pages, page.slug),
        dochead=render_dochead(page),
        toc=render_toc(page),
        body=page.body,
        pager=render_pager(pages, idx),
    )


# --------------------------------------------------------------------------
# ワーク一覧の生成
# --------------------------------------------------------------------------

def render_chapters(pages: list[Page]) -> str:
    """トップページに置く4つの章のカード。"""
    cards = []
    for p in pages:
        if not p.chapter:
            continue
        works = [w for w in WORKS if w.page == p.slug]
        main_n = sum(1 for w in works if w.kind == "main")
        cards.append(f"""<a class="chcard chcard--{p.accent}" href="{p.slug}.html">
  <span class="chcard-num" aria-hidden="true">{html.escape(p.chapter)}</span>
  <span class="chcard-body">
    <span class="chcard-kicker">第 {html.escape(p.chapter)} 章</span>
    <span class="chcard-title">{inline(p.chapter_title)}</span>
    <span class="chcard-q">{inline(p.chapter_q)}</span>
    <span class="chcard-meta">約{p.minutes}分 ・ ワーク {len(works)}（主要 {main_n}）</span>
  </span>
</a>""")
    return f'<div class="chcards">{"".join(cards)}</div>'


def render_worklist() -> str:
    by_chapter: dict[str, list[Work]] = {}
    for w in WORKS:
        by_chapter.setdefault(w.page, []).append(w)

    out: list[str] = []
    for slug, label in CHAPTER_LABEL.items():
        items = by_chapter.get(slug, [])
        if not items:
            continue
        main_n = sum(1 for w in items if w.kind == "main")
        rows = []
        for w in items:
            badge = "主要" if w.kind == "main" else "補助"
            ps = '<span class="wl-ps" title="プランシートへ転記">PS</span>' if w.plansheet else ""
            rows.append(
                f'<li class="wl-item wl-item--{w.kind}">'
                f'<label class="work-check wl-check">'
                f'<input type="checkbox" class="work-toggle" data-work="{html.escape(w.wid, quote=True)}"'
                f' aria-label="ワーク{html.escape(w.wid, quote=True)}を完了にする">'
                f'<span class="work-check-box" aria-hidden="true"></span></label>'
                f'<span class="wl-badge wl-badge--{w.kind}">{badge}</span>'
                f'<span class="wl-id">{html.escape(w.wid)}</span>'
                f'<a class="wl-title" href="{w.page}.html#{w.anchor}">{inline(w.title)}</a>'
                f"{ps}</li>"
            )
        out.append(
            f'<section class="wl-chapter"><h2 class="h2" id="wl-{slug}">'
            f'<span class="h2-text">{html.escape(label)}</span></h2>'
            f'<p class="wl-meta">全 {len(items)} ワーク（うち主要ワーク {main_n}）</p>'
            f'<ul class="wl-list">{"".join(rows)}</ul></section>'
        )
    return "".join(out)


# --------------------------------------------------------------------------
# エントリポイント
# --------------------------------------------------------------------------

def main() -> None:
    pages = [load_page(cfg) for cfg in PAGES]

    # ワーク一覧を差し込む（全ページのパース後に確定するため）
    worklist_html = render_worklist()
    chapters_html = render_chapters(pages)
    injected = False
    for p in pages:
        if WORKLIST_TOKEN in p.body:
            p.body = p.body.replace(WORKLIST_TOKEN, worklist_html)
            injected = True
        p.body = p.body.replace(CHAPTERS_TOKEN, chapters_html)
    if not injected:
        raise SystemExit("エラー: :::worklist ブロックがどのページにも見つかりません")

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    shutil.copytree(ASSETS, DIST / "assets")
    (DIST / ".nojekyll").write_text("", encoding="utf-8")

    # ページ → そのページのワーク番号一覧（サイドバーの章別進捗に使う）
    works_by_page: dict[str, list[str]] = {}
    for w in WORKS:
        works_by_page.setdefault(w.page, []).append(w.wid)
    worksmap = json.dumps(works_by_page, ensure_ascii=False, separators=(",", ":"))

    for idx, page in enumerate(pages):
        (DIST / f"{page.slug}.html").write_text(
            build_page(page, pages, idx, worksmap), encoding="utf-8"
        )

    # 検索インデックス
    index = []
    for p in pages:
        for entry in p.search:
            index.append({
                "u": f"{p.slug}.html",
                "p": p.nav_title,
                "s": entry["s"],
                "a": entry["a"],
                "t": entry["t"],
            })
    (DIST / "search.json").write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    total_main = sum(1 for w in WORKS if w.kind == "main")
    print(f"✓ {len(pages)} ページ / ワーク {len(WORKS)} 件（主要 {total_main} 件）")
    print(f"✓ 検索インデックス {len(index)} セクション")
    print(f"✓ 出力先: {DIST}")


if __name__ == "__main__":
    main()
