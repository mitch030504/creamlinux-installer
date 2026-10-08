//! Manual, read-only host analysis; the Python sources are embedded for AppImages.
use crate::{installer::Game, lepton};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Stdio;

#[derive(Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct CompatibilityResult {
    pub analyzed: bool,
    pub steam_api_found: bool,
    pub architecture: Option<String>,
    pub total_public_exports: Option<usize>,
    pub function_exports: Option<usize>,
    pub supported_function_exports: Option<usize>,
    pub unsupported_exports: Vec<String>,
    pub required_unsupported_exports: Vec<String>,
    pub proxy_compatible: Option<bool>,
    pub compatibility_scope: Option<String>,
    pub notes: Vec<String>,
    pub provider_sha256: Option<String>,
    pub current_proxy: Option<serde_json::Value>,
    pub consumer_evidence: Option<serde_json::Value>,
    pub runtime_resolution_evidence: Option<serde_json::Value>,
    pub target_specific_forwarding: Option<serde_json::Value>,
    pub analysis_exit_code: Option<i32>,
}

/// Explicit, read-only artifact inspection. Nothing is generated or installed.
#[derive(Debug, Default, Deserialize)]
pub struct ArtifactOptions {
    pub target_proxy_dir: Option<PathBuf>,
    pub hardware_bundle: Option<PathBuf>,
    pub hardware_results: Option<PathBuf>,
}

impl ArtifactOptions {
    fn validate(&self) -> Result<(), String> {
        if self.hardware_bundle.is_some() != self.hardware_results.is_some()
            || (self.hardware_bundle.is_some() && self.target_proxy_dir.is_none())
        {
            return Err("Select a generated proxy directory and both the hardware bundle and results directory.".into());
        }
        for path in [
            &self.target_proxy_dir,
            &self.hardware_bundle,
            &self.hardware_results,
        ]
        .into_iter()
        .flatten()
        {
            if !path.is_absolute() || !path.exists() {
                return Err(
                    "Selected validation artifacts must exist at absolute local paths.".into(),
                );
            }
        }
        Ok(())
    }
}

fn reader_path(resources: Option<&Path>) -> Option<PathBuf> {
    // Explicit overrides are deliberately returned even when broken: Python's
    // capability check must report the failure instead of silently falling back.
    if let Some(path) = std::env::var_os("CREAMLINUX_LLVM_READELF") {
        return Some(PathBuf::from(path));
    }
    resources
        .map(|root| root.join("compatibility/runtime/bin/llvm-readelf"))
        .filter(|path| path.is_file())
}

fn incomplete(note: impl Into<String>) -> CompatibilityResult {
    CompatibilityResult {
        notes: vec![note.into()],
        analysis_exit_code: Some(2),
        ..Default::default()
    }
}

fn prerequisite(info: &lepton::LeptonIntrospection) -> Option<CompatibilityResult> {
    let note = if !info.available {
        "Lepton CLI is unavailable."
    } else if !info.running {
        "Lepton game is not running or its running probe failed."
    } else if info.package.is_none()
        || info.context.is_none()
        || info.apk_path.is_none()
        || info.steam_api_path.is_none()
        || info.primary_abi.is_none()
    {
        "Package, ABI, APK, or Steam API path is unavailable; analysis is incomplete."
    } else {
        return None;
    };
    Some(incomplete(note))
}

pub async fn analyze(
    game: &Game,
    resources: Option<&Path>,
    artifacts: ArtifactOptions,
) -> CompatibilityResult {
    if !game.runtime.is_lepton() {
        return incomplete("Compatibility analysis only supports Lepton games.");
    }
    if let Err(error) = artifacts.validate() {
        return incomplete(error);
    }
    let cli = lepton::find_lepton_cli();
    let info = lepton::inspect_game_with_cli(game, cli.as_deref()).await;
    if let Some(result) = prerequisite(&info) {
        return result;
    }
    match run(
        cli.as_deref().unwrap(),
        &info,
        reader_path(resources).as_deref(),
        &artifacts,
    )
    .await
    {
        Ok(result) => result,
        Err(error) => incomplete(format!("Analysis incomplete: {error}")),
    }
}

async fn run(
    cli: &Path,
    info: &lepton::LeptonIntrospection,
    reader: Option<&Path>,
    artifacts: &ArtifactOptions,
) -> Result<CompatibilityResult, String> {
    let temp = tempfile::tempdir().map_err(|e| e.to_string())?;
    let root = temp.path();
    let files = [
        (
            "compatibility.py",
            include_str!("../../tools/android-steam-proxy/compatibility.py"),
        ),
        (
            "tests/scan_consumers.py",
            include_str!("../../tools/android-steam-proxy/tests/scan_consumers.py"),
        ),
        (
            "generated/reference-manifest.json",
            include_str!("../../tools/android-steam-proxy/generated/reference-manifest.json"),
        ),
        (
            "validation_evidence.py",
            include_str!("../../tools/android-steam-proxy/validation_evidence.py"),
        ),
        (
            "generate.py",
            include_str!("../../tools/android-steam-proxy/generate.py"),
        ),
        (
            "generate_target_proxy.py",
            include_str!("../../tools/android-steam-proxy/generate_target_proxy.py"),
        ),
        (
            "verify_target_proxy.py",
            include_str!("../../tools/android-steam-proxy/verify_target_proxy.py"),
        ),
    ];
    for (name, content) in files {
        let path = root.join(name);
        std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
        std::fs::write(path, content).map_err(|e| e.to_string())?;
    }
    let mut command = host_python();
    command
        .arg(root.join("compatibility.py"))
        .arg("live")
        .arg("--lepton")
        .arg(cli)
        .arg("--context")
        .arg(info.context.as_deref().ok_or("Missing context")?)
        .arg("--package")
        .arg(info.package.as_deref().ok_or("Missing package")?)
        .arg("--json")
        .env("TMPDIR", root)
        .env("PYTHONNOUSERSITE", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    if let Some(reader) = reader {
        command.arg("--readelf").arg(reader);
    }
    for (flag, path) in [
        ("--target-proxy-dir", &artifacts.target_proxy_dir),
        ("--hardware-bundle", &artifacts.hardware_bundle),
        ("--hardware-results", &artifacts.hardware_results),
    ] {
        if let Some(path) = path {
            command.arg(flag).arg(path);
        }
    }
    let child = command
        .spawn()
        .map_err(|e| format!("Host Python 3 unavailable: {e}"))?;
    let output = tokio::time::timeout(
        std::time::Duration::from_secs(600),
        child.wait_with_output(),
    )
    .await
    .map_err(|_| "Host analysis timed out after 10 minutes".to_string())?
    .map_err(|e| e.to_string())?;
    decode_output(output)
}

fn host_python() -> tokio::process::Command {
    // AppRun sets PYTHONHOME/PYTHONPATH for bundled apps, but this analyzer
    // deliberately uses host Python and its complete standard library.
    let mut command = tokio::process::Command::new("python3");
    command
        .args(["-E", "-s", "-B"])
        .env_remove("LD_PRELOAD")
        .env_remove("LD_LIBRARY_PATH");
    command
}

fn decode_output(output: std::process::Output) -> Result<CompatibilityResult, String> {
    // Completed incompatibility (1) and expected operational failures (2) both
    // carry useful JSON. Keep the CLI's conservative conclusions unchanged.
    if !matches!(output.status.code(), Some(0..=2)) {
        return Err(format!(
            "Host analyzer failed: {}",
            String::from_utf8_lossy(&output.stderr)
        ));
    }
    let mut result: CompatibilityResult = serde_json::from_slice(&output.stdout).map_err(|e| {
        format!(
            "Invalid analyzer result (exit {:?}): {e}; {}",
            output.status.code(),
            String::from_utf8_lossy(&output.stderr)
                .chars()
                .take(4000)
                .collect::<String>()
        )
    })?;
    result.analysis_exit_code = output.status.code();
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn info() -> lepton::LeptonIntrospection {
        lepton::LeptonIntrospection {
            available: true,
            running: true,
            context: Some("steamlaunch-1408230".into()),
            package: Some("com.example".into()),
            primary_abi: Some("arm64-v8a".into()),
            apk_path: Some("/data/app/base.apk".into()),
            steam_api_path: Some("/data/app/lib/arm64/libsteam_api.so".into()),
        }
    }
    #[test]
    fn serialization_preserves_unknown_and_false() {
        for compatible in [None, Some(false), Some(true)] {
            let result = CompatibilityResult {
                proxy_compatible: compatible,
                ..Default::default()
            };
            let json = serde_json::to_string(&result).unwrap();
            assert_eq!(
                serde_json::from_str::<CompatibilityResult>(&json).unwrap(),
                result
            );
            assert!(json.contains("\"function_exports\":null"));
        }
    }
    #[test]
    fn unavailable_cli() {
        let mut state = info();
        state.available = false;
        let result = prerequisite(&state).unwrap();
        assert_eq!(result.proxy_compatible, None);
        assert!(result.notes[0].contains("CLI"));
    }
    #[test]
    fn not_running() {
        let mut state = info();
        state.running = false;
        assert_eq!(prerequisite(&state).unwrap().proxy_compatible, None);
    }
    #[test]
    fn missing_paths_are_incomplete() {
        let mut state = info();
        state.steam_api_path = None;
        assert!(!prerequisite(&state).unwrap().analyzed);
        assert!(prerequisite(&info()).is_none());
    }
    #[test]
    fn separate_states_survive_backend_roundtrip() {
        let mut result = incomplete("fixture");
        result.proxy_compatible = Some(false);
        result.provider_sha256 = Some("provider-hash".into());
        result.current_proxy = Some(serde_json::json!({"compatible":false}));
        result.target_specific_forwarding = Some(serde_json::json!({
            "generation_status":"hardware_validated", "validated":false,
            "validation_evidence":{"provider_sha256":"provider-hash", "scope":"function harness only"}}));
        let restored: CompatibilityResult =
            serde_json::from_slice(&serde_json::to_vec(&result).unwrap()).unwrap();
        assert_eq!(result, restored);
        assert_eq!(restored.proxy_compatible, Some(false));
    }
    #[test]
    fn legacy_results_without_new_fields_still_deserialize() {
        let mut value = serde_json::to_value(incomplete("legacy")).unwrap();
        for key in [
            "provider_sha256",
            "current_proxy",
            "consumer_evidence",
            "runtime_resolution_evidence",
            "target_specific_forwarding",
        ] {
            value.as_object_mut().unwrap().remove(key);
        }
        let restored: CompatibilityResult = serde_json::from_value(value).unwrap();
        assert_eq!(restored.target_specific_forwarding, None);
    }
    #[test]
    fn partial_hardware_evidence_is_rejected() {
        let options = ArtifactOptions {
            hardware_results: Some("/fixture".into()),
            ..Default::default()
        };
        assert!(options.validate().is_err());
        assert!(ArtifactOptions::default().validate().is_ok());
    }
    #[tokio::test]
    async fn host_python_ignores_appimage_python_paths() {
        let output = host_python()
            .args([
                "-c",
                "import encodings,json; print(json.dumps({'stdlib': True}))",
            ])
            .env("PYTHONHOME", "/nonexistent-appimage/usr")
            .env("PYTHONPATH", "/nonexistent-appimage/usr/share/pyshared")
            .output()
            .await
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&output.stdout).unwrap()["stdlib"],
            true
        );
    }
    #[cfg(unix)]
    #[test]
    fn startup_failure_keeps_analyzer_diagnostic() {
        use std::os::unix::process::ExitStatusExt;
        let error = decode_output(std::process::Output {
            status: std::process::ExitStatus::from_raw(2 << 8),
            stdout: vec![],
            stderr: b"cannot open analyzer script".to_vec(),
        })
        .unwrap_err();
        assert!(error.contains("cannot open analyzer script"));
        assert!(error.contains("Some(2)"));
    }
}
