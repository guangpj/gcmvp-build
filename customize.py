#!/usr/bin/env python3
"""
gcmvp 白标定制脚本 —— 对 RustDesk 1.5.x 官方源码做幂等修改。
在 GitHub Actions 中 checkout 源码后运行本脚本，再执行官方构建。

用法: python3 customize.py [源码根目录]
默认源码根目录为当前目录。

幂等设计：每处修改都先检测目标片段是否存在，已改过则跳过。
若源码版本变化导致某个片段找不到，会打印 WARNING 但不中断，
便于人工核对（不会静默失败）。
"""
import re
import sys
from pathlib import Path

# GitHub Windows runners default to cp1252; Chinese log details would crash
# with UnicodeEncodeError before the build even starts.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
APPLY_NAME = "gcmvp"
APP_DISPLAY = "GCMVP Remote"
CHANGES = []


def log(tag, path, detail):
    CHANGES.append((tag, str(path), detail))
    print(f"[{tag}] {path}: {detail}")


def edit(path, replacements, required=True):
    """
    replacements: list of (old, new, desc)
    对每个 old 做精确字符串替换；找不到时按 required 决定警告/报错。
    """
    p = ROOT / path
    if not p.exists():
        log("MISS", path, "文件不存在，跳过")
        return
    text = p.read_text(encoding="utf-8", errors="surrogateescape")
    orig = text
    for old, new, desc in replacements:
        if old in text:
            text = text.replace(old, new)
            log("OK", path, desc)
        elif new in text:
            log("SKIP", path, f"已应用: {desc}")
        else:
            if required:
                log("WARN", path, f"未找到目标片段: {desc}")
            else:
                log("INFO", path, f"可选片段未找到: {desc}")
    if text != orig:
        p.write_text(text, encoding="utf-8", errors="surrogateescape")


def regex_edit(path, pattern, repl, desc, count=0, required=True):
    p = ROOT / path
    if not p.exists():
        log("MISS", path, "文件不存在，跳过")
        return
    text = p.read_text(encoding="utf-8", errors="surrogateescape")
    new_text, n = re.subn(pattern, repl, text, count=count)
    if n:
        p.write_text(new_text, encoding="utf-8", errors="surrogateescape")
        log("OK", path, f"{desc} ({n} 处)")
    elif required:
        log("WARN", path, f"正则未匹配: {desc}")


def insert_before(path, anchor, block, desc, sentinel=None):
    """在 anchor 首次出现前插入 block；sentinel（哨兵串）已存在则跳过，保证幂等。"""
    p = ROOT / path
    if not p.exists():
        log("MISS", path, "文件不存在，跳过")
        return
    text = p.read_text(encoding="utf-8", errors="surrogateescape")
    if sentinel and sentinel in text:
        log("SKIP", path, f"已应用: {desc}")
        return
    if anchor in text:
        p.write_text(text.replace(anchor, block + anchor, 1),
                     encoding="utf-8", errors="surrogateescape")
        log("OK", path, desc)
    else:
        log("WARN", path, f"未找到锚点: {desc}")


print(f"=== gcmvp customize on {ROOT} ===")

# ---------------------------------------------------------------- 需求 1（已调整 2026-11-26）
# 原方案完全禁用中继；实测双侧对称 NAT 打洞无法成功，按用户决定恢复
# RustDesk 原版"打洞优先、失败回退中继"行为：以下三段禁用修改已移除，
# 源码保持原样即可（get_relay_server 自动推导 hbbs 地址 :21117，
# client.rs 直连失败回退 request_relay）。
# 中继仍只作兜底：P2P 成功时画面不过服务器，不产生流量。

# license 安装时写入 relay-server 的行为移除
edit("src/core_main.rs", [(
    'crate::ui_interface::set_option("relay-server".into(), lic.relay);',
    'let _ = lic.relay; // gcmvp: ignore license relay',
    "忽略 license 中的 relay 配置",
)])

# ---------------------------------------------------------------- 需求 2
# 隐藏托盘：start_tray 无条件返回
edit("src/tray.rs", [(
    """pub fn start_tray() {
    if crate::ui_interface::get_builtin_option(keys::OPTION_HIDE_TRAY) == "Y" {""",
    """pub fn start_tray() {
    return; // gcmvp: no system tray icon at all
    if crate::ui_interface::get_builtin_option(keys::OPTION_HIDE_TRAY) == "Y" {""",
    "start_tray 无条件返回（隐藏托盘图标）",
)])

# 连接请求不弹窗：把 Click/Both approve mode 的弹窗条件改为永假
edit("src/server/connection.rs", [(
    """            if (password::approve_mode() == ApproveMode::Click && !allow_logon_screen_password)
                || password::approve_mode() == ApproveMode::Both && !password::has_valid_password()
            {""",
    """            if false && ((password::approve_mode() == ApproveMode::Click && !allow_logon_screen_password)
                || password::approve_mode() == ApproveMode::Both && !password::has_valid_password())
            {""",
    "连接请求弹窗总闸关闭",
)])

# ---------------------------------------------------------------- 无人值守访问（2026-11-26 追加）
# 全部走 RustDesk 官方 unattended-access 机制：
#   verification-method = 仅永久密码   -> 被控端不再显示随机验证码
#   approve-mode        = password     -> 连接请求不需要点击确认
#   hide_cm             = true         -> "已连接/权限面板"窗口不再弹出
# 共享密码：exe 同目录 gcmvp.pwd（纯文本，默认 aa12），每次连接实时读取，
# gcmvp-pass.exe 修改后立即生效、无需重启；控制端连接时自动携带（只输 ID）。
# 说明：仅用于自有或已获机主明确授权的设备；程序保持任务管理器可见、
# 可用随包 gcmvp-exit.exe 退出；不做隐藏进程/自启/反检测。

# 1) 共享密码读取函数（common.rs）
insert_before("src/common.rs",
    "#[inline]\npub fn is_custom_client() -> bool {",
    """// gcmvp: shared access password. Plain-text gcmvp.pwd next to the exe;
// gcmvp-pass.exe rewrites it without a rebuild. Read fresh on every login
// attempt so password changes apply immediately. Fallback: built-in default.
pub fn gcmvp_shared_password() -> String {
    let mut candidates: Vec<std::path::PathBuf> = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join("gcmvp.pwd"));
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.join("gcmvp.pwd"));
    }
    for p in candidates {
        if let Ok(s) = std::fs::read_to_string(&p) {
            let t = s.trim().to_string();
            if !t.is_empty() {
                return t;
            }
        }
    }
    "aa12".to_string()
}

""",
    "注入共享密码读取函数（默认 aa12）",
    sentinel="pub fn gcmvp_shared_password")

# 2) 被控端：validate_password 优先校验共享密码
edit("src/server/connection.rs", [(
    """    fn validate_password(&mut self, allow_permanent_password: bool) -> bool {
        if password::temporary_enabled() {""",
    """    fn validate_password(&mut self, allow_permanent_password: bool) -> bool {
        // gcmvp: accept the shared static password (gcmvp.pwd, default "aa12")
        // before any stored-password logic; read fresh on every attempt.
        {
            let shared = crate::gcmvp_shared_password();
            if !shared.is_empty() && self.validate_password_plain(&shared) {
                self.set_conn_audit_primary_auth(
                    ConnAuditPrimaryAuth::PermanentPassword,
                );
                return true;
            }
        }
        if password::temporary_enabled() {""",
    "被控端校验共享密码（无人值守固定密码）",
)])

# 3) 控制端：连接时自动注入共享密码（用户只输 ID 点连接即可）
edit("src/client.rs", [(
    "let p = crate::ui_interface::get_builtin_option(keys::OPTION_DEFAULT_CONNECT_PASSWORD);",
    "let p = crate::gcmvp_shared_password(); // gcmvp: auto shared password (aa12 / gcmvp.pwd)",
    "控制端自动携带共享密码（只输 ID 即可连接）",
)])

# 4) 官方无人值守开关：仅永久密码 + 密码审批 + 隐藏连接管理窗口（CM）
edit("libs/hbb_common/src/password_security.rs", [
    (
        """fn verification_method() -> VerificationMethod {
    let method = Config::get_option("verification-method");
    if method == "use-temporary-password" {
        VerificationMethod::OnlyUseTemporaryPassword
    } else if method == "use-permanent-password" {
        VerificationMethod::OnlyUsePermanentPassword
    } else {
        VerificationMethod::UseBothPasswords // default
    }
}""",
        """fn verification_method() -> VerificationMethod {
    // gcmvp: unattended access - permanent password only
    VerificationMethod::OnlyUsePermanentPassword
}""",
        "验证方式固定为仅永久密码（不显示随机验证码）",
    ),
    (
        """pub fn approve_mode() -> ApproveMode {
    let mode = Config::get_option("approve-mode");
    if mode == "password" {
        ApproveMode::Password
    } else if mode == "click" {
        ApproveMode::Click
    } else {
        ApproveMode::Both
    }
}""",
        """pub fn approve_mode() -> ApproveMode {
    // gcmvp: unattended access - password approval, no click prompt
    ApproveMode::Password
}""",
        "审批模式固定为密码（连接请求不弹确认）",
    ),
    (
        """pub fn hide_cm() -> bool {
    approve_mode() == ApproveMode::Password
        && verification_method() == VerificationMethod::OnlyUsePermanentPassword
        && crate::config::option2bool("allow-hide-cm", &Config::get_option("allow-hide-cm"))
}""",
        """pub fn hide_cm() -> bool {
    // gcmvp: incoming sessions never show the connection-manager window
    true
}""",
        "被控端连接管理窗口（已连接/权限面板）不再显示",
    ),
])

# 5) 被控端主页不展示密码面板（密码由共享文件提供，界面只留识别码）
edit("flutter/lib/desktop/pages/desktop_home_page.dart", [(
    "      if (!isOutgoingOnly) buildPasswordBoard(context),",
    "      // gcmvp: password board hidden - fixed shared password via gcmvp.pwd",
    "隐藏被控端密码面板（识别码保留）",
)])

# ---------------------------------------------------------------- 需求 3
# Cargo.toml 品牌
edit("Cargo.toml", [
    ('name = "rustdesk"\nversion', 'name = "gcmvp"\nversion', "package name -> gcmvp"),
    ('authors = ["rustdesk <info@rustdesk.com>"]',
     'authors = ["gcmvp <support@gcmvp.local>"]', "authors"),
    ('description = "RustDesk Remote Desktop"',
     'description = "GCMVP Remote Desktop"', "description"),
    ('default-run = "rustdesk"', 'default-run = "gcmvp"', "default-run"),
    ('name = "librustdesk"', 'name = "libgcmvp"', "lib name"),
])

# Cargo.lock 同步包名，否则 --locked 构建会直接失败
edit("Cargo.lock", [(
    'name = "rustdesk"\nversion = "1.5.3"',
    'name = "gcmvp"\nversion = "1.5.3"',
    "Cargo.lock 包名 -> gcmvp",
)])

# build.py 的库文件存在性检查跟随新 lib 名
edit("build.py", [(
    "target/release/librustdesk.dll",
    "target/release/libgcmvp.dll",
    "build.py 库检查 -> libgcmvp.dll",
)])

# Windows 可执行资源信息
edit("flutter/windows/runner/Runner.rc", [
    ('VALUE "FileDescription", "RustDesk Remote Desktop"',
     'VALUE "FileDescription", "GCMVP Remote Desktop"', "FileDescription"),
    ('VALUE "InternalName", "rustdesk"',
     'VALUE "InternalName", "gcmvp"', "InternalName"),
    ('VALUE "OriginalFilename", "rustdesk.exe"',
     'VALUE "OriginalFilename", "gcmvp.exe"', "OriginalFilename"),
    ('VALUE "ProductName", "RustDesk"',
     'VALUE "ProductName", "GCMVP"', "ProductName"),
])

# Flutter Windows CMake / main.cpp
edit("flutter/windows/CMakeLists.txt", [
    ('project(rustdesk LANGUAGES CXX)', 'project(gcmvp LANGUAGES CXX)', "cmake project"),
    ('set(BINARY_NAME "rustdesk")', 'set(BINARY_NAME "gcmvp")', "BINARY_NAME"),
    ('librustdesk.dll', 'libgcmvp.dll', "dll name in cmake"),
])
edit("flutter/windows/runner/main.cpp", [
    ('librustdesk.dll', 'libgcmvp.dll', "dll name"),
    ('std::wstring app_name = L"RustDesk";',
     'std::wstring app_name = L"GCMVP";', "app_name"),
])

# 关键：Dart 层 FFI 仍按文件名加载 Rust 核心库。只改 C++/CMake 不够，
# 不改这里 Flutter 初始化会抛 "Failed to load dynamic library 'librustdesk.dll'"
# 并直接白屏（native_model.dart:145 -> initEnv -> runMainApp）。
edit("flutter/lib/models/native_model.dart", [(
    "DynamicLibrary.open('librustdesk.dll')",
    "DynamicLibrary.open('libgcmvp.dll')",
    "Dart FFI 加载 libgcmvp.dll（修复白屏根因）",
)])

# Sciter/安装路径与便携打包器默认可执行名，避免仍去找 rustdesk.exe
edit("src/platform/windows.rs", [(
    'let dst = dir.join("rustdesk.exe");',
    'let dst = dir.join("gcmvp.exe");',
    "Windows 服务辅助程序名 -> gcmvp.exe",
)])
edit("libs/portable/generate.py", [(
    "options.executable = 'rustdesk.exe'",
    "options.executable = 'gcmvp.exe'",
    "便携打包器默认可执行名 -> gcmvp.exe",
)])
edit("build.py", [(
    "f'python3 ./generate.py -f ../../{flutter_build_dir_2} -o . -e ../../{flutter_build_dir_2}/rustdesk.exe'",
    "f'python3 ./generate.py -f ../../{flutter_build_dir_2} -o . -e ../../{flutter_build_dir_2}/gcmvp.exe'",
    "build.py 便携打包入口 -> gcmvp.exe",
)])

# 隐私模式注入进程名清掉 RustDesk 痕迹（该辅助 exe 不随包交付，仅避免二进制残留）
for f in ["libs/portable/src/main.rs", "src/privacy_mode/win_topmost_window.rs"]:
    edit(f, [(
        '"RuntimeBroker_rustdesk.exe"',
        '"RuntimeBroker_gcmvp.exe"',
        "置顶注入进程名 -> RuntimeBroker_gcmvp.exe",
    )], required=False)

# 全局字符串残留：把面向用户可见的 RustDesk 替换为 GCMVP（谨慎，只处理明确品牌串）
for f in ["src/common.rs", "src/naming.rs", "src/lang/en.rs", "src/lang.rs"]:
    edit(f, [
        ('"RustDesk"', '"GCMVP"', "品牌字符串 -> GCMVP"),
    ], required=False)

# hbb_common 子模块的 APP_NAME / ORG 默认值：这是 get_rustdesk_app_name() 的
# 真正来源，Windows 原生层会用它覆盖 main.cpp 里的 app_name，决定窗口标题。
# 不改这里，标题永远是 "RustDesk"。
edit("libs/hbb_common/src/config.rs", [
    ('RwLock::new("RustDesk".to_owned())',
     'RwLock::new("gcmvp".to_owned())', "APP_NAME 默认值 -> gcmvp"),
], required=False)

# ---------------------------------------------------------------- 需求 4
# 被控端极简 UI：删除警告/品牌/logo/提示/帮助卡片，但必须保留
# buildIDBoard + buildPasswordBoard，否则页面会变成白屏。
edit("flutter/lib/desktop/pages/desktop_home_page.dart", [(
    """      if (!isOutgoingOnly) buildPresetPasswordWarning(),
      if (bind.isCustomClient())
        Align(
          alignment: Alignment.center,
          child: loadPowered(context),
        ),
      Align(
        alignment: Alignment.center,
        child: loadLogo(),
      ),
      buildTip(context),
""",
    """      // gcmvp: minimal UI - only ID and password boards are kept.
""",
    "移除警告/powered/logo/提示，保留识别码与密码面板",
)])
edit("flutter/lib/desktop/pages/desktop_home_page.dart", [(
    """      FutureBuilder<Widget>(
        future: Future.value(
            Obx(() => buildHelpCards(stateGlobal.updateUrl.value))),
        builder: (_, data) {
          if (data.hasData) {
            if (isIncomingOnly) {
              if (isInHomePage()) {
                Future.delayed(Duration(milliseconds: 300), () {
                  _updateWindowSize();
                });
              }
            }
            return data.data!;
          } else {
            return const Offstage();
          }
        },
      ),
""",
    """      // gcmvp: help/update cards hidden.
""",
    "隐藏帮助/更新卡片",
)])

# 关闭行为：恢复官方 setPreventClose(true) —— 点 X 只隐藏窗口，进程常驻后台
# 继续接受远程连接（无人值守）；真正退出用随包的 gcmvp-exit.exe。
# （官方 tabbar_widget.onWindowClose 对主窗口执行 windowManager.hide()，
# 之前改 false 是为修白屏期"关不掉"，白屏根因（FFI）已修复，此处还原。）
# 不做修改，源码保持官方原样即可。

# 窗口标题强制改为 GCMVP（避免运行时配置仍显示 RustDesk）
edit("flutter/lib/common.dart", [(
    "String getWindowName({WindowType? overrideType}) {\n  final name = bind.mainGetAppNameSync();",
    'String getWindowName({WindowType? overrideType}) {\n  final name = "GCMVP"; // gcmvp: forced window title',
    "窗口标题 -> GCMVP",
)])

# 控制端极简 UI：只保留远程 ID 输入框
edit("flutter/lib/desktop/pages/connection_page.dart", [(
    """            Divider().paddingOnly(right: 12),
            Expanded(child: PeerTabPage()),""",
    """            // gcmvp: minimal UI — address book and divider hidden.""",
    "控制端隐藏通讯录与分隔线",
)])

# ---------------------------------------------------------------- 需求 5(构建命名由 workflow 处理)

# ---------------------------------------------------------------- 默认内置选项（APP_NAME）
# 通过编译期环境变量在 workflow 注入，无需改 hbb_common 子模块源码。

# ---------------------------------------------------------------- 可选：编译期注入自建服务器
# 放一个 server-config.json 在脚本同目录（仓库根）即可把 hbbs 地址和公钥写死进二进制，
# 这样 exe 名保持 gcmvp.exe、进程名保持 gcmvp、客户零配置双击即用。
# 文件不存在或 host 为空时，本段完全跳过，不影响其它构建。
#   {"host": "1.2.3.4", "key": "ROx6...NTQ="}
import json
_cfg_path = Path(__file__).resolve().parent / "server-config.json"
if _cfg_path.exists():
    try:
        _cfg = json.loads(_cfg_path.read_text(encoding="utf-8"))
        _host = str(_cfg.get("host", "")).strip()
        _key = str(_cfg.get("key", "")).strip()
        if _host:
            _host_with_port = _host if ":" in _host else f"{_host}:21116"
            edit("libs/hbb_common/src/config.rs", [
                ('pub static ref PROD_RENDEZVOUS_SERVER: RwLock<String> = RwLock::new("".to_owned());',
                 f'pub static ref PROD_RENDEZVOUS_SERVER: RwLock<String> = RwLock::new("{_host_with_port}".to_owned());',
                 f"编译期内置 hbbs 地址 {_host_with_port}"),
                ('pub const RENDEZVOUS_SERVERS: &[&str] = &["rs-ny.rustdesk.com"];',
                 f'pub const RENDEZVOUS_SERVERS: &[&str] = &["{_host}"];',
                 "公共服务器列表替换为自建地址"),
            ] + ([(
                'pub const RS_PUB_KEY: &str = "OeVuKk5nlHiXp+APNn0Y3pC1Iwpwn44JGqrQCsWqmBw=";',
                f'pub const RS_PUB_KEY: &str = "{_key}";',
                "内置 hbbs 公钥",
            )] if _key else []), required=False)
        else:
            print("[INFO] server-config.json 存在但 host 为空，跳过服务器注入")
    except Exception as _e:
        print(f"[WARN] server-config.json 解析失败，跳过服务器注入: {_e}")

print("\n=== summary ===")
from collections import Counter
c = Counter(t for t, _, _ in CHANGES)
for tag in ["OK", "SKIP", "WARN", "MISS", "INFO"]:
    if c[tag]:
        print(f"  {tag}: {c[tag]}")
if c["WARN"]:
    print("\n[!] 有未匹配的片段，请检查上面 WARN 项是否影响需求。")
print("=== done ===")
