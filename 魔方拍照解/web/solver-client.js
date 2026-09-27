function formatNodes(value) {
  return new Intl.NumberFormat("zh-CN").format(Math.max(0, Number(value) || 0));
}

export function createSolveSnapshot({ cube_size = 3, facelets, metric = "HTM", timeout_seconds = 180 }) {
  if (!["HTM", "QTM"].includes(metric)) throw new Error("未知计步方式");
  return Object.freeze({
    cube_size,
    facelets,
    metric,
    max_depth: cube_size === 2 ? (metric === "QTM" ? 14 : 11) : (metric === "QTM" ? 26 : 20),
    timeout_seconds,
  });
}

export function solveKey(snapshot) {
  return `${snapshot.cube_size}:${snapshot.facelets}:${snapshot.metric}:${snapshot.max_depth}`;
}

export function metricExplanation(metric) {
  return `${metric}：R2 等 180° 转动计 ${metric === "QTM" ? 2 : 1} 步，90° 正反转均计 1 步`;
}

// Request identity survives selection changes and delayed POST / polling responses.
export function createSolveLifecycle({ cancelJob, clearTimer = clearTimeout }) {
  return {
    generation: 0, jobId: null, key: null, pollTimer: null,
    cancelActive() {
      this.key = null;
      if (this.jobId) cancelJob(this.jobId);
      this.jobId = null;
    },
    invalidate() {
      this.generation += 1;
      this.cancelActive();
      if (this.pollTimer !== null) clearTimer(this.pollTimer);
      this.pollTimer = null;
    },
    accepts(generation, snapshot, data) {
      if (generation === this.generation && data.metric === snapshot.metric) return true;
      if (data.job_id) cancelJob(data.job_id);
      return false;
    },
  };
}

export function describeSearchProgress(job) {
  const metric = job.metric || job.progress?.metric || "HTM";
  if (job.status === "queued") {
    const position = Math.max(1, Number(job.queue_position) || 1);
    return {
      status: `${metric} 最短性验证排队中（第 ${position} 位）`,
      detail: job.incumbent_depth == null ? `${metric}：等待严格搜索` : `${metric}：当前可用解 ${job.incumbent_depth} 步`,
    };
  }
  const progress = job.progress;
  if (!progress) {
    return { status: `正在验证 ${metric} 严格最短解...`, detail: `${metric}：正在初始化搜索表` };
  }
  const current = Number(progress.current_depth);
  const completed = Number(progress.completed_depth);
  const elapsed = Number(progress.elapsed_seconds) || 0;
  const nodes = formatNodes(progress.nodes);
  let proof = "尚未完成一个新深度";
  if (completed >= Number(progress.lower_bound)) proof = `已严格排除 ≤ ${completed} 步`;
  let interval = "";
  if (job.incumbent_depth != null && completed + 1 <= Number(job.incumbent_depth)) {
    interval = `；最短长度区间 ${completed + 1}–${job.incumbent_depth} 步`;
  }
  return {
    status: `${metric}：正在检查 ${current} 步预算`,
    detail: `${metric}：${proof}${interval}；累计 ${nodes} 节点，${elapsed.toFixed(1)}s`,
  };
}
