#!/usr/bin/env python3
# ── v6 (2025-06-07)
import random   # 你之前已经 import 过，这里确保存在即可
import re, random, sys
from dataclasses import dataclass
from typing import List
from docx import Document
from rich.console import Console
from rich.prompt  import Prompt
import textwrap
DOCX_FILE    = "full_answer.docx"   # ← 只解析这一个文件
NUM_PRACTICE = 20                   # 模式1题量
MC_RATIO     = 0.6                  # 模式1选择题比例
LEAD_JUNK = re.compile(r"^[\s、，,．\.]+")

console = Console()

# ---------- 数据类 ----------
@dataclass
class Question:
    qid: str
    stem: str
    options: List[str]      # 选项行（可为空）
    answer: str             # 'A' / 'B'…
    qtype: str              # "mc" / "tf"

DEBUG      = False                 # True 时打印详细日志
Q_HEAD     = re.compile(r"^\s*(?:Q\s*)?(\d+)[\s\.\、\．\)\）]\s*(.*)", re.I)
OPT_PAT = re.compile(r"^\s*[A-E][\s\.\、]", re.I)
ANS_PAT = re.compile(
    r"(?:答案|参考答案|answer|key|correct\s*answer)"
    r"\s*[:：—\-]?\s*[\(（]?\s*([A-E]|正确|错误|对|错)\s*[\)）]?",
    re.I
)


TF_MAP = {"正确": "A", "对": "A", "ERROR": "B", "错误": "B", "错": "B",
          "TRUE": "A", "T": "A", "FALSE": "B", "F": "B"}

def tidy_tf(ans_raw: str) -> str:
    s = ans_raw.strip().upper()
    return TF_MAP.get(s, s[:1])  # 如果匹配不到取首字母

def parse_docx(path: str) -> list:
    """
    解析 full_answer.docx → List[Question]

    关键点：
      1. 题号行可能同时含题干 & “参考答案：…”
      2. 答案也可能与最后一个选项在同一行
      3. 判断题没有选项行，用 build() 里逻辑统一归一化 A/B
      4. 若仍找不到答案，则 DEBUG 打印 [MISS-ANS]
    """
    doc  = Document(path)
    qs   = []

    idx  = None                   # 当前题号
    stem = ""                     # 题干（累计多行）
    opts = []                     # 选项行
    ans  = ""                     # 正确答案（A/B/正确/错误）

    for para in doc.paragraphs:
        txt = para.text.strip()
        if not txt:
            continue

        # ---------- (1) 题号行 ----------
        m = Q_HEAD.match(txt)
        if m:
            # <- 保存上一题（若已找到答案）
            if idx and ans:
                qs.append(build(idx, stem, opts, ans))
            elif idx and DEBUG:
                print(f"[MISS-ANS] Q{idx} | stem='{stem[:40]}…'")

            # 解析新题
            idx  = m.group(1)
            rest = m.group(2)          # 题干 + 可能的 inline 答案
            opts, ans = [], ""

            # 如果这一行就带“参考答案”
            hit = ANS_PAT.search(rest)
            if hit:
                ans  = hit.group(1).strip()
                rest = ANS_PAT.sub("", rest).strip()   # 去掉答案字段
                rest = LEAD_JUNK.sub("", rest)     # ★ 新增

            stem = rest
            if DEBUG:
                tag = f" [inline-ANS={ans}]" if ans else ""
                print(f"\n[NEW]  Q{idx}  {stem[:50]}…{tag}")
            continue

        # ---------- (2) 答案行（单独成段或跟在选项后） ----------
        hit = ANS_PAT.search(txt)
        if hit:
            ans = hit.group(1).strip()
            if DEBUG:
                print(f"  [ANS]  {ans}  ← '{txt[:60]}…'")
            # 同一行如果还含选项文字，也当作选项保存
            if OPT_PAT.match(txt):
                opts.append(ANS_PAT.sub("", txt).strip())
            continue

        # ---------- (3) 选项行 ----------
        if OPT_PAT.match(txt):
            opts.append(txt)
            if DEBUG:
                print(f"  [OPT]  {txt[:60]}…")
            continue

        # ---------- (4) 单独的字母或“正确/错误”行作为答案 ----------
        if idx and not ans and re.fullmatch(r"(?:[A-D]|正确|错误|对|错)", txt, re.I):
            ans = txt
            if DEBUG:
                print(f"  [ANS-SINGLE]  {ans}")
            continue

        # ---------- (5) 题干续行 ----------
        stem += " " + txt
        if DEBUG:
            print(f"  [STEM+] {txt[:60]}…")

    # ---------- 收尾 ----------
    if idx and ans:
        qs.append(build(idx, stem, opts, ans))
    elif idx and DEBUG:
        print(f"[MISS-ANS] Q{idx} | stem='{stem[:40]}…'")

    return qs


def build(idx, stem, opts, ans_raw) -> Question:
    stem = LEAD_JUNK.sub("", stem.strip())   # ★ 新增
    qtype = "mc" if len(opts) > 2 else "tf"
    ans   = ans_raw.upper()
    if qtype == "tf":
        ans = tidy_tf(ans)
    return Question(idx, stem.strip(), opts[:], ans, qtype)

# ---------- 交互 ----------
def ask(q: Question, cur: int, tot: int) -> bool:
    """
    显示 1-n 纯文本选项；用户可输数字 1-5 或字母 A-E
    cur 当前题号（从 1 开始），tot 总题数
    """
    # 显示进度，而不是 Word 原来的题号
    console.rule(f"[bold cyan]Question {cur}/{tot}")

    # —— 题干换行输出 ——
    term_width = console.size.width or 80
    wrapped = textwrap.fill(q.stem, width=term_width)
    console.print(wrapped, style="bold")

    # ---------- 构造 (letter, clean_text) ----------
    if not q.options:                      # 判断题
        raw_opts = [("A", "正确"), ("B", "错误")]
    else:
        raw_opts = []
        for raw in q.options:
            m = re.match(r"\s*([A-E])[\s\.\、]\s*(.*)", raw, re.I)
            if m:
                raw_opts.append((m.group(1).upper(), m.group(2).strip()))
            else:                          # fallback：整行当正文
                raw_opts.append(("", raw.strip()))

    random.shuffle(raw_opts)               # 打乱顺序

    # ---------- 显示 & 建立映射 ----------
    num2letter, letter2num = {}, {}
    for idx, (letter, text) in enumerate(raw_opts, 1):
        console.print(f"  {idx}. {text}")  # 仅数字 + 文本
        if letter:
            num2letter[str(idx)] = letter
            letter2num[letter] = str(idx)

    # ---------- 收答 ----------
    inp = Prompt.ask("[yellow]Your answer").strip().upper()
    user_letter = num2letter.get(inp, inp)    # 数字→字母；字母留字母
    correct     = (user_letter == q.answer)

    # ---------- 反馈 ----------
    if correct:
        console.print("✅  Correct!", style="bold green")
    else:
        # 找到正确数字编号 + 文本
        right_num  = letter2num.get(q.answer, "?")
        right_text = next((t for l, t in raw_opts if l == q.answer), "")
        console.print(
            f"❌  Wrong!  Correct: {right_num}. {right_text}",
            style="bold red"
        )
    return correct



def run_quiz(pool: List[Question]):
    score = 0
    total = len(pool)
    for idx, q in enumerate(pool, 1):          # 从 1 开始计数
        if ask(q, idx, total):                 # 把 idx,total 传进去
            score += 1
    console.print(f"\n[bold magenta]Finished![/]  "
                  f"Score: {score}/{total}  "
                  f"Accuracy: {score/total:.1%}")
    


def mode_one(bank: List[Question]):
    mc_need = round(NUM_PRACTICE * MC_RATIO)
    tf_need = NUM_PRACTICE - mc_need
    mc_pool = [q for q in bank if q.qtype == "mc"]
    tf_pool = [q for q in bank if q.qtype == "tf"]
    # 防止题量不足
    mc_need = min(mc_need, len(mc_pool))
    tf_need = min(tf_need, len(tf_pool))
    selected = random.sample(mc_pool, mc_need) + random.sample(tf_pool, tf_need)
    random.shuffle(selected)
    run_quiz(selected)

def mode_two(bank: List[Question]):
    random.shuffle(bank)
    run_quiz(bank)

# ---------- 主函数 ----------
def main():
    bank = parse_docx(DOCX_FILE)
    console.print(f"[bold green]题库已加载：{len(bank)} 题[/]")
    while True:
        mode = Prompt.ask("\n选择模式 1) 随机20题  2) 全部练习  q) 退出")
        if mode == "1":
            mode_one(bank)
        elif mode == "2":
            mode_two(bank)
        elif mode.lower() == "q":
            break
        else:
            console.print("[red]无效输入，请重新选择。[/]")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[cyan]Bye![/]")
        sys.exit()
