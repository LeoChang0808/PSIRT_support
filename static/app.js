(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const saveIndicator = document.getElementById("save-indicator");
  const exportReadinessNode = document.getElementById("export-readiness");
  let exportReadiness = {};
  try {
    exportReadiness = JSON.parse(exportReadinessNode?.textContent || "{}");
  } catch (_error) {
    exportReadiness = {};
  }

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm || "確定執行此操作？")) event.preventDefault();
    });
  });

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
    const exportWarningDialog = document.getElementById("export-warning-dialog");
    const exportWarningSummary = document.getElementById("export-warning-summary");
    const exportMissingSection = document.getElementById("export-missing-section");
    const exportMissingCount = document.getElementById("export-missing-count");
    const exportMissingList = document.getElementById("export-missing-list");
    const exportMissingMore = document.getElementById("export-missing-more");
    const exportIncompleteSection = document.getElementById("export-incomplete-section");
    const exportIncompleteCount = document.getElementById("export-incomplete-count");
    const exportIncompleteList = document.getElementById("export-incomplete-list");
    const exportIncompleteMore = document.getElementById("export-incomplete-more");
    const exportWarningCancel = document.getElementById("export-warning-cancel");
    const exportWarningContinue = document.getElementById("export-warning-continue");
    let pendingExportUrl = "";
    const liveExportReadiness = () => {
      const state = JSON.parse(JSON.stringify(exportReadiness || {}));
      (state.fields || []).forEach((field) => {
        const stored = [...document.querySelectorAll("[name]")].find((item) => item.name === field.name);
        if (!stored) return;
        const picker = field.picker_name
          ? [...document.querySelectorAll("[name]")].find((item) => item.name === field.picker_name)
          : null;
        const value = picker ? picker.value : stored.value;
        field.filled = Boolean(String(value || "").trim());
      });
      return state;
    };
    const renderWarningList = (list, more, items, labelFor) => {
      list.replaceChildren();
      items.slice(0, 6).forEach((item) => {
        const row = document.createElement("li");
        row.textContent = labelFor(item);
        list.append(row);
      });
      const remaining = items.length - 6;
      more.textContent = remaining > 0 ? `另有 ${remaining} 項未列出。` : "";
    };
    const openExportWarning = (href, state) => {
      const missing = (state.fields || []).filter((field) => !field.filled);
      const incomplete = state.incomplete_steps || [];
      if (!missing.length && !incomplete.length) return false;
      pendingExportUrl = href;
      const reasons = [];
      if (missing.length) reasons.push(`尚有 ${missing.length} 個欄位未填`);
      if (incomplete.length) reasons.push(`${incomplete.length} 個流程步驟未完成`);
      exportWarningSummary.textContent = `${reasons.join("，")}。仍可選擇繼續匯出。`;
      exportMissingSection.hidden = !missing.length;
      exportMissingCount.textContent = `${missing.length} 項`;
      renderWarningList(exportMissingList, exportMissingMore, missing, (field) => field.label);
      exportIncompleteSection.hidden = !incomplete.length;
      exportIncompleteCount.textContent = `${incomplete.length} 項`;
      renderWarningList(
        exportIncompleteList, exportIncompleteMore, incomplete,
        (item) => `${item.code} · ${item.label}`,
      );
      exportWarningDialog.showModal();
      return true;
    };
    document.querySelectorAll("[data-export-link]").forEach((link) => {
      link.addEventListener("click", (event) => {
        if (openExportWarning(link.href, liveExportReadiness())) event.preventDefault();
      });
    });
    exportWarningCancel?.addEventListener("click", () => {
      pendingExportUrl = "";
      exportWarningDialog.close();
    });
    exportWarningContinue?.addEventListener("click", () => {
      if (!pendingExportUrl) return exportWarningDialog.close();
      const url = pendingExportUrl;
      pendingExportUrl = "";
      exportWarningDialog.close();
      window.location.assign(url);
    });
    exportWarningDialog?.addEventListener("close", () => {
      if (exportWarningDialog.returnValue !== "continue") pendingExportUrl = "";
    });
    const intermediateToggle = stepForm.querySelector("[data-intermediate-toggle]");
    const intermediateSubmission = stepForm.querySelector("[data-intermediate-submission]");
    if (intermediateToggle && intermediateSubmission) {
      const syncIntermediateCard = () => {
        intermediateSubmission.hidden = !intermediateToggle.checked;
        document.querySelectorAll("[data-intermediate-pdf]").forEach((item) => {
          item.hidden = !intermediateToggle.checked;
        });
      };
      syncIntermediateCard();
      intermediateToggle.addEventListener("change", syncIntermediateCard);
    }
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
          if (result.export_readiness) exportReadiness = result.export_readiness;
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

    const evidenceDialog = document.getElementById("evidence-dialog");
    const evidenceDialogForm = document.getElementById("evidence-dialog-form");
    const evidenceDialogError = document.getElementById("evidence-dialog-error");
    const evidenceDialogCancel = document.getElementById("evidence-dialog-cancel");
    let activeEvidenceSelect = null;
    const restoreEvidenceSelection = () => {
      if (activeEvidenceSelect) {
        activeEvidenceSelect.value = activeEvidenceSelect.dataset.previousValue || "";
        activeEvidenceSelect = null;
      }
    };
    if (evidenceDialog && evidenceDialogForm) {
      stepForm.querySelectorAll("[data-evidence-select]").forEach((select) => {
        select.dataset.previousValue = select.value;
        select.addEventListener("change", () => {
          if (select.value !== "__create__") {
            select.dataset.previousValue = select.value;
            return;
          }
          activeEvidenceSelect = select;
          select.value = select.dataset.previousValue || "";
          evidenceDialogError.textContent = "";
          evidenceDialogForm.reset();
          const timezone = document.getElementById("awareness-timezone")?.value || "Asia/Taipei";
          const timezoneField = evidenceDialogForm.elements.namedItem("timezone");
          if (timezoneField) timezoneField.value = timezone;
          evidenceDialog.showModal();
          evidenceDialogForm.elements.namedItem("evidence_id")?.focus();
        });
      });

      evidenceDialogCancel?.addEventListener("click", () => {
        restoreEvidenceSelection();
        evidenceDialog.close();
      });
      evidenceDialog.addEventListener("cancel", restoreEvidenceSelection);
      evidenceDialog.addEventListener("click", (event) => {
        if (event.target === evidenceDialog) {
          restoreEvidenceSelection();
          evidenceDialog.close();
        }
      });
      evidenceDialogForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!activeEvidenceSelect) return;
        const submitButton = evidenceDialogForm.querySelector("[type='submit']");
        const data = Object.fromEntries(new FormData(evidenceDialogForm).entries());
        data.step = stepForm.dataset.step;
        data.field_name = activeEvidenceSelect.name;
        if (evidenceDialogError) evidenceDialogError.textContent = "";
        if (submitButton) submitButton.disabled = true;
        try {
          const response = await fetch(
            "/api/cases/" + encodeURIComponent(stepForm.dataset.caseId) + "/evidence",
            {
              method: "POST",
              headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
              body: JSON.stringify(data),
            },
          );
          const result = await response.json();
          if (!response.ok || !result.ok) throw new Error(result.error || "建立證據失敗。");
          const evidence = result.evidence;
          if (result.export_readiness) exportReadiness = result.export_readiness;
          stepForm.querySelectorAll("[data-evidence-select]").forEach((select) => {
            let option = [...select.options].find((item) => item.value === evidence.evidence_id);
            if (!option) {
              option = document.createElement("option");
              option.value = evidence.evidence_id;
              option.textContent = evidence.evidence_id + (evidence.kind ? " · " + evidence.kind : "");
              const createOption = select.querySelector("option[value='__create__']");
              select.insertBefore(option, createOption?.nextSibling || null);
            }
          });
          activeEvidenceSelect.value = evidence.evidence_id;
          activeEvidenceSelect.dataset.previousValue = evidence.evidence_id;
          activeEvidenceSelect = null;
          evidenceDialog.close();
          queueSave();
          setSaveState("證據已建立，Evidence ID 已選入欄位", "saved");
        } catch (error) {
          if (evidenceDialogError) evidenceDialogError.textContent = error.message || "建立證據失敗。";
        } finally {
          if (submitButton) submitButton.disabled = false;
        }
      });
    }
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
    if (evidenceList) {
      const renumberEvidence = () => {
        [...evidenceList.querySelectorAll(".evidence-list-item")].forEach((card, index) => {
          card.dataset.evidenceRow = String(index);
          const number = card.querySelector(".evidence-number");
          if (number) number.textContent = String(index + 1);
          card.querySelectorAll("[name]").forEach((field) => {
            field.name = field.name.replace(/evidence__\d+__/, "evidence__" + index + "__");
          });
          card.querySelectorAll("[data-sync-target], [data-legacy-target]").forEach((field) => {
            if (field.dataset.syncTarget) {
              field.dataset.syncTarget = field.dataset.syncTarget.replace(
                /evidence__\d+__/, "evidence__" + index + "__",
              );
            }
            if (field.dataset.legacyTarget) {
              field.dataset.legacyTarget = field.dataset.legacyTarget.replace(
                /evidence__\d+__/, "evidence__" + index + "__",
              );
            }
          });
        });
      };
      evidenceList.addEventListener("click", (event) => {
        const remove = event.target.closest(".remove-evidence");
        if (!remove) return;
        remove.closest(".evidence-list-item")?.remove();
        renumberEvidence();
        if (!evidenceList.querySelector(".evidence-list-item")) {
          const empty = document.createElement("li");
          empty.className = "empty-inline evidence-empty";
          const title = document.createElement("strong");
          title.textContent = "尚無證據紀錄";
          const hint = document.createElement("p");
          hint.textContent = "請回到 D1–D6 任一 Evidence ID 下拉選單，選擇「建立證據」。";
          empty.append(title, hint);
          evidenceList.append(empty);
        }
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
          if (result.export_readiness) exportReadiness = result.export_readiness;
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
