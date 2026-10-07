/** @typedef {"manual" | "issues" | "requests" | "home" | "releases" | "tomato_jianpu"} HelpDestination */
/** @typedef {{status: "available" | "up_to_date" | "unknown_version" | "unavailable", current_version: string, latest_version: string | null}} UpdateResult */

/** @param {HelpDestination} destination @param {string} language */
export async function openHelpDestination(destination, language) {
  if (!["manual", "issues", "requests", "home", "releases", "tomato_jianpu"].includes(destination)) {
    throw new Error("Unsupported help destination.");
  }
  const invoke = window.__TAURI__?.core.invoke;
  if (!invoke) throw new Error("Opening Help links requires the desktop application.");
  await invoke("open_help_destination", { destination, language });
}

/** @returns {Promise<UpdateResult>} */
export async function checkForUpdate() {
  const invoke = window.__TAURI__?.core.invoke;
  if (!invoke) throw new Error("Checking updates requires the desktop application.");
  const result = await invoke("check_for_update", {});
  if (!result || !["available", "up_to_date", "unknown_version", "unavailable"].includes(result.status)
    || typeof result.current_version !== "string"
    || !(result.latest_version === null || typeof result.latest_version === "string")
    || (result.status !== "unavailable" && !result.latest_version)) {
    throw new Error("Invalid update response.");
  }
  return result;
}
