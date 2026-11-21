/* The upstream app owns chat and inference. This file only joins its navigation. */
(() => {
  const header = document.querySelector(".st-header") || document.querySelector("body.strata-api-monitor > header");
  if (!header || document.getElementById("strata-console-link")) return;
  const fallback = new URL(location.href);
  fallback.port = location.protocol === "https:" ? "5667" : "5666";
  fallback.pathname = "/app/ai-workstation/"; fallback.search = ""; fallback.hash = "";
  let consoleUrl = fallback;
  try {
    const requested = new URL(new URL(location.href).searchParams.get("console") || fallback.href);
    if (["http:", "https:"].includes(requested.protocol) && requested.hostname === location.hostname &&
        requested.pathname === "/app/ai-workstation/" && !requested.username && !requested.password) consoleUrl = requested;
  } catch (_) {}
  const link = document.createElement("a");
  link.id = "strata-console-link"; link.className = "st-header__console";
  link.href = consoleUrl.href; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = "模型管理";
  link.setAttribute("aria-label", "打开 Strata 模型管理");
  const tabs = header.querySelector(".st-tabs");
  if (tabs) tabs.before(link); else header.append(link);
})();
