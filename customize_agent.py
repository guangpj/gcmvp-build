#!/usr/bin/env python3
"""gcmvp 被控端（agent）专用定制脚本。

在 customize.py 的全部通用白标补丁之上，再做三件事：
  1. 把 DesktopHomePage 换成"只有一个框、框中央是 ID"的极简页面；
  2. 把主窗口固定成刚好放下这个框的小尺寸；
  3. 换成自绘的蓝色 G 图标（exe 资源 + Flutter 窗口图标）。

配合 flutter-build.yml 的 build-profile=agent 使用：build.py 不带
--skip-portable-pack，产出一个自解压的单文件 gcmvp.exe。

用法: python3 customize_agent.py [源码根目录]
"""
import shutil
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

# ---------------------------------------------------------------- 通用补丁
print("=== step 1/2: apply common gcmvp customization ===", flush=True)
subprocess.run([sys.executable, str(HERE / "customize.py"), str(ROOT)],
               check=True)

CHANGES = []


def log(tag, path, detail):
    CHANGES.append((tag, str(path), detail))
    print(f"[{tag}] {path}: {detail}")


def edit(path, old, new, desc, required=True):
    p = ROOT / path
    if not p.exists():
        log("MISS", path, "文件不存在，跳过")
        return
    text = p.read_text(encoding="utf-8", errors="surrogateescape")
    if old in text:
        p.write_text(text.replace(old, new, 1),
                     encoding="utf-8", errors="surrogateescape")
        log("OK", path, desc)
    elif new in text:
        log("SKIP", path, f"已应用: {desc}")
    elif required:
        log("WARN", path, f"未找到目标片段: {desc}")


print(f"=== step 2/2: agent-only customization on {ROOT} ===", flush=True)

# ---------------------------------------------------------------- 极简 ID 页
# 保留 initState 里每秒 fetchID 的定时器（它会 setState 刷新 ID），
# 只替换 build()：去掉左栏（密码/帮助/在线状态）和右栏（连接页）。
OLD_BUILD = """  @override
  Widget build(BuildContext context) {
    super.build(context);
    final isIncomingOnly = bind.isIncomingOnly();
    return _buildBlock(
        child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        buildLeftPane(context),
        if (!isIncomingOnly) const VerticalDivider(width: 1),
        if (!isIncomingOnly) Expanded(child: buildRightPane(context)),
      ],
    ));
  }"""

NEW_BUILD = """  @override
  Widget build(BuildContext context) {
    super.build(context);
    // gcmvp-agent: one centered box, showing only the device ID.
    // serverId 由 fetchID() 每秒刷新并 notifyListeners()，必须监听，否则
    // build 只发生一次，永远停在初始的 "Generating ..."（正在生成中）。
    return ListenableBuilder(
      listenable: gFFI.serverModel,
      builder: (context, _) {
        final id = gFFI.serverModel.serverId.text;
        return Scaffold(
          backgroundColor: const Color(0xFFF4F7FB),
          body: Center(
            child: Container(
              width: 320,
              height: 116,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: const Color(0xFF2F65BA), width: 2),
                boxShadow: const [
                  BoxShadow(
                    color: Color(0x22000000),
                    blurRadius: 10,
                    offset: Offset(0, 3),
                  ),
                ],
              ),
              child: SelectableText(
                id,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 38,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 2,
                  color: Color(0xFF1B3A6B),
                ),
              ),
            ),
          ),
        );
      },
    );
  }"""

edit("flutter/lib/desktop/pages/desktop_home_page.dart",
     OLD_BUILD, NEW_BUILD, "被控端主页替换为极简 ID 框（监听 ID 刷新）")

# ---------------------------------------------------------------- 标题栏按钮
# 主页被 DesktopTab 包着：tail=设置、showMaximize=最大化/全屏、showLogo=左上角图标。
# 被控端只要右上角"最小化 + 关闭"，其余全部去掉。
OLD_TAB = """            body: DesktopTab(
              controller: tabController,
              tail: Offstage(
                offstage: bind.isIncomingOnly() || bind.isDisableSettings(),
                child: ActionIcon(
                  message: 'Settings',
                  icon: IconFont.menu,
                  onTap: DesktopTabPage.onAddSetting,
                  isClose: false,
                ),
              ),
            )));"""
NEW_TAB = """            // gcmvp-agent: keep only minimize + close, no settings/logo/maximize.
            body: DesktopTab(
              controller: tabController,
              showLogo: false,
              showMaximize: false,
              tail: null,
            )));"""
edit("flutter/lib/desktop/pages/desktop_tab_page.dart",
     OLD_TAB, NEW_TAB, "标题栏只留最小化+关闭，去设置/全屏/左上角 icon")

# ---------------------------------------------------------------- 关窗断流修复
# 被控端关极简 ID 窗口后，DesktopServerPage.onWindowClose() 会 closeAll()+
# gFFI.close() 断开所有连接并关闭 core，导致控制端断流。改成只隐藏、保持服务。
OLD_SERVER_CLOSE = """  @override
  void onWindowClose() {
    // Other platforms keep the old behaviour exactly: the ambiguity this guards against is a
    // Linux session logout, which closes every window in the session.
    final byOperator = _cmClosedByOperator || !isLinux;
    Future.wait([gFFI.serverModel.closeAll(byOperator: byOperator), gFFI.close()]).then((_) {
      if (isMacOS) {
        RdPlatformChannel.instance.terminate();
      } else {
        windowManager.setPreventClose(false);
        windowManager.close();
      }
    });
    super.onWindowClose();
  }"""
NEW_SERVER_CLOSE = """  @override
  void onWindowClose() {
    // gcmvp-agent: hide only - do NOT closeAll()/gFFI.close() here.
    // Closing the compact ID window must keep serving the connected controller.
    windowManager.hide();
    super.onWindowClose();
  }"""
edit("flutter/lib/desktop/pages/server_page.dart",
     OLD_SERVER_CLOSE, NEW_SERVER_CLOSE,
     "关极简窗口只隐藏、不断开连接（修复断流）")

# ---------------------------------------------------------------- 禁止 UAC 提权弹窗
# 便携单 exe 未安装：控制端请求提权/启动 --portable-service 时，
# elevate_or_run_as_system() 会 ShellExecute(runas) 弹 Windows UAC。
# 无人值守场景没人点 UAC，弹了反而卡住：直接让该函数不发起提权。
OLD_ELEVATE = """pub fn elevate_or_run_as_system(is_setup: bool, is_elevate: bool, is_run_as_system: bool) {
    // avoid possible run recursively due to failed run.
    log::info!("""
NEW_ELEVATE = """pub fn elevate_or_run_as_system(is_setup: bool, is_elevate: bool, is_run_as_system: bool) {
    // gcmvp-agent: never trigger a UAC prompt (unattended agent, no one to click it).
    // The main process still captures the screen via GDI/DXGI fallback, so normal
    // remote view/control keeps working without an elevated portable service.
    // Gate on an opt-in env var so the rest of the function stays reachable (no
    // unreachable_code lint): by default it is absent -> return immediately.
    if std::env::var_os("GCMVP_ALLOW_ELEVATE").is_none() {
        log::info!("gcmvp-agent: elevation suppressed (no UAC prompt)");
        return;
    }
    // avoid possible run recursively due to failed run.
    log::info!("""
edit("src/platform/windows.rs", OLD_ELEVATE, NEW_ELEVATE,
     "禁止 UAC 提权弹窗（无人值守被控端）")

# 控制端连接管理窗口不再显示"提权"按钮：can_elevate() 返回 false。
OLD_CAN_ELEVATE = """pub fn can_elevate() -> bool {
    #[cfg(windows)]
    return !crate::platform::is_installed();
    #[cfg(not(windows))]
    return false;
}"""
NEW_CAN_ELEVATE = """pub fn can_elevate() -> bool {
    // gcmvp-agent: hide the elevation button - agent never elevates (no UAC).
    return false;
}"""
edit("src/ui_cm_interface.rs", OLD_CAN_ELEVATE, NEW_CAN_ELEVATE,
     "隐藏提权按钮（不再请求提权）")

# 打开需要管理员权限的软件时，被控端 portable_check() 每秒上报 UAC /
# foreground-elevated 状态，控制端收到后自动弹"请求提权"对话框。
# 无人值守场景不需要这些提示：整个 portable_check() 直接返回。
OLD_PORTABLE_CHECK = """    fn portable_check(&mut self) {
        if self.portable.is_installed || !self.is_remote() || !self.keyboard {
            return;
        }"""
NEW_PORTABLE_CHECK = """    fn portable_check(&mut self) {
        // gcmvp-agent: never report UAC / foreground-elevated state, so the
        // controller won't auto-pop the "Request Elevation" dialog when an
        // admin-privileged app is opened on the agent side.
        // Env-gated so the rest stays reachable (no unreachable_code lint);
        // absent by default -> skip all elevation reporting.
        if std::env::var_os("GCMVP_ALLOW_ELEVATE").is_none() {
            return;
        }
        if self.portable.is_installed || !self.is_remote() || !self.keyboard {
            return;
        }"""
edit("src/server/connection.rs", OLD_PORTABLE_CHECK, NEW_PORTABLE_CHECK,
     "不上报 UAC/提权状态，控制端不再弹请求提权框")

# ---------------------------------------------------------------- 固定小窗口
# customize.py 已在 setPreventClose 后插入窗口守卫 listener，锚点要带上它。
OLD_WIN = """    await windowManager.ensureInitialized();
    windowManager.setPreventClose(true);
    windowManager.addListener(_gcmvpWindowGuard); // gcmvp: keep alive on close
    if (isMacOS) {"""
NEW_WIN = """    await windowManager.ensureInitialized();
    windowManager.setPreventClose(true);
    windowManager.addListener(_gcmvpWindowGuard); // gcmvp: keep alive on close
    // gcmvp-agent: compact fixed window that fits the single ID box
    await windowManager.setSize(const Size(420, 220));
    await windowManager.setMinimumSize(const Size(420, 220));
    await windowManager.setMaximumSize(const Size(420, 220));
    if (isMacOS) {"""
edit("flutter/lib/main.dart", OLD_WIN, NEW_WIN,
     "被控端窗口固定为 420x220")

# windowManager 的 waitUntilReadyToShow 回调里还会用上次保存的位置/尺寸
# 覆盖上面的 setSize（实测恢复成 800x600），必须在那里再固定一次。
OLD_RESTORE = """    // Restore the location of the main window before window hide or show.
    await restoreWindowPosition(WindowType.Main);"""
NEW_RESTORE = """    // gcmvp-agent: do not restore old geometry; keep the compact ID box.
    await windowManager.setSize(const Size(420, 220));
    await windowManager.setMinimumSize(const Size(420, 220));
    await windowManager.setMaximumSize(const Size(420, 220));
    await windowManager.center();"""
edit("flutter/lib/main.dart", OLD_RESTORE, NEW_RESTORE,
     "禁止旧窗口配置覆盖被控端小窗口")

# ---------------------------------------------------------------- 便携包品牌残留
# 单 exe 自解压目录名与打包器资源元数据也去掉 RustDesk 痕迹。
edit("libs/portable/src/main.rs",
     'const APP_PREFIX: &str = "rustdesk";',
     'const APP_PREFIX: &str = "gcmvp";',
     "自解压目录名 -> gcmvp")
for old, new in [
    ('ProductName = "RustDesk"', 'ProductName = "GCMVP"'),
    ('OriginalFilename = "rustdesk.exe"', 'OriginalFilename = "gcmvp.exe"'),
    ('FileDescription = "RustDesk Remote Desktop"',
     'FileDescription = "GCMVP Remote Desktop"'),
]:
    edit("libs/portable/Cargo.toml", old, new, "打包器资源元数据 -> GCMVP")

# ---------------------------------------------------------------- 换图标
ICON = HERE / "tools" / "gcmvp_agent.ico"
if not ICON.is_file():
    log("MISS", ICON, "图标文件不存在，请运行 tools/make_agent_icon.py")
else:
    for rel in [
        # single-file portable packer embeds this one at compile time
        "res/icon.ico",
        "flutter/windows/runner/resources/app_icon.ico",
        "flutter/assets/icon.ico",
    ]:
        dst = ROOT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ICON, dst)
        log("OK", rel, "替换为 gcmvp agent 蓝色 G 图标")

print(f"=== agent customization done: {len(CHANGES)} changes ===")
