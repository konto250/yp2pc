"use strict";
const form = document.querySelector("#login-form");
const errorBox = document.querySelector("#login-error");
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  errorBox.hidden = true;
  try {
    const response = await fetch("/api/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: document.querySelector("#password").value }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "ログインできませんでした。");
    document.querySelector("#password").value = "";
    location.replace("/");
  } catch (error) {
    errorBox.textContent = error.message || "接続できませんでした。";
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
  }
});
