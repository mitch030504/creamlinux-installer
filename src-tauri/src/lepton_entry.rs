//! Read-only entry points avoid all installer startup and mutation handlers.
use crate::{installer::Game, lepton_compatibility::ArtifactOptions, searcher::GameRuntime};

pub struct InspectorRequest {
    pub game: Game,
    pub headless: bool,
    pub artifacts: ArtifactOptions,
}

/// Frame distribution never falls through to legacy startup, even via its ELF.
pub fn frame_entry_allowed(args: &[String]) -> bool {
    matches!(args.first().map(String::as_str),
        Some("--lepton-inspector" | "--lepton-compatibility" | "--lepton-release-info"))
}

#[cfg(test)]
mod distribution_tests {
    #[test]
    fn frame_distribution_rejects_default_and_unknown_startup() {
        for first in [None, Some("--install"), Some("--anything")] {
            let args = first.into_iter().map(str::to_owned).collect::<Vec<_>>();
            assert!(!super::frame_entry_allowed(&args));
        }
        for first in ["--lepton-inspector", "--lepton-compatibility", "--lepton-release-info"] {
            assert!(super::frame_entry_allowed(&[first.into()]));
        }
    }
}

pub fn parse(args: &[String]) -> Result<Option<InspectorRequest>, String> {
    let headless = match args.first().map(String::as_str) {
        Some("--lepton-compatibility") => true,
        Some("--lepton-inspector") => false,
        _ => return Ok(None),
    };
    let id = args.get(1).filter(|s| !s.is_empty() && s.len() <= 10 && s.bytes().all(|b| b.is_ascii_digit()))
        .ok_or("Usage: --lepton-compatibility APPID [--target-proxy-dir PATH --hardware-bundle PATH --hardware-results PATH] or --lepton-inspector APPID")?;
    let mut artifacts = ArtifactOptions::default();
    let rest = &args[2..];
    if !headless && !rest.is_empty() {
        return Err(
            "Inspector launch accepts only an AppID; select artifacts in the inspector.".into(),
        );
    }
    if rest.len() % 2 != 0 {
        return Err("Validation artifact options need a path.".into());
    }
    for pair in rest.chunks_exact(2) {
        let slot = match pair[0].as_str() {
            "--target-proxy-dir" => &mut artifacts.target_proxy_dir,
            "--hardware-bundle" => &mut artifacts.hardware_bundle,
            "--hardware-results" => &mut artifacts.hardware_results,
            _ => return Err("Unknown read-only compatibility option.".into()),
        };
        if slot.is_some() {
            return Err("Duplicate validation artifact option.".into());
        }
        *slot = Some(pair[1].clone().into());
    }
    Ok(Some(InspectorRequest {
        headless,
        artifacts,
        game: Game {
            id: id.clone(),
            title: format!("Steam App {id}"),
            path: String::new(),
            runtime: GameRuntime::LeptonAndroid,
            native: false,
            api_files: Vec::new(),
            android_package: None,
            lepton_context: None,
            cream_installed: false,
            smoke_installed: false,
            installing: false,
        },
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn args(values: &[&str]) -> Vec<String> {
        values.iter().map(|s| s.to_string()).collect()
    }
    #[test]
    fn explicit_modes_and_artifacts_only() {
        assert!(parse(&[]).unwrap().is_none());
        let request = parse(&args(&[
            "--lepton-compatibility",
            "448280",
            "--target-proxy-dir",
            "/artifact",
        ]))
        .unwrap()
        .unwrap();
        assert!(request.headless);
        assert!(request.game.runtime.is_lepton());
        assert_eq!(
            request.artifacts.target_proxy_dir.unwrap().to_str(),
            Some("/artifact")
        );
        assert!(
            !parse(&args(&["--lepton-inspector", "448280"]))
                .unwrap()
                .unwrap()
                .headless
        );
    }
    #[test]
    fn invalid_or_mutation_arguments_are_rejected() {
        for values in [
            &["--lepton-inspector", "../448280"][..],
            &["--lepton-compatibility", "448280", "--install", "/game"],
            &[
                "--lepton-inspector",
                "448280",
                "--target-proxy-dir",
                "/artifact",
            ],
            &["--lepton-compatibility"],
            &["--lepton-compatibility", "448280", "--hardware-results"],
        ] {
            assert!(parse(&args(values)).is_err());
        }
    }
}
