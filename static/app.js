(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const appRoot = document.querySelector('meta[name="application-root"]')?.content || "";
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

  async function parseApiResponse(response, failureMessage) {
    let body;
    try {
      body = JSON.parse(await response.text());
    } catch (_error) {
      throw new Error(`${failureMessage}（HTTP ${response.status}，伺服器回應格式無效）`);
    }
    if (!response.ok || !body?.ok) {
      throw new Error(body?.error || `${failureMessage}（HTTP ${response.status}）`);
    }
    return body;
  }

  const evidenceReadinessDefinitions = [
    ["evidence_id", "Evidence ID", ""],
    ["obtained_at", "取得時間", "_picker"],
    ["timezone", "時區", ""],
    ["kind", "證據類型", ""],
    ["description", "內容描述", ""],
    ["source", "來源", ""],
    ["location", "受控保存位置", ""],
    ["custodian", "保管人", ""],
  ];
  const appendEvidenceReadiness = (evidence) => {
    if (!Array.isArray(exportReadiness.fields)) return;
    let maxIndex = -1;
    exportReadiness.fields.forEach((field) => {
      const match = /^evidence__(\d+)__/.exec(field.name || "");
      if (match) maxIndex = Math.max(maxIndex, Number(match[1]));
    });
    exportReadiness.fields = exportReadiness.fields.filter(
      (field) => field.name !== "evidence__none",
    );
    const index = maxIndex + 1;
    evidenceReadinessDefinitions.forEach(([key, label, pickerSuffix]) => {
      const name = `evidence__${index}__${key}`;
      exportReadiness.fields.push({
        name,
        picker_name: pickerSuffix ? `${name}${pickerSuffix}` : "",
        label: `D7 · ${evidence.evidence_id || "證據"} · ${label}`,
        filled: Boolean(String(evidence[key] || "").trim()),
      });
    });
  };

  let storageWriteQueue = Promise.resolve();
  function enqueueStorageWrite(operation) {
    const result = storageWriteQueue.then(operation, operation);
    storageWriteQueue = result.catch(() => {});
    return result;
  }

  let flushAwarenessSave = async () => {};
  const stepForm = document.getElementById("step-form");
  const setStorageVersion = (version) => {
    if (version === undefined || version === null) return;
    const nextVersion = String(version);
    if (stepForm) {
      stepForm.dataset.storageVersion = nextVersion;
      const stepVersion = stepForm.querySelector("[name='storage_version']");
      if (stepVersion) stepVersion.value = nextVersion;
    }
    const awarenessForm = document.getElementById("awareness-form");
    if (awarenessForm) {
      awarenessForm.dataset.storageVersion = nextVersion;
      const awarenessVersion = awarenessForm.querySelector("[name='storage_version']");
      if (awarenessVersion) awarenessVersion.value = nextVersion;
    }
  };
  if (stepForm) {
    let timer;
    let latestStepSave = Promise.resolve(true);
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
      const evidenceList = document.getElementById("evidence-list");
      if (evidenceList && Array.isArray(state.fields)) {
        state.fields = state.fields.filter(
          (field) => field.name !== "evidence__none" && !/^evidence__\d+__/.test(field.name),
        );
        const cards = [...evidenceList.querySelectorAll(".evidence-list-item")];
        if (!cards.length) {
          state.fields.push({
            name: "evidence__none",
            picker_name: "",
            label: "D7 · Evidence 索引",
            filled: false,
          });
        }
        cards.forEach((card, index) => {
          const evidenceId = card.querySelector(`[name="evidence__${index}__evidence_id"]`)?.value.trim() || "證據";
          evidenceReadinessDefinitions.forEach(([key, label, pickerSuffix]) => {
            const name = `evidence__${index}__${key}`;
            const stored = card.querySelector(`[name="${name}"]`);
            const pickerName = pickerSuffix ? `${name}${pickerSuffix}` : "";
            state.fields.push({
              name,
              picker_name: pickerName,
              label: `D7 · ${evidenceId} · ${label}`,
              filled: Boolean(String(stored?.value || "").trim()),
            });
          });
        });
      }
      (state.fields || []).forEach((field) => {
        const stored = [...document.querySelectorAll("[name]")].find((item) => item.name === field.name);
        if (!stored) return;
        const picker = field.picker_name
          ? [...document.querySelectorAll("[name]")].find((item) => item.name === field.picker_name)
          : null;
        const value = picker?.value || stored.value;
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
    const saveStepNow = async () => {
      setSaveState("正在保存…", "saving");
      try {
        const result = await enqueueStorageWrite(async () => {
          const response = await fetch(
            appRoot + "/api/cases/" + encodeURIComponent(stepForm.dataset.caseId) + "/auto-save",
            {
              method: "POST",
              headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
              body: JSON.stringify({
                step: stepForm.dataset.step,
                storage_version: Number(stepForm.dataset.storageVersion || 0),
                values: formObject(stepForm),
              }),
            },
          );
          const responseBody = await parseApiResponse(response, "保存失敗");
          setStorageVersion(responseBody.storage_version);
          return responseBody;
        });
        setSaveState("已自動保存", "saved");
        if (result.submission_state) setSubmissionBadge(result.submission_state);
        return true;
      } catch (error) {
        setSaveState(error.message || "保存失敗，請按「儲存」", "error");
        return false;
      }
    };
    const queueSave = () => {
      clearTimeout(timer);
      setSaveState("正在保存…", "saving");
      timer = setTimeout(() => {
        latestStepSave = saveStepNow();
      }, 650);
    };
    const flushStepSave = async () => {
      clearTimeout(timer);
      await latestStepSave;
      latestStepSave = saveStepNow();
      return await latestStepSave;
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
        data.storage_version = Number(stepForm.dataset.storageVersion || 0);
        if (evidenceDialogError) evidenceDialogError.textContent = "";
        if (submitButton) submitButton.disabled = true;
        try {
          const result = await enqueueStorageWrite(async () => {
            data.storage_version = Number(stepForm.dataset.storageVersion || 0);
            const response = await fetch(
              appRoot + "/api/cases/" + encodeURIComponent(stepForm.dataset.caseId) + "/evidence",
              {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
                body: JSON.stringify(data),
              },
            );
            const responseBody = await parseApiResponse(response, "建立證據失敗。");
            setStorageVersion(responseBody.storage_version);
            return responseBody;
          });
          const evidence = result.evidence;
          appendEvidenceReadiness(evidence);
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

    stepForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      clearTimeout(timer);
      setSaveState("正在保存…", "saving");
      try {
        await flushAwarenessSave();
        await storageWriteQueue;
        HTMLFormElement.prototype.submit.call(stepForm);
      } catch (error) {
        setSaveState(error.message || "保存失敗，請先重試", "error");
      }
    });

    const evidenceList = document.getElementById("evidence-list");
    if (evidenceList) {
      const evidenceDeleteDialog = document.getElementById("evidence-delete-dialog");
      const evidenceDeleteTitle = document.getElementById("evidence-delete-title");
      const evidenceDeleteDescription = document.getElementById("evidence-delete-description");
      const evidenceDeleteReferencesSection = document.getElementById("evidence-delete-references-section");
      const evidenceDeleteReferences = document.getElementById("evidence-delete-references");
      const evidenceDeleteNoReferences = document.getElementById("evidence-delete-no-references");
      const evidenceDeleteError = document.getElementById("evidence-delete-error");
      const evidenceDeleteConfirm = document.getElementById("evidence-delete-confirm");
      const evidenceDeleteCancel = document.getElementById("evidence-delete-cancel");
      let activeEvidenceDeleteCard = null;
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
      const updateEvidenceTitle = (card) => {
        const evidenceId = card.querySelector("[data-evidence-id-input]")?.value.trim() || "未命名證據";
        const title = card.querySelector(".evidence-summary-copy strong");
        if (title) title.textContent = evidenceId;
        card.querySelector(".remove-evidence")?.setAttribute(
          "aria-label", `刪除 Evidence ID ${evidenceId}`,
        );
      };
      const addEmptyEvidenceMessage = () => {
        if (evidenceList.querySelector(".evidence-list-item")) return;
        const empty = document.createElement("li");
        empty.className = "empty-inline evidence-empty";
        const title = document.createElement("strong");
        title.textContent = "尚無證據紀錄";
        const hint = document.createElement("p");
        hint.textContent = "請回到 D1–D6 任一 Evidence ID 下拉選單，選擇「建立證據」。";
        empty.append(title, hint);
        evidenceList.append(empty);
      };
      evidenceDeleteCancel?.addEventListener("click", () => {
        activeEvidenceDeleteCard = null;
        evidenceDeleteDialog?.close();
      });
      evidenceDeleteDialog?.addEventListener("cancel", () => {
        activeEvidenceDeleteCard = null;
      });
      evidenceList.addEventListener("input", (event) => {
        const field = event.target.closest("[data-evidence-id-input]");
        if (field) updateEvidenceTitle(field.closest(".evidence-list-item"));
      });
      evidenceList.addEventListener("click", (event) => {
        const remove = event.target.closest(".remove-evidence");
        if (!remove) return;
        activeEvidenceDeleteCard = remove.closest(".evidence-list-item");
        if (!activeEvidenceDeleteCard || !evidenceDeleteDialog) return;
        const evidenceId = activeEvidenceDeleteCard.querySelector("[data-evidence-id-input]")?.value.trim() || "未命名證據";
        const references = [...activeEvidenceDeleteCard.querySelectorAll(".evidence-reference-list span")]
          .map((item) => item.textContent.trim())
          .filter(Boolean);
        evidenceDeleteTitle.textContent = `確定刪除 Evidence ID ${evidenceId}？`;
        evidenceDeleteDescription.textContent = references.length
          ? "刪除後會移除紀錄，並清除以下欄位中的 Evidence ID 引用。"
          : "刪除後會移除這筆證據紀錄。";
        evidenceDeleteReferences.replaceChildren();
        references.forEach((reference) => {
          const item = document.createElement("li");
          item.textContent = reference;
          evidenceDeleteReferences.append(item);
        });
        evidenceDeleteReferencesSection.hidden = !references.length;
        evidenceDeleteNoReferences.hidden = Boolean(references.length);
        evidenceDeleteError.textContent = "";
        evidenceDeleteDialog.showModal();
        evidenceDeleteConfirm?.focus();
      });
      evidenceDeleteConfirm?.addEventListener("click", async () => {
        if (!activeEvidenceDeleteCard) return;
        evidenceDeleteConfirm.disabled = true;
        evidenceDeleteCancel.disabled = true;
        evidenceDeleteError.textContent = "";
        try {
          clearTimeout(timer);
          if (!await flushStepSave()) {
            throw new Error("案件欄位尚未保存成功，請先處理保存錯誤後再刪除。");
          }
          const evidenceId = activeEvidenceDeleteCard
            .querySelector("[data-evidence-id-input]")?.value.trim();
          if (!evidenceId) throw new Error("Evidence ID 不可留空。");
          await enqueueStorageWrite(async () => {
            const response = await fetch(
              appRoot + "/api/cases/" + encodeURIComponent(stepForm.dataset.caseId) + "/evidence/delete",
              {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
                body: JSON.stringify({
                  evidence_id: evidenceId,
                  confirm_delete: true,
                  storage_version: Number(stepForm.dataset.storageVersion || 0),
                }),
              },
            );
            const responseBody = await parseApiResponse(response, "刪除證據失敗");
            setStorageVersion(responseBody.storage_version);
            return responseBody;
          });
          activeEvidenceDeleteCard.remove();
          activeEvidenceDeleteCard = null;
          renumberEvidence();
          addEmptyEvidenceMessage();
          evidenceDeleteDialog.close();
          setSaveState("證據與引用欄位已刪除", "saved");
        } catch (error) {
          evidenceDeleteError.textContent = error.message || "刪除證據失敗。";
        } finally {
          evidenceDeleteConfirm.disabled = false;
          evidenceDeleteCancel.disabled = false;
        }
      });
    }
  }

  const awarenessForm = document.getElementById("awareness-form");
  if (awarenessForm) {
    let timer;
    let pending = false;
    let saveAgain = false;
    let dirty = false;
    const status = document.getElementById("awareness-save");
    const saveAwarenessNow = () => enqueueStorageWrite(async () => {
      const payload = formObject(awarenessForm);
      const response = await fetch(
        appRoot + "/api/cases/" + encodeURIComponent(awarenessForm.dataset.caseId) + "/awareness",
        {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
          body: JSON.stringify(payload),
        },
      );
      const responseBody = await parseApiResponse(response, "保存失敗");
      setStorageVersion(responseBody.storage_version);
      updateDeadlineCards(
        responseBody.deadlines,
        responseBody.deadline_labels,
        responseBody.awareness?.timezone,
      );
      return responseBody;
    });
    const queueAwarenessSave = () => {
      dirty = true;
      clearTimeout(timer);
      if (status) status.textContent = "正在保存…";
      timer = setTimeout(async () => {
        if (pending) {
          saveAgain = true;
          return;
        }
        pending = true;
        try {
          await saveAwarenessNow();
          if (!saveAgain) dirty = false;
          if (status) status.textContent = "已保存";
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
    flushAwarenessSave = async () => {
      clearTimeout(timer);
      if (pending) await storageWriteQueue;
      clearTimeout(timer);
      saveAgain = false;
      if (!dirty) return;
      pending = true;
      try {
        await saveAwarenessNow();
        dirty = false;
        if (status) status.textContent = "已保存";
      } finally {
        pending = false;
        saveAgain = false;
        clearTimeout(timer);
      }
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
