function formatNodes(value) {
  return new Intl.NumberFormat("zh-CN").format(Math.max(0, Number(value) || 0));
}

export function describeSearchProgress(job) {
  if (job.status === "queued") {
    const position = Math.max(1, Number(job.queue_position) || 1);
    return {
      status: `最短性验证排队中（第 ${position} 位）`,
      detail: job.incumbent_depth == null ? "等待严格搜索" : `当前可用解：${job.incumbent_depth} 步`,
    };
  }
  const progress = job.progress;
  if (!progress) {
    return { status: "正在验证严格最短解...", detail: "正在初始化搜索表" };
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
    status: `正在检查 ${current} 步深度`,
    detail: `${proof}${interval}；累计 ${nodes} 节点，${elapsed.toFixed(1)}s`,
  };
}
