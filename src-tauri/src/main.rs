// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use serde::Deserialize;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State};
use tauri::path::BaseDirectory;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

#[cfg(windows)]
use win32job::Job;

const MACS_DOWNLOAD_URL: &str = "https://www.macs-steel.org/";

/// Holds the running sidecar process + the port it bound to.
///
/// On Windows, also holds a Job Object handle with `KILL_ON_JOB_CLOSE`. The
/// job object is what guarantees the sidecar dies when this process dies for
/// *any* reason — graceful exit, panic, NSIS update killing us, Task Manager
/// — without which PyInstaller's `_internal/*.dll` stays locked and the next
/// install fails. We keep the handle in app state so the only point at which
/// the job is destroyed is when the parent process exits.
struct SidecarState {
    port: u16,
    log_dir: PathBuf,
    child: Mutex<Option<Child>>,
    #[cfg(windows)]
    _job: Option<Job>,
}

#[derive(Deserialize)]
struct HealthResponse {
    #[allow(dead_code)]
    sidecar: String,
    macs_installed: bool,
    macs_version: Option<String>,
}

/// Reserve an OS-assigned free TCP port on 127.0.0.1, then close the socket so
/// the sidecar can bind to it. There's a tiny TOCTOU window — acceptable for a
/// single-user desktop app.
fn pick_free_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind("127.0.0.1:0")?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

/// Spawn the Python FastAPI sidecar.
///
/// Dev (debug builds): runs `python -m macs_automation.app --port <N>` from the
/// project root (one level above `src-tauri/`). Prefers the 32-bit venv-32
/// interpreter so FRACOF COM is reachable without extra setup.
///
/// Prod (release builds): runs the PyInstaller-produced onedir bundle shipped
/// via Tauri's `bundle.resources`. The exe lives at
/// `<Resource>/binaries/i-macs-sidecar-x86_64-pc-windows-msvc/i-macs-sidecar.exe`;
/// CWD is set to that directory so PyInstaller's `_MEIPASS`-relative imports work.
///
/// `log_dir` is forwarded as `--log-dir` so the sidecar writes a rotating
/// `sidecar.log` for post-mortem debugging on user machines.
fn spawn_sidecar(
    app: &AppHandle,
    port: u16,
    log_dir: &std::path::Path,
) -> Result<Child, String> {
    let log_dir_str = log_dir.to_string_lossy().into_owned();
    let app_version = app.package_info().version.to_string();

    if cfg!(debug_assertions) {
        // Project root = parent of src-tauri/
        let manifest_dir = env!("CARGO_MANIFEST_DIR");
        let project_root = std::path::Path::new(manifest_dir)
            .parent()
            .ok_or_else(|| "could not resolve project root".to_string())?
            .to_path_buf();

        // Prefer the 32-bit venv interpreter (FRACOF COM is 32-bit), then
        // fall back to a generic venv, then PATH.
        let venv32_python = project_root.join("venv-32").join("Scripts").join("python.exe");
        let venv_python = project_root.join("venv").join("Scripts").join("python.exe");
        let python_cmd = if venv32_python.exists() {
            venv32_python.to_string_lossy().into_owned()
        } else if venv_python.exists() {
            venv_python.to_string_lossy().into_owned()
        } else {
            "python".to_string()
        };

        // Dev: no MACS_DB_PATH set, so the sidecar falls back to
        // <repo>/results.db (where the user's accumulated dev history
        // already lives).
        return Command::new(python_cmd)
            .args([
                "-m",
                "macs_automation.app",
                "--port",
                &port.to_string(),
                "--log-dir",
                &log_dir_str,
            ])
            .env("MACS_APP_VERSION", &app_version)
            .current_dir(&project_root)
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| format!("failed to spawn dev sidecar: {e}"));
    }

    // Production: locate the bundled sidecar exe. Tauri's resource glob
    // handling can map `binaries/<dir>/**/*` to either `<Resource>/<dir>/...`
    // or `<Resource>/...` depending on convention; probe a small set rather
    // than commit to one and break when versions shift.
    let candidate_relative_paths = [
        "binaries/i-macs-sidecar-x86_64-pc-windows-msvc/i-macs-sidecar.exe",
        "i-macs-sidecar-x86_64-pc-windows-msvc/i-macs-sidecar.exe",
        "i-macs-sidecar.exe",
    ];
    let resolver = app.path();
    let sidecar_exe = candidate_relative_paths
        .iter()
        .filter_map(|rel| resolver.resolve(rel, BaseDirectory::Resource).ok())
        .find(|p| p.exists())
        .ok_or_else(|| {
            format!(
                "Could not locate bundled sidecar in Resource dir. Tried: {}",
                candidate_relative_paths.join(", ")
            )
        })?;

    let sidecar_dir = sidecar_exe
        .parent()
        .ok_or_else(|| "no parent for sidecar exe".to_string())?
        .to_path_buf();

    // %LOCALAPPDATA%\i-macs\results.db on Windows — same convention as
    // log_dir. Without this the bundled sidecar resolved DB_PATH relative
    // to __file__ inside _internal\, which Windows either ACL-denies (data
    // wiped each launch) or silently virtualizes into VirtualStore (data
    // exists but the user can't find it). See issue #11.
    let db_path = resolver
        .resolve("i-macs/results.db", BaseDirectory::LocalData)
        .map_err(|e| format!("resolve db_path: {e}"))?;
    if let Some(parent) = db_path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("create_dir_all db_path parent: {e}"))?;
    }

    Command::new(&sidecar_exe)
        .args(["--port", &port.to_string(), "--log-dir", &log_dir_str])
        .env("MACS_DB_PATH", &db_path)
        .env("MACS_APP_VERSION", &app_version)
        .current_dir(&sidecar_dir)
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("failed to spawn release sidecar: {e}"))
}

/// Block until `GET http://127.0.0.1:<port>/healthz` returns HTTP 200, parse
/// the body so the caller can decide whether to nag about MACS+ being missing.
fn wait_for_health(port: u16, timeout: Duration) -> Result<HealthResponse, String> {
    let url = format!("http://127.0.0.1:{port}/healthz");
    let deadline = Instant::now() + timeout;
    let mut last_err = String::from("not ready");

    while Instant::now() < deadline {
        match ureq::get(&url).timeout(Duration::from_millis(500)).call() {
            Ok(resp) if resp.status() == 200 => {
                return resp
                    .into_json::<HealthResponse>()
                    .map_err(|e| format!("decode /healthz body: {e}"));
            }
            Ok(resp) => {
                last_err = format!("status {}", resp.status());
            }
            Err(e) => {
                last_err = e.to_string();
            }
        }
        thread::sleep(Duration::from_millis(200));
    }
    Err(format!("sidecar /healthz never went green: {last_err}"))
}

/// Show the "MACS+ is missing — please install it from macs-steel.org" dialog
/// when /healthz reports macs_installed=false. Non-blocking so the user can
/// still see the rest of the UI and read logs.
fn show_macs_missing_dialog(app: &AppHandle) {
    let app_for_dialog = app.clone();
    let _ = app
        .dialog()
        .message(format!(
            "MACS+ is not installed on this machine.\n\n\
             i-macs needs MACS+ to drive its FRACOF calculation engine. \
             Install MACS+ from {MACS_DOWNLOAD_URL}, then restart i-macs.\n\n\
             You can keep using the app to inspect logs and previous results, \
             but new calculations will fail until MACS+ is present."
        ))
        .title("MACS+ not detected")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Open download page".into(),
            "Continue".into(),
        ))
        .show(move |opened| {
            if opened {
                use tauri_plugin_opener::OpenerExt;
                let _ = app_for_dialog.opener().open_url(MACS_DOWNLOAD_URL, None::<&str>);
            }
        });
}

#[tauri::command]
fn get_sidecar_port(state: State<SidecarState>) -> u16 {
    state.port
}

/// Path to the directory that contains sidecar.log. The React
/// SidecarErrorScreen surfaces this so the user can paste the log into
/// a bug report or open the folder via plugin-opener.
#[tauri::command]
fn get_log_dir(state: State<SidecarState>) -> String {
    state.log_dir.to_string_lossy().into_owned()
}

/// Explicitly stop the sidecar. Called from the JS updater before
/// `downloadAndInstall()` so NSIS doesn't fight a live PyInstaller for
/// `_internal/*.dll` locks. The Job Object also catches this case, but
/// kicking the child first lets the OS release file handles deterministically
/// (see Tauri issue #12309 for the race we're sidestepping).
#[tauri::command]
fn shutdown_sidecar(state: State<SidecarState>) -> Result<(), String> {
    let mut guard = state
        .child
        .lock()
        .map_err(|e| format!("sidecar lock poisoned: {e}"))?;
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
        println!("[tauri] sidecar shut down on request");
    }
    Ok(())
}

/// Bind the freshly spawned sidecar to a Job Object so it inherits this
/// process's lifetime. KILL_ON_JOB_CLOSE means: when our last handle to the
/// job closes (which happens when our process dies, however it dies), the
/// kernel terminates every member. PyInstaller's onedir bootstrap re-execs
/// into `_internal\`, but `AssignProcessToJobObject` propagates by default,
/// so assigning the bootstrap PID covers the re-exec too.
#[cfg(windows)]
fn assign_sidecar_to_job(child: &Child) -> Result<Job, String> {
    use std::os::windows::io::AsRawHandle;

    let job = Job::create().map_err(|e| format!("CreateJobObject: {e}"))?;
    let mut info = job
        .query_extended_limit_info()
        .map_err(|e| format!("query_extended_limit_info: {e}"))?;
    info.limit_kill_on_job_close();
    job.set_extended_limit_info(&info)
        .map_err(|e| format!("set_extended_limit_info: {e}"))?;
    job.assign_process(child.as_raw_handle() as isize)
        .map_err(|e| format!("AssignProcessToJobObject: {e}"))?;
    Ok(job)
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            let port = pick_free_port().map_err(|e| format!("pick_free_port: {e}"))?;
            println!("[tauri] picked sidecar port: {port}");

            // %LOCALAPPDATA%\i-macs\logs on Windows.
            let log_dir = app
                .path()
                .resolve("i-macs/logs", BaseDirectory::LocalData)
                .map_err(|e| format!("resolve log_dir: {e}"))?;
            std::fs::create_dir_all(&log_dir)
                .map_err(|e| format!("create_dir_all log_dir: {e}"))?;
            println!("[tauri] sidecar log_dir: {}", log_dir.display());

            let child = spawn_sidecar(app.handle(), port, &log_dir)?;
            println!("[tauri] sidecar spawned (pid {})", child.id());

            #[cfg(windows)]
            let job = match assign_sidecar_to_job(&child) {
                Ok(j) => {
                    println!("[tauri] sidecar bound to Job Object (KILL_ON_JOB_CLOSE)");
                    Some(j)
                }
                Err(err) => {
                    eprintln!(
                        "[tauri] WARNING: Job Object setup failed: {err} — sidecar may orphan if parent dies abruptly"
                    );
                    None
                }
            };

            // Health-check on a worker thread so the window can come up while
            // the sidecar finishes booting; surface the MACS+-missing dialog
            // once the response lands.
            let app_handle_for_health = app.handle().clone();
            thread::spawn(move || {
                match wait_for_health(port, Duration::from_secs(30)) {
                    Ok(health) => {
                        println!(
                            "[tauri] /healthz alive: macs_installed={} version={:?}",
                            health.macs_installed, health.macs_version
                        );
                        if !health.macs_installed {
                            show_macs_missing_dialog(&app_handle_for_health);
                        }
                        // Let the React side know the sidecar is ready so it
                        // can drop any "starting…" UI and fetch ref-data.
                        let _ = app_handle_for_health.emit("sidecar-ready", &health.macs_installed);
                    }
                    Err(err) => {
                        eprintln!("[tauri] WARNING: {err}");
                        let _ = app_handle_for_health.emit("sidecar-error", err);
                    }
                }
            });

            app.manage(SidecarState {
                port,
                log_dir,
                child: Mutex::new(Some(child)),
                #[cfg(windows)]
                _job: job,
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_sidecar_port,
            get_log_dir,
            shutdown_sidecar
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<SidecarState>() {
                    if let Ok(mut guard) = state.child.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                            println!("[tauri] sidecar killed");
                        }
                    }
                }
            }
        });
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;

    /// Spawns a long-running child, assigns it to a Job Object, drops the
    /// job, and verifies the kernel terminated the child via
    /// KILL_ON_JOB_CLOSE. This is the load-bearing safety net that makes
    /// auto-updates immune to PyInstaller orphan sidecars — if it ever
    /// regresses, NSIS installs will start failing on locked DLLs again.
    #[test]
    fn job_object_kills_child_when_dropped() {
        let mut child = Command::new("ping")
            .args(["-n", "60", "127.0.0.1"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn ping");

        {
            let job = assign_sidecar_to_job(&child).expect("assign to job");
            // Job dropped at end of scope -> KILL_ON_JOB_CLOSE fires.
            drop(job);
        }

        let deadline = Instant::now() + Duration::from_secs(5);
        while Instant::now() < deadline {
            match child.try_wait() {
                Ok(Some(_)) => return,
                Ok(None) => thread::sleep(Duration::from_millis(50)),
                Err(e) => panic!("try_wait error: {e}"),
            }
        }

        let _ = child.kill();
        panic!("child still alive after job dropped — KILL_ON_JOB_CLOSE did not fire");
    }
}
