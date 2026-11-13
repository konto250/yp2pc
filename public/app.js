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
let activeFeedId;

function durationText(seconds) {
  if (!seconds) return "";
  const minutes = Math.floor(seconds / 60);
  return minutes >= 60 ? `${Math.floor(minutes / 60)}時間${minutes % 60}分` : `${minutes}分`;
}

function showFeed(data) {
  activeFeedId = data.id;
  document.querySelector("#result-title").textContent = data.title;
  document.querySelector("#result-meta").textContent = `${data.author} · ${data.episodes.length}エピソード`;
  feedUrl.value = data.feedUrl;
  document.querySelector("#am-feed-url").value = data.amFeedUrl;
  document.querySelector("#am-rss-link").href = data.amFeedUrl;
  document.querySelector("#am-copy-status").textContent = "モノラル・帯域制限・軽い歪みとノイズを加えた別番組です。";
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
    audio.src = `/audio/${encodeURIComponent(episode.id)}.m4a${episode.sha256 ? `?v=${encodeURIComponent(episode.sha256.slice(0, 16))}` : ""}`;
    audio.setAttribute("aria-label", `${episode.title}を試聴`);
    const quality = document.createElement("select");
    quality.setAttribute("aria-label", `${episode.title}の試聴音質`);
    for (const [value, label] of [["normal", "通常音質"], ["am", "AMラジオ音質"]]) {
      const option = document.createElement("option");
      option.value = value; option.textContent = label; quality.append(option);
    }
    const normalSource = audio.src;
    quality.addEventListener("change", () => {
      audio.pause();
      audio.src = quality.value === "am" ? `/audio/${encodeURIComponent(episode.id)}.am.m4a` : normalSource;
      message.textContent = "再生ボタンで選んだ音質を試聴できます。";
    });
    const message = document.createElement("p");
    message.className = "audio-message";
    message.setAttribute("role", "status");
    audio.addEventListener("waiting", () => { message.textContent = "音声を読み込んでいます…"; });
    audio.addEventListener("playing", () => { message.textContent = ""; });
    audio.addEventListener("error", () => { message.textContent = "保存済み音声を再生できませんでした。接続を確認して再試行してください。AM版が未生成の場合は、同じプレイリストを再登録してください。"; });
    item.append(title, meta, quality, audio, message);
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
    if (response.status === 401) { location.replace("/login"); throw new Error("再ログインしてください。"); }
    let data;
    try { data = await response.json(); } catch { throw new Error("サーバーから応答を取得できませんでした。時間をおいて再試行してください。"); }
    if (!response.ok) throw new Error(data.error || "フィードを作成できませんでした。");
    showFeed(data);
    await loadFeeds();
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

const managementStatus = document.querySelector("#management-status");
async function copyFeedInput(input, status, label) {
  try {
    await navigator.clipboard.writeText(input.value);
    status.textContent = `${label}のRSS URLをコピーしました。`;
  } catch {
    input.focus(); input.select(); input.setSelectionRange(0, input.value.length);
    status.textContent = "URLを選択しました。長押しまたは端末のコピー操作でコピーしてください。";
  }
}
document.querySelector("#am-copy-button").addEventListener("click", () =>
  copyFeedInput(document.querySelector("#am-feed-url"), document.querySelector("#am-copy-status"), "AM版"));
async function loadFeeds() {
  const response = await fetch("/api/feeds");
  if (response.status === 401) { location.replace("/login"); return; }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "一覧を取得できませんでした。");
  const list = document.querySelector("#managed-feeds");
  list.replaceChildren();
  if (!data.feeds.length) managementStatus.textContent = "登録済みのフィードはありません。";
  for (const feed of data.feeds) {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = feed.title;
    const count = document.createElement("span");
    count.className = "episode-meta";
    count.textContent = `${feed.episodeCount}エピソード`;
    item.append(title, count);
    for (const [label, value] of [["通常音質", feed.feedUrl], ["AMラジオ音質", feed.amFeedUrl]]) {
      const group = document.createElement("div");
      group.className = "managed-quality";
      const caption = document.createElement("span");
      caption.textContent = `${label}のRSS URL`;
      const row = document.createElement("div"); row.className = "copy-row";
      const url = document.createElement("input");
      url.readOnly = true; url.value = value;
      url.setAttribute("aria-label", `${feed.title}の${label}RSS URL`);
      const copy = document.createElement("button");
      copy.type = "button"; copy.className = "secondary";
      copy.textContent = `${label}をコピー`;
      copy.addEventListener("click", () => copyFeedInput(url, managementStatus, label));
      row.append(url, copy); group.append(caption, row); item.append(group);
    }
    const actions = document.createElement("div");
    actions.className = "feed-actions";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "削除";
    remove.addEventListener("click", async () => {
      const removeMedia = document.querySelector("#remove-media").checked;
      const detail = removeMedia ? "ほかのフィードで使っていない保存音声・画像も削除します。" : "保存音声・画像は残します。";
      if (!confirm(`「${feed.title}」の通常版・AM版のフィードを削除しますか？\n${detail}`)) return;
      remove.disabled = true;
      try {
        const response = await fetch(`/api/feeds/${encodeURIComponent(feed.id)}`, {
          method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ removeMedia }),
        });
        if (response.status === 401) { location.replace("/login"); return; }
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "削除できませんでした。");
        if (activeFeedId === feed.id) {
          result.querySelectorAll("audio").forEach((audio) => audio.pause());
          result.hidden = true;
        }
        await loadFeeds();
        managementStatus.textContent = data.cleanupFailures.length
          ? "フィードを削除しました。一部の保存ファイルを削除できませんでした。"
          : `フィードを削除しました。${removeMedia ? `保存ファイル${data.removedFiles}件を削除しました。` : "保存音声・画像は残しています。"}`;
      } catch (error) {
        managementStatus.textContent = error.message;
        remove.disabled = false;
      }
    });
    actions.append(remove);
    item.append(actions);
    list.append(item);
  }
}

document.querySelector("#refresh-feeds").addEventListener("click", () => {
  managementStatus.textContent = "";
  loadFeeds().catch((error) => { managementStatus.textContent = error.message; });
});
document.querySelector("#logout-button").addEventListener("click", async () => {
  try {
    const response = await fetch("/api/logout", { method: "POST" });
    if (!response.ok) throw new Error("ログアウトできませんでした。");
    location.replace("/login");
  } catch (error) { managementStatus.textContent = error.message; }
});
loadFeeds().catch((error) => { managementStatus.textContent = error.message; });
