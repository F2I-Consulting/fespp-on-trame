/*
 * Ask the host for something it computes on demand and wait for its answer —
 * the whole filtered table a Copy CSV hands over, when the widget holds one
 * page of it (the Values card).
 *
 * A widget emits; trame drops what a controller returns. So the request
 * carries a fresh number `n`, the host writes its answer `{n, ...}` into the
 * state variable bound to one of the widget's props, and the promise resolves
 * when `read()` (that prop) carries the same `n`. It rejects after
 * `timeoutMs`: an export that never comes says so (FpExport's "Export
 * failed"), it does not hang.
 *
 *   csvText() {
 *     return askHost(this, (n) => this.$emit("export-values", { n }),
 *                    () => this.valuesCsv).then((a) => a.text);
 *   }
 */
let asked = 0;

export function askHost(vm, emit, read, timeoutMs = 60000) {
  asked += 1;
  const n = `${asked}-${Date.now()}`;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      stop();
      reject(new Error("the server did not answer"));
    }, timeoutMs);
    const stop = vm.$watch(read, (answer) => {
      if (!answer || answer.n !== n) return;
      clearTimeout(timer);
      stop();
      resolve(answer);
    });
    emit(n);
  });
}
