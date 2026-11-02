//! PolyMech Studio desktop shell.
//!
//! Starts the bundled Python backend (`backend/polymech-backend`) as a child process, waits for
//! it to print `POLYMECH_PORT=<port>`, then points the main window at http://127.0.0.1:<port>/.
//! The backend listens on loopback only and exits by itself if this process disappears.
//! Native menus forward their actions to the page as `polymech:menu` DOM events.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::menu::{AboutMetadata, MenuBuilder, MenuItemBuilder, PredefinedMenuItem, SubmenuBuilder};
use tauri::webview::DownloadEvent;
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

const STARTUP_TIMEOUT: Duration = Duration::from_secs(240);

struct Backend(Mutex<Option<Child>>);

fn data_dir(app: &AppHandle) -> tauri::Result<PathBuf> {
    if let Some(dir) = std::env::var_os("POLYMECH_DATA_DIR") {
        return Ok(PathBuf::from(dir));
    }
    Ok(app.path().data_dir()?.join("PolyMechStudio"))
}

fn log_dir(app: &AppHandle) -> tauri::Result<PathBuf> {
    #[cfg(windows)]
    return Ok(app.path().local_data_dir()?.join("PolyMechStudio/logs"));
    #[cfg(not(windows))]
    app.path().app_log_dir()
}

fn js_string(s: &str) -> String {
    serde_json::to_string(s).expect("strings are JSON serializable")
}

fn system_accent() -> Option<String> {
    #[cfg(windows)]
    {
        use winreg::{enums::HKEY_CURRENT_USER, RegKey};
        return RegKey::predef(HKEY_CURRENT_USER)
            .open_subkey("Software\\Microsoft\\Windows\\DWM")
            .and_then(|key| key.get_value::<u32, _>("ColorizationColor"))
            .ok().map(|color| format!("#{:06x}", color & 0xffffff));
    }
    #[cfg(not(windows))]
    None
}

fn send_menu_event(window: &WebviewWindow, id: &str) {
    let _ = window.eval(format!(
        "window.dispatchEvent(new CustomEvent('polymech:menu', {{ detail: {} }}))",
        js_string(id)
    ));
}

fn startup_failed(app: &AppHandle, why: &str, log: &Path) {
    if let Some(w) = app.get_webview_window("main") {
        let text = format!("{why}\n\n后端日志：{}", log.display());
        let _ = w.eval(format!(
            "window.polymechStartupFailed && window.polymechStartupFailed({})",
            js_string(&text)
        ));
    }
}

/// ~/Downloads/<name>, with " (n)" appended instead of overwriting an existing file.
/// POLYMECH_DOWNLOAD_DIR overrides the folder (used by the self-test).
fn download_target(dir: &Path, name: &str) -> PathBuf {
    let candidate = dir.join(name);
    if !candidate.exists() {
        return candidate;
    }
    let p = Path::new(name);
    let stem = p.file_stem().and_then(|s| s.to_str()).unwrap_or("download");
    let ext = p.extension().and_then(|s| s.to_str()).map(|e| format!(".{e}")).unwrap_or_default();
    (1_u64..)
        .map(|n| dir.join(format!("{stem} ({n}){ext}")))
        .find(|c| !c.exists())
        .unwrap_or(candidate)
}

fn start_backend(app: &AppHandle) -> tauri::Result<()> {
    let res = app.path().resource_dir()?;
    #[cfg(windows)]
    let exe = res.join("backend/polymech-backend.exe");
    #[cfg(not(windows))]
    let exe = res.join("backend/polymech-backend");
    let web = res.join("web");
    let log_dir = log_dir(app)?;
    fs::create_dir_all(&log_dir)?;
    let log_path = log_dir.join("backend.log");
    let log = File::create(&log_path)?;

    let mut command = Command::new(&exe);
    #[cfg(windows)]
    {
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW; stdout remains the startup pipe
        command.env("POLYMECH_LOCAL_BRIDGE_EXE", res.join("bridge/polymech-bridge.exe"));
    }
    let spawned = command
        .arg("--static")
        .arg(&web)
        .arg("--control-stdin")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(log)
        .spawn();
    let mut child = match spawned {
        Ok(c) => c,
        Err(e) => {
            startup_failed(app, &format!("无法启动本地计算服务：{e}\n{}", exe.display()), &log_path);
            return Ok(());
        }
    };
    let stdout = child.stdout.take();
    app.state::<Backend>().0.lock().unwrap().replace(child);

    let started = Arc::new(AtomicBool::new(false));
    let (handle, flag, log1) = (app.clone(), started.clone(), log_path.clone());
    std::thread::spawn(move || {
        if let Some(out) = stdout {
            for line in BufReader::new(out).lines().map_while(Result::ok) {
                if let Some(port) = line.strip_prefix("POLYMECH_PORT=") {
                    let url = format!("http://127.0.0.1:{}/", port.trim());
                    if let (Some(w), Ok(u)) = (handle.get_webview_window("main"), Url::parse(&url)) {
                        let _ = w.navigate(u);
                        flag.store(true, Ordering::SeqCst);
                        if std::env::var_os("POLYMECH_DESKTOP_SELFTEST").is_some() {
                            selftest_downloads(w);
                        }
                    }
                }
            }
        }
        // stdout closed: the backend has exited
        if !flag.load(Ordering::SeqCst) {
            startup_failed(&handle, "本地计算服务启动失败。", &log1);
        } else if let Some(w) = handle.get_webview_window("main") {
            let _ = w.eval("document.title = 'PolyMech Studio（计算服务已停止）'");
        }
    });
    let (handle, log2) = (app.clone(), log_path);
    std::thread::spawn(move || {
        std::thread::sleep(STARTUP_TIMEOUT);
        if !started.load(Ordering::SeqCst) {
            startup_failed(&handle, "本地计算服务启动超时。", &log2);
        }
    });
    Ok(())
}

/// Self-test (POLYMECH_DESKTOP_SELFTEST=<result file>): once the UI has loaded, trigger the two
/// download kinds the UI uses — a link to a backend URL and a JavaScript blob (api.download).
/// The download handler appends one line per finished download to the result file.
fn selftest_downloads(w: WebviewWindow) {
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_secs(4));
        // WebView2 limits multiple automatic downloads without a user gesture. Its test
        // runs each kind in a fresh window; ordinary exports are initiated by user clicks.
        let kind = if cfg!(windows) {
            std::env::var("POLYMECH_SELFTEST_DOWNLOAD_KIND").unwrap_or_default()
        } else {
            String::new()
        };
        let script = r#"(() => {
                const kind = __KIND__;
                const click = (href, name) => { const a = document.createElement('a'); a.href = href; a.download = name; document.body.append(a); a.click(); a.remove(); };
                if (kind !== 'blob') click('/api/health', 'selftest_link.json');
                if (kind !== 'link') setTimeout(() => click(URL.createObjectURL(new Blob([document.title], { type: 'text/plain' })), 'selftest_blob.txt'), 1500);
            })()"#.replace("__KIND__", &js_string(&kind));
        let _ = w.eval(script);
    });
}

fn selftest_record(line: &str) {
    if let Some(path) = std::env::var_os("POLYMECH_DESKTOP_SELFTEST") {
        use std::io::Write;
        if let Ok(mut f) = fs::OpenOptions::new().create(true).append(true).open(path) {
            let _ = writeln!(f, "{line}");
        }
    }
}

fn stop_backend(app: &AppHandle) {
    if let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() {
        if let Some(mut control) = child.stdin.take() {
            let _ = control.write_all(b"shutdown\n");
        }
        let deadline = Instant::now() + Duration::from_secs(90);
        while Instant::now() < deadline {
            if matches!(child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = child.kill(); // fallback only for the child this application spawned
        let _ = child.wait();
    }
}

fn build_menu(app: &AppHandle) -> tauri::Result<tauri::menu::Menu<tauri::Wry>> {
    let item = |id: &str, text: &str, accel: Option<&str>| {
        let b = MenuItemBuilder::with_id(id, text);
        match accel {
            Some(a) => b.accelerator(a).build(app),
            None => b.build(app),
        }
    };
    let about = AboutMetadata {
        name: Some("PolyMech Studio".into()),
        version: Some(env!("CARGO_PKG_VERSION").into()),
        comments: Some("聚合物弹性体力学数据分析：确定性计算 + AI 辅助理解 + 数据溯源".into()),
        ..Default::default()
    };
    #[cfg(target_os = "macos")]
    let app_menu = SubmenuBuilder::new(app, "PolyMech Studio")
        .item(&PredefinedMenuItem::about(app, Some("关于 PolyMech Studio"), Some(about))?)
        .separator()
        .item(&item("settings", "设置…", Some("CmdOrCtrl+,"))?)
        .separator()
        .item(&PredefinedMenuItem::services(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::hide(app, None)?)
        .item(&PredefinedMenuItem::hide_others(app, None)?)
        .item(&PredefinedMenuItem::show_all(app, None)?)
        .separator()
        .item(&PredefinedMenuItem::quit(app, Some("退出 PolyMech Studio"))?)
        .build()?;
    let file = SubmenuBuilder::new(app, "文件")
        .item(&item("import", "导入数据…", Some("CmdOrCtrl+O"))?)
        .item(&item("export_figure", "导出图片…", Some("CmdOrCtrl+E"))?)
        .separator()
        .item(&item("reveal_data", if cfg!(windows) { "打开数据文件夹" } else { "在 Finder 中显示数据文件夹" }, None)?)
        .item(&item("reveal_logs", if cfg!(windows) { "打开日志文件夹" } else { "在 Finder 中显示日志" }, None)?)
        .separator()
        .item(&PredefinedMenuItem::close_window(app, Some("关闭窗口"))?);
    #[cfg(windows)]
    let file = file
        .separator()
        .item(&item("settings", "设置…", Some("CmdOrCtrl+,"))?)
        .item(&PredefinedMenuItem::quit(app, Some("退出"))?);
    let file = file.build()?;
    let edit = SubmenuBuilder::new(app, "编辑")
        .item(&PredefinedMenuItem::undo(app, Some("撤销"))?)
        .item(&PredefinedMenuItem::redo(app, Some("重做"))?)
        .separator()
        .item(&PredefinedMenuItem::cut(app, Some("剪切"))?)
        .item(&PredefinedMenuItem::copy(app, Some("拷贝"))?)
        .item(&PredefinedMenuItem::paste(app, Some("粘贴"))?)
        .item(&PredefinedMenuItem::select_all(app, Some("全选"))?)
        .build()?;
    let view = SubmenuBuilder::new(app, "显示")
        .item(&item("nav:/", "概览", Some("CmdOrCtrl+1"))?)
        .item(&item("nav:/experiments", "实验", Some("CmdOrCtrl+2"))?)
        .item(&item("nav:/analysis", "分析", Some("CmdOrCtrl+3"))?)
        .item(&item("nav:/plots", "绘图工作室", Some("CmdOrCtrl+4"))?)
        .item(&item("nav:/materials", "材料数据库", Some("CmdOrCtrl+5"))?)
        .item(&item("nav:/reports", "报告", Some("CmdOrCtrl+6"))?)
        .separator()
        .item(&item("toggle_sidebar", "显示/隐藏侧边栏", Some("CmdOrCtrl+Alt+S"))?)
        .item(&item("recalculate", "重新计算", Some("CmdOrCtrl+R"))?)
        .separator()
        .item(&item("reload", "重新载入界面", Some("CmdOrCtrl+Shift+R"))?)
        .item(&PredefinedMenuItem::fullscreen(app, Some("进入全屏幕"))?)
        .build()?;
    #[cfg(target_os = "macos")]
    let window = SubmenuBuilder::new(app, "窗口")
        .item(&PredefinedMenuItem::minimize(app, Some("最小化"))?)
        .item(&PredefinedMenuItem::maximize(app, Some("缩放"))?)
        .build()?;
    #[cfg(target_os = "macos")]
    return MenuBuilder::new(app).items(&[&app_menu, &file, &edit, &view, &window]).build();
    #[cfg(not(target_os = "macos"))]
    {
        let help = SubmenuBuilder::new(app, "帮助")
            .item(&item("nav:/help", "使用说明", Some("F1"))?)
            .item(&PredefinedMenuItem::about(app, Some("关于 PolyMech Studio"), Some(about))?)
            .build()?;
        MenuBuilder::new(app).items(&[&file, &edit, &view, &help]).build()
    }
}

fn reveal_dir(path: PathBuf) {
    #[cfg(windows)]
    let tool = "explorer.exe";
    #[cfg(not(windows))]
    let tool = "open";
    let _ = Command::new(tool).arg(path).spawn();
}

fn on_menu(app: &AppHandle, id: &str) {
    let Some(w) = app.get_webview_window("main") else { return };
    match id {
        "reveal_data" => {
            if let Ok(dir) = data_dir(app) { reveal_dir(dir); }
        }
        "reveal_logs" => {
            if let Ok(dir) = log_dir(app) {
                reveal_dir(dir);
            }
        }
        "reload" => {
            let _ = w.eval("location.reload()");
        }
        other => send_menu_event(&w, other),
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .manage(Backend(Mutex::new(None)))
        .menu(|app| build_menu(app))
        .on_menu_event(|app, event| on_menu(app, event.id().as_ref()))
        .setup(|app| {
            let handle = app.handle().clone();
            let downloads = std::env::var_os("POLYMECH_DOWNLOAD_DIR")
                .map(PathBuf::from)
                .map(Ok)
                .unwrap_or_else(|| app.path().download_dir())?;
            fs::create_dir_all(&downloads)?;
            // WebKit does not report the saved path when a download finishes: remember it by URL
            let pending: Arc<Mutex<HashMap<String, PathBuf>>> = Arc::default();
            let builder = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("PolyMech Studio")
                .inner_size(1440.0, 900.0)
                .min_inner_size(1100.0, 700.0)
                .initialization_script(format!(
                    "window.__POLYMECH_PLATFORM__ = {}; window.__POLYMECH_ACCENT__ = {};",
                    js_string(if cfg!(windows) { "windows" } else { "macos" }),
                    serde_json::to_string(&system_accent()).unwrap()
                ))
                // let the page receive HTML5 drag & drop (file import, Plot Studio series)
                .disable_drag_drop_handler()
                .on_download(move |webview, event| {
                    match event {
                        DownloadEvent::Requested { url, destination } => {
                            let name = destination
                                .file_name()
                                .and_then(|n| n.to_str())
                                .filter(|n| !n.is_empty())
                                .map(str::to_owned)
                                .or_else(|| url.path_segments().and_then(|mut s| s.next_back().map(str::to_owned)))
                                .unwrap_or_else(|| "download".into());
                            *destination = download_target(&downloads, &name);
                            pending.lock().unwrap().insert(url.to_string(), destination.clone());
                        }
                        DownloadEvent::Finished { url, path, success } => {
                            let path = path.or_else(|| pending.lock().unwrap().remove(url.as_str()));
                            selftest_record(&format!(
                                "download {} {}",
                                if success { "ok" } else { "failed" },
                                path.as_ref().map(|p| p.display().to_string()).unwrap_or_default()
                            ));
                            let detail = match (success, path) {
                                (true, Some(p)) => format!("{{ ok: true, path: {} }}", js_string(&p.display().to_string())),
                                _ => "{ ok: false }".to_string(),
                            };
                            let _ = webview.eval(format!(
                                "window.dispatchEvent(new CustomEvent('polymech:downloaded', {{ detail: {detail} }}))"
                            ));
                        }
                        _ => {}
                    }
                    true
                });
            let window = builder.build()?;
            #[cfg(windows)]
            {
                use tauri::window::{Effect, EffectsBuilder};
                use winreg::{enums::HKEY_CURRENT_USER, RegKey};
                let transparency = RegKey::predef(HKEY_CURRENT_USER)
                    .open_subkey("Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize")
                    .and_then(|key| key.get_value::<u32, _>("EnableTransparency"))
                    .unwrap_or(0);
                let reduced = data_dir(&handle).ok()
                    .and_then(|dir| fs::read(dir.join("settings.json")).ok())
                    .and_then(|bytes| serde_json::from_slice::<serde_json::Value>(&bytes).ok())
                    .and_then(|settings| settings.get("reduce_transparency").and_then(|v| v.as_bool()))
                    .unwrap_or(false);
                if transparency == 1 && !reduced {
                    // Unsupported systems retain a solid background; effects never block startup.
                    let _ = window.set_effects(EffectsBuilder::new().effect(Effect::Mica).build());
                }
            }
            #[cfg(not(windows))]
            let _ = window;
            start_backend(&handle)?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build PolyMech Studio");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            stop_backend(handle);
        }
    });
}
