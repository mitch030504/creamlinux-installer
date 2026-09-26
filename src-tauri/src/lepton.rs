use crate::installer::Game;
use log::{debug, warn};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Structured information returned from Lepton runtime introspection.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq)]
pub struct LeptonIntrospection {
    /// Whether Valve's host Lepton CLI is available on the system.
    pub available: bool,
    /// Whether the Lepton container context for this game is currently running.
    pub running: bool,
    /// The Lepton container context name (e.g. "steamlaunch-1408230").
    pub context: Option<String>,
    /// The Android package identifier (e.g. "com.MightyCoconut.WalkaboutMiniGolf").
    pub package: Option<String>,
    /// The detected primary ABI of the package (e.g. "arm64-v8a", "armeabi-v7a").
    pub primary_abi: Option<String>,
    /// Full path to base.apk inside the Android container.
    pub apk_path: Option<String>,
    /// Full path to libsteam_api.so inside the Android container if found.
    pub steam_api_path: Option<String>,
}

/// Locate Valve's host Lepton CLI tool.
///
/// Priority:
/// 1. `LEPTON_CLI_PATH` or `LEPTON_PATH` environment variable override.
/// 2. Default Steam Frame installation: `~/.local/share/Steam/steamapps/common/Lepton/lepton`
/// 3. Other common Linux / SteamOS Steam paths.
/// 4. System `PATH`.
pub fn find_lepton_cli() -> Option<PathBuf> {
    if let Ok(env_path) = std::env::var("LEPTON_CLI_PATH").or_else(|_| std::env::var("LEPTON_PATH"))
    {
        let p = PathBuf::from(env_path);
        if p.is_file() {
            return Some(p);
        }
    }

    if let Ok(home) = std::env::var("HOME") {
        let default_lepton =
            PathBuf::from(&home).join(".local/share/Steam/steamapps/common/Lepton/lepton");
        if default_lepton.is_file() {
            return Some(default_lepton);
        }

        let common_locations = [
            ".steam/steam/steamapps/common/Lepton/lepton",
            ".steam/root/steamapps/common/Lepton/lepton",
            ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps/common/Lepton/lepton",
        ];
        for rel in &common_locations {
            let p = PathBuf::from(&home).join(rel);
            if p.is_file() {
                return Some(p);
            }
        }
    }

    if let Some(paths) = std::env::var_os("PATH") {
        for dir in std::env::split_paths(&paths) {
            let candidate = dir.join("lepton");
            if candidate.is_file() {
                return Some(candidate);
            }
        }
    }

    None
}

/// Helper to execute a command via host Lepton CLI with a strict timeout.
pub async fn run_lepton_command(
    lepton_path: &Path,
    args: &[&str],
    timeout_duration: Duration,
) -> Result<(i32, String, String), String> {
    debug!("Executing Lepton command: {:?} {:?}", lepton_path, args);

    let command_future = tokio::process::Command::new(lepton_path)
        .args(args)
        .output();

    match tokio::time::timeout(timeout_duration, command_future).await {
        Ok(Ok(output)) => {
            let code = output.status.code().unwrap_or(-1);
            let stdout = String::from_utf8_lossy(&output.stdout).to_string();
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            Ok((code, stdout, stderr))
        }
        Ok(Err(e)) => Err(format!("Failed to execute {:?}: {}", lepton_path, e)),
        Err(_) => Err(format!(
            "Command {:?} {:?} timed out after {:?}",
            lepton_path, args, timeout_duration
        )),
    }
}

/// Parse the output of `lepton ps` (or `lepton list_containers`) to see if the target context is running.
///
/// Output lines typically look like:
/// `steamlaunch-1408230 (10.88.0.2, adb on 5555, ... packages: com.MightyCoconut.WalkaboutMiniGolf)`
pub fn parse_lepton_ps(output: &str, target_context: &str) -> (bool, Option<String>) {
    let mut is_running = false;
    let mut discovered_pkg: Option<String> = None;

    for line in output.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with(target_context) {
            let remainder = &trimmed[target_context.len()..];
            if remainder.is_empty() || remainder.starts_with(' ') || remainder.starts_with('(') {
                is_running = true;
                if let Some(pkg_idx) = trimmed.find("packages:") {
                    let after_pkg = &trimmed[pkg_idx + "packages:".len()..];
                    let pkg_name = after_pkg
                        .trim_matches(|c: char| c == ' ' || c == ')' || c == '(')
                        .split(',')
                        .next()
                        .unwrap_or("")
                        .trim();
                    if !pkg_name.is_empty() {
                        discovered_pkg = Some(pkg_name.to_string());
                    }
                }
                break;
            }
        }
    }

    (is_running, discovered_pkg)
}

/// Parse output of `pm path <package>`.
///
/// Returns the path to base.apk (or primary apk).
///
/// Example outputs:
/// `package:/data/app/~~HASH/com.pkg-HASH/base.apk`
/// `package:/data/app/~~HASH/com.pkg-HASH/base.apk\npackage:/data/app/~~HASH/com.pkg-HASH/split.apk`
pub fn parse_pm_path(output: &str) -> Option<String> {
    let mut fallback_path: Option<String> = None;

    for line in output.lines() {
        let trimmed = line.trim().trim_end_matches('\r');
        let path = if let Some(stripped) = trimmed.strip_prefix("package:") {
            stripped.trim()
        } else if trimmed.starts_with('/') && trimmed.ends_with(".apk") {
            trimmed
        } else {
            continue;
        };

        if path.is_empty() {
            continue;
        }

        if path.ends_with("base.apk") {
            return Some(path.to_string());
        }

        if fallback_path.is_none() {
            fallback_path = Some(path.to_string());
        }
    }

    fallback_path
}

/// Derive the package installation root directory from base.apk path.
///
/// E.g. `/data/app/~~HASH/com.pkg-HASH/base.apk` -> `/data/app/~~HASH/com.pkg-HASH`
pub fn derive_package_install_root(apk_path: &str) -> Option<String> {
    let path = Path::new(apk_path);
    let parent = path.parent()?;
    let parent_str = parent.to_string_lossy().to_string();
    if parent_str.is_empty() || parent_str == "/" {
        None
    } else {
        Some(parent_str)
    }
}

/// Parse primary ABI from `dumpsys package <package>` or `getprop ro.product.cpu.abi`.
///
/// Typical dumpsys output:
/// `primaryCpuAbi=arm64-v8a`
/// `primaryCpuAbi: arm64-v8a`
/// `Primary ABI: arm64-v8a`
pub fn parse_primary_abi(output: &str) -> Option<String> {
    if let Ok(dumpsys_regex) = Regex::new(r"(?i)primary(?:cpu)?abi\s*[:=]\s*([a-zA-Z0-9_\-]+)") {
        for line in output.lines() {
            let trimmed = line.trim().trim_end_matches('\r');
            if let Some(caps) = dumpsys_regex.captures(trimmed) {
                if let Some(val_match) = caps.get(1) {
                    let val = val_match.as_str().trim();
                    if !val.is_empty() && val != "null" && val != "none" {
                        return Some(val.to_string());
                    }
                }
            }
        }
    }

    // Direct token fallback (e.g. from getprop ro.product.cpu.abi)
    let known_abis = [
        "arm64-v8a",
        "armeabi-v7a",
        "armeabi",
        "x86_64",
        "x86",
        "riscv64",
    ];
    for line in output.lines() {
        let trimmed = line.trim().trim_end_matches('\r');
        for abi in &known_abis {
            if trimmed.eq_ignore_ascii_case(abi) {
                return Some(abi.to_string());
            }
        }
    }

    None
}

/// Parse discovery output searching for `<package-install-root>/lib/*/libsteam_api.so`.
pub fn parse_steam_api_path(output: &str) -> Option<String> {
    for line in output.lines() {
        let trimmed = line.trim().trim_end_matches('\r');
        if trimmed.starts_with('/') && trimmed.ends_with("libsteam_api.so") {
            return Some(trimmed.to_string());
        }
    }
    None
}

/// Inspect a Lepton / Android game from the Linux host.
///
/// Guarantees:
/// - Only operates on `GameRuntime::LeptonAndroid`.
/// - Does not start the container if it is not currently running.
/// - Treats an idle / non-running container as a normal non-fatal state.
/// - Queries package information dynamically via `pm path` and `dumpsys`.
/// - Does not modify or copy any Android packages or libraries.
pub async fn inspect_game(game: &Game) -> LeptonIntrospection {
    let lepton_cli = find_lepton_cli();
    inspect_game_with_cli(game, lepton_cli.as_deref()).await
}

async fn inspect_game_with_cli(game: &Game, lepton_cli: Option<&Path>) -> LeptonIntrospection {
    let context = game
        .lepton_context
        .clone()
        .unwrap_or_else(|| format!("steamlaunch-{}", game.id));
    let mut package = game.android_package.clone();
    debug!("Inspecting Lepton context {}", context);

    let lepton_cli = match lepton_cli {
        Some(path) => path,
        None => {
            debug!(
                "Lepton CLI not found on host; context={} running=false",
                context
            );
            return LeptonIntrospection {
                available: false,
                running: false,
                context: Some(context),
                package,
                primary_abi: None,
                apk_path: None,
                steam_api_path: None,
            };
        }
    };

    // `ps` lists inactive contexts too and may contain ANSI colors. Only a
    // successful no-op inside the context establishes that it is running.
    let is_running = match run_lepton_command(
        lepton_cli,
        &["exec", &context, "true"],
        Duration::from_secs(5),
    )
    .await
    {
        Ok((code, stdout, stderr)) => {
            debug!(
                "Lepton running probe: context={} exit_status={} stdout={:?} stderr={:?}",
                context, code, stdout, stderr
            );
            if code == 0 {
                true
            } else if stdout.contains("not a running context")
                || stderr.contains("not a running context")
            {
                debug!(
                    "Lepton context {} is idle (normal non-fatal state)",
                    context
                );
                false
            } else {
                warn!(
                    "Lepton running probe failed: context={} exit_status={} stdout={:?} stderr={:?}; treating as not running",
                    context, code, stdout, stderr
                );
                false
            }
        }
        Err(e) => {
            warn!(
                "Lepton running probe could not complete: context={} exit_status=unavailable stdout=unavailable stderr=unavailable error={}; treating as not running",
                context, e
            );
            false
        }
    };
    debug!("Lepton context={} running={}", context, is_running);

    if !is_running {
        return LeptonIntrospection {
            available: true,
            running: false,
            context: Some(context),
            package,
            primary_abi: None,
            apk_path: None,
            steam_api_path: None,
        };
    }

    // Preserve the optional package metadata fallback. A listing failure must
    // never override the successful running-state probe.
    if package.is_none() {
        match run_lepton_command(lepton_cli, &["ps"], Duration::from_secs(5)).await {
            Ok((0, stdout, _)) => package = parse_lepton_ps(&stdout, &context).1,
            Ok((code, _, stderr)) => warn!(
                "Lepton package metadata query failed: context={} exit_status={} stderr={:?}",
                context, code, stderr
            ),
            Err(e) => warn!(
                "Failed to query Lepton package metadata: context={} error={}",
                context, e
            ),
        }
    }

    // Context is running! Query details inside container without starting or modifying anything.
    let mut apk_path = None;
    let mut install_root = None;
    let mut primary_abi = None;
    let mut steam_api_path = None;

    if let Some(pkg) = &package {
        // 1. Query apk_path via `pm path <package>`
        match run_lepton_command(
            &lepton_cli,
            &["exec", &context, "pm", "path", pkg],
            Duration::from_secs(5),
        )
        .await
        {
            Ok((code, stdout, stderr)) => {
                if stderr.contains("is not a running context") {
                    debug!(
                        "Container {} stopped before pm path; final running=false",
                        context
                    );
                    return LeptonIntrospection {
                        available: true,
                        running: false,
                        context: Some(context),
                        package,
                        primary_abi: None,
                        apk_path: None,
                        steam_api_path: None,
                    };
                }
                if code == 0 {
                    apk_path = parse_pm_path(&stdout);
                    install_root = apk_path.as_deref().and_then(derive_package_install_root);
                }
            }
            Err(e) => warn!("Failed to run pm path in Lepton context {}: {}", context, e),
        }

        // 2. Query ABI via `dumpsys package <package>`
        match run_lepton_command(
            &lepton_cli,
            &["exec", &context, "dumpsys", "package", pkg],
            Duration::from_secs(5),
        )
        .await
        {
            Ok((code, stdout, _)) if code == 0 => {
                primary_abi = parse_primary_abi(&stdout);
            }
            Ok(_) | Err(_) => {}
        }
    }

    // Fallback for ABI via getprop if dumpsys didn't provide it
    if primary_abi.is_none() {
        if let Ok((code, stdout, _)) = run_lepton_command(
            &lepton_cli,
            &["exec", &context, "getprop", "ro.product.cpu.abi"],
            Duration::from_secs(5),
        )
        .await
        {
            if code == 0 {
                primary_abi = parse_primary_abi(&stdout);
            }
        }
    }

    // 3. Steam API discovery: <package-install-root>/lib/*/libsteam_api.so
    if let Some(root) = &install_root {
        let lib_dir = format!("{}/lib", root);
        match run_lepton_command(
            &lepton_cli,
            &[
                "exec",
                &context,
                "find",
                &lib_dir,
                "-name",
                "libsteam_api.so",
            ],
            Duration::from_secs(5),
        )
        .await
        {
            Ok((code, stdout, _)) if code == 0 => {
                steam_api_path = parse_steam_api_path(&stdout);
            }
            _ => {}
        }

        if steam_api_path.is_none() {
            let ls_cmd = format!("ls {}/*/libsteam_api.so 2>/dev/null", lib_dir);
            if let Ok((code, stdout, _)) = run_lepton_command(
                &lepton_cli,
                &["exec", &context, "sh", "-c", &ls_cmd],
                Duration::from_secs(5),
            )
            .await
            {
                if code == 0 {
                    steam_api_path = parse_steam_api_path(&stdout);
                }
            }
        }
    }

    debug!(
        "Lepton inspection complete: context={} running=true",
        context
    );
    LeptonIntrospection {
        available: true,
        running: true,
        context: Some(context),
        package,
        primary_abi,
        apk_path,
        steam_api_path,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_pm_path_single_base_apk() {
        let output =
            "package:/data/app/~~6d2vA==/com.MightyCoconut.WalkaboutMiniGolf-4b1sB==/base.apk\n";
        assert_eq!(
            parse_pm_path(output),
            Some(
                "/data/app/~~6d2vA==/com.MightyCoconut.WalkaboutMiniGolf-4b1sB==/base.apk"
                    .to_string()
            )
        );
    }

    #[test]
    fn test_parse_pm_path_with_splits() {
        let output = "\
package:/data/app/~~xyz123/com.example.game-abc456/base.apk
package:/data/app/~~xyz123/com.example.game-abc456/split_config.arm64_v8a.apk
";
        assert_eq!(
            parse_pm_path(output),
            Some("/data/app/~~xyz123/com.example.game-abc456/base.apk".to_string())
        );
    }

    #[test]
    fn test_parse_pm_path_crlf_and_whitespace() {
        let output = "  package:/data/app/com.example-1/base.apk\r\n";
        assert_eq!(
            parse_pm_path(output),
            Some("/data/app/com.example-1/base.apk".to_string())
        );
    }

    #[test]
    fn test_parse_pm_path_missing_or_error() {
        assert_eq!(parse_pm_path(""), None);
        assert_eq!(parse_pm_path("Error: package not found\n"), None);
    }

    #[test]
    fn test_derive_package_install_root() {
        let apk = "/data/app/~~6d2vA==/com.MightyCoconut.WalkaboutMiniGolf-4b1sB==/base.apk";
        assert_eq!(
            derive_package_install_root(apk),
            Some("/data/app/~~6d2vA==/com.MightyCoconut.WalkaboutMiniGolf-4b1sB==".to_string())
        );

        assert_eq!(derive_package_install_root("/base.apk"), None);
        assert_eq!(derive_package_install_root(""), None);
    }

    #[test]
    fn test_parse_primary_abi_dumpsys_arm64() {
        let dumpsys_output = "\
Package [com.MightyCoconut.WalkaboutMiniGolf] (8fa9e10):
    userId=10042
    pkg=Package{1a2b3c com.MightyCoconut.WalkaboutMiniGolf}
    codePath=/data/app/~~6d2vA==/com.MightyCoconut.WalkaboutMiniGolf-4b1sB==
    primaryCpuAbi=arm64-v8a
    secondaryCpuAbi=null
";
        assert_eq!(
            parse_primary_abi(dumpsys_output),
            Some("arm64-v8a".to_string())
        );
    }

    #[test]
    fn test_parse_primary_abi_dumpsys_armeabi_v7a() {
        let dumpsys_output = "    primaryCpuAbi: armeabi-v7a\r\n";
        assert_eq!(
            parse_primary_abi(dumpsys_output),
            Some("armeabi-v7a".to_string())
        );
    }

    #[test]
    fn test_parse_primary_abi_dumpsys_null() {
        let dumpsys_output = "    primaryCpuAbi=null\n    secondaryCpuAbi=null\n";
        assert_eq!(parse_primary_abi(dumpsys_output), None);
    }

    #[test]
    fn test_parse_primary_abi_getprop_token() {
        let getprop_output = "arm64-v8a\n";
        assert_eq!(
            parse_primary_abi(getprop_output),
            Some("arm64-v8a".to_string())
        );

        let getprop_output_x86_64 = "x86_64\r\n";
        assert_eq!(
            parse_primary_abi(getprop_output_x86_64),
            Some("x86_64".to_string())
        );
    }

    #[test]
    fn test_parse_primary_abi_empty_or_invalid() {
        assert_eq!(parse_primary_abi(""), None);
        assert_eq!(parse_primary_abi("unknown_arch_string"), None);
    }

    #[test]
    fn test_parse_steam_api_path_found() {
        let find_output = "/data/app/~~6d2vA==/com.MightyCoconut.WalkaboutMiniGolf-4b1sB==/lib/arm64/libsteam_api.so\n";
        assert_eq!(
            parse_steam_api_path(find_output),
            Some("/data/app/~~6d2vA==/com.MightyCoconut.WalkaboutMiniGolf-4b1sB==/lib/arm64/libsteam_api.so".to_string())
        );
    }

    #[test]
    fn test_parse_steam_api_path_crlf_and_multiple() {
        let output = "\
/data/app/~~xyz/com.test-1/lib/arm64/libsteam_api.so\r
/data/app/~~xyz/com.test-1/lib/arm/libsteam_api.so\r
";
        assert_eq!(
            parse_steam_api_path(output),
            Some("/data/app/~~xyz/com.test-1/lib/arm64/libsteam_api.so".to_string())
        );
    }

    #[test]
    fn test_parse_steam_api_path_not_found() {
        assert_eq!(parse_steam_api_path(""), None);
        assert_eq!(
            parse_steam_api_path("find: '/lib': No such file or directory"),
            None
        );
    }

    #[test]
    fn test_parse_lepton_ps_running_with_package() {
        let ps_output = "\
dev (10.88.0.3, adb on 5556, gdb on 6667)
steamlaunch-1408230 (10.88.0.2, adb on 5555, gdb on 6666, lldb on 7777, packages: com.MightyCoconut.WalkaboutMiniGolf)
";
        let (running, pkg) = parse_lepton_ps(ps_output, "steamlaunch-1408230");
        assert!(running);
        assert_eq!(pkg, Some("com.MightyCoconut.WalkaboutMiniGolf".to_string()));
    }

    #[test]
    fn test_parse_lepton_ps_not_running() {
        let ps_output = "dev (10.88.0.3, adb on 5556, gdb on 6667)\n";
        let (running, pkg) = parse_lepton_ps(ps_output, "steamlaunch-1408230");
        assert!(!running);
        assert_eq!(pkg, None);
    }

    #[test]
    fn test_parse_lepton_ps_empty() {
        let (running, pkg) = parse_lepton_ps("", "steamlaunch-1408230");
        assert!(!running);
        assert_eq!(pkg, None);
    }

    fn walkabout_game() -> Game {
        Game {
            id: "1408230".to_string(),
            title: "Walkabout Mini Golf".to_string(),
            path: "/path/to/game".to_string(),
            runtime: crate::searcher::GameRuntime::LeptonAndroid,
            native: false,
            api_files: Vec::new(),
            android_package: Some("com.MightyCoconut.WalkaboutMiniGolf".to_string()),
            lepton_context: Some("steamlaunch-1408230".to_string()),
            cream_installed: false,
            smoke_installed: false,
            installing: false,
        }
    }

    fn assert_no_android_details(result: &LeptonIntrospection) {
        assert!(!result.running);
        assert_eq!(result.primary_abi, None);
        assert_eq!(result.apk_path, None);
        assert_eq!(result.steam_api_path, None);
    }

    #[tokio::test]
    async fn test_inspect_game_cli_missing_returns_non_fatal() {
        let result = inspect_game_with_cli(&walkabout_game(), None).await;
        assert!(!result.available);
        assert_no_android_details(&result);
        assert_eq!(result.context.as_deref(), Some("steamlaunch-1408230"));
        assert_eq!(
            result.package.as_deref(),
            Some("com.MightyCoconut.WalkaboutMiniGolf")
        );
    }

    #[cfg(unix)]
    mod probe {
        use super::*;
        use std::os::unix::fs::PermissionsExt;

        const PROBE: &str = "exec steamlaunch-1408230 true\n";

        // Exercise the real subprocess runner and inspection flow, recording every
        // invocation so an unexpected ps dependency or idle Android query fails.
        fn fake_cli(probe_body: &str, ps_body: &str) -> tempfile::TempDir {
            let dir = tempfile::tempdir_in(env!("CARGO_MANIFEST_DIR")).unwrap();
            let path = dir.path().join("lepton");
            let script = format!(
                r#"#!/bin/sh
printf '%s\n' "$*" >> "$0.calls"
case "$*" in
  'exec steamlaunch-1408230 true')
    {probe_body}
    ;;
  'ps')
    {ps_body}
    ;;
  'exec steamlaunch-1408230 pm path com.MightyCoconut.WalkaboutMiniGolf')
    echo 'package:/data/app/walkabout/base.apk'
    ;;
  'exec steamlaunch-1408230 dumpsys package com.MightyCoconut.WalkaboutMiniGolf')
    echo 'primaryCpuAbi=arm64-v8a'
    ;;
  'exec steamlaunch-1408230 find /data/app/walkabout/lib -name libsteam_api.so')
    echo '/data/app/walkabout/lib/arm64/libsteam_api.so'
    ;;
  'exec steamlaunch-1408230 getprop ro.product.cpu.abi')
    echo 'arm64-v8a'
    ;;
  *) echo "Unexpected command: $*" >&2; exit 99 ;;
esac
"#
            );
            std::fs::write(&path, script).unwrap();
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
            dir
        }

        fn calls(dir: &tempfile::TempDir) -> String {
            std::fs::read_to_string(dir.path().join("lepton.calls")).unwrap()
        }

        #[tokio::test]
        async fn probe_exit_zero_runs_android_inspection_in_order_without_ps() {
            let dir = fake_cli("exit 0", "exit 99");
            let result =
                inspect_game_with_cli(&walkabout_game(), Some(&dir.path().join("lepton"))).await;
            assert!(result.available);
            assert!(result.running);
            assert_eq!(result.primary_abi.as_deref(), Some("arm64-v8a"));
            assert_eq!(
                result.apk_path.as_deref(),
                Some("/data/app/walkabout/base.apk")
            );
            assert_eq!(
                result.steam_api_path.as_deref(),
                Some("/data/app/walkabout/lib/arm64/libsteam_api.so")
            );
            assert_eq!(
                calls(&dir),
                concat!(
                "exec steamlaunch-1408230 true\n",
                "exec steamlaunch-1408230 pm path com.MightyCoconut.WalkaboutMiniGolf\n",
                "exec steamlaunch-1408230 dumpsys package com.MightyCoconut.WalkaboutMiniGolf\n",
                "exec steamlaunch-1408230 find /data/app/walkabout/lib -name libsteam_api.so\n",
            )
            );
        }

        #[tokio::test]
        async fn probe_not_running_skips_all_android_inspection() {
            // A listed context must not override the authoritative exec result.
            let dir = fake_cli(
                "echo \"ERROR: 'steamlaunch-1408230' is not a running context\" >&2; exit 1",
                "echo 'steamlaunch-1408230 (packages: com.MightyCoconut.WalkaboutMiniGolf)'",
            );
            let result =
                inspect_game_with_cli(&walkabout_game(), Some(&dir.path().join("lepton"))).await;
            assert!(result.available);
            assert_no_android_details(&result);
            assert_eq!(calls(&dir), PROBE);
        }

        #[tokio::test]
        async fn arbitrary_probe_failure_is_non_fatal_and_skips_inspection() {
            let dir = fake_cli(
                "echo 'partial output'; echo 'transport unavailable' >&2; exit 42",
                "exit 99",
            );
            let result =
                inspect_game_with_cli(&walkabout_game(), Some(&dir.path().join("lepton"))).await;
            assert!(result.available);
            assert_no_android_details(&result);
            assert_eq!(calls(&dir), PROBE);
        }

        #[tokio::test]
        async fn probe_spawn_failure_is_non_fatal() {
            let dir = fake_cli("exit 0", "exit 99");
            let path = dir.path().join("lepton");
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
            let result = inspect_game_with_cli(&walkabout_game(), Some(&path)).await;
            assert!(result.available);
            assert_no_android_details(&result);
            assert!(!dir.path().join("lepton.calls").exists());
        }

        #[tokio::test]
        async fn optional_ps_failure_cannot_override_successful_probe() {
            let dir = fake_cli("exit 0", "exit 99");
            let mut game = walkabout_game();
            game.android_package = None;
            let result = inspect_game_with_cli(&game, Some(&dir.path().join("lepton"))).await;
            assert!(result.available);
            assert!(result.running);
            assert_eq!(result.package, None);
            assert_eq!(result.primary_abi.as_deref(), Some("arm64-v8a"));
            assert_eq!(result.apk_path, None);
            assert_eq!(result.steam_api_path, None);
            assert_eq!(
                calls(&dir),
                concat!(
                    "exec steamlaunch-1408230 true\n",
                    "ps\n",
                    "exec steamlaunch-1408230 getprop ro.product.cpu.abi\n",
                )
            );
        }

        #[tokio::test]
        async fn optional_ps_package_metadata_is_preserved_after_probe() {
            let dir = fake_cli(
                "exit 0",
                "echo 'steamlaunch-1408230 (packages: com.MightyCoconut.WalkaboutMiniGolf)'",
            );
            let mut game = walkabout_game();
            game.android_package = None;
            let result = inspect_game_with_cli(&game, Some(&dir.path().join("lepton"))).await;
            assert!(result.running);
            assert_eq!(result.package, walkabout_game().android_package);
            assert_eq!(
                result.apk_path.as_deref(),
                Some("/data/app/walkabout/base.apk")
            );
            assert_eq!(
                calls(&dir),
                concat!(
                "exec steamlaunch-1408230 true\n",
                "ps\n",
                "exec steamlaunch-1408230 pm path com.MightyCoconut.WalkaboutMiniGolf\n",
                "exec steamlaunch-1408230 dumpsys package com.MightyCoconut.WalkaboutMiniGolf\n",
                "exec steamlaunch-1408230 find /data/app/walkabout/lib -name libsteam_api.so\n",
            )
            );
        }
    }
}
