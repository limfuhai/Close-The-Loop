# Close the Loop

[English](README.md)

**无需人类看管、能够持续工作的 AI 智能体：因为它们会对照现实核查自己的记忆。**

Close the Loop 是漩涡环流（Xuanwo Huanliu）推出的开源智能体系统。它的智能体可以自行设定唤醒时间，以书面形式记录自己认为尚待完成的事项及其依据，并由一个独立的智能体在采取行动之前，对照真实世界核查这些判断。一切都在您自己的电脑上运行，使用您自己的模型密钥和邮箱。

---

## 问题所在

当今的智能体仍然需要人类来把关。智能体长时间独立工作时，它给自己留下的笔记会逐渐偏离现实。这一“智能体退化”问题早已广为人知，人们普遍认为，当今的智能体需要更好的记忆机制。

Close the Loop 的出发点是：智能体退化并不是一个记忆问题。智能体之所以退化，并非因为记忆不完美，而是因为即便记忆完美，也无法完美应对一个不断变化的外部世界。智能体真正缺少的是核查：什么是真实的、什么不是，情境是否已经改变，计划又有哪些变化，等等。

## 我们的思路

Close the Loop 为普通的本地智能体新增了三项能力：

1. 调度智能体（Scheduler）为自己设定唤醒时间，到点后 Windows 会带着它留给自己的消息将其唤醒，即使应用已经关闭也是如此。这使得智能体之间能够全天候持续检查邮箱动态。您可以借助调度智能体，让其他智能体在一个工作日内定期查看您的邮箱。
2. 账本智能体（Ledger）以类似日记的形式记录每一条证据。它还会记录审计智能体的核查结论，从而清除账本中此前可能存在的错误判断或记录。
3. 审计智能体（Auditor）在任何行动执行之前启动。它对照智能体自身笔记之外的记录（您的已发送邮件、收件箱和文件）核查每一条记录，并给出以下结论之一：已确认、已过时、相矛盾或无法核实。

## 工作原理

任何涉及您电脑的操作都通过**桥接程序（bridge）**进行。这是一个无任何依赖的小型 Python 脚本，在终端中运行即可。邮件直接通过 IMAP 和 SMTP 从您的电脑收发，因此任何支持应用专用密码的邮箱服务都可以使用。

Close the Loop 保存的所有内容都位于您主目录下的一个文件夹中：

| 路径 | 内容 |
|---|---|
| `~/Boundary/ledger/` | 带日期、只追加的指令与审计结论文件，以及当前索引 `LIVE.md` |
| `~/Boundary/wake/` | 待执行的唤醒任务，以及任务计划程序调用的运行脚本 |
| `~/Boundary/chats/messages.jsonl` | 已保存的对话回复，包括定时唤醒产生的回复 |

## 快速开始

### 环境要求

- Windows 10 或 11（调度功能使用 Windows 任务计划程序）
- Python 3.10 或更高版本
- Node.js 18 或更高版本
- DeepSeek 或 Moonshot（Kimi）的 API 密钥，或两者兼有
- 一个拥有应用专用密码或授权码的邮箱账户（Gmail、QQ 邮箱、163 邮箱等）

### 1. 获取代码

```
git clone https://github.com/limfuhai/close-the-loop.git
cd close-the-loop
pip install -r requirements.txt
npm install
```

### 2. 填写模型密钥

打开 `core/api_client.py`，在文件顶部的 `deepseek_api_key` 和 `moonshot_api_key` 中填入您的密钥。可以只填其中一个，也可以都填：没有密钥的模型会被自动跳过。

### 3. 创建配置文件

将 `.env.example` 复制为 `.env`，将 `.env.local.example` 复制为 `.env.local`，然后填写 `.env`：

- `BRIDGE_TOKEN`：任意一串足够长的随机字符串，是您的服务器与桥接程序之间共享的密钥。可以用以下命令生成：
  ```
  python -c "import secrets;print(secrets.token_urlsafe(32))"
  ```
- `MAIL_ADDRESS` 和 `MAIL_AUTH_CODE`：智能体使用的邮箱账户。邮箱服务商不允许应用使用您的普通密码登录，因此请使用应用专用密码：
  - **Gmail：** 开启两步验证，然后在 Google 账号 → 安全性 → 应用专用密码中创建。
  - **QQ 邮箱：** 在 QQ 邮箱设置中开启 IMAP/SMTP 服务，并生成授权码。

邮箱服务商会根据邮箱地址自动识别。如果使用自建邮件服务器，还需要设置 `MAIL_IMAP_HOST`、`MAIL_IMAP_PORT`、`MAIL_SMTP_HOST` 和 `MAIL_SMTP_PORT`。

### 4. 启动

在第一个终端中运行：
```
python core/compiler.py
```
在第二个终端中运行：
```
npm run dev
```
然后打开 http://localhost:3000。

### 5. 连接桥接程序

点击 **Download Bridge**。在第三个终端中进入文件保存的位置，运行：
```
python bridge.py
```
使用 Close the Loop 期间请保持该窗口开启。

### 6. 试一试

创建一个智能体，然后对它说：

> In 3 minutes, send an email to *your own address* with the subject "Scheduler test", saying hello from your scheduled future self. For now, just set the wake-up and nothing else.

（意为：3 分钟后，给*您自己的邮箱地址*发一封主题为“Scheduler test”的邮件，内容是来自定时唤醒的未来的你的问候。现在只设置唤醒，其他什么都不要做。）

三分钟后，Windows 会唤醒这个智能体，它仅凭过去的自己留下的消息完成发送。

接着试一试植入错误的测试：告诉账本智能体一封您确实发过的邮件和一封您从未发过的邮件，然后让审计智能体对照您的已发送邮件核查两者。您会在 `~/Boundary/ledger/` 中看到那条错误的记录被关闭。

## 局限

- 这是一个早期研究版本，用于验证其能力的测试非常有限。
- 调度功能目前仅支持 Windows。
- 桥接程序会在您的电脑上执行本地智能体发送给它的命令。请只在您信任的电脑上运行，并确保 `BRIDGE_TOKEN` 不为他人所知。
- 目前尚不能读取日历，因此审计智能体只能通过邮件往来核查会议安排。
- 已知问题：系统有时会错误地调用 DocsExecutor（一个生成 Word 文档的智能体），而不是审计智能体。如果智能体卡在这一步，请要求它们重试并调用审计智能体，通常重试一次即可解决。

## 参与贡献

欢迎提交 Issue 和 Pull Request。如果 Close the Loop 在您的电脑或邮箱上出了问题，这正是我们最想听到的反馈。

## 付费版本

**不想自己部署？** Close the Loop 也提供托管版本 Boundary：https://boundary.xuanwo.ai 。无需配置、无需模型密钥，也无需自行运行服务器（付费订阅）。您仍需在自己的电脑上运行小型桥接程序。请注意，用户可以免费注册，但免费用户的额度为零。请选择付费方案注册，以获得额度并使用应用。

## 许可证

Apache License 2.0。详见 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。
