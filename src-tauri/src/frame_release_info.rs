//! Headless release inspection of the *resolved* Tauri ACL; no GTK or installer.
pub fn inspect<R: tauri::Runtime>(context: &mut tauri::Context<R>) -> serde_json::Value {
    let csp_enabled = context.config().app.security.csp.is_some();
    let acl = context.runtime_authority_mut();
    let permitted = |window: &str| {
        acl.resolve_access(
            "plugin:window|close",
            window,
            window,
            &tauri::ipc::Origin::Local,
        )
        .is_some()
    };
    let main = permitted("main");
    let inspector = permitted("lepton-inspect-release-check");
    let unrelated = permitted("unrelated-release-check");
    let updater_allowed = acl.resolve_access("plugin:updater|check", "main", "main",
        &tauri::ipc::Origin::Local).is_some();
    serde_json::json!({
        "schema_version": 1,
        "read_only_release_inspection": true,
        "version": context.package_info().version.to_string(),
        "architecture": std::env::consts::ARCH,
        "production_assets_embedded": cfg!(feature = "custom-protocol"),
        "content_security_policy_enabled": csp_enabled,
        "resolved_window_close": {"main": main, "lepton_inspector": inspector,
            "unrelated_window": unrelated},
        "release_permissions_valid": main && inspector && !unrelated,
        "default_startup_is_legacy": !cfg!(feature = "frame-inspector-only"),
        "updater_check_allowed": updater_allowed,
        "inspector_distribution_only": cfg!(feature = "frame-inspector-only")
    })
}

#[cfg(test)]
mod tests {
    #[test]
    fn compiled_acl_allows_inspector_close_and_rejects_unrelated_window() {
        let mut context: tauri::Context<tauri::Wry> = tauri::generate_context!();
        let report = super::inspect(&mut context);
        assert_eq!(report["release_permissions_valid"], true);
        assert_eq!(report["read_only_release_inspection"], true);
        assert_eq!(report["inspector_distribution_only"], cfg!(feature = "frame-inspector-only"));
        assert_eq!(report["default_startup_is_legacy"], !cfg!(feature = "frame-inspector-only"));
    }
}
