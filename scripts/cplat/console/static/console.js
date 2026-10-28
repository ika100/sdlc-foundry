/* Console behaviour (spec 122): keymap, side panel, palette, polling, actions panel, copy buttons.
 * No dependencies. The only network access is same-origin fetch; every POST carries X-Console-Token.
 *
 * Markup it reads (design.md "Markup contract"):
 *   [data-need], [data-card]     selectable items; they open /panel/need/<id> unless they carry data-open="/panel/..."
 *                                or contain an <a href="/panel/...">
 *   [data-column]                Board columns (arrow keys move across them)
 *   button[data-action=KIND]     posts /api/actions {kind, object, args} from data-object and data-args (JSON or text);
 *                                data-confirm="text" asks first; a button inside a <form> adds the form fields to args
 *   form[data-post=/api/...]     submits its fields as JSON (with data-wrap, as {form: data-form, fields}) and shows the
 *                                answer in its [data-result]
 */
(function () {
  "use strict";

  var token = (document.querySelector('meta[name="console-token"]') || {}).content || "";
  var lastVersion = null;
  var opener = null;
  var activityTimer = null;
  var STALE_MS = 120000;
  var LOCAL_ACTIONS = ["open-system", "palette", "retry-source", "close-panel", "stop-console", "close-palette"];
  var DECISION_KEYS = {
    "a": ["approve", "approve-ship"],
    "p": ["promote"],
    "t": ["take-over"],
    "o": ["open-in-claude"]
  };

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  function api(method, path, body) {
    var headers = {};
    if (method === "POST") {
      headers["X-Console-Token"] = token;
      headers["Content-Type"] = "application/json";
    }
    return fetch(path, {
      method: method,
      headers: headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (r) {
      return r.text().then(function (t) {
        var data = null;
        try { data = t ? JSON.parse(t) : null; } catch (e) { data = t; }
        return { status: r.status, ok: r.ok, data: data, text: t };
      });
    });
  }

  function toast(message) {
    var box = $("#toast");
    if (!box) { return; }
    box.textContent = message;
    window.setTimeout(function () { if (box.textContent === message) { box.textContent = ""; } }, 6000);
  }

  function parseValue(text) {
    if (text === null || text === undefined || text === "") { return null; }
    try { return JSON.parse(text); } catch (e) { return text; }
  }

  /* ---------- selection and the keymap ---------- */

  function items() { return $all("[data-need], [data-card]"); }

  function selected() { return $("[data-selected='true']"); }

  function select(item) {
    $all("[data-selected='true']").forEach(function (n) { n.removeAttribute("data-selected"); n.removeAttribute("aria-selected"); });
    if (!item) { return; }
    item.setAttribute("data-selected", "true");
    item.setAttribute("aria-selected", "true");
    if (!item.hasAttribute("tabindex")) { item.setAttribute("tabindex", "-1"); }
    item.focus();
    if (item.scrollIntoView) { item.scrollIntoView({ block: "nearest" }); }
  }

  function moveInList(step) {
    var list = $all("[data-need]");
    if (!list.length) { list = $all("[data-card]"); }
    if (!list.length) { return; }
    var at = list.indexOf(selected());
    select(list[at < 0 ? (step > 0 ? 0 : list.length - 1) : Math.max(0, Math.min(list.length - 1, at + step))]);
  }

  function moveOnBoard(key) {
    var cards = $all("[data-card]");
    if (!cards.length) { return; }
    var current = selected();
    if (!current || cards.indexOf(current) < 0) { select(cards[0]); return; }
    var column = current.closest("[data-column]");
    if (!column) { moveInList(key === "ArrowUp" ? -1 : 1); return; }
    var inColumn = $all("[data-card]", column);
    var index = inColumn.indexOf(current);
    if (key === "ArrowUp" || key === "ArrowDown") {
      select(inColumn[Math.max(0, Math.min(inColumn.length - 1, index + (key === "ArrowUp" ? -1 : 1)))]);
      return;
    }
    var columns = $all("[data-column]");
    var step = key === "ArrowLeft" ? -1 : 1;
    for (var i = columns.indexOf(column) + step; i >= 0 && i < columns.length; i += step) {
      var target = $all("[data-card]", columns[i]);
      if (target.length) { select(target[Math.min(index, target.length - 1)]); return; }
    }
  }

  function openItem(item) {
    var url = item.getAttribute("data-open");
    var link = $("a[href^='/panel/']", item);
    if (!url && link) { url = link.getAttribute("href"); }
    if (!url && item.hasAttribute("data-need")) { url = "/panel/need/" + encodeURIComponent(item.getAttribute("data-need")); }
    if (url) { openPanel(url, item); }
  }

  function inTextField(target) {
    if (!target || !target.tagName) { return false; }
    var tag = target.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable === true ||
      target.closest("[contenteditable]:not([contenteditable='false'])") !== null;
  }

  function decisionButton(key) {
    var scopes = [$("aside[data-panel]"), selected()].filter(Boolean);
    for (var s = 0; s < scopes.length; s++) {
      var byKey = $all("button[data-action][aria-keyshortcuts='" + key + "']", scopes[s]);
      var byKind = DECISION_KEYS[key].map(function (kind) { return $("button[data-action='" + kind + "']", scopes[s]); });
      var found = byKey.concat(byKind).filter(function (b) { return b && !b.disabled; });
      if (found.length) { return found[0]; }
    }
    return null;
  }

  function onKey(event) {
    var key = event.key;
    if ((event.metaKey || event.ctrlKey) && (key === "k" || key === "K")) {
      event.preventDefault();
      openPalette();
      return;
    }
    if (key === "Escape") {
      if (!$("#palette").hidden) { closePalette(); event.preventDefault(); return; }
      if ($("aside[data-panel]")) { closePanel(); event.preventDefault(); return; }
      if (!$("#activity-panel").hidden) { toggleActivity(false); }
      return;
    }
    if (event.metaKey || event.ctrlKey || event.altKey || inTextField(event.target)) { return; }
    if (!$("#palette").hidden) { return; }
    if (key === "g") { window.location.href = "/guide"; event.preventDefault(); return; }
    if (key === "?") {
      openPanel("/panel/help/" + (document.body.getAttribute("data-place") || "inbox"), document.activeElement);
      event.preventDefault();
      return;
    }
    if (key === "j") { moveInList(1); event.preventDefault(); }
    else if (key === "k") { moveInList(-1); event.preventDefault(); }
    else if (key === "ArrowLeft" || key === "ArrowRight" || key === "ArrowUp" || key === "ArrowDown") {
      if (!$all("[data-card]").length) { return; }
      moveOnBoard(key);
      event.preventDefault();
    } else if (key === "Enter") {
      var tag = event.target.tagName;
      if (tag === "BUTTON" || tag === "A" || tag === "SUMMARY") { return; }
      var item = selected();
      if (item) { openItem(item); event.preventDefault(); }
    } else if (DECISION_KEYS[key]) {
      var button = decisionButton(key);
      if (button) { button.click(); event.preventDefault(); }
    }
  }

  /* ---------- side panel ---------- */

  function openPanel(url, from) {
    opener = from || document.activeElement;
    return api("GET", url).then(function (r) {
      var slot = $("#panel-slot");
      if (!r.ok) { toast("Could not open it (" + r.status + ")"); return; }
      slot.innerHTML = r.text;
      var panel = $("aside[data-panel]", slot);
      if (panel) {
        panel.setAttribute("tabindex", "-1");
        panel.focus();
      }
    });
  }

  function closePanel() {
    var slot = $("#panel-slot");
    slot.textContent = "";
    if (opener && document.contains(opener) && opener.focus) { opener.focus(); }
    else { $("#content").focus(); }
    opener = null;
  }

  /* ---------- palette ---------- */

  var paletteTimer = null;

  function loadPalette() {
    var q = $("#palette-q").value;
    return api("GET", "/palette?q=" + encodeURIComponent(q)).then(function (r) {
      if (r.ok) { $("#palette-results").innerHTML = r.text; }
    });
  }

  function openPalette() {
    opener = document.activeElement;
    $("#palette").hidden = false;
    $("#palette-q").focus();
    loadPalette();
  }

  function closePalette() {
    $("#palette").hidden = true;
    if (opener && document.contains(opener) && opener.focus) { opener.focus(); }
  }

  /* ---------- actions ---------- */

  function actionBody(button) {
    var args = parseValue(button.getAttribute("data-args")) || {};
    var form = button.closest("form");
    if (form && typeof args === "object") {
      new FormData(form).forEach(function (value, name) { args[name] = value; });
    }
    if (form && button.getAttribute("data-action") === "answer") { args = answerArgs(form, args); }
    return { kind: button.getAttribute("data-action"), object: parseValue(button.getAttribute("data-object")), args: args };
  }

  /* One text from the radios q1..qn and the free text, numbered by question: "1. Question: choice. 2. ... Own words." */
  function answerArgs(form, args) {
    var parts = [];
    $all("fieldset", form).forEach(function (set, i) {
      var legend = $("legend", set);
      var chosen = $("input[type='radio']:checked", set);
      if (chosen) { parts.push((i + 1) + ". " + (legend ? legend.textContent.trim() : "Question " + (i + 1)) + " " + chosen.value); }
    });
    var own = ((form.elements.answers || {}).value || "").trim();
    if (own) { parts.push(own); }
    args.answers = parts.join(" ");
    Object.keys(args).forEach(function (k) { if (/^q\d+$/.test(k)) { delete args[k]; } });
    return args;
  }

  function runAction(button) {
    var kind = button.getAttribute("data-action");
    var confirmText = button.getAttribute("data-confirm");
    if (confirmText && !window.confirm(confirmText)) { return; }
    if (kind === "open-in-claude" || kind === "take-over") {
      var object = parseValue(button.getAttribute("data-object"));
      var runId = object && typeof object === "object" ? object.run_id : object;
      return openInClaude(runId);
    }
    api("POST", "/api/actions", actionBody(button)).then(function (r) {
      if (r.status === 202) { toast("Started"); toggleActivity(true); refreshState(); }
      else if (r.status === 412) { toast("Needs " + (r.data && r.data.needs)); }
      else if (r.status === 409) { toast("Another action on this object is already running"); }
      else { toast((r.data && r.data.error) || "Could not start the action"); }
    });
  }

  function openInClaude(runId) {
    return api("POST", "/api/open-in-claude", { run_id: runId }).then(function (r) {
      var d = r.data || {};
      toast(d.started ? "Opened in Claude Code" : "Run this in a terminal: " + (d.command || ""));
    });
  }

  function retrySource(button) {
    var holder = button.closest("[data-source]");
    if (!holder) { return; }
    api("POST", "/api/sources/" + encodeURIComponent(holder.getAttribute("data-source")) + "/retry", {}).then(function () {
      window.setTimeout(refreshState, 1000);
    });
  }

  function stopConsole() {
    api("POST", "/api/shutdown", { confirm: false }).then(function (r) {
      if (r.status === 409) {
        var n = ((r.data && r.data.running) || []).length;
        if (window.confirm("Stop " + n + " running action" + (n === 1 ? "" : "s") + " and the console?")) {
          api("POST", "/api/shutdown", { confirm: true }).then(function () { toast("Console stopped"); });
        }
      } else if (r.status === 202) { toast("Console stopped"); }
    });
  }

  function submitForm(form) {
    var fields = {};
    new FormData(form).forEach(function (value, name) { fields[name] = value; });
    var body = form.hasAttribute("data-wrap") ? { form: form.getAttribute("data-form"), fields: fields } : fields;
    return api("POST", form.getAttribute("data-post"), body).then(function (r) {
      var out = $("[data-result]", form) || form.parentNode.querySelector("[data-result]");
      if (out) {
        var d = r.data;
        out.textContent = d && typeof d === "object" ? (d.answer || d.command || d.error || JSON.stringify(d, null, 2)) : String(d || "");
        if (d && Array.isArray(d.suggestions)) { showSuggestions(form, out, d.suggestions); }
      }
    });
  }

  /* Commands Claude proposes: shown with copy; nothing runs without the click on "Run this". */
  function showSuggestions(form, out, suggestions) {
    var old = $("[data-suggestions]", form.parentNode);
    if (old) { old.remove(); }
    if (!suggestions.length) { return; }
    var list = el("ul", { "data-suggestions": "", "class": "plain" });
    suggestions.forEach(function (s) {
      var li = el("li", { "class": "act" });
      var box = el("span", { "class": "command" });
      box.appendChild(el("code", { "data-command": "" }, s.command));
      box.appendChild(el("button", { type: "button", "class": "ghost", "data-copy": "", "aria-label": "Copy command" }, "Copy"));
      li.appendChild(box);
      if (s.diff) { li.appendChild(el("pre", {}, s.diff)); }
      var run = el("button", { type: "button", "class": "btn", "data-suggestion-run": "" }, "Run this");
      run.addEventListener("click", function () {
        if (!window.confirm("Run this command?\n\n" + s.command)) { return; }
        run.disabled = true;
        api("POST", "/api/actions", { kind: "model", object: { type: "system", repo: s.repo }, args: { command: s.command, level: "system" } })
          .then(function (r) {
            run.disabled = false;
            if (r.status === 202) { toast("Started"); toggleActivity(true); refreshState(); }
            else if (r.status === 412) { toast("Needs " + (r.data && r.data.needs)); }
            else { toast((r.data && r.data.error) || "Could not start the action"); }
          });
      });
      li.appendChild(run);
      list.appendChild(li);
    });
    out.insertAdjacentElement("afterend", list);
  }

  /* Opening another system starts its own console (POST /api/open-system) and shows the address it printed. */
  function openSystem(button) {
    var row = button.closest("[data-system]") || button.parentNode;
    var note = $("[data-open-note]", row);
    if (!note) {
      note = el("p", { "data-open-note": "", "class": "muted" }, "");
      row.appendChild(note);
    }
    var object = parseValue(button.getAttribute("data-object")) || {};
    note.textContent = "Starting its console ...";
    api("POST", "/api/open-system", { repo: object.repo }).then(function (r) {
      var d = r.data || {};
      if (r.status === 200 && d.url) {
        note.textContent = "Its console runs at ";
        note.appendChild(el("a", { href: d.url, target: "_blank", rel: "noopener noreferrer", "data-open-url": "" }, d.url));
      } else {
        note.textContent = (d.error || "Could not start its console") + (d.detail ? ": " + d.detail : "") + ". Run the command shown.";
      }
    });
  }

  /* "edit rules" in an environment column: open the form and preselect that environment. */
  function editRules(link) {
    var details = document.getElementById("form-environment");
    if (!details) { return false; }
    details.open = true;
    var field = $("[name='env']", details);
    if (field) {
      field.value = link.getAttribute("data-edit-env");
      field.dispatchEvent(new Event("change", { bubbles: true }));
      field.focus();
    }
    details.scrollIntoView({ block: "nearest" });
    return true;
  }

  /* ---------- copy ---------- */

  function copyCommand(button) {
    var box = button.closest(".command") || button.parentNode;
    var code = $("[data-command]", box) || $("[data-command]", button.parentNode.parentNode);
    if (!code) { return; }
    var text = code.textContent;
    var done = function () {
      button.textContent = "Copied";
      window.setTimeout(function () { button.textContent = "Copy"; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text); done(); });
    } else { fallbackCopy(text); done(); }
  }

  function fallbackCopy(text) {
    var area = el("textarea", { "aria-hidden": "true" });
    area.value = text;
    document.body.appendChild(area);
    area.select();
    try { document.execCommand("copy"); } catch (e) { /* the command stays selectable on the page */ }
    document.body.removeChild(area);
  }

  /* ---------- clicks ---------- */

  function onClick(event) {
    var target = event.target;
    var copy = target.closest("[data-copy]");
    if (copy) { copyCommand(copy); return; }
    var edit = target.closest("a[data-edit-env]");
    if (edit && editRules(edit)) { event.preventDefault(); return; }
    var link = target.closest("a[href^='/panel/']");
    if (link) { event.preventDefault(); openPanel(link.getAttribute("href"), link); return; }
    var button = target.closest("button[data-action], [data-activity]");
    if (button && button.hasAttribute("data-activity")) { toggleActivity(); return; }
    if (button) {
      if (button.disabled) { return; }
      var kind = button.getAttribute("data-action");
      if (button.hasAttribute("data-open")) { openPanel(button.getAttribute("data-open"), button); }
      else if (kind === "palette") { openPalette(); }
      else if (kind === "close-palette") { closePalette(); }
      else if (kind === "close-panel") { closePanel(); }
      else if (kind === "retry-source") { retrySource(button); }
      else if (kind === "stop-console") { stopConsole(); }
      else if (kind === "open-system") { openSystem(button); }
      else if (LOCAL_ACTIONS.indexOf(kind) < 0) { runAction(button); }
      return;
    }
    if (target.closest("#palette") === $("#palette") && target === $("#palette")) { closePalette(); return; }
    var item = target.closest("[data-need], [data-card]");
    if (item && !target.closest("a, button, input, summary")) { select(item); openItem(item); }
  }

  function onSubmit(event) {
    var form = event.target;
    if (form.getAttribute && form.getAttribute("data-post")) { event.preventDefault(); submitForm(form); }
  }

  /* ---------- polling /api/state ---------- */

  function markStale() {
    var now = Date.now();
    $all("time[data-read-at]").forEach(function (t) {
      var at = Date.parse(t.getAttribute("data-read-at"));
      var stale = isNaN(at) || now - at > STALE_MS;
      if (stale) { t.setAttribute("data-stale", "true"); } else { t.removeAttribute("data-stale"); }
      var word = $(".stale-word", t);
      if (stale && !word) { t.appendChild(document.createTextNode(" ")); t.appendChild(el("span", { "class": "stale-word" }, "stale")); }
      if (!stale && word) { word.remove(); }
    });
  }

  function applyState(state) {
    $all("[data-badge='inbox']").forEach(function (b) {
      b.textContent = String(state.badge);
      b.setAttribute("data-count", String(state.badge));
    });
    var act = $("[data-activity]");
    if (act && state.actions) {
      act.setAttribute("data-running", String(state.actions.running));
      act.setAttribute("data-failed", String(state.actions.failed));
      var text = $("[data-activity-text]", act);
      if (text) { text.textContent = state.actions.running + " running, " + state.actions.failed + " failed"; }
    }
    var banner = $("#banner");
    if (banner && state.banner) {
      banner.hidden = state.banner.length === 0;
      banner.textContent = "";
      if (state.banner.length) {
        banner.appendChild(el("p", {}, "Some actions are off until this is fixed (/platform:doctor checks it):"));
        var list = el("ul");
        state.banner.forEach(function (b) {
          var li = el("li");
          li.appendChild(el("strong", {}, b.piece));
          li.appendChild(document.createTextNode(" is missing. " + b.fix));
          list.appendChild(li);
        });
        banner.appendChild(list);
      }
    }
    var read = $(".stamp time[data-read-at]");
    if (read && state.read_at) { read.setAttribute("data-read-at", state.read_at); }
    markStale();
    if (lastVersion !== null && state.version !== lastVersion) { reloadContent(); }
    lastVersion = state.version;
  }

  function refreshState() {
    return api("GET", "/api/state").then(function (r) { if (r.ok && r.data) { applyState(r.data); } });
  }

  function reloadContent() {
    var keep = selected();
    var key = keep && (keep.getAttribute("data-need") || keep.getAttribute("data-card"));
    api("GET", window.location.pathname + window.location.search).then(function (r) {
      if (!r.ok) { return; }
      var doc = new DOMParser().parseFromString(r.text, "text/html");
      var fresh = doc.getElementById("content");
      var current = $("#content");
      if (!fresh || !current) { return; }
      var hadFocus = current.contains(document.activeElement);
      current.innerHTML = fresh.innerHTML;
      if (key) {
        var again = items().filter(function (n) { return (n.getAttribute("data-need") || n.getAttribute("data-card")) === key; })[0];
        if (again) {
          again.setAttribute("data-selected", "true");
          again.setAttribute("tabindex", "-1");
          if (hadFocus) { again.focus(); }
        }
      }
    });
  }

  /* ---------- actions panel ---------- */

  function toggleActivity(open) {
    var panel = $("#activity-panel");
    var show = open === undefined ? panel.hidden : open;
    panel.hidden = !show;
    $("[data-activity]").setAttribute("aria-expanded", String(show));
    window.clearInterval(activityTimer);
    if (show) {
      loadActions();
      activityTimer = window.setInterval(loadActions, 2000);
    }
  }

  function elapsed(a) {
    var start = Date.parse(a.started_at);
    var end = a.ended_at ? Date.parse(a.ended_at) : Date.now();
    var s = Math.max(0, Math.round((end - start) / 1000));
    return s < 60 ? s + " s" : Math.floor(s / 60) + " min " + (s % 60) + " s";
  }

  function safeUrl(url) { return /^https?:\/\//.test(url || "") ? url : null; }

  function actionItem(a) {
    var li = el("li", { "data-action-id": a.id });
    var head = el("div");
    head.appendChild(el("strong", {}, a.kind + " "));
    head.appendChild(el("span", { "class": a.state === "failed" ? "failed" : "" }, a.state));
    head.appendChild(document.createTextNode(" - " + elapsed(a)));
    li.appendChild(head);
    var box = el("span", { "class": "command" });
    box.appendChild(el("code", { "data-command": "" }, a.command));
    box.appendChild(el("button", { type: "button", "class": "ghost", "data-copy": "", "aria-label": "Copy command" }, "Copy"));
    li.appendChild(box);
    if (a.state === "running" && a.step) { li.appendChild(el("p", {}, a.step)); }
    if (a.state === "done") {
      var links = a.links || {};
      [["run", "Run"], ["pr", "Pull request"]].forEach(function (pair) {
        var href = safeUrl(links[pair[0]]) || (pair[0] === "run" && links.run ? "/panel/run/" + encodeURIComponent(links.run) : null);
        if (href) { var link = el("a", { href: href }, pair[1]); li.appendChild(link); li.appendChild(document.createTextNode(" ")); }
      });
    }
    if (a.state === "failed" || a.state === "stopped") {
      if (a.reason) { li.appendChild(el("p", { "class": "failed" }, a.reason)); }
      if (a.tail && a.tail.length) { li.appendChild(el("pre", {}, a.tail.join("\n"))); }
      li.appendChild(el("button", { type: "button", "class": "btn", "data-retry": a.id }, "Retry"));
      li.appendChild(el("button", { type: "button", "class": "btn", "data-claude": (a.links && a.links.run) || "" }, "Open in Claude Code"));
    }
    return li;
  }

  function loadActions() {
    api("GET", "/api/actions").then(function (r) {
      if (!r.ok || !Array.isArray(r.data)) { return; }
      var panel = $("#activity-panel");
      var focused = document.activeElement && panel.contains(document.activeElement) ? document.activeElement : null;
      if (focused && focused.tagName === "BUTTON" && !focused.hasAttribute("data-copy")) { return; }
      panel.textContent = "";
      panel.appendChild(el("h2", {}, "Actions"));
      if (!r.data.length) { panel.appendChild(el("p", {}, "Nothing has run yet.")); return; }
      var list = el("ul");
      r.data.slice().reverse().forEach(function (a) { list.appendChild(actionItem(a)); });
      panel.appendChild(list);
    });
  }

  function onActivityClick(event) {
    var retry = event.target.closest("[data-retry]");
    if (retry) {
      api("POST", "/api/actions/" + encodeURIComponent(retry.getAttribute("data-retry")) + "/retry", {}).then(function (r) {
        toast(r.status === 202 ? "Started again" : "Could not retry");
        loadActions();
      });
      return;
    }
    var claude = event.target.closest("[data-claude]");
    if (claude) { openInClaude(claude.getAttribute("data-claude")); }
  }

  /* ---------- model forms: a new preview on every change ---------- */

  var previewTimers = new WeakMap();

  function formFields(form) {
    var fields = {};
    new FormData(form).forEach(function (value, name) {
      name = name.replace(/\[\]$/, "");
      if (Object.prototype.hasOwnProperty.call(fields, name)) {
        fields[name] = [].concat(fields[name], value);
      } else { fields[name] = value; }
    });
    return fields;
  }

  function showPreview(form, doc) {
    var area = $("[data-preview]", form) || form;
    var cmd = $("[data-command]", area) || $("[data-command]", form);
    if (cmd) { cmd.textContent = doc.command || ""; }
    var diff = $("[data-diff]", area);
    if (!diff) { diff = el("pre", { "data-diff": "" }); area.appendChild(diff); }
    diff.textContent = doc.diff || "";
    var checks = $("[data-checks]", area);
    if (!checks) { checks = el("ul", { "data-checks": "" }); area.appendChild(checks); }
    checks.textContent = "";
    (doc.checks || []).forEach(function (c) {
      var li = el("li", { "data-ok": c.ok ? "true" : "false" }, (c.ok ? "ok: " : "failed: ") + c.key + " - " + c.rule);
      checks.appendChild(li);
    });
    var confirm = $("button[data-action='model']", form);
    if (confirm) {
      var off = !doc.valid;
      confirm.disabled = off;
      confirm.setAttribute("aria-disabled", off ? "true" : "false");
      confirm.setAttribute("data-args", JSON.stringify({ command: doc.command, level: "system" }));
    }
  }

  function requestPreview(form) {
    api("POST", "/api/preview", { form: form.getAttribute("data-form"), fields: formFields(form) }).then(function (r) {
      if (r.ok && r.data) { showPreview(form, r.data); }
      else {
        var confirm = $("button[data-action='model']", form);
        if (confirm) { confirm.disabled = true; confirm.setAttribute("aria-disabled", "true"); }
        toast((r.data && r.data.detail) || "Could not preview this change");
      }
    });
  }

  function onFormChange(event) {
    var form = event.target.closest ? event.target.closest("form[data-form]") : null;
    if (!form) { return; }
    window.clearTimeout(previewTimers.get(form));
    previewTimers.set(form, window.setTimeout(function () { requestPreview(form); }, 200));
  }

  /* ---------- start ---------- */

  function start() {
    document.addEventListener("keydown", onKey);
    document.addEventListener("click", onClick);
    document.addEventListener("submit", onSubmit);
    document.addEventListener("input", onFormChange);
    document.addEventListener("change", onFormChange);
    $("#activity-panel").addEventListener("click", onActivityClick);
    $("#palette-q").addEventListener("input", function () {
      window.clearTimeout(paletteTimer);
      paletteTimer = window.setTimeout(loadPalette, 150);
    });
    markStale();
    refreshState();
    window.setInterval(refreshState, 5000);
    window.setInterval(markStale, 15000);
  }

  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", start); } else { start(); }
})();
