; NSIS installer hooks (wired via bundle.windows.nsis.installerHooks).
;
; The default NSIS update overlays new files onto $INSTDIR without deleting
; files the new version no longer ships. The sidecar's _internal tree
; accumulated packages from every prior release (websockets/httptools from
; the uvicorn[standard] era), and rc.13's newer uvicorn crashed at boot
; against the rc.10-era leftovers on every updated machine.
;
; Removing the whole staged sidecar dir before install is safe: it contains
; only bundled resources. User data (results.db) lives under app-data, which
; main.rs resolves and creates separately.
!macro NSIS_HOOK_PREINSTALL
  RMDir /r "$INSTDIR\binaries"
!macroend
