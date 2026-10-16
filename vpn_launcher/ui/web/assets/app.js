// -*- coding: utf-8 -*-
// Мост страницы с логикой лаунчера (vpn_launcher/ui/web/bridge.py).
// Python вызывает VPL.apply(state) и VPL.modal(payload); мы зовём bridge.*
// QWebChannel выдаёт Qt-сигналы как методы - вызов отправляет команду в GUI-поток.
(function () {
  "use strict";

  // 15.10: ошибки JS раньше были невидимы - коллектора не существовало
  // (window.__errs читался при подключении, но никто его не заполнял).
  // Копим сюда и отдаём в журнал приложения через bridge.pageError.
  window.__errs = [];
  window.addEventListener("error", (event) => {
    window.__errs.push(String((event && event.message) || event));
  });
  window.addEventListener("unhandledrejection", (event) => {
    window.__errs.push("unhandled: " + String(event && event.reason));
  });

  const $ = (sel, root) => (root || document).querySelector(sel);

  const VPL = {
    bridge: null,
    state: null,
    revealed: false,
    pickedServer: -1,
    pickedExcl: -1,
    dropOpen: false,

    // ---- соединение с Qt ------------------------------------------------
    connect() {
      // Qt6 отдаёт класс как QWebChannel, Qt5 - как qWebChannel
      const Channel = window.QWebChannel || window.qWebChannel;
      if (typeof qt === "undefined" || !Channel) {
        document.body.setAttribute("data-web", "no-channel");
        return;
      }
      new Channel(qt.webChannelTransport, (channel) => {
        this.bridge = channel.objects.bridge;
        if (window.__errs && window.__errs.length) {
          this.bridge.pageError(window.__errs.join(" | "));
        }
        this.bridge.ready();
        document.body.setAttribute("data-web", "ready");
      });
    },

    // ---- состояние из Python -------------------------------------------
    flushErrs() {
      if (!this.bridge || !window.__errs.length) return;
      try {
        // забираем пачкой: журнал пишется построчно, воронку не делаем
        this.bridge.pageError(window.__errs.splice(0, 20).join(" | "));
      } catch (exc) {
        // канал недоступен - записи уже изъяты, повтор не нужен
        void exc;
      }
    },

    apply(s) {
      const first = this.state === null;
      this.state = s;
      this.flushErrs();
      this.renderSubscription(s);
      this.renderServers(s);
      this.renderProcesses(s);
      this.renderModes(s);
      this.renderStatus(s);
      this.renderButtons(s);
      this.renderDpi(s);
      this.renderUpdate(s);
      if (first) this.buildDrop(s.picker || []);
    },

    renderUpdate(s) {
      const banner = $("#updateBanner");
      const info = s.update;
      if (!info) {
        banner.hidden = true;
        return;
      }
      const text = $("#updateText");
      const now = $("#updateNow");
      if (info.phase === "downloading") {
        text.textContent = "Скачивание обновления " + (info.progress || 0) + "%...";
        now.disabled = true;
      } else if (info.phase === "error") {
        text.textContent = "Ошибка загрузки обновления: " + (info.error || "");
        now.disabled = false;
      } else {
        text.textContent = "Доступна версия " + info.version;
        now.disabled = false;
      }
      banner.hidden = false;
    },

    renderSubscription(s) {
      const input = $("#subscriptionUrl");
      if (document.activeElement !== input && input.value !== (s.subUrl || "")) {
        input.value = s.subUrl || "";
      }
    },

    renderServers(s) {
      const body = $("#serverList");
      const rows = s.servers || [];
      if (!rows.length) {
        if (body.dataset.empty !== "1") {
          body.innerHTML =
            '<tr class="empty-row"><td colspan="3">Подписка не загружена</td></tr>';
          body.dataset.empty = "1";
        }
        return;
      }
      const sig = rows
        .map((r) => r.name + "|" + r.proto + "|" + r.pingText)
        .join(";") + "#" + s.serverSelected;
      if (body.dataset.sig === sig) return;
      body.dataset.sig = sig;
      delete body.dataset.empty;
      body.innerHTML = rows
        .map((r) => {
          const sel = r.i === s.serverSelected ? " selected" : "";
          return (
            '<tr class="server-row' + sel + '" data-i="' + r.i + '">' +
            '<td><span class="protocol">' + esc(r.proto.toUpperCase()) + "</span></td>" +
            "<td>" + esc(r.name) + "</td>" +
            '<td class="ping ' + r.pingClass + '">' + esc(r.pingText) + "</td></tr>"
          );
        })
        .join("");
    },

    renderProcesses(s) {
      const list = $("#processList");
      const items = s.excl || [];
      const sig = items.join(";") + "#" + s.exclSelected;
      if (list.dataset.sig === sig) return;
      list.dataset.sig = sig;
      list.innerHTML = items
        .map(
          (name, i) =>
            '<div class="process-item' +
            (i === s.exclSelected ? " selected" : "") +
            '" data-i="' + i + '"><span class="process-dot"></span>' +
            esc(name) +
            "</div>"
        )
        .join("");
      const hint = $("#appsHint");
      if (hint) hint.textContent = s.appHint || "";
      const head = $("#appSecHeading");
      if (head) setHeadingText(head, s.appSec || "Исключения");
      const pin = $("#processInput");
      if (pin && document.activeElement !== pin && pin.value !== (s.procText || "")) {
        pin.value = s.procText || "";
      }
    },

    renderModes(s) {
      // подсветка СЕГМЕНТА и положение радио-точки обязаны ехать вместе:
      // в макете точка стояла статически в разметке и после переключения
      // оставалась на прошлом варианте (13.10)
      const sync = (sel, value, key) => {
        $$(sel).forEach((b) => {
          const on = b.dataset[key] === value;
          b.classList.toggle("active", on);
          const dot = b.querySelector("input");
          if (dot) dot.checked = on;
        });
      };
      sync(".exception-segments .segment", s.appMode, "exclusionMode");
      sync(".mode-segments .segment", s.mode, "connectionMode");
    },

    renderStatus(s) {
      const lamp = $("#connectionLamp");
      if (lamp) {
        lamp.className = "status-lamp " + (s.lamp || "off");
      }
      const text = $("#connectionStatusText");
      if (text) text.textContent = s.status || "";
      const dpi = $("#dpiLamp");
      if (dpi) {
        // лампа обхода DPI: из моста приходит ready/connecting/off (те же
        // классы, что у лампы VPN), раньше ждали "on" - и она не загоралась
        const k = s.dpiLamp;
        dpi.className =
          "status-lamp " +
          (k === "ready" ? "dpi-active" : k === "connecting" ? "connecting" : "dpi-inactive");
      }
      const ip = $("#externalIp");
      if (ip && s.egress) ip.textContent = s.egress;
    },

    renderButtons(s) {
      const c = $("#connectButton");
      if (c) c.disabled = !s.connect;
      const d = $("#disconnectButton");
      if (d) d.disabled = !s.disconnect;
      const t = $("#checkConfigButton");
      if (t) t.disabled = !s.testcfg;
    },

    renderDpi(s) {
      const r = $("#rocket");
      if (!r) return;
      r.classList.toggle("active", !!(s.dpi && s.dpi.active));
      r.classList.toggle("is-busy", !!(s.dpi && s.dpi.busy));
    },

    // ---- модальные окна ------------------------------------------------
    modal(p) {
      const layer = $("#modalLayer");
      const okLabel = p.confirm ? "Продолжить" : "OK";
      layer.innerHTML =
        '<div class="modal-card">' +
        (p.title ? '<h3 class="modal-title">' + esc(p.title) + "</h3>" : "") +
        '<p class="modal-text' + (p.icon === "error" ? " error" : "") + '">' +
        esc(p.text) + "</p>" +
        '<div class="modal-actions">' +
        (p.confirm ? '<button class="ghost-button" data-a="0">Отмена</button>' : "") +
        '<button class="primary-button" data-a="1">' + okLabel + "</button>" +
        "</div></div>";
      layer.hidden = false;
      layer.onclick = (e) => {
        const btn = e.target.closest("button[data-a]");
        if (!btn) return;
        layer.hidden = true;
        layer.onclick = null;
        if (this.bridge) this.bridge.answerModal(p.id, btn.dataset.a === "1");
      };
    },

    // ---- выпадающий список процессов ------------------------------------
    buildDrop(items) {
      const drop = $("#processDrop");
      drop.innerHTML = items
        .map((t) => '<div class="drop-item">' + esc(t) + "</div>")
        .join("");
    },

    filterDrop(text) {
      const needle = (text || "").toLowerCase();
      const drop = $("#processDrop");
      let shown = 0;
      $$(".drop-item", drop).forEach((el) => {
        const hit = el.textContent.toLowerCase().includes(needle);
        el.hidden = !hit;
        if (hit) shown += 1;
      });
      this.dropOpen = shown > 0;
      this.placeDrop();
    },

    placeDrop() {
      const drop = $("#processDrop");
      const input = $("#processInput");
      const box = input.getBoundingClientRect();
      drop.hidden = !this.dropOpen;
      drop.style.left = box.left + "px";
      drop.style.top = box.bottom + 3 + "px";
      drop.style.width = box.width + "px";
    },

    closeDrop() {
      this.dropOpen = false;
      const drop = $("#processDrop");
      if (drop) drop.hidden = true;
    },

    // ---- перетаскивание окна -------------------------------------------
    startDrag(e) {
      if (!this.bridge) return;
      this.bridge.dragStart(e.screenX, e.screenY);
      const move = (ev) => this.bridge.dragMove(ev.screenX, ev.screenY);
      const up = () => {
        this.bridge.dragEnd();
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    },
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[c]);
  }

  // текст заголовка секции: иконка внутри h2 должна остаться на месте
  function setHeadingText(el, text) {
    const node = el.lastChild;
    if (node && node.nodeType === 3) node.nodeValue = text;
    else el.appendChild(document.createTextNode(text));
  }

  function $$(sel, root) {
    return [...(root || document).querySelectorAll(sel)];
  }

  // ---- обработчики ------------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    const b = () => VPL.bridge;

    $("#btnMinimize").onclick = () => b() && b().minimize();
    $("#btnClose").onclick = () => b() && b().closeWin();
    $("#btnLoad").onclick = () => b() && b().loadSub();
    $("#btnPing").onclick = () => b() && b().pingServers();
    $("#btnLog").onclick = () => b() && b().openLog();
    $("#connectButton").onclick = () => b() && b().connectVpn();
    $("#disconnectButton").onclick = () => b() && b().disconnectVpn();
    $("#checkConfigButton").onclick = () => b() && b().testConfig();

    // поле подписки: показываем/скрываем URL, наружу - текст без пауз
    const sub = $("#subscriptionUrl");
    sub.addEventListener("focus", () => setSubType(true));
    sub.addEventListener("blur", () => setSubType(false));
    sub.addEventListener("input", () => b() && b().setSubUrl(sub.value));
    $("#toggleSubscriptionVisibility").addEventListener("mousedown", (e) =>
      e.preventDefault()
    );
    $("#toggleSubscriptionVisibility").addEventListener("click", () => {
      VPL.revealed = !VPL.revealed;
      setSubType(VPL.revealed);
      if (VPL.revealed) sub.focus();
    });

    function setSubType(visible) {
      sub.type = visible ? "text" : "password";
    }

    // серверы
    $("#serverList").addEventListener("click", (e) => {
      const row = e.target.closest(".server-row");
      if (!row) return;
      b() && b().selectServer(Number(row.dataset.i));
    });

    // исключения: выбор, двойной клик = удалить
    $("#processList").addEventListener("click", (e) => {
      const item = e.target.closest(".process-item");
      if (!item) return;
      b() && b().selectExcl(Number(item.dataset.i));
    });
    $("#processList").addEventListener("dblclick", () => b() && b().removeProcess());

    // поле процесса: печатаем, фильтруем список, Enter = добавить
    const pin = $("#processInput");
    pin.addEventListener("input", () => {
      b() && b().setProcText(pin.value);
      VPL.filterDrop(pin.value);
    });
    pin.addEventListener("focus", () => VPL.filterDrop(pin.value));
    pin.addEventListener("blur", () => window.setTimeout(() => VPL.closeDrop(), 120));
    pin.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        b() && b().addProcess();
      } else if (e.key === "Escape") {
        VPL.closeDrop();
      }
    });
    $("#addProcess").onclick = () => b() && b().addProcess();
    $("#removeProcess").onclick = () => b() && b().removeProcess();
    $("#clearProcesses").onclick = () => b() && b().clearProcesses();

    $("#processDrop").addEventListener("mousedown", (e) => {
      const item = e.target.closest(".drop-item");
      if (!item) return;
      e.preventDefault();
      pin.value = item.textContent;
      b() && b().setProcText(pin.value);
      VPL.closeDrop();
      pin.focus();
    });

    // сегменты режимов
    $$(".exception-segments .segment").forEach((btn) => {
      btn.onclick = () => b() && b().setAppMode(btn.dataset.exclusionMode);
    });
    $$(".mode-segments .segment").forEach((btn) => {
      btn.onclick = () => b() && b().setMode(btn.dataset.connectionMode);
    });

    // ракета DPI: ЛКМ - вкл/выкл, ПКМ - автоподбор
    const rocket = $("#rocket");
    rocket.onclick = () => b() && b().toggleDpi();
    rocket.oncontextmenu = (e) => {
      e.preventDefault();
      b() && b().autoDpi();
    };

    // плашка обновления (2.4.0)
    $("#updateNow").onclick = () => b() && b().doUpdate();
    $("#updateLater").onclick = () => b() && b().dismissUpdate();

    // перетаскивание окна за шапку
    const bar = $(".titlebar");
    bar.addEventListener("mousedown", (e) => {
      if (e.target.closest("button")) return;
      VPL.startDrag(e);
    });

    VPL.connect();
  });

  window.VPL = VPL;
})();