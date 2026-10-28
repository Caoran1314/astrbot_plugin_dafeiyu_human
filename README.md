<p align="center">
  <img src="https://img.shields.io/badge/AstrBot-%3E%3D4.24.0-blue" alt="AstrBot">
  <img src="https://img.shields.io/badge/version-v0.1.0-green" alt="version">
  <img src="https://img.shields.io/badge/license-MIT-brightgreen" alt="license">
  <img src="https://img.shields.io/badge/platform-aiocqhttp%20%7C%20webchat-purple" alt="platform">
</p>

# 大肥鱼拟人管线

让机器人像人在 QQ 上打字：会停顿、会分条、会打错字、不说 AI 腔

> 当前版本：**v0.1.0** · 许可证：**[MIT](LICENSE)** · 作者：**[Caoran1314](https://github.com/Caoran1314)**

---

## 为什么需要它

大模型默认的输出是"书面语 + 分点 + 句号"的客服腔。一句话就能看出是机器：

```text
❌ 未装本插件
你好呀！很高兴见到你～有什么我可以帮你的吗？
如果你需要的话，我可以：1. 陪你聊天 2. 帮你查资料 3. ...
```

```text
✅ 装上本插件
在的
怎么啦
```

差别不在内容，在**节奏和标点**。真人聊天是一句一条、几乎不用句号、更不会列 1.2.3.。

## 它做了四件事

```mermaid
flowchart LR
    A[LLM 原始回复] --> B[去 AI 腔]
    B --> C[删标点/去 markdown]
    C --> D[按语义切成多条]
    D --> E[注入延迟 + 打错字]
    E --> F[逐条发送]
```

| 步骤 | 做什么 | 举例 |
|---|---|---|
| **去 AI 腔** | 删掉"有什么可以帮你的""作为一个 AI"等整句 | 30+ 条内置黑名单，可自己加 |
| **删标点** | 去掉句号、冒号、破折号、markdown 标记 | `**重点**` → `重点` |
| **语义切分** | 按 `，。！？` 切成 1~3 条，每条 ≤30 字 | 长回复自动变多条 |
| **拟真细节** | 延迟 0.6~4 秒、1% 错字（短句不打） | 模拟真实打字速度 |

## 安装

### 方式一：插件市场（推荐）

面板 → 插件 → 插件市场 → 切到「大肥鱼插件集」→ 找到本插件 → 安装。

### 方式二：手动

```bash
cd AstrBot/data/plugins
git clone https://github.com/Caoran1314/astrbot_plugin_dafeiyu_human.git
```

然后重启 AstrBot，或在面板里点「重载」。

> 本插件**无第三方依赖**，纯标准库实现，不会影响 AstrBot 启动速度。

## 配置

装好后在 **面板 → 插件 → 大肥鱼拟人管线 → 配置** 里调。全部配置项：

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `delay_enable` | bool | `true` | 像人一样过一会儿才回，而不是秒回 |
| `delay_private_enable` | bool | `true` | 私聊启用延迟 |
| `delay_group_enable` | bool | `false` | 群聊里延迟会显得更自然，但可能错过话题 |
| `delay_short_probability` | float | `0.45` | 0~1，命中后等 0.6~4 秒，模拟打字和放下手头的事 |
| `delay_long_probability` | float | `0.0` | 0~1，命中后等 20~90 秒，模拟她在忙。0 表示关闭 |
| `delay_cooldown_seconds` | int | `20` | 刚回过话的这段时间内不再叠加延迟 |
| `polish_enable` | bool | `true` | 启用文本规整 |
| `drop_slop` | bool | `true` | 命中「综上所述」「有什么可以帮你」这类整句删除 |
| `spokenize` | bool | `true` | 非常→挺、因此→所以 等 |
| `strip_markdown` | bool | `true` | 去掉 markdown 痕迹 |
| `ban_colon` | bool | `true` | AI 中文最爱用冒号，真人在 QQ 上基本不写 |
| `ban_dash` | bool | `true` | 禁用破折号 |
| `ban_quotes` | bool | `true` | 去掉双引号 |
| `strip_trailing_period` | bool | `true` | 去掉句末句号 |
| `max_chars_per_line` | int | `30` | 超过就拆成下一条，建议 20~30 |
| `max_lines` | int | `6` | 超出的直接截断，防止刷屏 |
| `typo_rate` | float | `0.01` | 0~0.05，1% 已经很自然；短回复不会打错字 |
| `enforce_one_sentence_per_line` | bool | `true` | 配合平台的分段回复，才能逐条发出去 |
| `extra_banned_phrases` | list | `[]` | 命中就整句丢弃，一行一个 |
| `typo_min_chars` | int | `6` | 默认 6：只回「在」「嗯」这种绝不会打错，否则整句就变意思了 |

### 常用调法

- **觉得回复太慢** → 关掉 `delay_enable`，或把 `delay_max` 调到 2.0
- **觉得错字太多** → `typo_rate` 调成 0.005，或 `typo_min_chars` 调大
- **还是像 AI** → 往 `banned_phrases` 里加你讨厌的句子（一行一条）
- **想让回复更长** → `max_chars` 调到 50，但注意别超过 80

## 常见问题

**Q：会不会把正常的标点也删掉？**
A：会。这是设计选择——中文聊天里几乎不用句号。如果你想要句号，把 `strip_periods` 关掉。

**Q：错字会不会打错人名、数字、URL？**
A：不会。URL、行内代码、数字会被保护起来不参与改字；错字只作用于汉字，且短句（默认 <6 字）直接跳过。

**Q：会不会影响别的插件？**
A：只在 `on_llm_response` / `on_decorating_result` 钩子上改**出站文本**，不改任何全局状态。

**Q：和表情包插件冲突吗？**
A：不冲突。表情包的 `&&分类&&` 标记如果在出站前没被消耗掉，本插件会顺带清理。

## 兼容性

- AstrBot `>= 4.24.0`
- 平台：`aiocqhttp`（QQ）、`webchat`
- 不修改框架代码，不使用私有 API

## License

[MIT](LICENSE)
