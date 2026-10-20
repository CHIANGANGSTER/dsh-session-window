# DSH Desktop：会话在新窗口中打开

给 DSH Desktop 的会话右键菜单加一项「在新窗口中打开」。新窗口直接落在你点的那个会话上；两个窗口读写同一个 Host，会话、消息、设置天然一致，不需要任何窗口间同步代码。

*Right-click a Session in DSH Desktop and open it in a second window. Both windows read the same Host, so sessions and settings stay in sync with no synchronisation code.*

仓库：<https://github.com/CHIANGANGSTER/dsh-session-window>

---

## 安装

两步，每步一次操作，没有需要你双击的脚本。

### 第 1 步 · 装插件

在 DSH 侧边栏打开「插件」页 → 安装 → 粘贴下面这个地址：

```
https://github.com/CHIANGANGSTER/dsh-session-window/releases/latest/download/dsh-session-window-client.tgz
```

也可以在 [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin) 里搜索关键词 `session window`，或直接看 `session` 分类，找到本条目后按条目给出的地址安装。

### 第 2 步 · 打桌面壳补丁

插件只负责菜单项；真正开出第二个窗口需要桌面壳的支持。在 **Windows Terminal / PowerShell** 里执行一条命令（脚本会自动关闭并重新打开 DSH）：

```powershell
irm https://raw.githubusercontent.com/CHIANGANGSTER/dsh-session-window/main/install.ps1 | iex
```

脚本依次完成：定位安装目录 → 校验当前 `app.asar` 是受支持的版本 → 下载几 KB 的补丁定义 → 关闭 DSH → 在本机重建补丁件并**逐字节校验哈希** → 备份原件 → 替换 → 安装插件 → 重启 DSH。

补丁以 diff 形式随仓库分发，不下载任何预编译归档；锚点不匹配或哈希不符时不会替换任何文件。

> 请在独立终端里执行，不要在 DSH 会话里执行——替换 `app.asar` 时应用必须处于关闭状态。

### 支持的版本

| 项 | 值 |
| --- | --- |
| DSH Desktop | `0.2.1-rc.2`（Windows） |
| 原版 `app.asar` | `47874618bf5b3011fcaac10cd4c85f69da333e70d4f99b921207c78d0999512a` |
| 打补丁后 | `40b471241d607c5b1c04f555b6b68d63e387df5a1b694fa2f2147625d5986229` |

其它版本会被拒绝并打印实际哈希。DSH 升级后壳补丁会失效，需要重新适配：提 issue 附上版本号与 `app.asar` 的 SHA-256 即可。

---

## 使用

右键侧边栏任意一个会话 → **在新窗口中打开**，新窗口会落到该会话上。

两个窗口共享同一个 Host：在一个窗口里发消息、改设置，另一个窗口立即一致。关掉任意一个窗口不影响另一个。

---

## 卸载

```powershell
irm https://raw.githubusercontent.com/CHIANGANGSTER/dsh-session-window/main/uninstall.ps1 | iex
```

只撤销本插件与壳补丁，其它插件、会话、设置一律不动。原始 `app.asar` 在安装时已备份到 `resources\app.asar.before-session-window-*`。

---

## 为什么必须有壳补丁

DSH Desktop 的三条硬约束决定了这件事做不进插件：

1. 主进程的 `setWindowOpenHandler` 一律 `deny`，`window.open` 在桌面端被拒绝；
2. `preload` 暴露的桥只有 `browser` / `deviceInfo` / `keyboard` / `shortcuts` / `updates`，没有开窗 API；
3. 插件运行在 Host 子进程里，拿不到 Electron 的 `BrowserWindow`。

于是「菜单项」和「落到目标会话」做进插件，「创建窗口」这一下由壳提供。壳把能力暴露为 `globalThis.dshSessionWindow`（`version: 2`），插件只认这个契约：没有它时菜单项会置灰并提示「新窗口功能需适配当前版本」，而不是静默消失。

壳补丁共 21 处编辑，集中在四件事：窗口注册表与窗口工厂、三个 IPC 通道（`openSessionWindow` / `getPendingTarget` / `ackPendingTarget`）、把 WebSocket cookie 门从「仅主窗口」放宽到「任意已注册应用窗口」，以及多窗口下的快捷键 / 目录选择 / 主题 / locale 归属修正。

新窗口复用壳里既有的 `createWindow`，所以圆角、拖拽区、标题栏、外链接管与主窗口一致；关闭语义也做了分流——主窗口照旧收进托盘，副窗口直接关闭。

---

## 已知限制

- 同时最多 8 个窗口，超出后复用最早的一个。
- 窗口以阶梯方式偏移排列，不记忆上次的位置与尺寸。
- 同一会话重复点击会开出多个窗口（没有「已打开则聚焦」）。
- 仅在 Windows 上验证；macOS / Linux 未测试。
- DSH 每次升级都会覆盖 `app.asar`，壳补丁需要按新版本重新适配。

---

## 开发

```bash
# 插件：24 项断言 + 行为测试
node plugin/dsh-session-window-client/scripts/check.mjs

# 补丁锚点是否仍与目标版本匹配（不写任何文件）
node patch-asar.mjs --asar <原版 app.asar> --spec patches/r2 --check

# 重建补丁件并校验
node patch-asar.mjs --asar <原版 app.asar> --spec patches/r2 --out out.asar \
  --expect-sha256 47874618bf5b3011fcaac10cd4c85f69da333e70d4f99b921207c78d0999512a
```

没有 Node 时，可用应用自带运行时执行同样的操作：

```powershell
$env:ELECTRON_RUN_AS_NODE = '1'
& 'C:\Path\DeepSeek Harness.exe' patch-asar.mjs --asar <app.asar> --spec patches/r2 --check
```

### 目录

| 路径 | 内容 |
| --- | --- |
| `plugin/dsh-session-window-client/` | 客户端插件（`dsh.bundle` + `dsh.client`），`lib/` 为构建产物 |
| `patches/r2/` | 壳补丁定义（锚点 + 替换文本） |
| `patch-asar.mjs` | 补丁构建器：校验基线 → 重建 header 与 payload → 重算 integrity → 复检 |
| `install.ps1` / `uninstall.ps1` | 用户级一条命令安装 / 卸载 |
| `tools/` | 作者手工使用的安装器与自检脚本，普通用户不需要 |
