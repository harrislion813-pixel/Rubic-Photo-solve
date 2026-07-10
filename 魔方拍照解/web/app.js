const FACE_ORDER = ["U", "R", "F", "D", "L", "B"];
const FACE_HINTS = {
  U: "上面",
  R: "右面",
  F: "前面 / 基准",
  D: "下面",
  L: "左面",
  B: "后面",
};

const STICKER_COLORS = ["U", "R", "F", "D", "L", "B"];
const state = Object.fromEntries(
  FACE_ORDER.map((face) => [
    face,
    {
      stickers: Array(9).fill(face),
      samples: null,
      imageLoaded: false,
      canvas: null,
      ctx: null,
      sourceCanvas: null,
      corners: null,
      detection: null,
    },
  ]),
);

const facesRoot = document.querySelector("#faces");
const template = document.querySelector("#faceTemplate");
const statusText = document.querySelector("#statusText");
const faceletsText = document.querySelector("#faceletsText");
const solutionText = document.querySelector("#solutionText");
const depthText = document.querySelector("#depthText");
const solveBtn = document.querySelector("#solveBtn");
const timeoutInput = document.querySelector("#timeoutInput");
let solveGeneration = 0;
let solvePollTimer = null;
let activeJobId = null;
const cropDialog = document.querySelector("#cropDialog");
const cropCanvas = document.querySelector("#cropCanvas");
const cropCtx = cropCanvas.getContext("2d");
const cropTitle = document.querySelector("#cropTitle");
const cropConfidence = document.querySelector("#cropConfidence");
const redetectBtn = document.querySelector("#redetectBtn");
const applyCropBtn = document.querySelector("#applyCropBtn");
const cropEditor = {
  face: null,
  corners: null,
  scale: 1,
  dragging: -1,
};

function showError(element, message) {
  const span = document.createElement("span");
  span.className = "error";
  span.textContent = message;
  element.replaceChildren(span);
}

initFaces();
renderAll();

solveBtn.addEventListener("click", solveCube);
faceletsText.addEventListener("input", () => {
  solveGeneration += 1;
  cancelActiveJob();
  if (solvePollTimer !== null) {
    clearTimeout(solvePollTimer);
    solvePollTimer = null;
  }
  const compact = faceletsText.value.toUpperCase().replace(/[^URFDLB]/g, "");
  if (compact.length === 54) {
    applyFacelets(compact);
  }
});
redetectBtn.addEventListener("click", redetectCrop);
applyCropBtn.addEventListener("click", applyCrop);
cropCanvas.addEventListener("pointerdown", beginCornerDrag);
cropCanvas.addEventListener("pointermove", dragCorner);
cropCanvas.addEventListener("pointerup", endCornerDrag);
cropCanvas.addEventListener("pointercancel", endCornerDrag);

function initFaces() {
  for (const face of FACE_ORDER) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.dataset.face = face;
    node.querySelector(".face-name").textContent = `${face} 面`;
    node.querySelector(".face-hint").textContent = FACE_HINTS[face];

    const canvas = node.querySelector(".preview");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    state[face].canvas = canvas;
    state[face].ctx = ctx;
    drawEmptyPreview(face);

    node.querySelector(".file-input").addEventListener("change", (event) => {
      const file = event.target.files?.[0];
      if (file) loadImageForFace(face, file);
    });
    node.querySelector(".rotate-left").addEventListener("click", () => rotateFace(face, false));
    node.querySelector(".rotate-right").addEventListener("click", () => rotateFace(face, true));
    node.querySelector(".adjust-region").addEventListener("click", () => openCropEditor(face));

    const stickerRoot = node.querySelector(".stickers");
    for (let idx = 0; idx < 9; idx += 1) {
      const sticker = document.createElement("button");
      sticker.type = "button";
      sticker.className = "sticker";
      sticker.dataset.index = String(idx);
      sticker.addEventListener("click", () => cycleSticker(face, idx));
      stickerRoot.append(sticker);
    }
    facesRoot.append(node);
  }
}

function drawEmptyPreview(face) {
  const { canvas, ctx } = state[face];
  ctx.fillStyle = "#f9fbfc";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "#d8e0e6";
  ctx.lineWidth = 2;
  for (let i = 1; i < 3; i += 1) {
    const p = (canvas.width / 3) * i;
    ctx.beginPath();
    ctx.moveTo(p, 0);
    ctx.lineTo(p, canvas.height);
    ctx.moveTo(0, p);
    ctx.lineTo(canvas.width, p);
    ctx.stroke();
  }
  ctx.fillStyle = "#64727d";
  ctx.font = "bold 44px Segoe UI";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(face, canvas.width / 2, canvas.height / 2);
}

function loadImageForFace(face, file) {
  const image = new Image();
  image.onload = async () => {
    statusText.textContent = `${face} 面图像识别中...`;
    const sourceCanvas = document.createElement("canvas");
    const maxSide = 1600;
    const scale = Math.min(1, maxSide / Math.max(image.naturalWidth, image.naturalHeight));
    sourceCanvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    sourceCanvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const sourceCtx = sourceCanvas.getContext("2d", { willReadFrequently: true });
    sourceCtx.imageSmoothingEnabled = true;
    sourceCtx.imageSmoothingQuality = "high";
    sourceCtx.drawImage(image, 0, 0, sourceCanvas.width, sourceCanvas.height);

    try {
      const detected = await detectCubeFaceWithBackend(sourceCanvas);
      state[face].sourceCanvas = sourceCanvas;
      state[face].corners = detected.corners;
      state[face].detection = detected;
      rectifyFace(face);
      state[face].samples = sampleFace(face);
      state[face].imageLoaded = true;
      classifyAllFaces();
      renderAll();
    } catch (error) {
      showError(statusText, `图像识别失败：${error.message}`);
    } finally {
      URL.revokeObjectURL(image.src);
    }
  };
  image.onerror = () => {
    showError(statusText, "图片无法读取，请换一张照片");
    URL.revokeObjectURL(image.src);
  };
  image.src = URL.createObjectURL(file);
}

async function detectCubeFaceWithBackend(sourceCanvas) {
  try {
    const response = await fetch("/api/detect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: sourceCanvas.toDataURL("image/jpeg", 0.9) }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "检测服务不可用");
    if (!data.detected) return fallbackFaceDetection(sourceCanvas, "opencv");
    return {
      corners: data.corners.map(([x, y]) => ({
        x: clamp(x, 0, 1) * sourceCanvas.width,
        y: clamp(y, 0, 1) * sourceCanvas.height,
      })),
      confidence: data.confidence,
      mode: "auto",
      engine: "opencv",
      method: data.method,
    };
  } catch (error) {
    const fallback = detectCubeFace(sourceCanvas);
    fallback.engine = "browser";
    return fallback;
  }
}

function fallbackFaceDetection(sourceCanvas, engine = "browser") {
  const marginX = sourceCanvas.width * 0.16;
  const marginY = sourceCanvas.height * 0.16;
  return {
    corners: [
      { x: marginX, y: marginY },
      { x: sourceCanvas.width - marginX, y: marginY },
      { x: sourceCanvas.width - marginX, y: sourceCanvas.height - marginY },
      { x: marginX, y: sourceCanvas.height - marginY },
    ],
    confidence: 0,
    mode: "fallback",
    engine,
  };
}

function rectifyFace(face) {
  const { canvas, ctx, sourceCanvas, corners } = state[face];
  const sourceCtx = sourceCanvas.getContext("2d", { willReadFrequently: true });
  const source = sourceCtx.getImageData(0, 0, sourceCanvas.width, sourceCanvas.height);
  const output = ctx.createImageData(canvas.width, canvas.height);
  const homography = solveHomography(corners);

  for (let y = 0; y < canvas.height; y += 1) {
    const v = (y + 0.5) / canvas.height;
    for (let x = 0; x < canvas.width; x += 1) {
      const u = (x + 0.5) / canvas.width;
      const denominator = homography[6] * u + homography[7] * v + 1;
      const sourceX = (homography[0] * u + homography[1] * v + homography[2]) / denominator;
      const sourceY = (homography[3] * u + homography[4] * v + homography[5]) / denominator;
      sampleBilinear(source, sourceX, sourceY, output.data, (y * canvas.width + x) * 4);
    }
  }

  ctx.putImageData(output, 0, 0);
  drawSampleGrid(ctx, canvas.width, canvas.height);
}

function detectCubeFace(sourceCanvas) {
  const analysisCanvas = document.createElement("canvas");
  const maxSide = 420;
  const analysisScale = Math.min(1, maxSide / Math.max(sourceCanvas.width, sourceCanvas.height));
  analysisCanvas.width = Math.max(1, Math.round(sourceCanvas.width * analysisScale));
  analysisCanvas.height = Math.max(1, Math.round(sourceCanvas.height * analysisScale));
  const analysisCtx = analysisCanvas.getContext("2d", { willReadFrequently: true });
  analysisCtx.drawImage(sourceCanvas, 0, 0, analysisCanvas.width, analysisCanvas.height);

  const pixels = analysisCtx.getImageData(0, 0, analysisCanvas.width, analysisCanvas.height);
  const rawMask = buildStickerMask(pixels);
  const passes = Math.min(9, Math.max(3, Math.round(Math.min(analysisCanvas.width, analysisCanvas.height) * 0.018)));
  const closedMask = closeMask(rawMask, analysisCanvas.width, analysisCanvas.height, passes);
  const components = connectedComponents(closedMask, analysisCanvas.width, analysisCanvas.height);
  const candidates = [];
  const imageArea = analysisCanvas.width * analysisCanvas.height;

  for (const component of components) {
    const boxWidth = component.maxX - component.minX + 1;
    const boxHeight = component.maxY - component.minY + 1;
    const areaRatio = component.area / imageArea;
    const aspect = boxWidth / boxHeight;
    if (
      areaRatio < 0.012 ||
      areaRatio > 0.78 ||
      Math.min(boxWidth, boxHeight) < Math.min(analysisCanvas.width, analysisCanvas.height) * 0.11 ||
      aspect < 0.32 ||
      aspect > 3.1 ||
      component.boundary.length < 4
    ) {
      continue;
    }

    const hull = convexHull(component.boundary);
    if (hull.length < 4) continue;
    let corners = orderQuad(reduceHullToFour(hull));
    corners = expandQuad(corners, 1.025, analysisCanvas.width, analysisCanvas.height);
    const score = scoreQuad(
      corners,
      rawMask,
      analysisCanvas.width,
      analysisCanvas.height,
      component.area / (boxWidth * boxHeight),
    );
    candidates.push({ corners, score });
  }

  candidates.sort((a, b) => b.score - a.score);
  if (!candidates.length || candidates[0].score < 0.56) {
    return fallbackFaceDetection(sourceCanvas);
  }

  const best = candidates[0];
  return {
    corners: best.corners.map((point) => ({
      x: point.x / analysisScale,
      y: point.y / analysisScale,
    })),
    confidence: Math.round(clamp((best.score - 0.56) / 0.34, 0, 1) * 100),
    mode: "auto",
  };
}

function buildStickerMask(imageData) {
  const mask = new Uint8Array(imageData.width * imageData.height);
  const whitePixels = new Uint8Array(mask.length);
  const data = imageData.data;
  for (let index = 0; index < mask.length; index += 1) {
    const offset = index * 4;
    const r = data[offset];
    const g = data[offset + 1];
    const b = data[offset + 2];
    const maximum = Math.max(r, g, b);
    const minimum = Math.min(r, g, b);
    const chroma = maximum - minimum;
    const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    const colorfulSticker = maximum > 62 && chroma > 26 && chroma / Math.max(1, maximum) > 0.18;
    const whiteSticker = luma > 158 && chroma < 62;
    mask[index] = colorfulSticker || whiteSticker ? 1 : 0;
    whitePixels[index] = whiteSticker ? 1 : 0;
  }
  removeBorderWhiteBackground(mask, whitePixels, imageData.width, imageData.height);
  return mask;
}

function removeBorderWhiteBackground(mask, whitePixels, width, height) {
  const seen = new Uint8Array(mask.length);
  const queue = new Int32Array(mask.length);
  let head = 0;
  let tail = 0;
  const enqueue = (index) => {
    if (whitePixels[index] && !seen[index]) {
      seen[index] = 1;
      queue[tail++] = index;
    }
  };
  for (let x = 0; x < width; x += 1) {
    enqueue(x);
    enqueue((height - 1) * width + x);
  }
  for (let y = 0; y < height; y += 1) {
    enqueue(y * width);
    enqueue(y * width + width - 1);
  }

  while (head < tail) {
    const index = queue[head++];
    const x = index % width;
    mask[index] = 0;
    if (x > 0) enqueue(index - 1);
    if (x < width - 1) enqueue(index + 1);
    if (index >= width) enqueue(index - width);
    if (index < mask.length - width) enqueue(index + width);
  }
}

function closeMask(input, width, height, passes) {
  let output = input;
  for (let pass = 0; pass < passes; pass += 1) output = morphMask(output, width, height, true);
  for (let pass = 0; pass < passes; pass += 1) output = morphMask(output, width, height, false);
  return output;
}

function morphMask(input, width, height, dilate) {
  const output = new Uint8Array(input.length);
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const center = y * width + x;
      let value = dilate ? 0 : 1;
      for (let dy = -1; dy <= 1; dy += 1) {
        for (let dx = -1; dx <= 1; dx += 1) {
          const neighbor = input[center + dy * width + dx];
          value = dilate ? value || neighbor : value && neighbor;
        }
      }
      output[center] = value ? 1 : 0;
    }
  }
  return output;
}

function connectedComponents(mask, width, height) {
  const seen = new Uint8Array(mask.length);
  const queue = new Int32Array(mask.length);
  const components = [];
  const neighborOffsets = [-1, 1, -width, width];

  for (let start = 0; start < mask.length; start += 1) {
    if (!mask[start] || seen[start]) continue;
    let head = 0;
    let tail = 0;
    let area = 0;
    let minX = width;
    let maxX = 0;
    let minY = height;
    let maxY = 0;
    const boundary = [];
    queue[tail++] = start;
    seen[start] = 1;

    while (head < tail) {
      const index = queue[head++];
      const x = index % width;
      const y = Math.floor(index / width);
      area += 1;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
      let edge = false;

      for (const offset of neighborOffsets) {
        const neighbor = index + offset;
        const crossesRow = (offset === -1 && x === 0) || (offset === 1 && x === width - 1);
        if (neighbor < 0 || neighbor >= mask.length || crossesRow || !mask[neighbor]) {
          edge = true;
          continue;
        }
        if (!seen[neighbor]) {
          seen[neighbor] = 1;
          queue[tail++] = neighbor;
        }
      }
      if (edge) boundary.push({ x, y });
    }
    components.push({ area, minX, maxX, minY, maxY, boundary });
  }
  return components;
}

function convexHull(points) {
  const sorted = [...points].sort((a, b) => a.x - b.x || a.y - b.y);
  const cross = (origin, a, b) => (a.x - origin.x) * (b.y - origin.y) - (a.y - origin.y) * (b.x - origin.x);
  const lower = [];
  for (const point of sorted) {
    while (lower.length >= 2 && cross(lower.at(-2), lower.at(-1), point) <= 0) lower.pop();
    lower.push(point);
  }
  const upper = [];
  for (let index = sorted.length - 1; index >= 0; index -= 1) {
    const point = sorted[index];
    while (upper.length >= 2 && cross(upper.at(-2), upper.at(-1), point) <= 0) upper.pop();
    upper.push(point);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper);
}

function reduceHullToFour(hull) {
  const points = hull.map((point) => ({ ...point }));
  while (points.length > 4) {
    let removeAt = 0;
    let leastArea = Number.POSITIVE_INFINITY;
    for (let index = 0; index < points.length; index += 1) {
      const previous = points[(index - 1 + points.length) % points.length];
      const current = points[index];
      const next = points[(index + 1) % points.length];
      const area = Math.abs(
        (current.x - previous.x) * (next.y - previous.y) -
          (current.y - previous.y) * (next.x - previous.x),
      );
      if (area < leastArea) {
        leastArea = area;
        removeAt = index;
      }
    }
    points.splice(removeAt, 1);
  }
  return points;
}

function orderQuad(points) {
  const center = points.reduce((sum, point) => ({ x: sum.x + point.x / 4, y: sum.y + point.y / 4 }), { x: 0, y: 0 });
  let ordered = [...points].sort(
    (a, b) => Math.atan2(a.y - center.y, a.x - center.x) - Math.atan2(b.y - center.y, b.x - center.x),
  );
  const start = ordered.reduce(
    (best, point, index) => (point.x + point.y < ordered[best].x + ordered[best].y ? index : best),
    0,
  );
  ordered = ordered.slice(start).concat(ordered.slice(0, start));
  if (signedPolygonArea(ordered) < 0) ordered = [ordered[0], ...ordered.slice(1).reverse()];
  return ordered;
}

function expandQuad(corners, factor, width, height) {
  const center = corners.reduce((sum, point) => ({ x: sum.x + point.x / 4, y: sum.y + point.y / 4 }), { x: 0, y: 0 });
  return corners.map((point) => ({
    x: clamp(center.x + (point.x - center.x) * factor, 0, width - 1),
    y: clamp(center.y + (point.y - center.y) * factor, 0, height - 1),
  }));
}

function scoreQuad(corners, mask, width, height, fillRatio) {
  const sideLengths = corners.map((point, index) => distance(point, corners[(index + 1) % 4]));
  const shortest = Math.min(...sideLengths);
  const longest = Math.max(...sideLengths);
  const sideRatio = shortest / Math.max(1, longest);
  const shapeScore = clamp((sideRatio - 0.35) / 0.65, 0, 1);
  const areaRatio = Math.abs(signedPolygonArea(corners)) / (width * height);
  const areaScore = clamp(areaRatio / 0.045, 0, 1) * clamp((0.82 - areaRatio) / 0.22, 0, 1);

  const centerValues = [];
  for (const v of [1 / 6, 1 / 2, 5 / 6]) {
    for (const u of [1 / 6, 1 / 2, 5 / 6]) {
      centerValues.push(sampleMask(mask, width, height, bilinearQuad(corners, u, v), 2));
    }
  }
  const lineValues = [];
  for (const line of [1 / 3, 2 / 3]) {
    for (const along of [1 / 6, 1 / 2, 5 / 6]) {
      lineValues.push(sampleMask(mask, width, height, bilinearQuad(corners, line, along), 1));
      lineValues.push(sampleMask(mask, width, height, bilinearQuad(corners, along, line), 1));
    }
  }
  const centerScore = average(centerValues);
  const gridEvidence = clamp((centerScore - average(lineValues)) * 1.6, 0, 1);
  return centerScore * 0.3 + gridEvidence * 0.35 + shapeScore * 0.18 + clamp(fillRatio, 0, 1) * 0.07 + areaScore * 0.1;
}

function sampleMask(mask, width, height, point, radius) {
  let total = 0;
  let count = 0;
  const centerX = Math.round(point.x);
  const centerY = Math.round(point.y);
  for (let y = centerY - radius; y <= centerY + radius; y += 1) {
    for (let x = centerX - radius; x <= centerX + radius; x += 1) {
      if (x >= 0 && x < width && y >= 0 && y < height) {
        total += mask[y * width + x];
        count += 1;
      }
    }
  }
  return count ? total / count : 0;
}

function bilinearQuad(corners, u, v) {
  const topX = corners[0].x * (1 - u) + corners[1].x * u;
  const topY = corners[0].y * (1 - u) + corners[1].y * u;
  const bottomX = corners[3].x * (1 - u) + corners[2].x * u;
  const bottomY = corners[3].y * (1 - u) + corners[2].y * u;
  return { x: topX * (1 - v) + bottomX * v, y: topY * (1 - v) + bottomY * v };
}

function solveHomography(corners) {
  const unitCorners = [
    [0, 0],
    [1, 0],
    [1, 1],
    [0, 1],
  ];
  const matrix = [];
  unitCorners.forEach(([u, v], index) => {
    const { x, y } = corners[index];
    matrix.push([u, v, 1, 0, 0, 0, -x * u, -x * v, x]);
    matrix.push([0, 0, 0, u, v, 1, -y * u, -y * v, y]);
  });

  for (let column = 0; column < 8; column += 1) {
    let pivot = column;
    for (let row = column + 1; row < 8; row += 1) {
      if (Math.abs(matrix[row][column]) > Math.abs(matrix[pivot][column])) pivot = row;
    }
    [matrix[column], matrix[pivot]] = [matrix[pivot], matrix[column]];
    const divisor = matrix[column][column] || 1e-12;
    for (let item = column; item < 9; item += 1) matrix[column][item] /= divisor;
    for (let row = 0; row < 8; row += 1) {
      if (row === column) continue;
      const factor = matrix[row][column];
      for (let item = column; item < 9; item += 1) matrix[row][item] -= factor * matrix[column][item];
    }
  }
  return matrix.map((row) => row[8]);
}

function sampleBilinear(source, x, y, target, targetOffset) {
  const clampedX = clamp(x, 0, source.width - 1);
  const clampedY = clamp(y, 0, source.height - 1);
  const x0 = Math.floor(clampedX);
  const y0 = Math.floor(clampedY);
  const x1 = Math.min(source.width - 1, x0 + 1);
  const y1 = Math.min(source.height - 1, y0 + 1);
  const tx = clampedX - x0;
  const ty = clampedY - y0;
  const offsets = [
    (y0 * source.width + x0) * 4,
    (y0 * source.width + x1) * 4,
    (y1 * source.width + x0) * 4,
    (y1 * source.width + x1) * 4,
  ];
  for (let channel = 0; channel < 3; channel += 1) {
    const top = source.data[offsets[0] + channel] * (1 - tx) + source.data[offsets[1] + channel] * tx;
    const bottom = source.data[offsets[2] + channel] * (1 - tx) + source.data[offsets[3] + channel] * tx;
    target[targetOffset + channel] = Math.round(top * (1 - ty) + bottom * ty);
  }
  target[targetOffset + 3] = 255;
}

function signedPolygonArea(points) {
  return points.reduce((area, point, index) => {
    const next = points[(index + 1) % points.length];
    return area + point.x * next.y - next.x * point.y;
  }, 0) / 2;
}

function distance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function average(values) {
  return values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function drawSampleGrid(ctx, width, height) {
  ctx.strokeStyle = "rgba(255,255,255,0.9)";
  ctx.lineWidth = 2;
  for (let i = 1; i < 3; i += 1) {
    const p = (width / 3) * i;
    ctx.beginPath();
    ctx.moveTo(p, 0);
    ctx.lineTo(p, height);
    ctx.moveTo(0, p);
    ctx.lineTo(width, p);
    ctx.stroke();
  }
}

function sampleFace(face) {
  const { canvas, ctx } = state[face];
  const points = [1 / 6, 1 / 2, 5 / 6];
  const samples = [];
  for (const yRatio of points) {
    for (const xRatio of points) {
      samples.push(
        samples.length === 4
          ? sampleCenterRing(ctx, canvas.width * xRatio, canvas.height * yRatio)
          : samplePatch(ctx, canvas.width * xRatio, canvas.height * yRatio, 35),
      );
    }
  }
  return samples;
}

function sampleCenterRing(ctx, x, y) {
  const outerRadius = 33;
  const innerRadius = 21;
  const left = Math.max(0, Math.round(x - outerRadius));
  const top = Math.max(0, Math.round(y - outerRadius));
  const size = outerRadius * 2 + 1;
  const source = ctx.getImageData(left, top, size, size).data;
  const ring = [];
  for (let row = 0; row < size; row += 1) {
    for (let column = 0; column < size; column += 1) {
      const dx = Math.abs(column - outerRadius);
      const dy = Math.abs(row - outerRadius);
      if (Math.max(dx, dy) < innerRadius) continue;
      const offset = (row * size + column) * 4;
      ring.push(source[offset], source[offset + 1], source[offset + 2], source[offset + 3]);
    }
  }
  return summarizePatchPixels(Uint8ClampedArray.from(ring), true);
}

function samplePatch(ctx, x, y, radius, preferMajority = false) {
  const left = Math.max(0, Math.round(x - radius));
  const top = Math.max(0, Math.round(y - radius));
  const size = radius * 2 + 1;
  const data = ctx.getImageData(left, top, size, size).data;
  return summarizePatchPixels(data, preferMajority);
}

function classifyAllFaces() {
  for (const face of FACE_ORDER) {
    if (!state[face].samples) return;
  }
  const labels = assignBalancedColors(
    Object.fromEntries(FACE_ORDER.map((face) => [face, state[face].samples])),
    FACE_ORDER,
  );
  for (const face of FACE_ORDER) {
    state[face].stickers = labels[face];
  }
}

function cycleSticker(face, idx) {
  if (idx === 4) return;
  const current = state[face].stickers[idx];
  const next = STICKER_COLORS[(STICKER_COLORS.indexOf(current) + 1) % STICKER_COLORS.length];
  state[face].stickers[idx] = next;
  renderAll();
}

function rotateFace(face, clockwise) {
  const current = state[face].stickers;
  const rotated = clockwise
    ? [current[6], current[3], current[0], current[7], current[4], current[1], current[8], current[5], current[2]]
    : [current[2], current[5], current[8], current[1], current[4], current[7], current[0], current[3], current[6]];
  rotated[4] = face;
  state[face].stickers = rotated;
  renderAll();
}

function openCropEditor(face) {
  const source = state[face].sourceCanvas;
  if (!source) return;
  const scale = Math.min(1, 920 / source.width, 650 / source.height);
  cropCanvas.width = Math.max(1, Math.round(source.width * scale));
  cropCanvas.height = Math.max(1, Math.round(source.height * scale));
  cropEditor.face = face;
  cropEditor.scale = scale;
  cropEditor.dragging = -1;
  cropEditor.corners = state[face].corners.map((point) => ({ x: point.x * scale, y: point.y * scale }));
  cropTitle.textContent = `${face} 面 · 调整识别区域`;
  updateCropConfidence(state[face].detection);
  drawCropEditor();
  cropDialog.showModal();
}

function drawCropEditor() {
  if (!cropEditor.face) return;
  const source = state[cropEditor.face].sourceCanvas;
  cropCtx.clearRect(0, 0, cropCanvas.width, cropCanvas.height);
  cropCtx.drawImage(source, 0, 0, cropCanvas.width, cropCanvas.height);

  cropCtx.save();
  cropCtx.fillStyle = "rgba(3, 8, 11, 0.58)";
  cropCtx.beginPath();
  cropCtx.rect(0, 0, cropCanvas.width, cropCanvas.height);
  cropCtx.moveTo(cropEditor.corners[0].x, cropEditor.corners[0].y);
  for (let index = 1; index < 4; index += 1) {
    cropCtx.lineTo(cropEditor.corners[index].x, cropEditor.corners[index].y);
  }
  cropCtx.closePath();
  cropCtx.fill("evenodd");

  cropCtx.beginPath();
  cropCtx.moveTo(cropEditor.corners[0].x, cropEditor.corners[0].y);
  for (let index = 1; index < 4; index += 1) {
    cropCtx.lineTo(cropEditor.corners[index].x, cropEditor.corners[index].y);
  }
  cropCtx.closePath();
  cropCtx.strokeStyle = "#f4d33f";
  cropCtx.lineWidth = 3;
  cropCtx.stroke();

  cropEditor.corners.forEach((point, index) => {
    cropCtx.beginPath();
    cropCtx.arc(point.x, point.y, 11, 0, Math.PI * 2);
    cropCtx.fillStyle = "#f4d33f";
    cropCtx.fill();
    cropCtx.strokeStyle = "#172026";
    cropCtx.lineWidth = 2;
    cropCtx.stroke();
    cropCtx.fillStyle = "#172026";
    cropCtx.font = "bold 12px Segoe UI";
    cropCtx.textAlign = "center";
    cropCtx.textBaseline = "middle";
    cropCtx.fillText(String(index + 1), point.x, point.y);
  });
  cropCtx.restore();
}

function beginCornerDrag(event) {
  if (!cropEditor.face) return;
  const point = cropPointerPosition(event);
  const rect = cropCanvas.getBoundingClientRect();
  const threshold = 24 * (cropCanvas.width / Math.max(1, rect.width));
  let nearest = -1;
  let nearestDistance = threshold;
  cropEditor.corners.forEach((corner, index) => {
    const currentDistance = distance(corner, point);
    if (currentDistance < nearestDistance) {
      nearest = index;
      nearestDistance = currentDistance;
    }
  });
  if (nearest >= 0) {
    cropEditor.dragging = nearest;
    cropCanvas.setPointerCapture(event.pointerId);
  }
}

function dragCorner(event) {
  if (cropEditor.dragging < 0) return;
  const point = cropPointerPosition(event);
  cropEditor.corners[cropEditor.dragging] = {
    x: clamp(point.x, 0, cropCanvas.width - 1),
    y: clamp(point.y, 0, cropCanvas.height - 1),
  };
  cropConfidence.textContent = "手动调整中";
  drawCropEditor();
}

function endCornerDrag(event) {
  if (cropEditor.dragging < 0) return;
  cropEditor.dragging = -1;
  if (cropCanvas.hasPointerCapture(event.pointerId)) cropCanvas.releasePointerCapture(event.pointerId);
}

function cropPointerPosition(event) {
  const rect = cropCanvas.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * cropCanvas.width,
    y: ((event.clientY - rect.top) / rect.height) * cropCanvas.height,
  };
}

async function redetectCrop() {
  const face = cropEditor.face;
  if (!face) return;
  redetectBtn.disabled = true;
  cropConfidence.textContent = "重新识别中...";
  try {
    const detected = await detectCubeFaceWithBackend(state[face].sourceCanvas);
    cropEditor.corners = detected.corners.map((point) => ({
      x: point.x * cropEditor.scale,
      y: point.y * cropEditor.scale,
    }));
    updateCropConfidence(detected);
    drawCropEditor();
  } finally {
    redetectBtn.disabled = false;
  }
}

function applyCrop() {
  const face = cropEditor.face;
  if (!face) return;
  const corners = cropEditor.corners.map((point) => ({
    x: point.x / cropEditor.scale,
    y: point.y / cropEditor.scale,
  }));
  if (!isValidQuad(corners)) {
    showError(cropConfidence, "四个角发生交叉，请重新调整");
    return;
  }
  state[face].corners = corners;
  state[face].detection = { corners, confidence: 100, mode: "manual" };
  rectifyFace(face);
  state[face].samples = sampleFace(face);
  classifyAllFaces();
  renderAll();
  cropDialog.close();
}

function isValidQuad(corners) {
  const area = Math.abs(signedPolygonArea(corners));
  const source = state[cropEditor.face].sourceCanvas;
  if (area < source.width * source.height * 0.005) return false;
  const crosses = corners.map((point, index) => {
    const next = corners[(index + 1) % 4];
    const after = corners[(index + 2) % 4];
    return (next.x - point.x) * (after.y - next.y) - (next.y - point.y) * (after.x - next.x);
  });
  return crosses.every((value) => value > 0) || crosses.every((value) => value < 0);
}

function updateCropConfidence(detection) {
  if (!detection || detection.mode === "fallback") {
    cropConfidence.textContent = "未可靠定位，请调整四角";
  } else if (detection.mode === "manual") {
    cropConfidence.textContent = "手动区域";
  } else {
    cropConfidence.textContent = `自动识别置信度 ${detection.confidence}%`;
  }
}

function renderAll() {
  for (const face of FACE_ORDER) {
    const card = facesRoot.querySelector(`[data-face="${face}"]`);
    const adjustButton = card.querySelector(".adjust-region");
    const badge = card.querySelector(".detection-badge");
    adjustButton.disabled = !state[face].imageLoaded;
    if (state[face].imageLoaded) {
      const detection = state[face].detection;
      badge.hidden = false;
      badge.classList.toggle("low-confidence", detection.mode === "fallback" || detection.confidence < 55);
      badge.textContent =
        detection.mode === "manual"
          ? "手动区域"
          : detection.mode === "fallback"
            ? "请校正区域"
            : `识别 ${detection.confidence}%`;
    } else {
      badge.hidden = true;
    }
    const stickers = card.querySelectorAll(".sticker");
    state[face].stickers.forEach((color, idx) => {
      const sticker = stickers[idx];
      sticker.dataset.color = color;
      sticker.textContent = color;
      sticker.classList.toggle("center", idx === 4);
    });
  }
  updateFacelets();
}

function updateFacelets() {
  const facelets = FACE_ORDER.map((face) => state[face].stickers.join("")).join("");
  faceletsText.value = facelets;
  const counts = Object.fromEntries(FACE_ORDER.map((face) => [face, [...facelets].filter((x) => x === face).length]));
  const loadedCount = FACE_ORDER.filter((face) => state[face].imageLoaded).length;
  const reviewFaces = FACE_ORDER.filter(
    (face) => state[face].imageLoaded && (state[face].detection.mode === "fallback" || state[face].detection.confidence < 55),
  );
  const wrong = Object.entries(counts).filter(([, count]) => count !== 9);
  if (wrong.length) {
    showError(statusText, `色块数量需要校正：${wrong.map(([f, c]) => `${f}=${c}`).join("，")}`);
  } else if (reviewFaces.length) {
    statusText.textContent = `${reviewFaces.join("、")} 面的识别区域需要确认`;
  } else if (loadedCount < 6) {
    statusText.textContent = `已上传 ${loadedCount}/6 面，可先校正或继续上传`;
  } else {
    statusText.textContent = "54 个色块数量正确，可以求解";
  }
}

function applyFacelets(facelets) {
  let offset = 0;
  for (const face of FACE_ORDER) {
    state[face].stickers = facelets.slice(offset, offset + 9).split("");
    state[face].stickers[4] = face;
    offset += 9;
  }
  renderAll();
}

async function solveCube() {
  const facelets = faceletsText.value.toUpperCase().replace(/[^URFDLB]/g, "");
  cancelActiveJob();
  const generation = ++solveGeneration;
  if (solvePollTimer !== null) {
    clearTimeout(solvePollTimer);
    solvePollTimer = null;
  }
  solveBtn.disabled = true;
  solutionText.textContent = "正在生成快速解；随后会在后台继续验证严格最短解。";
  depthText.textContent = "";
  statusText.textContent = "求解中...";
  try {
    const response = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        facelets,
        max_depth: 20,
        timeout_seconds: Math.max(10, Number(timeoutInput.value) || 180),
      }),
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "求解失败");
    }
    if (generation !== solveGeneration) {
      if (data.job_id) cancelJob(data.job_id);
      return;
    }
    if (data.depth === 0) {
      solutionText.textContent = "已复原，无需转动";
    } else if (data.solution) {
      solutionText.textContent = data.solution;
    } else {
      solutionText.textContent = data.message || "快速搜索暂未返回解法，正在继续搜索。";
    }

    if (data.optimal) {
      depthText.textContent = `${data.depth} 步，${data.metric}，严格最短：是，耗时 ${data.elapsed_seconds}s`;
      statusText.textContent = "严格最短解已确认";
    } else if (data.depth !== null) {
      depthText.textContent = `${data.depth} 步，${data.metric}，当前为快速解，生成耗时 ${data.elapsed_seconds}s；后台正在验证最短性`;
      statusText.textContent = "快速解已生成，正在后台验证严格最短解...";
    } else {
      depthText.textContent = "后台正在继续搜索";
      statusText.textContent = "快速搜索尚未完成，后台继续搜索中...";
    }

    if (data.job_id) {
      activeJobId = data.job_id;
      pollOptimalJob(data.job_id, generation);
    }
  } catch (error) {
    showError(solutionText, error.message);
    showError(statusText, "求解失败");
  } finally {
    solveBtn.disabled = false;
  }
}

async function pollOptimalJob(jobId, generation) {
  if (generation !== solveGeneration) return;
  try {
    const response = await fetch(`/api/solve/${encodeURIComponent(jobId)}`, { cache: "no-store" });
    const data = await response.json();
    if (generation !== solveGeneration) return;
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "无法读取最短解任务状态");
    }

    if (data.status === "complete") {
      const result = data.result;
      solutionText.textContent = result.solution || "已复原，无需转动";
      depthText.textContent = `${result.depth} 步，${result.metric}，严格最短：是，验证耗时 ${result.elapsed_seconds}s`;
      statusText.textContent = "严格最短解已确认";
      solvePollTimer = null;
      if (activeJobId === jobId) activeJobId = null;
      return;
    }
    if (data.status === "timeout") {
      depthText.textContent += "；最短性验证已超时，当前快速解仍可使用";
      statusText.textContent = "快速解可用，但严格最短性尚未证明";
      solvePollTimer = null;
      if (activeJobId === jobId) activeJobId = null;
      return;
    }
    if (data.status === "error") {
      depthText.textContent += `；后台验证失败：${data.message || "未知错误"}`;
      statusText.textContent = "快速解可用，后台验证失败";
      solvePollTimer = null;
      if (activeJobId === jobId) activeJobId = null;
      return;
    }
    if (data.status === "cancelled") {
      statusText.textContent = "后台最短性验证已取消";
      solvePollTimer = null;
      if (activeJobId === jobId) activeJobId = null;
      return;
    }

    statusText.textContent = data.status === "queued" ? "快速解可用，最短性验证等待中..." : "快速解可用，正在验证严格最短解...";
    solvePollTimer = setTimeout(() => pollOptimalJob(jobId, generation), 1000);
  } catch (error) {
    if (generation !== solveGeneration) return;
    statusText.textContent = `快速解可用，后台状态暂时不可用：${error.message}`;
    solvePollTimer = setTimeout(() => pollOptimalJob(jobId, generation), 2000);
  }
}

function cancelJob(jobId) {
  fetch(`/api/solve/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }).catch(() => {});
}

function cancelActiveJob() {
  if (!activeJobId) return;
  const jobId = activeJobId;
  activeJobId = null;
  cancelJob(jobId);
}

function rgbToLab(rgb) {
  let [r, g, b] = rgb.map((v) => v / 255);
  [r, g, b] = [r, g, b].map((v) => (v > 0.04045 ? ((v + 0.055) / 1.055) ** 2.4 : v / 12.92));
  let x = r * 0.4124 + g * 0.3576 + b * 0.1805;
  let y = r * 0.2126 + g * 0.7152 + b * 0.0722;
  let z = r * 0.0193 + g * 0.1192 + b * 0.9505;
  x /= 0.95047;
  z /= 1.08883;
  const fx = labPivot(x);
  const fy = labPivot(y);
  const fz = labPivot(z);
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

function labPivot(value) {
  return value > 0.008856 ? Math.cbrt(value) : 7.787 * value + 16 / 116;
}

function labDistance(a, b) {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

function summarizePatchPixels(data, preferMajority = false) {
  const pixels = [];
  for (let index = 0; index < data.length; index += 4) {
    const r = data[index];
    const g = data[index + 1];
    const b = data[index + 2];
    const maximum = Math.max(r, g, b);
    const minimum = Math.min(r, g, b);
    const value = maximum / 255;
    if (value < 0.12) continue;
    pixels.push({
      r,
      g,
      b,
      value,
      saturation: (maximum - minimum) / Math.max(1, maximum),
    });
  }

  if (!pixels.length) {
    return makeColorDescriptor([0, 0, 0], 0, 0, 0);
  }

  const saturationSignal = quantile(
    pixels.map((pixel) => pixel.saturation),
    preferMajority ? 0.55 : 0.78,
  );
  const glareFraction =
    pixels.filter((pixel) => pixel.value > 0.86 && pixel.saturation < 0.12).length / pixels.length;
  const saturatedFraction =
    pixels.filter((pixel) => pixel.value > 0.16 && pixel.saturation > 0.24).length / pixels.length;
  const colorful =
    saturationSignal > 0.15 || (!preferMajority && glareFraction > 0.45 && saturatedFraction > 0.04);
  const saturationFloor = colorful
    ? Math.max(0.10, quantile(pixels.map((pixel) => pixel.saturation), 0.42))
    : 0;
  const brightnessCeiling = quantile(
    pixels.map((pixel) => pixel.value),
    0.97,
  );
  let selected = pixels.filter((pixel) => {
    if (!colorful) return true;
    const specular = pixel.value > Math.max(0.82, brightnessCeiling * 0.96) && pixel.saturation < saturationSignal * 0.55;
    return pixel.saturation >= saturationFloor && !specular;
  });
  if (selected.length < Math.max(12, pixels.length * 0.12)) selected = pixels;

  let weightTotal = 0;
  const rgb = [0, 0, 0];
  for (const pixel of selected) {
    const weight = colorful
      ? 0.15 + pixel.saturation * pixel.saturation * 3.2
      : Math.max(0.15, 1 - pixel.saturation * 2.5);
    rgb[0] += pixel.r * weight;
    rgb[1] += pixel.g * weight;
    rgb[2] += pixel.b * weight;
    weightTotal += weight;
  }
  rgb[0] /= weightTotal;
  rgb[1] /= weightTotal;
  rgb[2] /= weightTotal;

  return makeColorDescriptor(
    rgb,
    quantile(selected.map((pixel) => pixel.saturation), 0.65),
    quantile(selected.map((pixel) => pixel.value), 0.5),
    glareFraction,
  );
}

function makeColorDescriptor(rgb, saturation, value, glareFraction = 0) {
  const [r, g, b] = rgb.map((channel) => channel / 255);
  const maximum = Math.max(r, g, b);
  const minimum = Math.min(r, g, b);
  const delta = maximum - minimum;
  let hue = 0;
  if (delta > 1e-6) {
    if (maximum === r) hue = ((g - b) / delta) % 6;
    else if (maximum === g) hue = (b - r) / delta + 2;
    else hue = (r - g) / delta + 4;
    hue = ((hue / 6) % 1 + 1) % 1;
  }
  return {
    rgb,
    lab: rgbToLab(rgb),
    hue,
    saturation,
    value,
    glareFraction,
  };
}

function robustColorDistance(sample, center) {
  const labCost = labDistance(sample.lab, center.lab) * 0.62;
  const saturationCost = Math.abs(sample.saturation - center.saturation) * 42;
  const brightnessCost = Math.abs(sample.value - center.value) * 9;
  let hueCost = 0;
  if (sample.saturation > 0.14 && center.saturation > 0.14) {
    const hueDifference = Math.abs(sample.hue - center.hue);
    hueCost = Math.min(hueDifference, 1 - hueDifference) * 42;
  } else if ((sample.saturation > 0.20) !== (center.saturation > 0.20)) {
    hueCost = 18;
  }
  return labCost + saturationCost + brightnessCost + hueCost;
}

function minimumCostAssignment(costs) {
  const size = costs.length;
  if (!size || costs.some((row) => row.length !== size)) {
    throw new Error("颜色分配矩阵必须是非空方阵");
  }
  const rowPotential = Array(size + 1).fill(0);
  const columnPotential = Array(size + 1).fill(0);
  const matchedRow = Array(size + 1).fill(0);
  const path = Array(size + 1).fill(0);

  for (let row = 1; row <= size; row += 1) {
    matchedRow[0] = row;
    let column = 0;
    const minimum = Array(size + 1).fill(Number.POSITIVE_INFINITY);
    const used = Array(size + 1).fill(false);
    do {
      used[column] = true;
      const currentRow = matchedRow[column];
      let delta = Number.POSITIVE_INFINITY;
      let nextColumn = 0;
      for (let candidate = 1; candidate <= size; candidate += 1) {
        if (used[candidate]) continue;
        const reducedCost =
          costs[currentRow - 1][candidate - 1] - rowPotential[currentRow] - columnPotential[candidate];
        if (reducedCost < minimum[candidate]) {
          minimum[candidate] = reducedCost;
          path[candidate] = column;
        }
        if (minimum[candidate] < delta) {
          delta = minimum[candidate];
          nextColumn = candidate;
        }
      }
      for (let candidate = 0; candidate <= size; candidate += 1) {
        if (used[candidate]) {
          rowPotential[matchedRow[candidate]] += delta;
          columnPotential[candidate] -= delta;
        } else {
          minimum[candidate] -= delta;
        }
      }
      column = nextColumn;
    } while (matchedRow[column] !== 0);

    do {
      const previous = path[column];
      matchedRow[column] = matchedRow[previous];
      column = previous;
    } while (column !== 0);
  }

  const assignment = Array(size).fill(-1);
  for (let column = 1; column <= size; column += 1) {
    assignment[matchedRow[column] - 1] = column - 1;
  }
  return assignment;
}

function quantile(values, fraction) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const position = (sorted.length - 1) * Math.min(1, Math.max(0, fraction));
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  const weight = position - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
}

function assignBalancedColors(samplesByFace, faceOrder) {
  const prototypes = Object.fromEntries(faceOrder.map((face) => [face, samplesByFace[face][4]]));
  const items = [];
  for (const face of faceOrder) {
    samplesByFace[face].forEach((sample, index) => {
      if (index !== 4) items.push({ face, index, sample });
    });
  }
  const slots = faceOrder.flatMap((face) => Array(8).fill(face));
  let assignment = [];

  for (let iteration = 0; iteration < 3; iteration += 1) {
    const costs = items.map((item) =>
      slots.map((candidate) => robustColorDistance(item.sample, prototypes[candidate])),
    );
    assignment = minimumCostAssignment(costs);
    const groups = Object.fromEntries(
      faceOrder.map((face) => [face, [samplesByFace[face][4]]]),
    );
    items.forEach((item, row) => {
      groups[slots[assignment[row]]].push(item.sample);
    });
    for (const face of faceOrder) prototypes[face] = colorDescriptorMedoid(groups[face]);
  }

  const labels = Object.fromEntries(faceOrder.map((face) => [face, Array(9).fill(face)]));
  items.forEach((item, row) => {
    labels[item.face][item.index] = slots[assignment[row]];
  });
  return labels;
}

function colorDescriptorMedoid(descriptors) {
  let best = descriptors[0];
  let bestCost = Number.POSITIVE_INFINITY;
  for (const candidate of descriptors) {
    const cost = descriptors.reduce(
      (sum, descriptor) => sum + robustColorDistance(candidate, descriptor),
      0,
    );
    if (cost < bestCost) {
      best = candidate;
      bestCost = cost;
    }
  }
  return best;
}
