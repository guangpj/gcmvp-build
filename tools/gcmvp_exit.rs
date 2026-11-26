// gcmvp-exit: double-click to terminate all running gcmvp.exe processes.
// The main window only hides on close (process stays resident for unattended
// access); this tool is the explicit way to fully stop it.
#![windows_subsystem = "windows"]
use std::os::windows::process::CommandExt;
use std::process::Command;

#[link(name = "user32")]
extern "system" {
    fn MessageBoxW(hwnd: *mut core::ffi::c_void,
                   text: *const u16,
                   caption: *const u16,
                   typ: u32) -> i32;
}

fn to_wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

fn main() {
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    const MB_INFORMATION: u32 = 0x40;

    let ok = Command::new("taskkill")
        .args(["/F", "/T", "/IM", "gcmvp.exe"])
        .creation_flags(CREATE_NO_WINDOW)
        .status()
        .map(|s| s.success())
        .unwrap_or(false);

    let msg = if ok {
        "gcmvp has been stopped.\nAll remote sessions were closed."
    } else {
        "gcmvp is not running."
    };

    unsafe {
        MessageBoxW(std::ptr::null_mut(),
                    to_wide(msg).as_ptr(),
                    to_wide("gcmvp-exit").as_ptr(),
                    MB_INFORMATION);
    }
}
