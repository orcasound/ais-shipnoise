// Reload the page when a new build is published (version.json changes); checked every minute.
// A page can define window.canReload = () => false to postpone the reload, e.g. while audio plays.
(() => {
  const build = document.currentScript.dataset.build;
  setInterval(async () => {
    try {
      // The query string bypasses GitHub Pages' 10-minute CDN cache
      const response = await fetch(`version.json?t=${Date.now()}`, { cache: "no-store" });
      const latest = (await response.json()).build;
      if (latest && latest !== build && (!window.canReload || window.canReload())) {
        // Load with ?v=<build> so the CDN can't hand back the cached old page
        const url = new URL(location.href);
        url.searchParams.set("v", latest);
        location.replace(url);
      }
    } catch (e) {
      // Offline or mid-deploy: try again next minute
    }
  }, 60 * 1000);
})();
