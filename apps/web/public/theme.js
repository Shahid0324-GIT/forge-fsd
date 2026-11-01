// Apply the saved preference before React loads to avoid a bright flash.
(() => {
  let preference = 'system';
  try { preference = localStorage.getItem('forge.theme') || 'system'; } catch {}
  const dark = preference === 'dark' || (preference !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
})();
