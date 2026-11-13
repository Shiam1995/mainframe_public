/* api.js — thin fetch wrapper around the FastAPI backend.
   Everything is same-origin (the API also serves this frontend), so no CORS
   dance and no external hosts. */
(function () {
  const BASE = ""; // same origin

  async function req(method, path, body, isForm, noTrack) {
    const opts = { method, headers: {} };
    if (body !== undefined && body !== null) {
      if (isForm) {
        opts.body = body; // FormData
      } else {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
    }
    /* Every write in the app comes through here, which makes this the one
       place worth telling sync.js about — it drives the topbar "saved / saving
       / not saved" pill and the per-row mark. Reads are ignored: a failed GET
       shows you an empty screen, a failed WRITE silently loses your work. */
    /* `noTrack` is for POSTs that aren't writes — the barcode scanner posts a
       camera frame twice a second and gets data back; flashing "saving…" at
       every frame, and queueing a blurred one as a failed write, would be a
       lie about what happened. */
    const track = (method !== "GET" && window.sync && !noTrack)
      ? window.sync.begin(method, path, body, isForm) : null;
    try {
      const res = await fetch(BASE + path, opts);
      if (res.status === 204) { if (track) track.ok(null); return null; }
      const text = await res.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch { data = text; }
      if (!res.ok) {
        const msg = (data && data.detail) ? data.detail : `HTTP ${res.status}`;
        throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
      }
      if (track) track.ok(data);
      return data;
    } catch (err) {
      // Covers a rejected fetch (backend down, offline) as well as a non-2xx.
      if (track) track.fail(err);
      throw err;
    }
  }

  // Drops empty/undefined keys so `list({module: undefined})` isn't a filter.
  function query(obj) {
    const p = new URLSearchParams();
    Object.entries(obj || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") p.set(k, v);
    });
    const s = p.toString();
    return s ? "?" + s : "";
  }

  window.api = {
    get: (p) => req("GET", p),
    post: (p, b) => req("POST", p, b),
    patch: (p, b) => req("PATCH", p, b),
    del: (p) => req("DELETE", p),
    postForm: (p, form) => req("POST", p, form, true),
    // A POST that only reads (image in, data out) — kept out of the sync pill.
    postFormRead: (p, form) => req("POST", p, form, true, true),
    put: (p, b) => req("PUT", p, b),

    // Vision — content-creation module.
    vision: {
      pipelines: () => req("GET", "/api/vision/pipelines"),
      createPipeline: (b) => req("POST", "/api/vision/pipelines", b),
      updatePipeline: (id, b) => req("PUT", "/api/vision/pipelines/" + id, b),
      delPipeline: (id) => req("DELETE", "/api/vision/pipelines/" + id),
      addStage: (id, b) => req("POST", "/api/vision/pipelines/" + id + "/stages", b),
      updateStage: (id, sid, b) => req("PUT", "/api/vision/pipelines/" + id + "/stages/" + sid, b),
      delStage: (id, sid) => req("DELETE", "/api/vision/pipelines/" + id + "/stages/" + sid),
      reorderStages: (id, stage_ids) => req("PUT", "/api/vision/pipelines/" + id + "/reorder", { stage_ids }),
      tools: () => req("GET", "/api/vision/tools"),
      // writing / portfolio / network
      writing: () => req("GET", "/api/vision/writing"),
      createWriting: (b) => req("POST", "/api/vision/writing", b),
      updateWriting: (id, b) => req("PUT", "/api/vision/writing/" + id, b),
      advanceWriting: (id) => req("POST", "/api/vision/writing/" + id + "/advance"),
      delWriting: (id) => req("DELETE", "/api/vision/writing/" + id),
      portfolio: () => req("GET", "/api/vision/portfolio"),
      createPortfolio: (b) => req("POST", "/api/vision/portfolio", b),
      updatePortfolio: (id, b) => req("PUT", "/api/vision/portfolio/" + id, b),
      delPortfolio: (id) => req("DELETE", "/api/vision/portfolio/" + id),
      network: () => req("GET", "/api/vision/network"),
      createContact: (b) => req("POST", "/api/vision/network", b),
      updateContact: (id, b) => req("PUT", "/api/vision/network/" + id, b),
      delContact: (id) => req("DELETE", "/api/vision/network/" + id),
      contact: (id) => req("GET", "/api/vision/network/" + id),
      addInteraction: (id, b) => req("POST", "/api/vision/network/" + id + "/interactions", b),
      delInteraction: (id, iid) => req("DELETE", "/api/vision/network/" + id + "/interactions/" + iid),
      // YouTube
      videos: (qs) => req("GET", "/api/vision/videos" + (qs || "")),
      video: (id) => req("GET", "/api/vision/videos/" + id),
      createVideo: (b) => req("POST", "/api/vision/videos", b),
      updateVideo: (id, b) => req("PUT", "/api/vision/videos/" + id, b),
      delVideo: (id) => req("DELETE", "/api/vision/videos/" + id),
      advanceVideo: (id) => req("POST", "/api/vision/videos/" + id + "/advance"),
      addVideoEntry: (id, b) => req("POST", "/api/vision/videos/" + id + "/entries", b),
      delVideoEntry: (id, eid) => req("DELETE", "/api/vision/videos/" + id + "/entries/" + eid),
      // research
      addResearch: (id, b) => req("POST", "/api/vision/videos/" + id + "/research", b),
      updateResearch: (id, rid, b) => req("PUT", "/api/vision/videos/" + id + "/research/" + rid, b),
      delResearch: (id, rid) => req("DELETE", "/api/vision/videos/" + id + "/research/" + rid),
      // script markers
      addMarker: (id, b) => req("POST", "/api/vision/videos/" + id + "/markers", b),
      updateMarker: (id, mid, b) => req("PUT", "/api/vision/videos/" + id + "/markers/" + mid, b),
      delMarker: (id, mid) => req("DELETE", "/api/vision/videos/" + id + "/markers/" + mid),
      // storyboard
      addPanel: (id, b) => req("POST", "/api/vision/videos/" + id + "/storyboard", b),
      updatePanel: (id, sid, b) => req("PUT", "/api/vision/videos/" + id + "/storyboard/" + sid, b),
      delPanel: (id, sid) => req("DELETE", "/api/vision/videos/" + id + "/storyboard/" + sid),
      reorderPanels: (id, panel_ids) => req("PUT", "/api/vision/videos/" + id + "/storyboard/reorder", { panel_ids }),
      // thumbnail options
      addThumb: (id, b) => req("POST", "/api/vision/videos/" + id + "/thumbnails", b),
      updateThumb: (id, tid, b) => req("PUT", "/api/vision/videos/" + id + "/thumbnails/" + tid, b),
      delThumb: (id, tid) => req("DELETE", "/api/vision/videos/" + id + "/thumbnails/" + tid),
      addThumbFeedback: (id, tid, b) => req("POST", "/api/vision/videos/" + id + "/thumbnails/" + tid + "/feedback", b),
      delThumbFeedback: (id, tid, fid) => req("DELETE", "/api/vision/videos/" + id + "/thumbnails/" + tid + "/feedback/" + fid),
      // things a video's notes can @-mention (videos, concepts, ideas, docs)
      mentionables: (q) => req("GET", "/api/vision/mentionables?q=" + encodeURIComponent(q || "")),
      // prompt log (manual — no model API is ever called)
      addPrompt: (id, b) => req("POST", "/api/vision/videos/" + id + "/prompts", b),
      updatePrompt: (id, pid, b) => req("PUT", "/api/vision/videos/" + id + "/prompts/" + pid, b),
      usePromptAsScript: (id, pid) => req("POST", "/api/vision/videos/" + id + "/prompts/" + pid + "/use-as-script"),
      delPrompt: (id, pid) => req("DELETE", "/api/vision/videos/" + id + "/prompts/" + pid),
    },

    // Vault — finance / inventory / assets.
    /* One diary, two doors: `list({module})` is what a module's own tab shows,
       `day()` is what the Mainframe tab shows. Same nodes either way. */
    diary: {
      list: (q) => req("GET", "/api/diary" + query(q)),
      day: (d) => req("GET", "/api/diary/day/" + d),
      days: (limit) => req("GET", "/api/diary/days" + query({ limit })),
      create: (b) => req("POST", "/api/diary", b),
      update: (id, b) => req("PUT", "/api/diary/" + id, b),
      del: (id) => req("DELETE", "/api/diary/" + id),
      split: (text) => req("POST", "/api/diary/split", { text }),
      commit: (date, segments) => req("POST", "/api/diary/commit", { date, segments }),
    },

    vault: {
      accounts: () => req("GET", "/api/vault/accounts"),
      createAccount: (b) => req("POST", "/api/vault/accounts", b),
      updateAccount: (id, b) => req("PUT", "/api/vault/accounts/" + id, b),
      delAccount: (id) => req("DELETE", "/api/vault/accounts/" + id),
      transactions: (qs) => req("GET", "/api/vault/transactions" + (qs || "")),
      createTx: (b) => req("POST", "/api/vault/transactions", b),
      updateTx: (id, b) => req("PUT", "/api/vault/transactions/" + id, b),
      delTx: (id) => req("DELETE", "/api/vault/transactions/" + id),
      bulkImport: (b) => req("POST", "/api/vault/transactions/bulk", b),
      budget: () => req("GET", "/api/vault/budget"),
      createBudget: (b) => req("POST", "/api/vault/budget", b),
      months: (o) => req("GET", "/api/vault/months?n=" + (o.n || 6) + (o.end ? "&end=" + o.end : "")),
      setMonthCell: (b) => req("PUT", "/api/vault/months/cell", b),
      updateBudget: (id, b) => req("PUT", "/api/vault/budget/" + id, b),
      delBudget: (id) => req("DELETE", "/api/vault/budget/" + id),
      budgetActual: (month) => req("GET", "/api/vault/budget/actual" + (month ? "?month=" + month : "")),
      setIncome: (b) => req("PUT", "/api/vault/budget/income", b),
      investments: () => req("GET", "/api/vault/investments"),
      investmentsSummary: () => req("GET", "/api/vault/investments/summary"),
      createInvestment: (b) => req("POST", "/api/vault/investments", b),
      updateInvestment: (id, b) => req("PUT", "/api/vault/investments/" + id, b),
      delInvestment: (id) => req("DELETE", "/api/vault/investments/" + id),
      inventory: (qs) => req("GET", "/api/vault/inventory" + (qs || "")),
      createItem: (b) => req("POST", "/api/vault/inventory", b),
      updateItem: (id, b) => req("PUT", "/api/vault/inventory/" + id, b),
      delItem: (id) => req("DELETE", "/api/vault/inventory/" + id),
      diary: () => req("GET", "/api/vault/diary"),
      createDiary: (b) => req("POST", "/api/vault/diary", b),
      updateDiary: (id, b) => req("PUT", "/api/vault/diary/" + id, b),
      delDiary: (id) => req("DELETE", "/api/vault/diary/" + id),
      overview: (month) => req("GET", "/api/vault/overview" + (month ? "?month=" + month : "")),
      analytics: (kind, month) => req("GET", "/api/vault/analytics/" + kind + (month ? "?month=" + month : "")),
    },

    // Home screen — live stats, period snapshot, persisted preferences.
    home: {
      stats: () => req("GET", "/api/home/stats"),
      snapshot: (period) => req("GET", "/api/home/snapshot?period=" + (period || "weekly")),
      prefs: () => req("GET", "/api/home/prefs"),
      putPrefs: (data) => req("PUT", "/api/home/prefs", { data }),
    },

    wallpapers: {
      // Listing also syncs the cache, so images dropped in the folder show up
      // on the next home-screen load — no restart, no rescan click.
      list: () => req("GET", "/api/wallpapers"),
      rescan: (force) => req("POST", "/api/wallpapers/rescan?force=" + (force ? "1" : "0")),
    },

    // Module-card artwork, keyed by module. Same deal — the listing syncs.
    moduleCards: {
      list: () => req("GET", "/api/module-cards"),
      rescan: (force) => req("POST", "/api/module-cards/rescan?force=" + (force ? "1" : "0")),
    },

    // Images — Mainframe-level service, usable from any module/view.
    images: {
      list: (module, contextId) => {
        const q = [];
        if (module) q.push("module=" + encodeURIComponent(module));
        if (contextId) q.push("context_id=" + encodeURIComponent(contextId));
        return req("GET", "/api/images" + (q.length ? "?" + q.join("&") : ""));
      },
      upload: (file, name, module, contextId) => {
        const fd = new FormData();
        fd.append("file", file);
        fd.append("name", name);
        fd.append("module", module || "mainframe");
        if (contextId) fd.append("context_id", contextId);
        return req("POST", "/api/images", fd, true);
      },
      rename: (id, name) => req("PUT", "/api/images/" + id, { name }),
      del: (id) => req("DELETE", "/api/images/" + id),
      // manual ordering — Mainframe-level, any module's images
      reorder: (ids) => req("POST", "/api/images/reorder", { ids }),
      fileUrl: (id) => "/api/images/" + id + "/file",
    },
    health: () => req("GET", "/api/health"),

    // convenience per-resource helpers
    papers: {
      list: (q) => req("GET", "/api/synapse/papers" + (q || "")),
      get: (id) => req("GET", "/api/synapse/papers/" + id),
      upload: (form) => req("POST", "/api/synapse/papers", form, true),
      // A source typed in by hand — a book, a video series, a course. Same node
      // as an uploaded paper, just without a file.
      create: (b) => req("POST", "/api/synapse/papers/manual", b),
      // projects / decomposition tops / ideas a workspace subject can be brought
      // in from, grouped by kind
      linkable: () => req("GET", "/api/synapse/papers/linkable"),
      // move cards in the repository (shared reorder semantics)
      reorder: (ids) => req("POST", "/api/synapse/papers/reorder", { ids }),
      update: (id, b) => req("PATCH", "/api/synapse/papers/" + id, b),
      cycle: (id) => req("POST", "/api/synapse/papers/" + id + "/cycle-status"),
      del: (id) => req("DELETE", "/api/synapse/papers/" + id),
    },

    // Pulse module — habits / experiments / routines / medical / meds
    pulse: {
      habits: () => req("GET", "/api/pulse/habits"),
      habitTrends: () => req("GET", "/api/pulse/habits/trends"),
      trackingReport: (qs) => req("GET", "/api/pulse/tracking/report" + (qs || "")),
      createHabit: (b) => req("POST", "/api/pulse/habits", b),
      updateHabit: (id, b) => req("PUT", "/api/pulse/habits/" + id, b),
      delHabit: (id) => req("DELETE", "/api/pulse/habits/" + id),
      addSub: (id, b) => req("POST", "/api/pulse/habits/" + id + "/subs", b),
      delSub: (id, sid) => req("DELETE", "/api/pulse/habits/" + id + "/subs/" + sid),
      addHabitNote: (id, b) => req("POST", "/api/pulse/habits/" + id + "/notes", b),
      logDay: (id, b) => req("POST", "/api/pulse/habits/" + id + "/logs", b),
      areas: {
        week: (date) => req("GET", "/api/pulse/areas/week" + (date ? "?date=" + date : "")),
        list: () => req("GET", "/api/pulse/areas"),
        add: (b) => req("POST", "/api/pulse/areas", b),
        update: (key, b) => req("PATCH", "/api/pulse/areas/" + encodeURIComponent(key), b),
        del: (key) => req("DELETE", "/api/pulse/areas/" + encodeURIComponent(key)),
        markDay: (id, b) => req("POST", "/api/pulse/areas/habits/" + id + "/day", b),
      },
      experiments: () => req("GET", "/api/pulse/experiments"),
      createExperiment: (b) => req("POST", "/api/pulse/experiments", b),
      updateExperiment: (id, b) => req("PUT", "/api/pulse/experiments/" + id, b),
      delExperiment: (id) => req("DELETE", "/api/pulse/experiments/" + id),
      routines: () => req("GET", "/api/pulse/routines"),
      createRoutine: (b) => req("POST", "/api/pulse/routines", b),
      updateRoutine: (id, b) => req("PUT", "/api/pulse/routines/" + id, b),
      delRoutine: (id) => req("DELETE", "/api/pulse/routines/" + id),
      addStep: (id, b) => req("POST", "/api/pulse/routines/" + id + "/steps", b),
      delStep: (id, sid) => req("DELETE", "/api/pulse/routines/" + id + "/steps/" + sid),
      logStep: (id, sid, b) => req("POST", "/api/pulse/routines/" + id + "/steps/" + sid + "/logs", b),
      addRoutineNote: (id, b) => req("POST", "/api/pulse/routines/" + id + "/notes", b),
      sections: () => req("GET", "/api/pulse/sections"),
      medical: (sec) => req("GET", "/api/pulse/medical/" + sec),
      addMedical: (sec, b) => req("POST", "/api/pulse/medical/" + sec, b),
      updateMedical: (sec, id, b) => req("PUT", "/api/pulse/medical/" + sec + "/" + id, b),
      delMedical: (sec, id) => req("DELETE", "/api/pulse/medical/" + sec + "/" + id),
      uploadMedical: (sec, id, form) => req("POST", "/api/pulse/medical/" + sec + "/" + id + "/upload", form, true),
      medicalFileUrl: (sec, id) => "/api/pulse/medical/" + sec + "/" + id + "/file",
      meds: (sec) => req("GET", "/api/pulse/meds/" + sec),
      addMed: (sec, b) => req("POST", "/api/pulse/meds/" + sec, b),
      updateMed: (sec, id, b) => req("PUT", "/api/pulse/meds/" + sec + "/" + id, b),
      delMed: (sec, id) => req("DELETE", "/api/pulse/meds/" + sec + "/" + id),
      // Fitness sub-module
      fitness: {
        dashboard: () => req("GET", "/api/pulse/fitness/dashboard"),
        cycles: () => req("GET", "/api/pulse/fitness/cycles"),
        createCycle: (b) => req("POST", "/api/pulse/fitness/cycles", b),
        updateCycle: (id, b) => req("PUT", "/api/pulse/fitness/cycles/" + id, b),
        delCycle: (id) => req("DELETE", "/api/pulse/fitness/cycles/" + id),
        days: (cid) => req("GET", "/api/pulse/fitness/cycles/" + cid + "/days"),
        addDay: (cid, b) => req("POST", "/api/pulse/fitness/cycles/" + cid + "/days", b),
        updateDay: (id, b) => req("PUT", "/api/pulse/fitness/days/" + id, b),
        delDay: (id) => req("DELETE", "/api/pulse/fitness/days/" + id),
        maxes: () => req("GET", "/api/pulse/fitness/maxes"),
        addMax: (b) => req("POST", "/api/pulse/fitness/maxes", b),
        delMax: (id) => req("DELETE", "/api/pulse/fitness/maxes/" + id),
        workouts: (qs) => req("GET", "/api/pulse/fitness/workouts" + (qs || "")),
        // program day for today (or ?date=), its prescriptions and current maxes
        today: (qs) => req("GET", "/api/pulse/fitness/today" + (qs || "")),
        createWorkout: (b) => req("POST", "/api/pulse/fitness/workouts", b),
        replaceWorkout: (id, b) => req("PUT", "/api/pulse/fitness/workouts/" + id + "/replace", b),
        delWorkout: (id) => req("DELETE", "/api/pulse/fitness/workouts/" + id),
        goals: () => req("GET", "/api/pulse/fitness/goals"),
        addGoal: (b) => req("POST", "/api/pulse/fitness/goals", b),
        updateGoal: (id, b) => req("PUT", "/api/pulse/fitness/goals/" + id, b),
        delGoal: (id) => req("DELETE", "/api/pulse/fitness/goals/" + id),
        body: () => req("GET", "/api/pulse/fitness/body"),
        setBody: (region, b) => req("PUT", "/api/pulse/fitness/body/" + region, b),
        addBodyNote: (b) => req("POST", "/api/pulse/fitness/body/notes", b),
        bodyIssues: (status) => req("GET", "/api/pulse/fitness/body/issues?status=" + (status || "all")),
        addBodyIssue: (b) => req("POST", "/api/pulse/fitness/body/issues", b),
        addIssueUpdate: (id, b) => req("POST", "/api/pulse/fitness/body/issues/" + id + "/updates", b),
        patchBodyIssue: (id, b) => req("PATCH", "/api/pulse/fitness/body/issues/" + id, b),
        delBodyIssue: (id) => req("DELETE", "/api/pulse/fitness/body/issues/" + id),
        bodyDays: () => req("GET", "/api/pulse/fitness/body/days"),
        bodyDay: (d) => req("GET", "/api/pulse/fitness/body/days/" + d),
        setBodyDayEntry: (d, region, b) => req("PUT", "/api/pulse/fitness/body/days/" + d + "/" + encodeURIComponent(region), b),
        clearBodyDayEntry: (d, region) => req("DELETE", "/api/pulse/fitness/body/days/" + d + "/" + encodeURIComponent(region)),
        setBodyAllClear: (d, v) => req("PUT", "/api/pulse/fitness/body/days/" + d + "/all-clear", { all_clear: v }),
        carryBodyDay: (d, from) => req("POST", "/api/pulse/fitness/body/days/" + d + "/carry", { from_date: from }),
        issuesToDay: (b) => req("POST", "/api/pulse/fitness/body/issues/to-day", b),
        activityConfig: () => req("GET", "/api/pulse/fitness/activity/config"),
        setActivityConfig: (b) => req("PUT", "/api/pulse/fitness/activity/config", b),
        activity: () => req("GET", "/api/pulse/fitness/activity"),
        logActivity: (b) => req("POST", "/api/pulse/fitness/activity", b),
        delActivity: (id) => req("DELETE", "/api/pulse/fitness/activity/" + id),
        stretching: () => req("GET", "/api/pulse/fitness/stretching"),
        logStretch: (b) => req("POST", "/api/pulse/fitness/stretching", b),
        delStretch: (id) => req("DELETE", "/api/pulse/fitness/stretching/" + id),
        dayReview: (date) => req("GET", "/api/pulse/fitness/day-review?date=" + date),
        setDayBody: (region, b) => req("PUT", "/api/pulse/fitness/day-body/" + region, b),
        setDayNote: (b) => req("PUT", "/api/pulse/fitness/day-note", b),
      },
      // Benchmarks (periodic assessments + baseline)
      benchmarks: {
        baseline: () => req("GET", "/api/pulse/benchmarks/baseline"),
        setBaseline: (b) => req("PUT", "/api/pulse/benchmarks/baseline", b),
        metrics: () => req("GET", "/api/pulse/benchmarks/metrics"),
        toggleMetric: (key, b) => req("PUT", "/api/pulse/benchmarks/metrics/" + key, b),
        addMetric: (b) => req("POST", "/api/pulse/benchmarks/metrics", b),
        list: () => req("GET", "/api/pulse/benchmarks"),
        create: (b) => req("POST", "/api/pulse/benchmarks", b),
        quickSnapshot: (b) => req("POST", "/api/pulse/benchmarks/snapshot", b || {}),
        del: (id) => req("DELETE", "/api/pulse/benchmarks/" + id),
        compare: () => req("GET", "/api/pulse/benchmarks/compare"),
        trend: (key) => req("GET", "/api/pulse/benchmarks/trend/" + key),
        trends: () => req("GET", "/api/pulse/benchmarks/trends"),
        schedule: () => req("GET", "/api/pulse/benchmarks/schedule/info"),
        setSchedule: (b) => req("PUT", "/api/pulse/benchmarks/schedule/info", b),
        importBlood: (id) => req("POST", "/api/pulse/benchmarks/" + id + "/import-blood"),
      },
      // Nutrition — NUTRITION_SPEC (8 areas)
      // placeholder — the real calendar client is attached below, at the
      // Mainframe level, because the calendar is not a Pulse service.
      nutrition: {
        base: "/api/pulse/nutrition",
        dashboard: (d) => req("GET", "/api/pulse/nutrition/dashboard" + (d ? "?date_=" + d : "")),
        // my foods
        foods: (qs) => req("GET", "/api/pulse/nutrition/foods" + (qs || "")),
        addFood: (b) => req("POST", "/api/pulse/nutrition/foods", b),
        updateFood: (id, b) => req("PUT", "/api/pulse/nutrition/foods/" + id, b),
        delFood: (id) => req("DELETE", "/api/pulse/nutrition/foods/" + id),
        // food catalogue (USDA reference data — read-only, separate from my foods)
        catalog: (q, src) => req("GET", "/api/pulse/nutrition/catalog?q=" + encodeURIComponent(q || "") +
          (src ? "&source=" + encodeURIComponent(src) : "")),
        catalogFood: (fdc) => req("GET", "/api/pulse/nutrition/catalog/" + fdc),
        catalogStatus: () => req("GET", "/api/pulse/nutrition/catalog/status"),
        // Barcode scan: a photo or camera frame in, matching products out.
        // Decoded locally (zxing-cpp); the image is never stored.
        catalogScan: (form) => req("POST", "/api/pulse/nutrition/catalog/scan", form, true, true),
        catalogImport: () => req("POST", "/api/pulse/nutrition/catalog/import"),
        adoptFood: (fdc, b) => req("POST", "/api/pulse/nutrition/catalog/" + fdc + "/adopt", b),
        // food log
        log: (d) => req("GET", "/api/pulse/nutrition/log" + (d ? "?date_=" + d : "")),
        addEntry: (b) => req("POST", "/api/pulse/nutrition/log", b),
        quickAdd: (b) => req("POST", "/api/pulse/nutrition/log/quick", b),
        bulk: (b) => req("POST", "/api/pulse/nutrition/log/bulk", b),
        updateEntry: (id, b) => req("PUT", "/api/pulse/nutrition/log/" + id, b),
        delEntry: (id) => req("DELETE", "/api/pulse/nutrition/log/" + id),
        copyMeals: (b) => req("POST", "/api/pulse/nutrition/log/copy", b),
        // recipes
        recipes: () => req("GET", "/api/pulse/nutrition/recipes"),
        addRecipe: (b) => req("POST", "/api/pulse/nutrition/recipes", b),
        updateRecipe: (id, b) => req("PUT", "/api/pulse/nutrition/recipes/" + id, b),
        delRecipe: (id) => req("DELETE", "/api/pulse/nutrition/recipes/" + id),
        logRecipe: (id, qs) => req("POST", "/api/pulse/nutrition/recipes/" + id + "/log" + (qs || "")),
        // water
        water: (d) => req("GET", "/api/pulse/nutrition/water" + (d ? "?date_=" + d : "")),
        addWater: (b) => req("POST", "/api/pulse/nutrition/water", b),
        delWater: (id) => req("DELETE", "/api/pulse/nutrition/water/" + id),
        // weight & body
        weight: () => req("GET", "/api/pulse/nutrition/weight"),
        addWeight: (b) => req("POST", "/api/pulse/nutrition/weight", b),
        delWeight: (id) => req("DELETE", "/api/pulse/nutrition/weight/" + id),
        weightTrend: (days) => req("GET", "/api/pulse/nutrition/weight/trend" + (days ? "?days=" + days : "")),
        body: () => req("GET", "/api/pulse/nutrition/body"),
        addBody: (b) => req("POST", "/api/pulse/nutrition/body", b),
        delBody: (id) => req("DELETE", "/api/pulse/nutrition/body/" + id),
        // fasting
        fasting: () => req("GET", "/api/pulse/nutrition/fasting"),
        startFast: (b) => req("POST", "/api/pulse/nutrition/fasting/start", b),
        endFast: (id, b) => req("PUT", "/api/pulse/nutrition/fasting/" + id + "/end", b || {}),
        delFast: (id) => req("DELETE", "/api/pulse/nutrition/fasting/" + id),
        // goals
        goals: () => req("GET", "/api/pulse/nutrition/goals"),
        setGoals: (b) => req("PUT", "/api/pulse/nutrition/goals", b),
        intolerances: () => req("GET", "/api/pulse/nutrition/intolerances"),
        addIntolerance: (b) => req("POST", "/api/pulse/nutrition/intolerances", b),
        delIntolerance: (id) => req("DELETE", "/api/pulse/nutrition/intolerances/" + id),
        supplements: () => req("GET", "/api/pulse/nutrition/supplements"),
        addSupplement: (b) => req("POST", "/api/pulse/nutrition/supplements", b),
        delSupplement: (id) => req("DELETE", "/api/pulse/nutrition/supplements/" + id),
      },
      // Recovery (meditation / breathing / forest bathing / …)
      recovery: {
        types: () => req("GET", "/api/pulse/recovery/types"),
        addType: (b) => req("POST", "/api/pulse/recovery/types", b),
        delType: (id) => req("DELETE", "/api/pulse/recovery/types/" + id),
        sessions: (limit) => req("GET", "/api/pulse/recovery/sessions" + (limit ? "?limit=" + limit : "")),
        logSession: (b) => req("POST", "/api/pulse/recovery/sessions", b),
        delSession: (id) => req("DELETE", "/api/pulse/recovery/sessions/" + id),
        stats: () => req("GET", "/api/pulse/recovery/stats"),
        protocol: () => req("GET", "/api/pulse/recovery/protocol"),
        startProtocol: (b) => req("POST", "/api/pulse/recovery/protocol", b),
        updateProtocol: (b) => req("PATCH", "/api/pulse/recovery/protocol", b),
        reviseProtocol: (b) => req("POST", "/api/pulse/recovery/protocol/revise", b),
        addProtocolHabit: (b) => req("POST", "/api/pulse/recovery/protocol/habits", b),
        updateProtocolHabit: (id, b) => req("PATCH", "/api/pulse/recovery/protocol/habits/" + id, b),
        removeProtocolHabit: (id) => req("DELETE", "/api/pulse/recovery/protocol/habits/" + id),
        markProtocolDay: (id, b) => req("POST", "/api/pulse/recovery/protocol/habits/" + id + "/day", b),
      },
    },

    // Projects — files uploaded or linked (Mainframe-level)
    projects: {
      list: () => req("GET", "/api/projects"),
      create: (b) => req("POST", "/api/projects", b),
      update: (id, b) => req("PATCH", "/api/projects/" + id, b),
      del: (id) => req("DELETE", "/api/projects/" + id),
      uploadFile: (id, form) => req("POST", "/api/projects/" + id + "/files", form, true),
      addLink: (id, b) => req("POST", "/api/projects/" + id + "/links", b),
      delFile: (id, fid) => req("DELETE", "/api/projects/" + id + "/files/" + fid),
      downloadUrl: (id, fid) => "/api/projects/" + id + "/files/" + fid + "/download",
      push: (id, b) => req("POST", "/api/projects/" + id + "/push", b || {}),
      master: (id) => req("GET", "/api/projects/" + id + "/master"),
      // Documents bound to this project, with the hours worked inside each.
      // Those hours are a slice of the project's total, not an addition to it.
      docs: (id) => req("GET", "/api/projects/" + id + "/docs"),
      // Ideas attached to a project — one edge behind the References list, the
      // Database table and the knowledge map.
      ideas: (id) => req("GET", "/api/projects/" + id + "/ideas"),
      attachIdea: (id, b) => req("POST", "/api/projects/" + id + "/ideas", b),
      updateIdea: (id, iid, b) => req("PATCH", "/api/projects/" + id + "/ideas/" + iid, b),
      detachIdea: (id, iid) => req("DELETE", "/api/projects/" + id + "/ideas/" + iid),
      graph: (id) => req("GET", "/api/projects/" + id + "/graph"),
      connect: (id, b) => req("POST", "/api/projects/" + id + "/graph/edges", b),
      disconnect: (id, eid) => req("DELETE", "/api/projects/" + id + "/graph/edges/" + eid),
      // Passes — v1, v2, ... on a project. The Repository's reading instances,
      // for work you do rather than read. Hours are logged INTO one.
      passes: {
        list: (id) => req("GET", "/api/projects/" + id + "/passes"),
        create: (id, b) => req("POST", "/api/projects/" + id + "/passes", b),
        update: (id, iid, b) => req("PATCH", "/api/projects/" + id + "/passes/" + iid, b),
        del: (id, iid) => req("DELETE", "/api/projects/" + id + "/passes/" + iid),
        reorder: (id, ids) => req("POST", "/api/projects/" + id + "/passes/reorder", { ids }),
        addLink: (id, iid, b) => req("POST", "/api/projects/" + id + "/passes/" + iid + "/links", b),
        delLink: (id, iid, lid) =>
          req("DELETE", "/api/projects/" + id + "/passes/" + iid + "/links/" + lid),
      },
    },

    // Contribution heatmap
    heatmap: {
      // days <= 0 → all history (the week/month/year zoom levels need it)
      get: (days) => req("GET", "/api/activity/heatmap" + (days == null ? "" : "?days=" + days)),
      setCell: (b) => req("POST", "/api/activity/heatmap/cell", b),
    },

    // Work database — the Mainframe-level table every module pushes into.
    // Same rows drive the contribution grid (mins → colour, push → star).
    work: {
      list: (qs) => req("GET", "/api/work" + (qs || "")),
      days: () => req("GET", "/api/work/days"),
      create: (b) => req("POST", "/api/work", b),
      update: (id, b) => req("PATCH", "/api/work/" + id, b),
      del: (id) => req("DELETE", "/api/work/" + id),
      exportUrl: (qs) => "/api/work/export.csv" + (qs || ""),
      // paste many rows: preview parses + matches (saves nothing), import writes
      importPreview: (b) => req("POST", "/api/work/import/preview", b),
      importRows: (rows) => req("POST", "/api/work/import", { rows }),
      // What a session can be ON — seeded, plus any you add.
      // has work happened here that never got time logged against it?
      gap: (refId) => req("GET", "/api/work/gap?ref_id=" + encodeURIComponent(refId)),
      // …and the same question asked of everything at once — the topbar ⏱.
      gaps: () => req("GET", "/api/work/gaps"),
      // Things a session (or a running timer) can point at, per kind.
      targets: (kind) => req("GET", "/api/work/targets?kind=" + encodeURIComponent(kind)),
      kinds: () => req("GET", "/api/work/kinds"),
      addKind: (name) => req("POST", "/api/work/kinds", { name }),
      delKind: (name) => req("DELETE", "/api/work/kinds/" + encodeURIComponent(name)),
    },

    // Reference Map — global citation graph
    refgraph: {
      get: () => req("GET", "/api/synapse/refgraph"),
      addNode: (b) => req("POST", "/api/synapse/refgraph/nodes", b),
      delNode: (id) => req("DELETE", "/api/synapse/refgraph/nodes/" + id),
      addEdge: (b) => req("POST", "/api/synapse/refgraph/edges", b),
      delEdge: (id) => req("DELETE", "/api/synapse/refgraph/edges/" + id),
    },

    // Dictionary — global Mainframe term store
    dictionary: {
      base: "/api/synapse/dictionary",
      list: (qs) => req("GET", "/api/synapse/dictionary/terms" + (qs || "")),
      lookup: (name) => req("GET", "/api/synapse/dictionary/lookup?name=" + encodeURIComponent(name)),
      scan: (text) => req("POST", "/api/synapse/dictionary/scan", { text }),
      bulkAdd: (terms) => req("POST", "/api/synapse/dictionary/bulk-add", { terms }),
      get: (id) => req("GET", "/api/synapse/dictionary/terms/" + id),
      create: (b) => req("POST", "/api/synapse/dictionary/terms", b),
      update: (id, b) => req("PUT", "/api/synapse/dictionary/terms/" + id, b),
      del: (id) => req("DELETE", "/api/synapse/dictionary/terms/" + id),
      fromConcept: (b) => req("POST", "/api/synapse/dictionary/from-concept", b),
      addQuestion: (id, b) => req("POST", "/api/synapse/dictionary/terms/" + id + "/questions", b),
      updateQuestion: (id, qid, b) => req("PUT", "/api/synapse/dictionary/terms/" + id + "/questions/" + qid, b),
      delQuestion: (id, qid) => req("DELETE", "/api/synapse/dictionary/terms/" + id + "/questions/" + qid),
      addNote: (id, b) => req("POST", "/api/synapse/dictionary/terms/" + id + "/notes", b),
      delNote: (id, nid) => req("DELETE", "/api/synapse/dictionary/terms/" + id + "/notes/" + nid),
      link: (id, tid) => req("POST", "/api/synapse/dictionary/terms/" + id + "/related/" + tid),
      unlink: (id, tid) => req("DELETE", "/api/synapse/dictionary/terms/" + id + "/related/" + tid),
      uploadImage: (id, form) => req("POST", "/api/synapse/dictionary/terms/" + id + "/image", form, true),
      delImage: (id) => req("DELETE", "/api/synapse/dictionary/terms/" + id + "/image"),
    },

    // Documents — Mainframe-level word processor. Bodies are real files on
    // disk; these endpoints move metadata around and hand back rendered HTML.
    docs: {
      list: (q, folder) => {
        const p = new URLSearchParams();
        if (q) p.set("q", q);
        if (folder != null) p.set("folder", folder);
        const qs = p.toString();
        return req("GET", "/api/docs" + (qs ? "?" + qs : ""));
      },
      folders: () => req("GET", "/api/docs/folders"),
      get: (id) => req("GET", "/api/docs/" + id),
      create: (b) => req("POST", "/api/docs", b),
      // Body save is its own endpoint so a fast autosave never resends metadata.
      saveContent: (id, content) => req("PUT", "/api/docs/" + id + "/content", { content }),
      update: (id, b) => req("PATCH", "/api/docs/" + id, b),
      // Bind the document to the project whose hours it is, or pass null to
      // clear. Sending the field at all is what asks to change the binding.
      setProject: (id, projectId) =>
        req("PATCH", "/api/docs/" + id, { project_id: projectId || null }),
      duplicate: (id) => req("POST", "/api/docs/" + id + "/duplicate"),
      del: (id) => req("DELETE", "/api/docs/" + id),
      render: (content) => req("POST", "/api/docs/render", { content }),
      history: (id) => req("GET", "/api/docs/" + id + "/history"),
      snapshot: (id, name) => req("GET", "/api/docs/" + id + "/history/" + encodeURIComponent(name)),
      importFile: (form) => req("POST", "/api/docs/import", form, true),
      // Record a push — a timestamped work session with a ★ on the day's square.
      push: (id, b) => req("POST", "/api/docs/" + id + "/push", b || {}),
      exportUrl: (id, fmt) => "/api/docs/" + id + "/export" + (fmt ? "?fmt=" + fmt : ""),
      printUrl: (id) => "/api/docs/" + id + "/print",
    },

    // Sheets — user-defined databases. Formula values are computed server-side
    // (backend/formula.py) so the grid, the CSV and the JSON always agree.
    sheets: {
      // No argument lists every sheet; a project id lists that project's
      // tables. Same endpoint either way — see routes/sheets.py.
      list: (projectId) => req("GET", "/api/sheets"
        + (projectId ? "?project_id=" + encodeURIComponent(projectId) : "")),
      get: (id) => req("GET", "/api/sheets/" + id),
      create: (b) => req("POST", "/api/sheets", b),
      update: (id, b) => req("PATCH", "/api/sheets/" + id, b),
      del: (id) => req("DELETE", "/api/sheets/" + id),
      compute: (id) => req("GET", "/api/sheets/" + id + "/compute"),

      addColumn: (id, b) => req("POST", "/api/sheets/" + id + "/columns", b),
      updateColumn: (id, cid, b) => req("PATCH", "/api/sheets/" + id + "/columns/" + cid, b),
      delColumn: (id, cid) => req("DELETE", "/api/sheets/" + id + "/columns/" + cid),
      reorderColumns: (id, ids) => req("POST", "/api/sheets/" + id + "/columns/reorder", { ids }),

      addRow: (id, b) => req("POST", "/api/sheets/" + id + "/rows", b || {}),
      updateRow: (id, rid, values) => req("PATCH", "/api/sheets/" + id + "/rows/" + rid, { values }),
      delRow: (id, rid) => req("DELETE", "/api/sheets/" + id + "/rows/" + rid),
      bulkRows: (id, rows) => req("POST", "/api/sheets/" + id + "/rows/bulk", { rows }),
      reorderRows: (id, ids) => req("POST", "/api/sheets/" + id + "/rows/reorder", { ids }),

      saveView: (id, b) => req("POST", "/api/sheets/" + id + "/views", b),
      delView: (id, vid) => req("DELETE", "/api/sheets/" + id + "/views/" + vid),

      linkTargets: (kind) => req("GET", "/api/sheets/link-targets?kind=" + kind),
      importCsv: (form) => req("POST", "/api/sheets/import", form, true),
      exportUrl: (id, format) => "/api/sheets/" + id + "/export?format=" + (format || "csv"),
    },

    // Framework — the approach being taken, and why. The diagram saves whole.
    framework: {
      list: () => req("GET", "/api/framework"),
      get: (id) => req("GET", "/api/framework/" + id),
      create: (b) => req("POST", "/api/framework", b),
      update: (id, b) => req("PATCH", "/api/framework/" + id, b),
      del: (id) => req("DELETE", "/api/framework/" + id),
      saveDiagram: (id, b) => req("PUT", "/api/framework/" + id + "/diagram", b),
      attachIdea: (id, b) => req("POST", "/api/framework/" + id + "/ideas", b),
      detachIdea: (id, iid) => req("DELETE", "/api/framework/" + id + "/ideas/" + iid),
    },

    // Focus — the quick overview: current phase, goals, and what's moving.
    focus: {
      get: () => req("GET", "/api/focus"),
      set: (b) => req("PUT", "/api/focus", b),
      goals: () => req("GET", "/api/focus/goals"),
      addGoal: (b) => req("POST", "/api/focus/goals", b),
      updateGoal: (id, b) => req("PATCH", "/api/focus/goals/" + id, b),
      delGoal: (id) => req("DELETE", "/api/focus/goals/" + id),
    },

    // Snapshot — the whole "where am I right now" panel in one call. Pass the
    // section keys you actually want; a section left off isn't computed.
    snapshot: {
      get: (keys) => req("GET", "/api/snapshot"
        + (keys && keys.length ? "?sections=" + encodeURIComponent(keys.join(",")) : "")),
      sections: () => req("GET", "/api/snapshot/sections"),
    },

    // Recurring money — subscriptions and one-offs. A commitment, not a
    // payment: paying one mints a real transaction and rolls the date on.
    recurring: {
      list: () => req("GET", "/api/vault/recurring"),
      summary: () => req("GET", "/api/vault/recurring/summary"),
      create: (b) => req("POST", "/api/vault/recurring", b),
      update: (id, b) => req("PATCH", "/api/vault/recurring/" + id, b),
      del: (id) => req("DELETE", "/api/vault/recurring/" + id),
      pay: (id, b) => req("POST", "/api/vault/recurring/" + id + "/pay", b || {}),
    },

    // Reminders — messages you leave yourself, surfaced when they land.
    reminders: {
      list: (done) => req("GET", "/api/reminders" + (done ? "?include_done=true" : "")),
      due: () => req("GET", "/api/reminders/due"),
      create: (b) => req("POST", "/api/reminders", b),
      update: (id, b) => req("PATCH", "/api/reminders/" + id, b),
      del: (id) => req("DELETE", "/api/reminders/" + id),
    },

    // Calendar — Mainframe-level, like tasks and the work log. Not a module.
    calendar: {
      events: (from, to) => req("GET", "/api/calendar/events?from_=" + from + "&to=" + to),
      addEvent: (b) => req("POST", "/api/calendar/events", b),
      updateEvent: (id, b) => req("PUT", "/api/calendar/events/" + id, b),
      delEvent: (id) => req("DELETE", "/api/calendar/events/" + id),
      // The unified feed: events + tasks due + work logged, for a span of days.
      range: (from, to) => req("GET", "/api/calendar/range?from_=" + from + "&to=" + to),
      suggestions: (d, days) => req("GET", "/api/calendar/suggestions?date_=" + d + "&days=" + (days || 7)),
      freebusy: (d) => req("GET", "/api/calendar/freebusy?date_=" + d),
      importStatus: () => req("GET", "/api/calendar/import/status"),
      runImport: () => req("POST", "/api/calendar/import"),
    },
  };
})();
