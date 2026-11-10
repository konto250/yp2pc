"use strict";

const form = document.querySelector("#convert-form");
const input = document.querySelector("#playlist-url");
const submit = document.querySelector("#submit-button");
const progress = document.querySelector("#progress");
const errorBox = document.querySelector("#error");
const result = document.querySelector("#result");
const feedUrl = document.querySelector("#feed-url");
const copyButton = document.querySelector("#copy-button");
const copyStatus = document.querySelector("#copy-status");
let copyTimer;

function durationText(seconds) {
  if (!seconds) return "";
  const minutes = Math.floor(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}時間${minutes % 60}分` : `${minutes}分`;
}

function showFeed(data) {
  document.querySelector("#result-title").textContent = data.title;
  document.querySelector("#result-meta").textContent = `${data.author} · ${data.episodes.length}エピソード`;
  feedUrl.value = data.feedUrl;
  document.querySelector("#rss-link").href = data.feedUrl;
  document.querySelector("#youtube-link").href = data.playlistUrl;
  document.querySelector("#local-warning").hidden = !data.local;
  const warnings = [];
  if (data.totalCount > data.limit) warnings.push(`全${data.totalCount}件のうち先頭${data.limit}件を確認しました。`);
  if (data.issues.length) warnings.push(data.issues.map((issue) => `${issue.id}: ${issue.message}`).join(" "));
  const warning = document.querySelector("#partial-warning");
  warning.textContent = warnings.join(" ");
  warning.hidden = warnings.length === 0;
  const list = document.querySelector("#episodes");
  list.replaceChildren();
  for (const episode of data.episodes) {
    const item = document.createElement("li");
    if (episode.artworkUrl) {
      const thumbnail = document.createElement("img");
      thumbnail.src = episode.artworkUrl;
      thumbnail.alt = `${episode.title}のサムネイル`;
      thumbnail.className = "episode-thumbnail";
      thumbnail.width = 120;
      thumbnail.height = 120;
      thumbnail.loading = "lazy";
      item.append(thumbnail);
    }
    const title = document.createElement("strong");
    title.textContent = episode.title;
    const meta = document.createElement("span");
    meta.className = "episode-meta";
    meta.textContent = [durationText(episode.duration), `${(episode.size / 1000000).toFixed(1)} MB`].filter(Boolean).join(" · ");
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "none";
    // 同じ画面のオリジンで試聴します。本番用RSSのURLとは独立です。
    audio.src = `/audio/${encodeURIComponent(episode.id)}.m4a`;
    audio.setAttribute("aria-label", `${episode.title}を試聴`);
    const message = document.createElement("p");
    message.className = "audio-message";
    message.setAttribute("role", "status");
    audio.addEventListener("waiting", () => { message.textContent = "音声を読み込んでいます…"; });
    audio.addEventListener("playing", () => { message.textContent = ""; });
    audio.addEventListener("error", () => { message.textContent = "音声を再生できませんでした。YouTube側の制限または接続エラーの可能性があります。再度RSSを作成してお試しください。"; });
    item.append(title, meta, audio, message);
    list.append(item);
  }
  document.querySelector("#episode-count").textContent = `（${data.episodes.length}件）`;
  copyStatus.textContent = "このURLをPodcastアプリに登録してください。";
  copyButton.textContent = "URLをコピー";
  result.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (submit.disabled) return;
  submit.disabled = true;
  submit.querySelector("span").textContent = "確認中…";
  input.readOnly = true;
  progress.hidden = false;
  errorBox.hidden = true;
  result.querySelectorAll("audio").forEach((audio) => audio.pause());
  result.hidden = true;
  form.setAttribute("aria-busy", "true");
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 3600000);
  try {
    const response = await fetch("/api/feeds", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: input.value.trim() }), signal: controller.signal,
    });
    let data;
    try { data = await response.json(); } catch { throw new Error("サーバーから応答を取得できませんでした。時間をおいて再試行してください。"); }
    if (!response.ok) throw new Error(data.error || "フィードを作成できませんでした。");
    showFeed(data);
    result.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "nearest" });
  } catch (error) {
    errorBox.textContent = error.name === "AbortError" ? "取得がタイムアウトしました。時間をおいて再試行してください。" : (error.message || "接続できませんでした。");
    errorBox.hidden = false;
  } finally {
    clearTimeout(timer);
    progress.hidden = true;
    submit.disabled = false;
    submit.querySelector("span").textContent = "RSSを作成";
    input.readOnly = false;
    form.setAttribute("aria-busy", "false");
  }
});

copyButton.addEventListener("click", async () => {
  clearTimeout(copyTimer);
  try {
    if (!navigator.clipboard) throw new Error("コピー機能を利用できません。");
    await navigator.clipboard.writeText(feedUrl.value);
    copyButton.textContent = "コピーしました ✓";
    copyStatus.textContent = "RSSのURLをコピーしました。";
    copyTimer = setTimeout(() => { copyButton.textContent = "URLをコピー"; }, 2500);
  } catch {
    feedUrl.focus();
    feedUrl.select();
    feedUrl.setSelectionRange(0, feedUrl.value.length);
    if (document.execCommand("copy")) {
      copyButton.textContent = "コピーしました ✓";
      copyStatus.textContent = "RSSのURLをコピーしました。";
    } else {
      copyStatus.textContent = "URLを長押しして「コピー」を選んでください。PCではCtrl+C / ⌘Cも使えます。";
    }
  }
});
