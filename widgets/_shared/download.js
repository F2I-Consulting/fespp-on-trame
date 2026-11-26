// The browser takes `urls` (relative to the page, as the upload's), one after
// the other, each under the name its `file=` parameter gives.
export function downloadAll(urls) {
  (urls || []).forEach((url, i) => {
    setTimeout(() => {
      const link = document.createElement("a");
      link.href = new URL(url, window.location.href).href;
      link.download = decodeURIComponent(String(url).split("file=").pop() || "");
      document.body.appendChild(link);
      link.click();
      link.remove();
    }, 400 * i);
  });
}
