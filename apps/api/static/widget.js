// Groundwork chat widget. One file, no build step, no dependencies.
// Embed:
//   <script src="https://your-host/widget.js" data-key="ragpub_..." defer></script>
// Everything lives in a shadow root so the host page's CSS cannot reach in and
// this widget's CSS cannot leak out.
(function () {
  "use strict";

  var script = document.currentScript;
  if (!script) return;
  var publicKey = script.getAttribute("data-key");
  if (!publicKey) {
    console.error("[groundwork] the embed snippet is missing data-key");
    return;
  }
  // Default to the origin serving this file, which is the API that answers it.
  var api = (script.getAttribute("data-api") || new URL(script.src).origin).replace(/\/$/, "");
  var base = api + "/public/v1/chatbots/" + encodeURIComponent(publicKey);

  var host = document.createElement("div");
  host.style.cssText = "position:fixed;bottom:0;right:0;z-index:2147483000";
  var root = host.attachShadow({ mode: "open" });
  root.innerHTML = [
    "<style>",
    ":host,*{box-sizing:border-box}",
    "button,input{font:inherit;color:inherit}",
    '.w{position:fixed;bottom:20px;right:20px;font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:#18181b}',
    ".launch{width:56px;height:56px;border-radius:50%;border:0;background:#18181b;color:#fff;font-size:22px;cursor:pointer;box-shadow:0 6px 24px rgba(0,0,0,.22)}",
    ".launch:hover{background:#000}",
    ".launch:focus-visible,.send:focus-visible,.x:focus-visible,input:focus-visible{outline:2px solid #2563eb;outline-offset:2px}",
    ".panel{display:flex;flex-direction:column;width:380px;height:min(560px,calc(100vh - 40px));background:#fff;border:1px solid #e4e4e7;border-radius:14px;overflow:hidden;box-shadow:0 12px 48px rgba(0,0,0,.18)}",
    ".top{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid #e4e4e7;background:#fafafa}",
    ".top strong{font-size:15px}",
    ".x{border:0;background:none;font-size:20px;line-height:1;cursor:pointer;padding:4px 6px;border-radius:6px;color:#52525b}",
    ".x:hover{background:#e4e4e7}",
    ".log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}",
    ".msg{max-width:88%;padding:10px 13px;border-radius:12px;white-space:pre-wrap;overflow-wrap:anywhere}",
    ".them{background:#f4f4f5;align-self:flex-start;border-bottom-left-radius:4px}",
    ".me{background:#18181b;color:#fff;align-self:flex-end;border-bottom-right-radius:4px}",
    ".bad{background:#fef2f2;color:#991b1b;align-self:stretch;font-size:14px}",
    ".cites{align-self:flex-start;margin:0;padding:0 0 0 10px;list-style:none;font-size:12.5px;color:#52525b;display:flex;flex-direction:column;gap:5px;border-left:2px solid #e4e4e7}",
    ".cites b{color:#18181b;font-weight:600}",
    ".ask{display:flex;gap:8px;padding:12px;border-top:1px solid #e4e4e7}",
    "input{flex:1;min-width:0;padding:10px 12px;border:1px solid #d4d4d8;border-radius:9px;background:#fff}",
    ".send{padding:0 16px;border:0;border-radius:9px;background:#18181b;color:#fff;cursor:pointer}",
    ".send[disabled]{opacity:.5;cursor:default}",
    "[hidden]{display:none!important}",
    "@media (max-width:480px){.w{bottom:0;right:0;left:0}.panel{width:100vw;height:100vh;border:0;border-radius:0}}",
    "@media (prefers-reduced-motion:no-preference){.msg{animation:in .18s ease-out}@keyframes in{from{opacity:0;transform:translateY(4px)}}}",
    "</style>",
    '<div class="w">',
    '<button class="launch" aria-haspopup="dialog" aria-expanded="false" aria-label="Open chat">',
    '<span aria-hidden="true">&#128172;</span></button>',
    '<div class="panel" role="dialog" hidden>',
    '<div class="top"><strong></strong><button class="x" aria-label="Close chat">&times;</button></div>',
    '<div class="log" role="log" aria-live="polite"></div>',
    '<form class="ask"><input aria-label="Your question" placeholder="Ask a question&#8230;" ',
    'maxlength="4000" autocomplete="off" required><button class="send" type="submit">Send</button></form>',
    "</div></div>"
  ].join("");

  var find = function (selector) { return root.querySelector(selector); };
  var launch = find(".launch");
  var panel = find(".panel");
  var log = find(".log");
  var form = find(".ask");
  var input = form.querySelector("input");
  var send = find(".send");
  var title = find(".top strong");
  var loaded = false;
  var busy = false;

  function say(text, kind) {
    var line = document.createElement("div");
    line.className = "msg " + kind;
    line.textContent = text;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
    return line;
  }

  function cite(sources) {
    if (!sources || !sources.length) return;
    var list = document.createElement("ol");
    list.className = "cites";
    sources.forEach(function (source) {
      var item = document.createElement("li");
      var label = document.createElement("b");
      // textContent throughout: retrieved document text is data, never markup.
      label.textContent = "[" + source.id + "] " + source.document_name +
        (source.page_number ? " · page " + source.page_number : "") +
        (source.section ? " · " + source.section : "");
      item.appendChild(label);
      list.appendChild(item);
    });
    log.appendChild(list);
    log.scrollTop = log.scrollHeight;
  }

  function open() {
    panel.hidden = false;
    launch.hidden = true;
    launch.setAttribute("aria-expanded", "true");
    input.focus();
    if (loaded) return;
    loaded = true;
    fetch(base, { mode: "cors" })
      .then(function (response) {
        return response.ok ? response.json() : Promise.reject(response);
      })
      .then(function (bot) {
        title.textContent = bot.name;
        panel.setAttribute("aria-label", bot.name);
        if (bot.greeting) say(bot.greeting, "them");
      })
      .catch(function () {
        loaded = false;
        title.textContent = "Chat";
        say("This chat is unavailable right now.", "bad");
      });
  }

  function close() {
    panel.hidden = true;
    launch.hidden = false;
    launch.setAttribute("aria-expanded", "false");
    launch.focus();
  }

  launch.addEventListener("click", open);
  find(".x").addEventListener("click", close);
  root.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) {
      event.stopPropagation();
      close();
    }
  });

  function readStream(response) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    var answer = null;

    return (function pump() {
      return reader.read().then(function (chunk) {
        buffer += decoder.decode(chunk.value, { stream: !chunk.done });
        var frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || "";
        frames.forEach(function (frame) {
          var name = "";
          var payload = [];
          frame.split(/\r?\n/).forEach(function (line) {
            if (line.indexOf("event:") === 0) name = line.slice(6).trim();
            else if (line.indexOf("data:") === 0) payload.push(line.slice(5).replace(/^ /, ""));
          });
          if (!payload.length) return;
          var data = JSON.parse(payload.join("\n"));
          if (name === "token") {
            if (!answer) answer = say("", "them");
            answer.textContent += data.text;
            log.scrollTop = log.scrollHeight;
          } else if (name === "sources") {
            cite(data);
          } else if (name === "error") {
            throw new Error(data.detail || "The assistant is unavailable right now.");
          }
        });
        return chunk.done ? undefined : pump();
      });
    })();
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var question = input.value.trim();
    if (!question || busy) return;
    busy = true;
    send.disabled = true;
    input.value = "";
    say(question, "me");

    fetch(base + "/chat", {
      method: "POST",
      mode: "cors",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question })
    }).then(function (response) {
      if (!response.ok || !response.body) {
        return response.json().catch(function () { return {}; }).then(function (body) {
          throw new Error(typeof body.detail === "string" ? body.detail :
            "Sorry, something went wrong. Please try again.");
        });
      }
      return readStream(response);
    }).catch(function (error) {
      say(error.message || "Sorry, something went wrong. Please try again.", "bad");
    }).then(function () {
      busy = false;
      send.disabled = false;
      input.focus();
    });
  });

  (document.body || document.documentElement).appendChild(host);
})();
