(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const saveIndicator = document.getElementById("save-indicator");

  function setSaveState(message, state = "") {
    if (!saveIndicator) return;
    saveIndicator.textContent = message;
    saveIndicator.dataset.state = state;
  }

  function formObject(form) {
    const data = new FormData(form);
    return Object.fromEntries(data.entries());
  }

  const stepForm = document.getElementById("step-form");
  if (stepForm) {
    let timer;
    let pending = false;
    let saveAgain = false;
    const submissionBadge = stepForm.querySelector(".submission-status");
    const setSubmissionBadge = (state) => {
      if (!submissionBadge || !state) return;
      submissionBadge.className = "submission-status " + state.key;
      const label = submissionBadge.querySelector("strong");
      if (label) label.textContent = state.label;
    };
    const updateSubmissionBadgeLocally = () => {
      if (!submissionBadge) return;
      const field = (name) => stepForm.querySelector("[name='" + name + "']")?.value || "";
      const selected = field("srp_submission_status");
      const hasDetails = [
        field("srp_entry_completed_at"),
        field("srp_entry_timezone"),
        field("srp_submitted_at"),
        field("srp_submitted_timezone"),
        field("srp_reference_number"),
        field("srp_receipt_evidence_id"),
      ].every(Boolean);
      if (selected === "submitted_unverified" && hasDetails) {
        setSubmissionBadge({
          key: "unverified",
          label: "資料齊備；等待 D7 回執 Evidence ID 核對",
        });
      } else if (selected === "submitted_unverified") {
        setSubmissionBadge({ key: "unverified", label: "已回報提交，待補齊提交證據" });
      } else if (field("srp_entry_completed_at")) {
        setSubmissionBadge({ key: "not-submitted", label: "欄位已填，尚未正式提交" });
      } else {
        setSubmissionBadge({ key: "pending", label: "等待 SRP 人員回報" });
      }
    };
    const queueSave = () => {
      clearTimeout(timer);
      setSaveState("正在保存…", "saving");
      timer = setTimeout(async () => {
        if (pending) {
          saveAgain = true;
          return;
        }
        pending = true;
        try {
          const response = await fetch(
            "/api/cases/" + encodeURIComponent(stepForm.dataset.caseId) + "/auto-save",
            {
              method: "POST",
              headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
              body: JSON.stringify({
                step: stepForm.dataset.step,
                values: formObject(stepForm),
              }),
            },
          );
          const result = await response.json();
          if (!response.ok || !result.ok) throw new Error(result.error || "保存失敗");
          setSaveState("已自動保存", "saved");
          if (result.submission_state) setSubmissionBadge(result.submission_state);
        } catch (error) {
          setSaveState(error.message || "保存失敗，請按「儲存」", "error");
        } finally {
          pending = false;
          if (saveAgain) {
            saveAgain = false;
            queueSave();
          }
        }
      }, 650);
    };

    const handleAutoSave = (event) => {
      const field = event.currentTarget;
      if (field.matches("[data-evidence-select]") && field.value === "__create__") return;
      const syncTarget = field.dataset.syncTarget;
      if (syncTarget) {
        const storedValue = stepForm.elements.namedItem(syncTarget);
        if (storedValue) {
          const legacyValue = field.dataset.legacyValue || "";
          const legacyTargetName = field.dataset.legacyTarget || "";
          const legacyTarget = legacyTargetName
            ? stepForm.elements.namedItem(legacyTargetName)
            : null;
          if (legacyValue && legacyTarget) {
            const legacyNote = "原欄位文字：" + legacyValue;
            if (!legacyTarget.value.includes(legacyNote)) {
              legacyTarget.value = [legacyTarget.value.trim(), legacyNote].filter(Boolean).join("\n");
            }
            field.dataset.legacyValue = "";
          }
          const syncZone = field.dataset.syncZone || (
            syncTarget.endsWith("__obtained_at")
              ? syncTarget.replace(/obtained_at$/, "timezone")
              : ""
          );
          if (field.value && syncZone) {
            const zoneField = stepForm.elements.namedItem(syncZone);
            const defaultTimezone = document.getElementById("awareness-timezone")?.value || "Asia/Taipei";
            if (zoneField && !zoneField.value.trim()) zoneField.value = defaultTimezone;
          }
          storedValue.value = field.value.replace("T", " ");
        }
      }
      queueSave();
    };

    stepForm.querySelectorAll("[data-autosave]").forEach((field) => {
      field.addEventListener("input", handleAutoSave);
      field.addEventListener("change", handleAutoSave);
    });
    if (submissionBadge) {
      stepForm.querySelectorAll(".submission-card input, .submission-card select").forEach((field) => {
        field.addEventListener("input", updateSubmissionBadgeLocally);
        field.addEventListener("change", updateSubmissionBadgeLocally);
      });
    }

    stepForm.querySelectorAll("[data-intent]").forEach((button) => {
      button.addEventListener("click", () => {
        const intent = document.getElementById("form-intent");
        if (intent) intent.value = button.dataset.intent;
      });
    });

    stepForm.addEventListener("submit", () => {
      setSaveState("正在保存…", "saving");
    });

    const evidenceList = document.getElementById("evidence-list");
    const addEvidence = document.getElementById("add-evidence");
    if (evidenceList && addEvidence) {
      const renumberEvidence = () => {
        [...evidenceList.querySelectorAll(".evidence-card")].forEach((card, index) => {
          card.dataset.evidenceRow = String(index);
          const title = card.querySelector(".evidence-card-title strong");
          if (title) title.textContent = "Evidence " + (index + 1);
          card.querySelectorAll("[name]").forEach((field) => {
            field.name = field.name.replace(/evidence__\d+__/, "evidence__" + index + "__");
          });
        });
      };

      const makeLabel = (caption, name, placeholder = "") => {
        const label = document.createElement("label");
        const span = document.createElement("span");
        span.textContent = caption;
        const input = document.createElement("input");
        input.name = name;
        input.placeholder = placeholder;
        input.dataset.autosave = "";
        input.addEventListener("input", queueSave);
        input.addEventListener("change", queueSave);
        label.append(span, input);
        return label;
      };

      addEvidence.addEventListener("click", () => {
        const index = evidenceList.querySelectorAll(".evidence-card").length;
        const card = document.createElement("article");
        card.className = "evidence-card";
        card.dataset.evidenceRow = String(index);
        const heading = document.createElement("div");
        heading.className = "evidence-card-title";
        const strong = document.createElement("strong");
        strong.textContent = "Evidence " + (index + 1);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "remove-evidence";
        remove.textContent = "移除";
        heading.append(strong, remove);

        const grid = document.createElement("div");
        grid.className = "evidence-grid";
        grid.append(
          makeLabel("Evidence ID", "evidence__" + index + "__evidence_id", "EV-001"),
          makeLabel("取得時間／時區", "evidence__" + index + "__obtained_at"),
          makeLabel("證據類型", "evidence__" + index + "__kind", "例如 PoC、日誌"),
        );
        const description = document.createElement("label");
        description.className = "wide";
        const descriptionTitle = document.createElement("span");
        descriptionTitle.textContent = "內容描述";
        const descriptionInput = document.createElement("textarea");
        descriptionInput.name = "evidence__" + index + "__description";
        descriptionInput.rows = 2;
        descriptionInput.dataset.autosave = "";
        descriptionInput.addEventListener("input", queueSave);
        descriptionInput.addEventListener("change", queueSave);
        description.append(descriptionTitle, descriptionInput);
        grid.append(
          description,
          makeLabel("來源", "evidence__" + index + "__source"),
          makeLabel("受控保存位置", "evidence__" + index + "__location"),
          makeLabel("保管人", "evidence__" + index + "__custodian"),
          makeLabel("關聯步驟", "evidence__" + index + "__step", "D3、D5…"),
        );
        card.append(heading, grid);
        evidenceList.append(card);
        queueSave();
      });

      evidenceList.addEventListener("click", (event) => {
        const remove = event.target.closest(".remove-evidence");
        if (!remove) return;
        remove.closest(".evidence-card")?.remove();
        renumberEvidence();
        queueSave();
      });
    }
  }

  const awarenessForm = document.getElementById("awareness-form");
  if (awarenessForm) {
    let timer;
    let pending = false;
    let saveAgain = false;
    const status = document.getElementById("awareness-save");
    const queueAwarenessSave = () => {
      clearTimeout(timer);
      if (status) status.textContent = "正在保存…";
      timer = setTimeout(async () => {
        if (pending) {
          saveAgain = true;
          return;
        }
        pending = true;
        try {
          const payload = formObject(awarenessForm);
          const response = await fetch(
            "/api/cases/" + encodeURIComponent(awarenessForm.dataset.caseId) + "/awareness",
            {
              method: "POST",
              headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
              body: JSON.stringify(payload),
            },
          );
          const result = await response.json();
          if (!response.ok || !result.ok) throw new Error(result.error || "保存失敗");
          if (status) status.textContent = "已保存";
          updateDeadlineCards(result.deadlines, result.deadline_labels, result.awareness?.timezone);
        } catch (error) {
          if (status) status.textContent = error.message || "保存失敗";
        } finally {
          pending = false;
          if (saveAgain) {
            saveAgain = false;
            queueAwarenessSave();
          }
        }
      }, 700);
    };
    awarenessForm.querySelectorAll("[data-awareness-autosave]").forEach((field) => {
      field.addEventListener("input", queueAwarenessSave);
      field.addEventListener("change", queueAwarenessSave);
    });
  }

  function updateDeadlineCards(deadlines, labels, timezone) {
    document.querySelectorAll("[data-countdown]").forEach((card) => {
      const key = card.dataset.countdown;
      card.dataset.deadline = deadlines?.[key] || "";
      card.dataset.timezone = timezone || "Asia/Taipei";
      const date = document.getElementById("deadline-date-" + key);
      if (date) date.textContent = labels?.[key] || "截止時間待計算";
    });
    tickCountdowns();
  }

  function durationText(seconds) {
    const absolute = Math.abs(seconds);
    const days = Math.floor(absolute / 86400);
    const hours = Math.floor((absolute % 86400) / 3600);
    const minutes = Math.floor((absolute % 3600) / 60);
    const remainder = absolute % 60;
    const parts = [];
    if (days) parts.push(days + " 天");
    parts.push(hours + " 小時", minutes + " 分", remainder + " 秒");
    return parts.join(" ");
  }

  function tickCountdowns() {
    document.querySelectorAll("[data-countdown]").forEach((card) => {
      const value = document.getElementById("countdown-" + card.dataset.countdown);
      if (!value) return;
      const deadline = Date.parse(card.dataset.deadline || "");
      card.classList.remove("overdue");
      if (!Number.isFinite(deadline)) {
        value.textContent = "待填知悉時間";
        return;
      }
      const remaining = Math.floor((deadline - Date.now()) / 1000);
      if (remaining >= 0) {
        value.textContent = "剩餘 " + durationText(remaining);
      } else {
        value.textContent = "已逾期 " + durationText(remaining);
        card.classList.add("overdue");
      }
    });
  }

  tickCountdowns();
  window.setInterval(tickCountdowns, 1000);
})();
