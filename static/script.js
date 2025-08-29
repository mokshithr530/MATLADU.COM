const socket = io();

let username = "Anonymous";
let serverId = null;      // current room code
let replyTo = null;       // msg_id being replied to

// ---------- helpers ----------
function qs(id) { return document.getElementById(id); }
function setReplyPreview(msg) {
  replyTo = msg.msg_id;
  const box = qs("replyPreview");
  box.innerHTML = `
    <span>Replying to <b>${msg.username}</b>: ${msg.text ? escapeHTML(msg.text) : msg.file_name}</span>
    <button id="cancelReplyBtn" title="Cancel">✖</button>
  `;
  box.style.display = "flex";
  qs("cancelReplyBtn").onclick = clearReply;
}
function clearReply() {
  replyTo = null;
  const box = qs("replyPreview");
  box.style.display = "none";
  box.innerHTML = "";
}
function escapeHTML(s) {
  return (s || "").replace(/[&<>"']/g, m => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[m]));
}
function renderMessage(m) {
  const div = document.createElement("div");
  div.className = "message";

  let replyHTML = "";
  if (m.reply_to && m.reply_preview) {
    replyHTML = `<div class="reply-to">↪ ${escapeHTML(m.reply_preview)}</div>`;
  }

  if (m.type === "file") {
    div.innerHTML = `
      ${replyHTML}
      <strong>${escapeHTML(m.username)}:</strong>
      <a href="${m.file_url}" target="_blank">${escapeHTML(m.file_name)}</a>
    `;
  } else {
    div.innerHTML = `
      ${replyHTML}
      <strong>${escapeHTML(m.username)}:</strong> ${escapeHTML(m.text)}
    `;
  }

  // clicking a message prepares a reply
  div.addEventListener("click", () => {
    if (m.type === "text" || m.type === "file") setReplyPreview(m);
  });

  qs("chatBox").appendChild(div);
  qs("chatBox").scrollTop = qs("chatBox").scrollHeight;
}
function setUsers(list) {
  qs("usersOnline").textContent = `Online: ${list.length}`;
}

// ---------- boot ----------
document.addEventListener("DOMContentLoaded", () => {
  // pull username from query param or prompt
  const params = new URLSearchParams(location.search);
  username = params.get("username") || prompt("Enter username") || "Anonymous";

  // server controls
  qs("createServerBtn").onclick = () => {
    const name = prompt("Server name?");
    if (!name) return;
    socket.emit("create_server", { username, server_name: name });
  };

  qs("joinServerBtn").onclick = () => {
    const code = qs("joinCodeInput").value.trim().toUpperCase();
    if (!code) return;
    socket.emit("join_server", { username, server_id: code });
  };

  // file attach
  qs("attachBtn").onclick = () => qs("fileInput").click();
  qs("fileInput").addEventListener("change", async () => {
    if (!serverId) { alert("Join or create a server first."); return; }
    const file = qs("fileInput").files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("username", username);
    fd.append("server_id", serverId);
    await fetch("/upload", { method: "POST", body: fd });
    qs("fileInput").value = "";
  });

  // send text message
  qs("messageForm").addEventListener("submit", (e) => {
    e.preventDefault();
    if (!serverId) { alert("Join or create a server first."); return; }
    const text = qs("messageInput").value.trim();
    if (!text) return;
    socket.emit("chat_message", {
      username,
      server_id: serverId,
      text,
      reply_to: replyTo
    });
    qs("messageInput").value = "";
    clearReply();
  });

  // ---------- socket listeners ----------
  socket.on("joined_server", (info) => {
    serverId = info.server_id;
    qs("currentServer").textContent = `${info.server_name} — ${serverId}`;
    qs("chatBox").innerHTML = "";
    (info.history || []).forEach(renderMessage);
    setUsers(info.users_online || []);
  });

  socket.on("user_list", setUsers);

  socket.on("chat_message", (msg) => {
    renderMessage(msg);
  });

  socket.on("server_error", (err) => {
    alert(err.error || "Server error");
  });
});
