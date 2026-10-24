const HOST_SYSTEM = {linux: "linux", win32: "windows", darwin: "darwin"};

/**
 * Browser builds retain source fonts; desktop builds register application fonts only on Linux.
 * @param {{mode?: string, targetTriple?: string, hostPlatform?: string}} options
 */
export function shouldRegisterBundledFontFaces({
  mode = "development",
  targetTriple = process.env.TAURI_ENV_TARGET_TRIPLE,
  hostPlatform = process.platform,
} = {}) {
  if (mode !== "desktop") return true;
  const targetSystem = targetTriple ? targetTriple.split("-")[2] : HOST_SYSTEM[hostPlatform];
  return targetSystem === "linux";
}

/** Desktop targets use their target platform; browser builds detect the client at runtime. */
export function uiFontPlatformForTarget({
  mode = "development",
  targetTriple = process.env.TAURI_ENV_TARGET_TRIPLE,
  hostPlatform = process.platform,
} = {}) {
  if (mode !== "desktop") return "browser";
  const targetSystem = targetTriple ? targetTriple.split("-")[2] : HOST_SYSTEM[hostPlatform];
  return targetSystem === "darwin" ? "macos" : targetSystem;
}

/** Browser builds serve fonts from public assets; desktop builds load Linux assets from Tauri. */
export function shouldCopyFontAssetsToFrontend(desktop) {
  return !desktop;
}
