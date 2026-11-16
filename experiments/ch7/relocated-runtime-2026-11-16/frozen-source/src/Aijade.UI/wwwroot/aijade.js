// Small page helpers used by the AIJADE UI.
window.aijadeDownload = (name, text) => {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

// Images are served only with the account's bearer token, so they are fetched by .NET and shown through blob URLs.
window.aijadeBlobUrl = (bytes, mime) => URL.createObjectURL(new Blob([bytes], { type: mime }));
window.aijadeRevokeUrl = (url) => URL.revokeObjectURL(url);
