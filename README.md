# supersys

[![release](https://img.shields.io/github/v/release/wzqfwanj/supersys)](https://github.com/wzqfwanj/supersys/releases/latest)
[![release workflow](https://github.com/wzqfwanj/supersys/actions/workflows/release.yml/badge.svg)](https://github.com/wzqfwanj/supersys/actions/workflows/release.yml)

> 极简的个人每日系统：把在意的事拆成「状态」和「规划」，「规划」里定条件，「状态」里勾选做到的事，每天点一次「执行」，让智能体检查今天有没有做到。

## 界面预览

| 状态 · 饮食勾选 | 规划 · 条件定义 |
| --- | --- |
| ![状态](docs/status.png) | ![规划](docs/plan.png) |

| 智能体 + 每日统计 | 执行结果 |
| --- | --- |
| ![智能体](docs/agent.png) | ![执行结果](docs/check.png) |

手机上也做了适配，可以「添加到主屏幕」当 App 用：

| 手机 · 状态 | 手机 · 智能体 |
| --- | --- |
| ![手机状态](docs/mobile-status.png) | ![手机智能体](docs/mobile-agent.png) |

## 功能

界面是深色的，只有一个窗口、几行文字和一张图，没有多余的东西；数据全部存在本地。

**状态 / 规划**，都分成「基础」和「常态」两部分：

- 基础：身高、体重
- 常态：资金、收入、饮食、运动、今日

「规划」里定义每项的约束条件（每一行一个条件），「状态」里勾选自己实际做到的，两边一一对应；「资金」「收入」是数字，规划填目标、状态填实际。

**5 个智能体**，点「执行」一键检查：

| 智能体 | 检查什么 |
| --- | --- |
| 基础智能体 | 身高、体重条件是否都勾选 |
| 财务智能体 | 实际资金 ≥ 目标资金、实际收入 ≥ 目标收入 |
| 饮食智能体 | 饮食条件是否都勾选 |
| 运动智能体 | 只检查**今天该做**的动作（运动条件可以按星期几安排） |
| 监管智能体 | 目前只监管「今日」这一项 |

- 没勾选 = 未达标，会列出还差哪些条件；全部满足显示「已达标」。
- 运动条件可以直接把星期写进文字里，例如：`高脚杯深蹲，一三五七`（支持 `一、三、五、七`、`周一、周三`、`每天`、`周末`、`工作日`、`周一到周五`、`1357`；不写周几 = 每天）。
- 每次「执行」会记一条当天记录（同一天多次执行保留最后一次），智能体页面下方是最近 30 天的统计图：每根柱 = 当天达标数 / 智能体数，柱子越高越好，鼠标悬停可看具体达标数。

**桌面版**：双击图标打开独立窗口（没有浏览器地址栏），关窗口会缩到右下角托盘，右键托盘可以「打开 supersys」或「退出」。

## 下载

不想装 Python？直接下载打包好的安装包：

- **最新版**：<https://github.com/wzqfwanj/supersys/releases/latest>
- **Windows**：下载 `supersys.exe`（约 20 MB），双击运行即可，无需安装 Python 和依赖。
- **Android**：下载 `supersys.apk` 安装（手机和电脑连同一个 Wi-Fi，第一次打开填电脑上的服务地址，见下面「手机版」）。

说明：

- 需要 Windows 10/11（自带 Edge WebView2 运行时）；
- 首次运行 SmartScreen 可能提示「Windows 已保护你的电脑」：点「更多信息」→「仍要运行」；
- 数据存在 exe 旁边的 `data.db` 里；程序目录换一份就是一份新的数据；
- 关窗口会缩到右下角托盘，右键托盘图标可「打开 supersys」或「退出」。

exe 由 GitHub Actions 自动打包：仓库里打一个 `v*` 标签（如 `v1.1.0`），
[release 工作流](.github/workflows/release.yml) 就会在 Windows 环境里构建并自动发布到 Releases。

## 快速开始

需要 Windows + Python 3.10 以上（用到了 `sqlite3`、`http.server` 等标准库）。

```bash
git clone https://github.com/wzqfwanj/supersys.git
cd supersys
python -m pip install -r requirements.txt
```

**桌面版（推荐）**：双击桌面上的 `supersys` 图标，或运行 `启动supersys.bat`。第一次用可以先创建快捷方式：

```powershell
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut("$env:USERPROFILE\Desktop\supersys.lnk")
$lnk.TargetPath = (Get-Command pythonw).Source
$lnk.Arguments = '"' + (Get-Location).Path + '\desktop.py"'
$lnk.WorkingDirectory = (Get-Location).Path
$lnk.IconLocation = (Get-Location).Path + "\web\icon.ico"
$lnk.Save()
```

**浏览器版**（调试用）：

```bash
python server.py        # 默认 http://127.0.0.1:8000
python server.py 8080   # 指定端口
```

## 手机版

界面在手机上会自动适配（窄屏布局、触摸操作、弹窗从底部弹出），也可以「添加到主屏幕」当 App 用。

1. 在电脑上启动带局域网访问的服务：

   ```bash
   python server.py 8000 --lan
   ```

   终端会打印类似 `手机（同一 Wi-Fi）访问：http://192.168.0.102:8000` 的地址；

2. 手机连**同一个 Wi-Fi**，用浏览器打开上面打印的地址即可；

3. 想更像 App：直接下载 Releases 里的 `supersys.apk`（Android），装上后第一次打开填同一个地址；或者用浏览器菜单「添加到主屏幕」（iPhone Safari：分享 → 添加到主屏幕）。

说明：

- 手机只是访问电脑上的页面，**数据始终存在电脑的 `data.db`**，两边看到的是同一份数据；
- APK 是套壳 WebView，右下角「⋯」可以随时改服务器地址；电脑上的服务需要开着；
- `--lan` 会让同一局域网内的设备都能访问，公共 Wi-Fi 下不要开；
- 桌面版 exe 默认只允许本机访问；要用手机访问，用源码方式 `python server.py --lan`（或设置环境变量 `SUPERSYS_HOST=0.0.0.0`）。

## 数据

- 数据库：`data.db`（SQLite，和程序放在同一目录），第一次启动时如果存在旧的 `data.json` 会自动迁移进来。
- 个人数据（`data.db`、`data.json`、`desktop.log`）都写在 `.gitignore` 里，**不会提交到仓库**。
- 桌面版启动失败的日志在 `desktop.log`。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/sections` | 分区 / 智能体列表 |
| GET | `/api/plan`、`/api/status` | 规划 / 状态数据 |
| GET | `/api/runs` | 每天的执行记录 |
| POST | `/api/runs` | 保存今天执行结果 `{results}` |
| POST | `/api/plan/items`、`/api/status/items` | 新增条件 `{field, name}` |
| PATCH | `/api/plan/items/<id>`、`/api/status/items/<id>` | 修改条件 `{name}` |
| DELETE | `/api/plan/items/<id>`、`/api/status/items/<id>` | 删除条件 |
| POST | `/api/plan/batch`、`/api/status/batch` | 一次提交多条改动 |
| POST | `/api/plan/amounts`、`/api/status/amounts` | 保存数字字段 `{field, amount}` |
| GET | `/api/health` | 健康检查 |

条件在数据库里是**一行一条**，新增 / 改名 / 删除都是单行操作，所以开多个窗口同时改也不会互相覆盖。

## 项目结构

```
desktop.py       桌面版入口（本地服务 + pywebview 原生窗口 + 托盘图标）
启动supersys.bat  无控制台启动桌面版
server.py        后端（静态页面 + SQLite + REST 接口，支持 --lan 手机访问）
web/index.html   页面骨架
web/styles.css   极简样式（含手机端适配）
web/app.js       三个分区的交互、智能体判断、统计图
web/manifest.webmanifest  手机端 PWA 配置（添加到主屏幕）
web/icon*.png / icon.ico  应用图标
.github/workflows/release.yml  打标签自动打包 exe 并发版
docs/            界面截图
requirements.txt 桌面版依赖
data.db          SQLite 数据库（运行后生成，不提交）
```

## 开发

- 默认分支 `main`，开发分支 `dev`。
- 提交推送：
  ```bash
  git add -A
  git commit -m "改了什么"
  git push
  ```
- 如果直连 GitHub 超时，可以给 git / gh 配本地代理，例如：

  ```bash
  git config http.proxy http://127.0.0.1:7897
  # gh 用环境变量（PowerShell）：
  $env:HTTPS_PROXY = "http://127.0.0.1:7897"
  ```
- **发新版本**（自动打包 + 发布 exe）：
  ```bash
  git tag v1.1.0
  git push origin v1.1.0
  ```
  推送标签后，GitHub Actions 会自动构建 Windows exe 并发布到 Releases；也可以在 Actions 页面手动触发（只产出一个构建产物，不发版）。

## 许可

[MIT License](LICENSE)

