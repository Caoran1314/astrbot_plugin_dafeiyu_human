"""大肥鱼拟人出站管线（dafeiyu_human）。

三件事，按执行顺序：
1. on_llm_request   —— 拟人延迟：像人一样"过一会儿才回"，而不是秒回。
2. on_llm_response  —— 文本规整：去 AI 腔、禁标点、书面词换口语、注入错字。
3. on_decorating_result —— 最终兜底：保证一句一行，交给平台的 segmented_reply 逐条发。

设计约束：
- 任何异常都吞掉并回退原文本，绝不让机器人因为本插件报错而不说话。
- 延迟是可控的：默认只做 0.5~4s 的短延迟，长延迟需要显式开启。
"""
from __future__ import annotations

import asyncio
import random
import time

from astrbot import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig

from .text import polish

PLUGIN_NAME = "dafeiyu_human"


class DafeiyuHuman(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.cfg: dict = dict(config or {})
        self.rng = random.Random()
        self._last_request_at: dict[str, float] = {}
        logger.info(f"[{PLUGIN_NAME}] 已加载，配置项 {len(self.cfg)} 个")

    # ------------------------------------------------------------ 工具

    def _c(self, key: str, default):
        v = self.cfg.get(key, default)
        return default if v is None else v

    def _is_admin_cmd(self, event: AstrMessageEvent) -> bool:
        text = (getattr(event, "message_str", "") or "").lstrip()
        return text.startswith(("/", "!", "#"))

    def _scope_ok(self, event: AstrMessageEvent) -> bool:
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        is_group = "GroupMessage" in umo
        if is_group:
            return bool(self._c("delay_group_enable", False))
        return bool(self._c("delay_private_enable", True))

    # ------------------------------------------------------------ 1. 拟人延迟

    @filter.on_llm_request(priority=90000)
    async def human_delay(self, event: AstrMessageEvent, req) -> None:
        try:
            if not self._c("delay_enable", True):
                return
            if self._is_admin_cmd(event) or not self._scope_ok(event):
                return
            # 工具调用会触发多轮 LLM 请求；延迟只能加一次，否则一句话要等好几遍
            try:
                if getattr(event, "_dafeiyu_delayed", False):
                    return
                event._dafeiyu_delayed = True
            except Exception:
                pass
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            now = time.monotonic()
            # 同会话 20 秒内连续追问不叠加延迟，避免越聊越慢
            last = self._last_request_at.get(umo, 0.0)
            self._last_request_at[umo] = now
            if now - last < float(self._c("delay_cooldown_seconds", 20)):
                return

            p_short = float(self._c("delay_short_probability", 0.45))
            p_long = float(self._c("delay_long_probability", 0.0))
            roll = self.rng.random()
            if roll < p_long:
                lo = float(self._c("delay_long_min_seconds", 20))
                hi = float(self._c("delay_long_max_seconds", 90))
                wait = self.rng.uniform(lo, max(lo, hi))
                kind = "long"
            elif roll < p_long + p_short:
                lo = float(self._c("delay_short_min_seconds", 0.6))
                hi = float(self._c("delay_short_max_seconds", 4.0))
                wait = self.rng.uniform(lo, max(lo, hi))
                kind = "short"
            else:
                return
            logger.info(f"[{PLUGIN_NAME}] {kind} 延迟 {wait:.1f}s")
            await asyncio.sleep(wait)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # 延迟失败不影响回复
            logger.warning(f"[{PLUGIN_NAME}] 延迟异常已忽略: {e!r}")

    # ------------------------------------------------------------ 2. 文本规整

    @filter.on_llm_response(priority=95000)
    async def human_polish(self, event: AstrMessageEvent, resp) -> None:
        try:
            if not self._c("polish_enable", True):
                return
            text = getattr(resp, "completion_text", None)
            if not isinstance(text, str) or not text.strip():
                return
            out, meta = polish(text, self._cfg_for_text(), self.rng)
            if meta.get("fallback"):
                logger.info(f"[{PLUGIN_NAME}] 规整跳过（回退原文）")
                return
            try:
                resp.completion_text = out
            except Exception:
                return
            logger.info(
                f"[{PLUGIN_NAME}] 规整 {len(text)}→{len(out)} 字，"
                f"条数 {meta.get('lines')}，错字 {meta.get('typos')}，"
                f"去AI腔 {len(meta.get('slop_hits') or [])}")
            if meta.get("slop_hits"):
                logger.info(f"[{PLUGIN_NAME}] 去掉 AI 腔: {meta['slop_hits'][:3]}")
        except Exception as e:
            logger.warning(f"[{PLUGIN_NAME}] 规整异常已忽略: {e!r}")

    def _cfg_for_text(self) -> dict:
        keys = (
            "max_chars_per_line", "typo_rate", "typo_min_chars", "drop_slop",
            "spokenize", "strip_markdown", "ban_colon", "ban_dash", "ban_quotes",
            "strip_trailing_period", "max_lines",
        )
        out = {k: self.cfg[k] for k in keys if k in self.cfg}
        extra = self.cfg.get("extra_banned_phrases")
        if isinstance(extra, list):
            out["extra_banned"] = [str(x) for x in extra if str(x).strip()]
        return out

    # ------------------------------------------------------------ 3. 最终兜底

    @filter.on_decorating_result(priority=90000)
    async def human_final_split(self, event: AstrMessageEvent) -> None:
        """保证纯文本部分做到「一句一行」，让平台的分段回复逐条发出。"""
        try:
            if not self._c("enforce_one_sentence_per_line", True):
                return
            result = event.get_result()
            if not result or not getattr(result, "chain", None):
                return
            max_chars = int(self._c("max_chars_per_line", 30))
            max_lines = int(self._c("max_lines", 6))
            changed = False
            new_chain = []
            for comp in result.chain:
                if isinstance(comp, Plain) and isinstance(getattr(comp, "text", None), str):
                    original = comp.text
                    lines = []
                    for line in original.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        while len(line) > max_chars:
                            lines.append(line[:max_chars])
                            line = line[max_chars:]
                        if line:
                            lines.append(line)
                    if max_lines and len(lines) > max_lines:
                        lines = lines[:max_lines]
                    text = "\n".join(lines)
                    if text and text != original:
                        comp.text = text
                        changed = True
                    if not text:
                        changed = True
                        continue
                new_chain.append(comp)
            if changed:
                result.chain = new_chain
        except Exception as e:
            logger.warning(f"[{PLUGIN_NAME}] 分条异常已忽略: {e!r}")

    # ------------------------------------------------------------ 生命周期

    async def terminate(self) -> None:
        logger.info(f"[{PLUGIN_NAME}] 已卸载")
