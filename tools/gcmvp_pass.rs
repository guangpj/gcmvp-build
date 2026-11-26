// gcmvp-pass: change the shared access password (gcmvp.pwd next to the exe).
// Default password: aa12. Both the controller PC and the remote PC must use
// the SAME password (set on each machine, or copy gcmvp.pwd over).
// Changes apply on the next connection - no restart needed (the password is
// read fresh on every login attempt).
use std::env;
use std::fs;
use std::io::{self, Write};
use std::path::PathBuf;

fn main() {
    let dir: PathBuf = env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()))
        .unwrap_or_else(|| env::current_dir().unwrap_or_default());
    let path = dir.join("gcmvp.pwd");

    let current = fs::read_to_string(&path)
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|_| "aa12 (default, no gcmvp.pwd found)".to_string());

    println!("gcmvp password tool");
    println!("Current password : {}", current);
    println!("Stored as        : {}", path.display());
    println!("Note: both sides read gcmvp.pwd in their own gcmvp folder.");
    println!();
    print!("Enter new password (empty = cancel): ");
    io::stdout().flush().ok();

    let mut s = String::new();
    io::stdin().read_line(&mut s).ok();
    let new_pwd = s.trim().to_string();

    if new_pwd.is_empty() {
        println!("Cancelled. Password unchanged.");
    } else {
        match fs::write(&path, new_pwd.as_bytes()) {
            Ok(_) => {
                println!();
                println!("Saved: {}", path.display());
                println!("IMPORTANT: set the SAME password on the other PC too");
                println!("(run gcmvp-pass.exe there, or copy gcmvp.pwd over).");
                println!("Takes effect on the next connection, no restart needed.");
            }
            Err(e) => println!("Failed to write {}: {}", path.display(), e),
        }
    }

    println!();
    println!("Press Enter to close...");
    io::stdout().flush().ok();
    let mut s = String::new();
    io::stdin().read_line(&mut s).ok();
}
