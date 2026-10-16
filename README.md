# DSH Desktop: open a Session in a second window

在**官方 DeepSeek Harness 桌面端**里，右键会话行 → 在新窗口中打开。
不改 Host、不改插件、不额外开进程：只给桌面壳的 `app.asar` 打 5 处补丁。

---

## 为什么必须改壳

桌面壳是唯一能创建窗口的进程，而它主动堵住了这条路：

```js
// app.asar/lib/main.js:549   (createWindow 内)
window.webContents.setWindowOpenHandler(({ url }) => {
  if (["http:", "https:"].includes(new URL(url).protocol)) shell.openExternal(url);
  return { action: "deny" };          // 一律拒绝新建窗口
});
```

再加上 preload 没暴露任何开窗能力（`createProductApi()` 只有 `browser` /
`deviceInfo` / `keyboard` / `shortcuts` / `updates`），而且 dsh 插件跑在子进程
里、拿不到 Electron —— 所以「插件形式开新窗口」在官方桌面端不存在。

**顺带一个必踩的坑**：壳里 WebSocket 的认证头只给主窗口注 cookie：

```js
// main.js:11585
if (hostUrl === void 0 || hostCookie === void 0 ||
    details.webContentsId !== mainWindow?.webContents.id) return callback({});
```

第二个窗口因此拿不到 cookie，`ws://127.0.0.1/api/remote.mux` 直接 401，
表现就是「开了个空白窗口」。本补丁把它改成「任一已注册应用窗口的主帧」。

---

## 改了哪 5 处

| # | 文件 | 位置 | 内容 |
|---|---|---|---|
| 1 | `lib/main.js` | electron import | 补 `WebContents`（用于按 id 定位调用窗口） |
| 2 | `lib/main.js` | `const createMainWindow = () => {` 前 | `__dshWindows` 注册表 + `__dshWindows.open({sessionId})` 窗口工厂 |
| 3 | `lib/main.js` | `const enterWorkspace = async` 前 | 两个 IPC：`open-session-window`、`show-session-menu` |
| 4 | `lib/main.js` | `onBeforeSendHeaders` | cookie 注入不再限定唯一主窗口 |
| 5 | `lib/preload-app.cjs` | `exposeInMainWorld("dshDesktop", …)` 后 | `dshSessionWindow`：右键菜单桥 + `open-session` 事件 |

窗口工厂的要点：

- 复用既有 `createWindow(appPreload, false, true)`，所以圆角/拖拽区/Windows
  标题栏 overlay/外链接管**自动与主窗口一致**；
- 新窗口按 `base + 40*n` 阶梯偏移，不叠在主窗口上；
- 上限 8 个；超限时复用已有窗口并把目标会话发过去；
- 关闭语义分流：**主窗口**照旧 hide-to-tray，**副窗口**直接关（不留托盘幽灵窗口）；
- `sessionId` 会在 `loadURL` 解析后通过 `dsh-desktop:open-session` 发给新窗口。

---

## 安装

> ⚠️ **必须先关掉 DeepSeek Harness。** 它是唯一读到这个文件的进程，运行中 Windows
> 会锁住 `app.asar`，替换必然失败。而关掉它也意味着关掉正在给你发指令的那个会话 ——
> 所以**安装动作不能靠对话触发**，必须由一个能自己跑完的文件完成。

### 闪退是怎么被修掉的（两个真实坑）

**坑 1：安装器把自己杀了。**
第一版用 `taskkill /IM "DeepSeek Harness.exe" /T /F`，`/T` 会杀掉整棵进程树。
实测进程树是这样的：

```
assistant 的 powershell.exe  ←  DeepSeek Harness.exe  ←  ...  ←  explorer.exe
```

从 DSH 里开出来的任何命令行（包括你双击的那个安装器，如果它也是 DSH 的后代）
都在这棵树里 —— 于是脚本杀到自己，`pause` 还没执行，窗口就闪退了。

**修法**：`install.cmd` 先把自己和整套工具**搬到 `%TEMP%\dsh-session-window-<时间戳>\`**，
再用 `start` 在新控制台里跑。新控制台的父进程不再是 DSH，所以 DSH 退出不会带走它。
同时 `taskkill /T` 被彻底移除，改成只对应用**自身**的进程调 `Stop-Process`，
不碰任何其他东西（包括你正在用的终端）。

**坑 2：PowerShell 把中文脚本读成乱码。**
PowerShell 5.1 对**无 BOM 的 UTF-8 `.ps1`** 按系统 ANSI（中文系统 = GBK）解码，
中文字符串会变成 mojibake，`。` 甚至会把后面的引号吞掉，直接语法错误：

```
字符串缺少终止符: '。    ← install.ps1 一行中文注释引起的整脚本崩
```

**修法**：所有可执行脚本（`.ps1` / `.cmd`）**全 ASCII**，`log.ps1` 用
`System.IO.File` 以 ASCII 追加日志；中文只留在 README 这种不执行的文件里。
顺带所有脚本统一 **UTF-8 BOM + CRLF**。

### 无人值守安装（推荐）

**`install.cmd` 自己把整件事做完**，关掉应用后你不需要再输入任何命令：

1. 把整套工具搬进 `%TEMP%`，用 `start` 开一个**独立控制台**
2. 停掉 DeepSeek Harness（只停它自己的进程，`/T` 已移除）
3. 轮询等 `app.asar` 的文件锁释放（最长 45 秒）
4. 备份为 `app.asar.original-<时间戳>`
5. 替换成打了补丁的 `app.asar`，校验字节数
6. 输出结果 → `pause` **等你按任意键**，不会一闪而过
7. 全过程写入 `install.log`（ASCII，可事后查）

顺序：

```
先在这个会话里把想问的问完/做完
→ 双击  install.cmd
→ 它杀掉 DSH、装好、停在「按任意键」
→ 重新打开 DeepSeek Harness
→ 右键会话行 → Open in new window
```

**装之前建议先预演**（不杀进程、不写文件，现在就能跑）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\install.ps1" -WhatIf -LogPath "$env:TEMP\whatif.log"
```

想看 staging 逻辑而不真的开跑（测试钩子）：

```powershell
set DSH_SESSION_WINDOW_NO_RUN=1
install.cmd
set DSH_SESSION_WINDOW_NO_RUN=
```

### 桌面快捷方式

```powershell
.\make-shortcut.ps1          # 在桌面生成 "Install DSH session-window patch.lnk"
```

之后双击那个快捷方式即可。

### 手动分步（可选）

每条都写成**单行**：反引号续行（`` ` ``）必须是行尾最后一个字符，从聊天窗口复制
时极易带上尾随空格，PowerShell 会报
`Missing expression after unary operator '--'` 之类看不懂的错。

```powershell
cd "E:\Software\DSH Desktop\dsh-session-window"
python build-patches.py
python patch-asar.py --asar "E:\Software\DeepSeek Harness\resources\app.asar" --check
python patch-asar.py --asar "E:\Software\DeepSeek Harness\resources\app.asar" --out ".\work\app.asar.patched"
python verify-asar.py
.\install.ps1
```

先跑 `--check` 确认 5 处锚点全部匹配，再真正写出补丁件。
`install.ps1` 要求应用已关闭；加 `-Force` 让它自己结束进程。

### 装之前先体检（强烈建议，现在就能跑）

不替换任何文件、不影响正在运行的应用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\dry-run.ps1"
```

逐项报告：目标 asar 是否存在、补丁件是否真的不同、**哪些进程正锁着文件**、
安装目录是否可写、备份名是否被占、配套脚本是否齐全。

> 已修过的坑：`param([string]$Patched = (Join-Path $PSScriptRoot ...))` 在
> `powershell -File` 调用下会以
> `Cannot bind argument to parameter 'Path' because it is an empty string`
> 直接崩 —— 参数默认值绑定阶段 `$PSScriptRoot` 仍是空的，`Join-Path` 收到空串。
> 三个脚本现在都在函数体内解析脚本目录。

## 使用

启动后**右键侧边栏的会话行** → 菜单里选 `Open in new window`。
（`0imzero/dsh-workspace-menu` 之类的会话菜单插件**不要同时装**，两者都会接
`contextmenu`，会抢事件。）

## 回滚

**双击 `rollback.cmd`**（同样会自己结束进程、自动挑最新备份、结束前 pause）。

或手动：

```powershell
.\rollback.ps1
.\rollback.ps1 -Backup "E:\Software\DeepSeek Harness\resources\app.asar.original-20261015-120000"
```

## 已知限制

1. **新窗口落在上次的会话位置**，不一定自动切到你右键的那条。原因：客户端
   `uiWorkspace.openSession(id)` 在应用挂载后才可用，而 `loadURL` 的 resolve 时刻
   早于它。要精确跳转，往
   `C:\Users\<你>\.dsh\profiles\desktop\cordis.patch.yml` 的 `insert:` 里加一个 10 行
   客户端插件订阅 `dshSessionWindow.onOpenSession` 即可（该 profile 开了
   `patchReload: live`，改完自动生效）。
2. **应用自动更新会覆盖** `app.asar` —— 重新跑一次 `install.ps1` 即可；锚点若因新版
   本漂移，`patch-asar.py` 会**明确报错并拒绝写文件**，不会产出坏壳。
3. `resources\app.asar` 在安装目录下（非 `WindowsApps` 受保护路径），
   当前用户有 Modify 权限，无需管理员。
4. 同步机制不依赖本补丁：会话/设置的真值在 Host，`$events` 按连接各发一份，
   所以两个窗口天然一致；**没有**任何窗口间状态复制代码。

---

## 文件说明

| 文件 | 作用 |
|---|---|
| `build-patches.py` | 生成 `patches/*.json`（5 处锚点编辑） |
| `patch-asar.py` | 读原 asar、按锚点替换、重算 header/offset/integrity、写出新 asar |
| `verify-asar.py` | 校验 prefix 布局、11470 个 payload 的 integrity、两个源文件语法、补丁标记 |
| `install.ps1` / `rollback.ps1` | 安装 / 回滚（含进程检查、自动备份） |
| `work/` | 原 asar 副本与产物（约 240MB，可随时删） |

### asar 布局（本工具依赖的事实）

```
offset 0   u32 comment_size = 4            // pickle 判别值
offset 4   u32 pickle_length = json_size+8 // = 8 + 3392048
offset 8   u32 header_size   = json_size+4 // = 4 + 3392048
offset 12  u32 json_size     = 3392048     // {"files":… 的字节数
offset 16  {json}{padding}                 // header 内容
payload    starts at header_size + 12 = 3392064
```

节点两种形态：packed 用 `{size, offset, integrity}`（offset 相对 payload 起点），
`app.asar.unpacked/` 里的 1497 个用 `{size, unpacked: true, integrity}`，本工具原样保留。

