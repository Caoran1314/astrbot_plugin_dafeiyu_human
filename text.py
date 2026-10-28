"""文本后处理纯函数层：不依赖 AstrBot，可单独单测。

设计原则：
1. 任何一步失败都要能回退到原文本（宁可像 AI，也不能发空）。
2. 所有随机行为都接受外部 rng，便于复现与测试。
"""
from __future__ import annotations

import random
import re

# ---------------------------------------------------------------- AI 腔黑名单
# 来自 stop-slop-zh / 大肥鱼人格卡 / 实际翻车记录
BANNED_PHRASES = [
    # 结构腔
    "首先", "其次", "最后", "综上所述", "总而言之", "总的来说", "值得注意的是",
    "需要注意的是", "由此可见", "换句话说", "不难发现", "事实上",
    # 客服腔
    "有什么可以帮你", "有什么可以帮您", "希望对你有帮助", "希望对你有所帮助",
    "随时找我", "随时联系我", "还有别的需要吗", "如果还有其他问题",
    "作为一个AI", "作为一个 AI", "作为语言模型", "我无法",
    # 强行共情 / 总结升华
    "这是个好问题", "我理解你的感受", "我能理解你的感受", "让我来帮你",
    "大家觉得呢", "你觉得呢", "祝您", "祝你一切",
    # 营销腔
    "保证解压", "一绝", "真管用", "包你满意", "强烈推荐", "绝对有效", "强烈安利",
]
# 「不是……而是……」这类对仗句式单独用正则
BANNED_PATTERNS = [
    re.compile(r"不是[^，。！？\n]{0,12}而是[^，。！？\n]{0,20}"),
    re.compile(r"不仅[^，。！？\n]{0,12}而且[^，。！？\n]{0,20}"),
    re.compile(r"让我们一起[^。！？\n]{0,20}"),
    # 客服腔：中间常夹「这个回答/这些内容」，所以不能只靠字符串精确匹配
    re.compile(r"希望[^，。！？\n]{0,12}对你有(?:所)?帮助"),
    re.compile(r"这(?:个|是)好问题"),
    re.compile(r"如果(?:你)?还有(?:其他|别的)?问题"),
    re.compile(r"随时(?:可以)?(?:找我|联系我)"),
    re.compile(r"还有(?:别的|其他)(?:需要|问题)吗"),
]

# 书面 -> 口语（只做安全的整词替换）
SPOKEN_REPLACE = {
    "非常": "挺",
    "十分": "挺",
    "确实": "真的",
    "因此": "所以",
    "但是": "不过",
    "然而": "不过",
    "此外": "还有",
    "同时": "然后",
    "立刻": "马上",
    "目前": "现在",
    "或许": "可能",
    "是否": "是不是",
    "已经": "都",
    "无法": "没法",
    "如果": "要是",
}

# 同音/形近错字：值是被打进文本的错字
HOMOPHONES = {
    "的": ["得", "地"],
    "在": ["再"],
    "再": ["在"],
    "做": ["作"],
    "哪": ["那"],
    "那": ["哪"],
    "已经": ["以经"],
    "觉得": ["决得"],
    "因为": ["因位"],
    "知道": ["之道"],
    "时候": ["时后"],
    "什么": ["甚么"],
    "真的": ["真得"],
    "没事": ["没是"],
}

# 句末不该出现的标点（大肥鱼人格：不用句号）
TRAILING_PUNCT = "。；;"

_URL_RE = re.compile(r"https?://\S+")
_CODE_RE = re.compile(r"`[^`]*`")
_DIGIT_RE = re.compile(r"\d")

# 表情包/媒体标记：meme_manager 用 &&分类&&，框架偶尔用 [图片] 之类。
# 正常情况下插件会消耗掉，一旦没消耗就会变成用户可见的乱码，
# 所以出站前兜底清一遍。
_MARKER_RE = [
    # 「&&confused&&」，以及被平台插空格后的「& &confused& &」
    re.compile(r"(?:&+\s*){2,}[A-Za-z_\u4e00-\u9fff]{1,20}(?:\s*&+){2,}"),
    re.compile(r"&{1,2}\s*[A-Za-z_\u4e00-\u9fff]{1,20}\s*&{1,2}"),
    # 收尾：孤立的 && / & & 直接清掉（中文聊天里不会正常出现）
    re.compile(r"(?:&+\s*){2,}"),
    re.compile(r"\[(?:图片|表情|语音|视频|文件|Image|Record|Video|File)[^\]]{0,20}\]"),
    re.compile(r"<\|?[^>|]{1,30}\|?>"),      # 残留的内部标签
]


def _protect(text: str):
    """把 URL / 行内代码替换成占位符，避免被改写。"""
    slots: list[str] = []

    def _take(m):
        slots.append(m.group(0))
        return f"\x00{len(slots) - 1}\x00"

    protected = _URL_RE.sub(_take, text)
    protected = _CODE_RE.sub(_take, protected)
    return protected, slots


def _restore(text: str, slots: list[str]) -> str:
    for i, s in enumerate(slots):
        text = text.replace(f"\x00{i}\x00", s)
    return text


# ---------------------------------------------------------------- 单步处理

def strip_markdown(text: str) -> str:
    """去掉 markdown 痕迹：标题、加粗、列表符号、引用块。"""
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)          # 标题
        line = re.sub(r"^\s{0,3}>\s?", "", line)                 # 引用
        line = re.sub(r"^\s{0,3}[-*+]\s+", "", line)             # 无序列表
        line = re.sub(r"^\s{0,3}\d+[.、)]\s+", "", line)         # 有序列表
        line = line.replace("**", "").replace("__", "").replace("~~", "")
        out.append(line.rstrip())
    return "\n".join(out)


def ban_punctuation(text: str, cfg=None) -> str:
    """按人格设定清掉「AI 中文最爱」的标点：冒号、破折号、双引号、句末句号。"""
    cfg = cfg or {}
    s = text

    if cfg.get("ban_colon", True):
        s = re.sub(r"\s*[：]\s*", "，", s)
    if cfg.get("ban_dash", True):
        s = re.sub(r"\s*(?:——|—|--)+\s*", "，", s)
    if cfg.get("ban_quotes", True):
        s = re.sub(r"[“\"「『]([^”\"」』\n]{0,60})[”\"」』]", r"\1", s)
    if cfg.get("strip_trailing_period", True):
        lines = []
        for line in s.splitlines():
            line = line.rstrip()
            while line and line[-1] in TRAILING_PUNCT:
                line = line[:-1]
            lines.append(line)
        s = "\n".join(lines)

    # 收尾清理：避免出现「，，」「，。」这类
    s = re.sub(r"[，,]{2,}", "，", s)
    s = re.sub(r"^[，,]+", "", s)
    s = re.sub(r"([，,])\s*$", "", s)
    return s.strip()


def strip_markers(text: str) -> tuple[str, int]:
    """清掉泄漏的表情包/媒体/内部标签。返回 (文本, 清掉几处)。"""
    n = 0
    out = text
    for pat in _MARKER_RE:
        out, k = pat.subn("", out)
        n += k
    if n:
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r"\n{2,}", "\n", out).strip()
    return out, n


def drop_slop(text: str, extra: list[str] | None = None) -> tuple[str, list[str]]:
    """按行丢弃 AI 腔句子。整段被删空时返回原文（安全回退）。"""
    words = list(BANNED_PHRASES) + list(extra or [])
    hits: list[str] = []
    kept: list[str] = []
    for line in text.splitlines():
        raw = line
        bad = next((w for w in words if w and w in line), None)
        if bad:
            hits.append(bad)
            continue
        matched = None
        for pat in BANNED_PATTERNS:
            m = pat.search(line)
            if m:
                matched = m.group(0)
                line = pat.sub("", line).strip()
                break
        if matched:
            hits.append(matched)
            if not line:
                continue
        kept.append(line if line else raw)
    result = "\n".join(kept).strip()
    if not result:
        return text, []          # 全删空 -> 不改，避免发出空消息
    return result, hits


def spokenize(text: str) -> str:
    """书面词换口语。只替换独立出现、不挨着数字的词。"""
    s, slots = _protect(text)
    for formal, casual in SPOKEN_REPLACE.items():
        s = s.replace(formal, casual)
    return _restore(s, slots)


def split_lines(text: str, max_chars: int = 30) -> list[str]:
    """切成「一句一条」的行：先按换行，再按标点，最后硬切。"""
    lines: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        while len(line) > max_chars:
            cut = -1
            for i, ch in enumerate(line):
                if i >= 3 and ch in "，。！？~…、 ":
                    cut = i + 1
                    if i + 1 >= max_chars:
                        break
            if cut <= 0:
                cut = max_chars
            head = line[:cut].rstrip("，。！？~…、 ")
            if head:
                lines.append(head)
            line = line[cut:].strip("，。！？~…、 ")
        if line:
            lines.append(line)
    return lines


def apply_typos(text: str, rate: float = 0.0, rng: random.Random | None = None,
                min_chars: int = 6) -> tuple[str, int]:
    """按概率注入同音错字。返回 (新文本, 注入处数)。

    min_chars：太短的回复（比如只回一个「在」）绝不打错字——
    错一个字整句意思就变了，真人也不会在单字回复上打错。
    """
    if rate <= 0 or not text:
        return text, 0
    if len(text.strip()) < max(0, int(min_chars)):
        return text, 0
    rng = rng or random.Random()
    s, slots = _protect(text)
    out = list(s)
    n = 0
    i = 0
    while i < len(out):
        for wrong_word, variants in HOMOPHONES.items():
            L = len(wrong_word)
            if "".join(out[i:i + L]) != wrong_word:
                continue
            # 不碰数字、英文、占位符
            if _DIGIT_RE.search(wrong_word):
                continue
            if rng.random() >= rate:
                continue
            repl = rng.choice(variants)
            out[i:i + L] = list(repl)
            n += 1
            i += len(repl)
            break
        else:
            i += 1
    return _restore("".join(out), slots), n


# ---------------------------------------------------------------- 主入口

DEFAULT_CFG = {
    "max_chars_per_line": 30,
    "typo_rate": 0.02,
    "drop_slop": True,
    "spokenize": True,
    "strip_markdown": True,
    "ban_colon": True,
    "ban_dash": True,
    "ban_quotes": True,
    "strip_trailing_period": True,
    "max_lines": 6,
}


def polish(text: str, cfg: dict | None = None, rng: random.Random | None = None) -> tuple[str, dict]:
    """完整管线：返回 (最终文本, 元信息)。元信息给 eval 用。"""
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    meta = {"orig_len": len(text or ""), "lines": 0, "typos": 0, "slop_hits": [],
            "fallback": False}
    if not text or not text.strip():
        meta["fallback"] = True
        return text, meta

    try:
        s, removed = strip_markers(text)
        meta["markers"] = removed
        if not s.strip():
            meta["fallback"] = True
            return text, meta
        if cfg["strip_markdown"]:
            s = strip_markdown(s)
        if cfg["drop_slop"]:
            s, hits = drop_slop(s, cfg.get("extra_banned"))
            meta["slop_hits"] = hits
        if cfg["spokenize"]:
            s = spokenize(s)
        s = ban_punctuation(s, cfg)
        s = re.sub(r"\n{2,}", "\n", s).strip()

        if not s:
            meta["fallback"] = True
            return text, meta

        lines = split_lines(s, int(cfg["max_chars_per_line"]))
        max_lines = int(cfg.get("max_lines") or 0)
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]

        out = "\n".join(lines)
        out, n = apply_typos(out, float(cfg["typo_rate"]), rng,
                             int(cfg.get("typo_min_chars", 6)))
        meta["typos"] = n
        meta["lines"] = len(lines)
        if not out.strip():
            meta["fallback"] = True
            return text, meta
        return out, meta
    except Exception:
        meta["fallback"] = True
        return text, meta
