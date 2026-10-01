function formatNodes(value) {
  return new Intl.NumberFormat("zh-CN").format(Math.max(0, Number(value) || 0));
}

export function describeQtmTiming(job, result = job) {
  const fields = [
    ["首候选", job.first_candidate_seconds],
    ["原生搜索", job.native_search_seconds ?? result.elapsed_seconds],
    ["请求累计", job.request_elapsed_seconds],
  ];
  return fields
    .filter(([, value]) => typeof value === "number" && Number.isFinite(value) && value >= 0)
    .map(([label, value]) => `${label} ${value.toFixed(2)}s`)
    .join("，");
}

export function describeSearchProgress(job) {
  const candidate = job.candidate_cost ?? job.candidate_result?.cost ?? job.incumbent_depth;
  const lower = job.proven_lower_bound;
  const gap = job.proof_gap;
  const qtmInterval = job.metric === "QTM" && candidate != null
    ? `候选 ${candidate} 步${lower == null ? "" : `；已证下界 ${lower} 步；差值 ${gap ?? Math.max(0, candidate - lower)} 步`}`
    : "";
  if (job.status === "queued") {
    const position = Math.max(1, Number(job.queue_position) || 1);
    return {
      status: `最短性验证排队中（第 ${position} 位）`,
      detail: qtmInterval || (candidate == null ? "等待严格搜索" : `当前可用解：${candidate} 步`),
    };
  }
  const progress = job.progress;
  if (!progress) {
    return { status: "正在初始化搜索表", detail: qtmInterval || "等待严格搜索" };
  }
  const current = Number(progress.current_depth);
  const completed = Number(progress.completed_depth);
  const elapsed = Number(progress.elapsed_seconds) || 0;
  const nodes = formatNodes(progress.nodes);
  let proof = "尚未完成一个新深度";
  if (completed >= Number(progress.lower_bound)) proof = `已严格排除 ≤ ${completed} 步`;
  let interval = "";
  if (candidate != null && completed + 1 <= Number(candidate)) {
    interval = `；最短长度区间 ${completed + 1}–${candidate} 步`;
  }
  return {
    status: progress.phase === "waiting_strong" ? "正在校验强表" : `正在检查 ${current} 步深度`,
    detail: `${qtmInterval || `${proof}${interval}`}；累计 ${nodes} 节点，${elapsed.toFixed(1)}s`,
  };
}
