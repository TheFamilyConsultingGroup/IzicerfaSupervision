const token = location.hash.slice(1);
history.replaceState(null, "", location.pathname);
if (/^[A-Za-z0-9_-]{40,100}$/.test(token)) {
  document.getElementById("token").value = token;
  document.getElementById("confirm").disabled = false;
}
